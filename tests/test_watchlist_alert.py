"""#116, #145: one watchlist alert Issue; a comment only when a satellite or industry-watch state changes."""
import json
from pathlib import Path
import sys

import pytest
import yaml

from scripts import watchlist_alert
from scripts.watchlist_alert import (
    MARKER, AlertContextError, parse_state, require_alert_context, sync,
)

ROOT = Path(__file__).resolve().parents[1]
SATELLITES = ["2330.TW", "2317.TW", "2454.TW"]
RUN_URL = "https://github.com/iceboxi/market-research/actions/runs/{}"


class FakeSink:
    """GitHub Issues stand-in recording every write."""

    def __init__(self, issues=()):
        self.issues = {issue["number"]: dict(issue) for issue in issues}
        self.comments, self.calls = {}, []

    def find(self, marker):
        return [dict(i) for i in self.issues.values() if marker in (i.get("body") or "")]

    def create(self, title, body):
        number = max([900, *self.issues]) + 1
        self.issues[number] = {"number": number, "title": title, "body": body, "state": "open"}
        self.calls.append("create")
        return {"number": number}

    def update(self, number, body):
        self.issues[number]["body"] = body
        self.calls.append("update")

    def find_comments(self, number, marker):
        return [c for c in self.comments.get(number, []) if marker in c]

    def create_comment(self, number, body):
        self.comments.setdefault(number, []).append(body)
        self.calls.append("comment")


def zone(value="fair", close=2425.0):
    if value == "not_evaluated":
        return {"status": "not_evaluated", "zone": "not_evaluated", "reason": "TTM EPS unavailable",
                "price": None, "review_prices_twd": None}
    return {"status": "available", "zone": value, "reason": None,
            "price": {"close": close, "session": "2026-10-28"},
            "review_prices_twd": {"low": 1290.75, "mid": 2016.36, "high": 2429.64}}


def thesis(value="ok", reason=None, titles=()):
    return {"status": value, "reason": reason, "cutoff": "2026-10-29",
            "revenue": {"months": [{"period": "2026-09", "yoy_pct": 38.42}]},
            "announcements": {"items": [{"title": t, "published_at": "2026-10-29T17:00:00+08:00"}
                                        for t in titles]}}


def receipt(day="2026-10-29", **overrides):
    symbols = {}
    for symbol in SATELLITES:
        record = {"symbol": symbol, "status": "complete", "company_name": f"name-{symbol[:4]}",
                  "valuation_zone": zone(), "thesis_check": thesis()}
        record.update(overrides.get(symbol, {}))
        symbols[symbol] = record
    return {"generated_utc": f"{day}T09:00:00+00:00", "pilot_coverage": {"symbols": symbols}}


def run(sink, data, run_id="1"):
    return sync(sink, data, SATELLITES, run_id=run_id, run_url=RUN_URL.format(run_id))


def stored(sink, number=901):
    return parse_state(sink.issues[number]["body"])["symbols"]


def test_first_run_creates_the_issue_and_one_baseline_comment():
    sink = FakeSink()
    result = run(sink, receipt())
    assert sink.calls == ["create", "comment", "update"]
    assert result["kind"] == "baseline" and result["comment"] == "posted"
    assert len(result["changes"]) == 6  # three satellites x (zone, thesis)
    [comment] = sink.comments[901]
    assert "## 初始狀態（基線）：2026-10-29（請檢視，非買賣建議）" in comment
    assert "| 2330.TW name-2330 | 估值區間 | — → 合理區間 | 收盤 2,425.00；偏低／合理／偏高 " \
           "1,290.75／2,016.36／2,429.64 | 2026-10-28 |" in comment
    assert "| 2330.TW name-2330 | 論點 | — → 未觸發 | 月營收年增率 2026-09 +38.42% | 2026-10-29 |" in comment
    body = sink.issues[901]["body"]
    assert body.startswith(MARKER) and "請檢視，非買賣建議" in body
    assert stored(sink) == {s: {"zone": "fair", "thesis": "ok"} for s in SATELLITES}


def test_unchanged_state_updates_the_body_but_never_comments():
    sink = FakeSink()
    run(sink, receipt())
    result = run(sink, receipt(day="2026-10-30"), run_id="2")
    assert result["kind"] == "change" and result["changes"] == []
    assert result["comment"] == "not_needed"
    assert len(sink.comments[901]) == 1
    assert "最後更新：2026-10-30" in sink.issues[901]["body"]


def test_zone_or_thesis_change_comments_old_new_basis_and_date():
    sink = FakeSink()
    run(sink, receipt())
    changed = receipt(day="2026-10-30", **{
        "2454.TW": {"valuation_zone": zone("above_high", close=4235.0)},
        "2317.TW": {"thesis_check": thesis("review", "當日重大公告 1 則", ["董事會決議增資"])}})
    result = run(sink, changed, run_id="2")
    assert [(c["symbol"], c["item"], c["old"], c["new"]) for c in result["changes"]] == [
        ("2317.TW", "thesis", "ok", "review"), ("2454.TW", "zone", "fair", "above_high")]
    comment = sink.comments[901][-1]
    assert "## 狀態改變：2026-10-30（請檢視，非買賣建議）" in comment
    assert "| 2454.TW name-2454 | 估值區間 | 合理區間 → 高於偏高價 | 收盤 4,235.00；" in comment
    assert "| 2317.TW name-2317 | 論點 | 未觸發 → 請檢視 | 當日重大公告 1 則：董事會決議增資 | 2026-10-29 |" in comment
    assert RUN_URL.format(2) in comment
    assert stored(sink)["2454.TW"] == {"zone": "above_high", "thesis": "ok"}


def test_not_evaluated_is_not_a_change_and_keeps_the_last_value():
    sink = FakeSink()
    run(sink, receipt())
    gap = receipt(day="2026-10-30", **{"2330.TW": {"valuation_zone": zone("not_evaluated")}})
    assert run(sink, gap, run_id="2")["comment"] == "not_needed"
    assert stored(sink)["2330.TW"]["zone"] == "fair"
    assert "| 2330.TW name-2330 | 未評估：TTM EPS unavailable |" in sink.issues[901]["body"]
    assert run(sink, receipt(day="2026-10-31"), run_id="3")["comment"] == "not_needed"
    moved = receipt(day="2026-11-02", **{"2330.TW": {"valuation_zone": zone("above_high")}})
    result = run(sink, moved, run_id="4")
    assert [(c["old"], c["new"]) for c in result["changes"]] == [("fair", "above_high")]


def test_failed_research_is_not_evaluated_with_its_reason():
    sink = FakeSink()
    run(sink, receipt())
    failed = receipt(day="2026-10-30", **{"2317.TW": {
        "status": "failed", "error_type": "ReadTimeout", "valuation_zone": None, "thesis_check": None}})
    assert run(sink, failed, run_id="2")["changes"] == []
    assert "| 2317.TW name-2317 | 未評估：研究失敗：ReadTimeout |" in sink.issues[901]["body"]
    assert stored(sink)["2317.TW"] == {"zone": "fair", "thesis": "ok"}


@pytest.mark.parametrize("body, note", [
    (MARKER + "\n<!-- watchlist-alert-state:{broken -->\n", "狀態 JSON 無法解析"),
    (MARKER + '\n<!-- watchlist-alert-state:{"schema":9,"symbols":{}} -->\n', "狀態版本不符"),
    (MARKER + '\n<!-- watchlist-alert-state:{"schema":1,"symbols":{"2330.TW":{"zone":"cheap","thesis":"ok"}}} -->\n',
     "2330.TW 的狀態值無效"),
])
def test_corrupt_state_is_rebuilt_and_explained(body, note):
    sink = FakeSink([{"number": 5, "body": body, "state": "open"}])
    result = run(sink, receipt())
    assert result["kind"] == "rebuilt" and result["issue_number"] == 5
    assert result["note"].startswith(note)
    [comment] = sink.comments[5]
    assert "## 重建基線" in comment and "前次狀態無法使用" in comment
    assert stored(sink, 5) == {s: {"zone": "fair", "thesis": "ok"} for s in SATELLITES}


def test_rerun_of_the_same_run_never_comments_twice():
    sink = FakeSink()
    run(sink, receipt())
    changed = receipt(day="2026-10-30", **{"2454.TW": {"valuation_zone": zone("above_high")}})
    first = run(sink, changed, run_id="7")
    # Reply lost after the comment: the body still holds the old state.
    sink.issues[901]["body"] = sink.issues[901]["body"].replace('"above_high"', '"fair"')
    again = run(sink, changed, run_id="7")
    assert (first["comment"], again["comment"]) == ("posted", "already_posted")
    assert sum("watchlist-alert-run:7" in c for c in sink.comments[901]) == 1


def test_interrupted_creation_still_gets_its_baseline_comment():
    sink = FakeSink([{"number": 3, "body": MARKER + "\n初始化中。\n", "state": "open"}])
    result = run(sink, receipt())
    assert result["kind"] == "baseline" and result["comment"] == "posted"


def test_only_one_open_issue_is_used_and_closed_ones_are_ignored():
    closed = {"number": 1, "body": MARKER, "state": "closed"}
    sink = FakeSink([closed])
    assert run(sink, receipt())["issue_number"] == 901
    two = FakeSink([{"number": 1, "body": MARKER, "state": "open"},
                    {"number": 2, "body": MARKER, "state": "open"}])
    with pytest.raises(ValueError, match="More than one open"):
        run(two, receipt())
    assert two.calls == []


@pytest.mark.parametrize("env", [
    {"GITHUB_REF": "refs/heads/feat/x", "GITHUB_EVENT_NAME": "workflow_dispatch", "SCAN_MARKET": "tw"},
    {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "push", "SCAN_MARKET": "both"},
    {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "pull_request", "SCAN_MARKET": "tw"},
    {"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "schedule", "SCAN_MARKET": "us"},
    {},
])
def test_branch_and_validation_runs_never_write(env, tmp_path, monkeypatch):
    with pytest.raises(AlertContextError):
        require_alert_context(env)
    for key in ("GITHUB_REF", "GITHUB_EVENT_NAME", "SCAN_MARKET"):
        monkeypatch.delenv(key, raising=False)
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    def forbidden(*args, **kwargs):
        raise AssertionError("GitHub sink must not be created")
    monkeypatch.setattr(watchlist_alert, "GitHubResearchSink", forbidden)
    (tmp_path / "daily_receipt.json").write_text(json.dumps(receipt()), encoding="utf-8")
    monkeypatch.setattr(sys, "argv", ["watchlist_alert", "--receipt", str(tmp_path / "daily_receipt.json"),
                                      "--repo", "o/r", "--run-id", "1", "--run-url", "u", "--out", str(tmp_path)])
    watchlist_alert.main()
    result = json.loads((tmp_path / "watchlist_alert_receipt.json").read_text())
    assert result["status"] == "skipped"


def test_production_context_is_allowed():
    for event in ("schedule", "workflow_dispatch"):
        require_alert_context({"GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": event,
                               "SCAN_MARKET": "tw"})


def test_workflow_runs_the_alert_only_from_main_schedule_or_dispatch():
    jobs = yaml.safe_load((ROOT / ".github/workflows/scan.yml").read_text())["jobs"]
    steps = [step for job in jobs.values() for step in job.get("steps", [])
             if "watchlist_alert" in step.get("run", "")]
    assert len(steps) == 1
    condition = steps[0]["if"]
    assert "github.ref == 'refs/heads/main'" in condition
    assert "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'" in condition
    assert "env.SCAN_MARKET != 'us'" in condition


# ---------------------------------------------------------------- industry watch (#145)

def pb_zone(value="fair", close=454.5):
    if value == "not_evaluated":
        return {"status": "not_evaluated", "zone": "not_evaluated", "price": None,
                "reason": "Only 120 PBR samples in the 5-year window; need 750",
                "review_prices_twd": None, "pbr_history": None}
    return {"status": "available", "zone": value, "reason": None,
            "price": {"close": close, "session": "2026-10-30", "source": "twse_stock_day_official_raw_ohlcv"},
            "review_prices_twd": {"low": 83.23, "mid": 112.22, "high": 242.96},
            "pbr_history": {"latest_pbr": 4.86, "latest_percentile_rank": 89.0, "samples": 1200}}


def momentum(value="ok"):
    if value == "not_evaluated":
        return {"status": "not_evaluated", "reason": "缺月營收：2026-09", "latest_period": "2026-09",
                "latest_published": None, "months": []}
    reason = {"ok": "3 個月滾動年增率連續下降 2 個月（門檻 3）",
              "slowing": "3 個月滾動年增率連續下降 3 個月（門檻 3）",
              "contracting": "3 個月滾動年增率 -4.20%，低於 0"}[value]
    return {"status": value, "reason": reason, "latest_period": "2026-09", "latest_published": "2026-10-06",
            "months": [{"period": "2026-08", "rolling_3m_yoy_pct": 628.6},
                       {"period": "2026-09", "rolling_3m_yoy_pct": 611.7}]}


def industry_row(symbol="2408.TW", name="南亞科", zone_value="fair", momentum_value="ok"):
    return {"symbol": symbol, "name": name, "group": "memory", "status": "available",
            "price_position": {"status": "available", "close": 454.5, "session": "2026-10-30"},
            "pb_zone": pb_zone(zone_value), "revenue_momentum": momentum(momentum_value)}


def with_industry(data, *rows):
    data["industry_watch"] = {"status": "complete", "cutoff": "2026-10-30",
                              "groups": [{"id": "memory", "name": "記憶體", "rationale": "理由",
                                          "symbols": [r["symbol"] for r in rows]}],
                              "rows": list(rows)}
    return data


TWO = (industry_row(), industry_row("2344.TW", "華邦電"))


def industry_stored(sink, number=901):
    return parse_state(sink.issues[number]["body"])["industry"]


def schema_one_issue():
    """The live #139 body before #145: satellites only, all fair / ok."""
    state = {"schema": 1, "as_of": "2026-10-30",
             "symbols": {s: {"zone": "fair", "thesis": "ok"} for s in SATELLITES}}
    return {"number": 139, "state": "open",
            "body": MARKER + "\n<!-- watchlist-alert-state:" + json.dumps(state) + " -->\n"}


def test_schema_one_state_gets_one_baseline_comment_for_the_new_industry_items_only():
    sink = FakeSink([schema_one_issue()])
    result = run(sink, with_industry(receipt(day="2026-10-30"), *TWO))
    assert result["kind"] == "baseline" and result["comment"] == "posted" and result["industry"] == "evaluated"
    assert [(c["symbol"], c["item"], c["old"]) for c in result["changes"]] == [
        ("2408.TW", "pb_zone", None), ("2408.TW", "momentum", None),
        ("2344.TW", "pb_zone", None), ("2344.TW", "momentum", None)]
    [comment] = sink.comments[139]
    assert "## 初始狀態（基線）：2026-10-30（請檢視，非買賣建議）" in comment
    assert ("| 2408.TW 南亞科 | 股價淨值比區間 | — → 合理區間 | 收盤 454.50；偏低／合理／偏高 "
            "83.23／112.22／242.96；PBR 4.86（P89） | 2026-10-30 |") in comment
    assert ("| 2408.TW 南亞科 | 營收動能 | — → 未放緩 | 3 個月滾動年增率 2026-08 +628.6% → 2026-09 +611.7%；"
            "3 個月滾動年增率連續下降 2 個月（門檻 3） | 2026-09（2026-10-06） |") in comment
    assert "2330.TW" not in comment  # unchanged satellites are not repeated
    state = parse_state(sink.issues[139]["body"])
    assert state["symbols"] == {s: {"zone": "fair", "thesis": "ok"} for s in SATELLITES}
    assert state["industry"] == {s: {"pb_zone": "fair", "momentum": "ok"} for s in ("2408.TW", "2344.TW")}
    assert '"schema":2' in sink.issues[139]["body"]


def test_body_shows_the_industry_table_by_group():
    sink = FakeSink()
    run(sink, with_industry(receipt(), *TWO))
    body = sink.issues[901]["body"]
    assert "## 產業觀察" in body and "### 記憶體" in body
    assert ("| 2408.TW 南亞科 | 合理區間 | 454.50（2026-10-30） | 4.86（P89） | 83.23／112.22／242.96 | 未放緩 "
            "| 3 個月滾動年增率 2026-08 +628.6% → 2026-09 +611.7%；3 個月滾動年增率連續下降 2 個月（門檻 3） |") in body
    assert "| 2330.TW name-2330 | 合理區間 |" in body  # the satellite table stays


def test_unchanged_industry_updates_the_body_but_never_comments():
    sink = FakeSink()
    run(sink, with_industry(receipt(), *TWO))
    result = run(sink, with_industry(receipt(day="2026-10-30"), *TWO), run_id="2")
    assert result["kind"] == "change" and result["changes"] == [] and result["comment"] == "not_needed"
    assert len(sink.comments[901]) == 1 and "最後更新：2026-10-30" in sink.issues[901]["body"]


def test_zone_and_momentum_changes_share_one_comment_with_satellite_changes():
    sink = FakeSink()
    run(sink, with_industry(receipt(), *TWO))
    changed = with_industry(
        receipt(day="2026-10-30", **{"2454.TW": {"valuation_zone": zone("above_high", close=4235.0)}}),
        industry_row(zone_value="above_high"), industry_row("2344.TW", "華邦電", momentum_value="slowing"))
    result = run(sink, changed, run_id="2")
    assert [(c["symbol"], c["item"], c["old"], c["new"]) for c in result["changes"]] == [
        ("2454.TW", "zone", "fair", "above_high"), ("2408.TW", "pb_zone", "fair", "above_high"),
        ("2344.TW", "momentum", "ok", "slowing")]
    assert len(sink.comments[901]) == 2
    comment = sink.comments[901][-1]
    assert "## 狀態改變：2026-10-30（請檢視，非買賣建議）" in comment
    assert "| 2408.TW 南亞科 | 股價淨值比區間 | 合理區間 → 高於偏高價 | 收盤 454.50；" in comment
    assert ("| 2344.TW 華邦電 | 營收動能 | 未放緩 → 放緩 | 3 個月滾動年增率 2026-08 +628.6% → 2026-09 +611.7%；"
            "3 個月滾動年增率連續下降 3 個月（門檻 3） | 2026-09（2026-10-06） |") in comment
    assert "| 2454.TW name-2454 | 估值區間 | 合理區間 → 高於偏高價 |" in comment
    assert industry_stored(sink) == {"2408.TW": {"pb_zone": "above_high", "momentum": "ok"},
                                     "2344.TW": {"pb_zone": "fair", "momentum": "slowing"}}


def test_not_evaluated_industry_items_are_not_a_change_and_keep_the_last_value():
    sink = FakeSink()
    run(sink, with_industry(receipt(), *TWO))
    gap = with_industry(receipt(day="2026-10-30"),
                        industry_row(zone_value="not_evaluated", momentum_value="not_evaluated"), TWO[1])
    result = run(sink, gap, run_id="2")
    assert result["changes"] == [] and result["comment"] == "not_needed"
    assert industry_stored(sink)["2408.TW"] == {"pb_zone": "fair", "momentum": "ok"}
    body = sink.issues[901]["body"]
    assert ("| 2408.TW 南亞科 | 未評估：Only 120 PBR samples in the 5-year window; need 750 | —（—） | — "
            "| —／—／— | 未評估：缺月營收：2026-09 | 缺月營收：2026-09 |") in body
    back = with_industry(receipt(day="2026-10-31"), industry_row(zone_value="below_low"), TWO[1])
    assert [(c["old"], c["new"]) for c in run(sink, back, run_id="3")["changes"]] == [("fair", "below_low")]


def test_failed_or_missing_industry_section_keeps_the_stored_values():
    sink = FakeSink()
    run(sink, with_industry(receipt(), *TWO))
    failed = receipt(day="2026-10-30")
    failed["industry_watch"] = {"status": "failed", "error_type": "ConnectError", "reason": "unreachable"}
    result = run(sink, failed, run_id="2")
    assert result["changes"] == [] and result["industry"] == "failed"
    assert "本次取得失敗：ConnectError：unreachable；保留上次已評估的狀態。" in sink.issues[901]["body"]
    assert industry_stored(sink) == {s: {"pb_zone": "fair", "momentum": "ok"} for s in ("2408.TW", "2344.TW")}
    result = run(sink, receipt(day="2026-10-31"), run_id="3")
    assert result["changes"] == [] and result["industry"] == "not_run"
    assert "本次未執行產業觀察，保留上次已評估的狀態。" in sink.issues[901]["body"]
    assert industry_stored(sink) == {s: {"pb_zone": "fair", "momentum": "ok"} for s in ("2408.TW", "2344.TW")}


def test_a_newly_added_industry_stock_gets_a_baseline_comment():
    sink = FakeSink()
    run(sink, with_industry(receipt(), TWO[0]))
    added = with_industry(receipt(day="2026-10-30"), TWO[0], industry_row("8299.TWO", "群聯"))
    result = run(sink, added, run_id="2")
    assert result["kind"] == "baseline"
    assert [(c["symbol"], c["item"]) for c in result["changes"]] == [
        ("8299.TWO", "pb_zone"), ("8299.TWO", "momentum")]
    comment = sink.comments[901][-1]
    assert "## 初始狀態（基線）：2026-10-30" in comment and "2408.TW" not in comment
    assert "| 8299.TWO 群聯 | 股價淨值比區間 | — → 合理區間 |" in comment


def test_an_item_first_seen_as_not_evaluated_waits_for_its_first_value():
    sink = FakeSink([schema_one_issue()])
    first = run(sink, with_industry(receipt(day="2026-10-30"), industry_row(zone_value="not_evaluated")))
    assert [(c["item"], c["new"]) for c in first["changes"]] == [("momentum", "ok")]
    assert industry_stored(sink, 139)["2408.TW"] == {"pb_zone": None, "momentum": "ok"}
    later = run(sink, with_industry(receipt(day="2026-10-31"), industry_row()), run_id="2")
    assert later["kind"] == "baseline"
    assert [(c["item"], c["old"], c["new"]) for c in later["changes"]] == [("pb_zone", None, "fair")]


def test_invalid_industry_state_is_rebuilt():
    state = {"schema": 2, "symbols": {}, "industry": {"2408.TW": {"pb_zone": "cheap", "momentum": "ok"}}}
    sink = FakeSink([{"number": 5, "state": "open",
                      "body": MARKER + "\n<!-- watchlist-alert-state:" + json.dumps(state) + " -->\n"}])
    result = run(sink, with_industry(receipt(), *TWO))
    assert result["kind"] == "rebuilt" and result["note"] == "2408.TW 的狀態值無效"
    assert "## 重建基線" in sink.comments[5][0]
