"""#131: Taiwan up/down colours across the page and a cap on embedded versions."""
from market_research.beginner_view import BEGINNER_CSS
from market_research.research_site import (
    CSS, MAX_EMBEDDED_VERSIONS, _chg, latest_only_records, render_research_site_html,
)
from test_multi_stock_pages import report, site_data


def test_rises_are_red_and_falls_green_everywhere():
    assert "--up:#c62828;--down:#1a7f37" in CSS
    assert ".chg.up{color:var(--up)}.chg.down{color:var(--down)}" in CSS
    assert ".pc-up{color:var(--up)" in BEGINNER_CSS and "--pc-up" not in BEGINNER_CSS
    assert _chg(3.0).startswith('<span class="chg up">▲')
    assert _chg(-3.0).startswith('<span class="chg down">▼')


def stored_versions(count):
    records = {}
    for i in range(count):
        r = report(close=1000.0 + i)
        stamp = f"2026-10-{20 + i // 24:02d}T{i % 24:02d}:30:00+00:00"
        r["generated_utc"] = r["started_utc"] = stamp
        made, skipped = latest_only_records([r])
        assert skipped == {}
        records.update(made)  # chronological, so the subject ends on the newest
    return records


def test_only_the_newest_versions_are_embedded_and_older_ones_are_marked():
    total = MAX_EMBEDDED_VERSIONS + 2
    data = site_data(render_research_site_html(stored_versions(total)))
    stock = data["stocks"][0]
    assert len(stock["snapshots"]) == MAX_EMBEDDED_VERSIONS
    assert len(data["views"]["2330.TW"]) == MAX_EMBEDDED_VERSIONS
    latest = data["views"]["2330.TW"][stock["latest_snapshot_id"]]
    assert f"研究版本（歷史快照，共 {total} 個）" in latest
    assert latest.count(f"未內嵌（頁面只保留最近 {MAX_EMBEDDED_VERSIONS} 版）") == 2
    assert latest.count("檢視此版本") == MAX_EMBEDDED_VERSIONS - 1  # every embedded one but the current


def test_small_histories_are_unchanged():
    data = site_data(render_research_site_html(stored_versions(3)))
    assert len(data["views"]["2330.TW"]) == 3
    assert "未內嵌" not in "".join(data["views"]["2330.TW"].values())
