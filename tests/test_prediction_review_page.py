"""#183 PL6: the prediction scorecard page on the knowledge site."""
from datetime import datetime, timezone
from pathlib import Path
import re

from market_research.knowledge_site import LinkMapper, build_knowledge_site, render_markdown
from scripts.prediction_review import render_page, sync
from tests.test_knowledge_site import _markdown_tables
from tests.test_prediction_review import FakeSink
from tests.test_prediction_review_results import UP_WEEK, WEEKLY, bars

KB = Path(__file__).resolve().parents[1] / "knowledge"
RUN_URL = "https://github.com/iceboxi/market-research/actions/runs/9"
SEEN = {"first_seen": datetime.fromisoformat("2026-11-18T00:03:59+08:00")}
NOW = datetime.fromisoformat("2026-11-24T16:00:00+08:00")


def synced():
    sink = FakeSink()
    result = sync(sink, [WEEKLY], {WEEKLY["id"]: SEEN}, NOW, run_id="9", run_url=RUN_URL,
                  bars_fn=lambda symbol, since: bars(UP_WEEK))
    return sink, result


def test_page_renders_every_table_and_heading():
    _, result = synced()
    page = render_page(result["records"], [{**WEEKLY, "reasoning": "兩天跌 8.2%。\n反面：升息。"}],
                       result["as_of"], RUN_URL)
    body, title = render_markdown(page, LinkMapper({"README.md", "predictions.md"}))
    assert title == "預測成績表"
    assert body.count("<table>") == _markdown_tables(page) == 2
    assert len(re.findall(r"<h[1-6] id=", body)) == sum(1 for line in page.split("\n") if re.match(r"^#{1,6}\s", line))
    assert "非買賣建議" in page and "資料日期：2026-11-24" in page and RUN_URL in page
    assert 'href="index.html#預測紀錄"' in body
    assert "<h3 id=" in body and "兩天跌 8.2%。 反面：升息。" in body


def test_page_scorecard_matches_the_issue_body():
    sink, result = synced()
    page = render_page(result["records"], [WEEKLY], result["as_of"], RUN_URL)
    issue = sink.issues[901]["body"]

    def scorecard_rows(text):
        return [line for line in text.split("\n") if line.startswith("| 全部 ")]
    assert scorecard_rows(page) == scorecard_rows(issue) == ["| 全部 | 1 | 1.00 | 0.55 | 0.2025 | 0 | — | — |"]
    assert "| `W-20261117-taiex` | 週預測 |" in page


def test_knowledge_site_adds_the_generated_page_with_its_own_source(tmp_path):
    _, result = synced()
    generated = tmp_path / "predictions.md"
    generated.write_text(render_page(result["records"], [WEEKLY], result["as_of"], RUN_URL), encoding="utf-8")
    written = build_knowledge_site(KB, tmp_path / "site", extra=((generated, "預測紀錄的每日判定（執行紀錄）", RUN_URL),),
                                   generated=datetime(2026, 11, 24, 8, tzinfo=timezone.utc))
    page = tmp_path / "site" / "predictions.html"
    assert page in written
    html = page.read_text(encoding="utf-8")
    assert f'來源：<a href="{RUN_URL}">預測紀錄的每日判定（執行紀錄）</a>' in html
    index = (tmp_path / "site" / "index.html").read_text(encoding="utf-8")
    assert '<a href="predictions.html" aria-current="false">預測成績表</a>' in index
    assert "blob/main/knowledge/README.md" in index  # knowledge pages keep their own source


def test_without_the_generated_page_the_site_is_unchanged(tmp_path):
    written = build_knowledge_site(KB, tmp_path / "site")
    assert not (tmp_path / "site" / "predictions.html").exists()
    assert len(written) == len(list(KB.glob("*.md")))
