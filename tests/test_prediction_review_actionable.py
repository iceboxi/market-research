"""#183: predictions that can be acted on — range claims, held misses on the first breach, and the
decision rule each result maps to."""
from datetime import date, datetime

import pytest

from market_research.knowledge_site import LinkMapper, render_markdown
from market_research.prediction_review import base_rate, edited_fields, evaluate, range_coverage
from scripts.prediction_review import render_page, render_scorecard
from tests.test_prediction_review_results import UP_WEEK, at, bars, entry, run
from tests.test_prediction_review_scorecard import START, history

DECISION = {"rule": "0050 停止加碼：收盤跌破 37,837", "if_hit": "停止加碼維持",
            "if_miss": "被迫賣出還有下一段，不提前分批"}
HELD_LOW = {"kind": "held", "symbol": "TAIEX", "op": ">", "level": 37837.05, "basis": "intraday"}
RANGE = {"kind": "range", "symbol": "TAIEX", "low": 39000, "high": 41000}


# ---------------------------------------------------------------- range


@pytest.mark.parametrize("check_close, status", [(40500.0, "hit"), (41000.0, "hit"), (39000.0, "hit"),
                                                 (41000.5, "miss"), (38999.5, "miss")])
def test_range_claim_holds_the_check_close_inclusive(check_close, status):
    sink, _, records, _ = run([entry("P-20261117-range", RANGE, 5)], at("2026-11-24"),
                              {"TAIEX": bars(UP_WEEK[:-1] + [check_close])})
    record = records["P-20261117-range"]
    assert (record["status"], record["check_session"], record["check_close"]) == (status, "2026-11-24", check_close)
    assert record["condition"] == "加權指數 第 5 個交易日收盤在 39,000–41,000 之間"
    inside = 1 if status == "hit" else 0
    width = (41000 - 39000) / 40092.11 * 100
    assert f"| 0.55 | 1 | {inside} | {inside:.2f} | {width:.1f}% |" in sink.issues[901]["body"]


def test_range_base_rate_counts_closes_inside_the_band():
    # Closes alternate 1000, 1010: every 2-session change is exactly 0.
    frame = history(lambda i: 1000 + (i % 2) * 10)
    start_close = float(frame["close"].iloc[-1])
    around = {**RANGE, "low": start_close * 0.99, "high": start_close * 1.01}
    above = {**RANGE, "low": start_close * 1.001, "high": start_close * 1.01}
    assert base_rate(around, 2, START, frame)["rate"] == 1.0
    assert base_rate(above, 2, START, frame)["rate"] == 0.0
    # One session: half the changes are +1%, half about −0.99%; a band of [−0.5%, +1.5%] holds only the rises.
    band = {**RANGE, "low": start_close * 0.995, "high": start_close * 1.015}
    closes = frame["close"].to_numpy()
    starts = [i for i, d in enumerate(frame.index) if d.date() >= date(2021, 11, 17) and i + 1 < len(frame)]
    expected = sum(1 for i in starts if -0.005 <= closes[i + 1] / closes[i] - 1 <= 0.015) / len(starts)
    rate = base_rate(band, 1, START, frame)["rate"]
    assert rate == pytest.approx(round(expected, 4)) and 0.4 < rate < 0.6


def coverage_record(status, probability, low, high, start_close=36000.0, kind="range"):
    claim = {"kind": kind, "symbol": "TAIEX", "low": low, "high": high}
    return {"id": f"x{low}", "status": status, "probability": probability, "method": "judgment",
            "method_version": None, "claim": claim, "start_close": start_close, "base_rate": None}


def test_range_coverage_by_stated_probability():
    records = [coverage_record("hit", 0.5, 35100, 36900), coverage_record("miss", 0.5, 35460, 36540),
               coverage_record("hit", 0.8, 34200, 37800), coverage_record("pending", 0.8, 1, 2),
               {**coverage_record("hit", 0.5, 1, 2), "claim": {"kind": "return"}}]
    half, wide = range_coverage(records)
    assert (half["probability"], half["judged"], half["inside"], half["coverage"]) == (0.5, 2, 1, 0.5)
    assert half["mean_width_pct"] == pytest.approx((5.0 + 3.0) / 2)
    assert (wide["judged"], wide["coverage"], wide["mean_width_pct"]) == (1, 1.0, pytest.approx(10.0))
    table = render_scorecard(records)
    assert "| 0.50 | 2 | 1 | 0.50 | 4.0% |" in table and "| 0.80 | 1 | 1 | 1.00 | 10.0% |" in table


def test_no_range_prediction_adds_no_coverage_table():
    assert not any("設定機率" in line for line in render_scorecard([coverage_record("hit", 0.5, 1, 2, kind="return")]))


# ---------------------------------------------------------------- held: miss on the first breach


def held_lows(breach_low):
    # 11/16 … 11/20; the start day's own low (37,000) never counts.
    return [40000.0, 37000.0, 39000.0, 39000.0, breach_low]


def test_a_breach_before_the_check_session_is_a_miss_at_once():
    held = entry("P-20261117-37837", HELD_LOW, 10, decision=DECISION)
    frame = bars(UP_WEEK[:5], lows=held_lows(35738.68))
    sink, result, records, calls = run([held], at("2026-11-20"), {"TAIEX": frame})
    record = records["P-20261117-37837"]
    assert (record["status"], record["breach_session"], record["breach_price"]) == ("miss", "2026-11-20", 35738.68)
    assert record["decided_early"] is True and record["expected_check_session"] == "2026-12-01"
    assert calls == [("TAIEX", date(2026, 11, 17))] and result["changes"] == ["P-20261117-37837"]
    [comment] = sink.comments[901]
    assert "未命中：2026-11-20 最低價 35,738.68，未到檢查日就確定；2026-11-17 收 40,092.11" in comment
    assert "- `P-20261117-37837` 未命中：被迫賣出還有下一段，不提前分批（規則：0050 停止加碼：收盤跌破 37,837）" in comment


def test_held_without_a_breach_stays_pending_until_due():
    held = entry("P-20261117-37837", HELD_LOW, 10)
    _, result, records, calls = run([held], at("2026-11-20"), {"TAIEX": bars(UP_WEEK[:5], lows=held_lows(38000.0))})
    assert (records["P-20261117-37837"]["status"], records["P-20261117-37837"]["reason"]) == ("pending", None)
    assert calls == [("TAIEX", date(2026, 11, 17))] and result["changes"] == []  # 11/20 is a Friday: only the weekly reminder


def test_a_failed_source_leaves_a_held_prediction_pending_before_it_is_due():
    held = entry("P-20261117-37837", HELD_LOW, 10)
    _, _, records, _ = run([held], at("2026-11-20"), {}, fail=("TAIEX",))
    assert (records["P-20261117-37837"]["status"], records["P-20261117-37837"]["reason"]) == ("pending", None)


def test_touching_the_level_is_a_breach_for_a_close_cap():
    cap = {"kind": "held", "symbol": "TAIEX", "op": "<", "level": 41000, "basis": "close"}
    closes = [41040.08, 40092.11, 40500.0, 41000.0, 40100.0]  # 11/19 closes exactly on the level
    _, _, records, _ = run([entry("P-20261117-cap", cap, 21)], at("2026-11-20"), {"TAIEX": bars(closes)})
    record = records["P-20261117-cap"]
    assert (record["status"], record["breach_session"], record["breach_price"]) == ("miss", "2026-11-19", 41000.0)


def test_an_unexplained_gap_is_never_an_early_miss():
    otc = entry("P-20261117-8299", {"kind": "held", "symbol": "8299.TWO", "op": ">", "level": 1500, "basis": "intraday"}, 10)
    frame = bars([1600.0, 1635.0, 1640.0, 820.0, 830.0]).drop(columns="reference_price")
    _, _, records, _ = run([otc], at("2026-11-20"), {"8299.TWO": frame})
    assert records["P-20261117-8299"]["status"] == "pending"


def test_other_claims_fetch_nothing_before_they_are_due():
    _, _, records, calls = run([entry("P-20261117-range", RANGE, 5)], at("2026-11-20"), {})
    assert calls == [] and records["P-20261117-range"]["status"] == "pending"


# ---------------------------------------------------------------- the decision rule


def test_the_decision_cannot_change_after_first_seen():
    original = entry("P-20261121-39385", HELD_LOW, 21, decision=DECISION)
    assert edited_fields(original, {**original, "decision": {**DECISION, "if_miss": "改寫"}}) == ["decision"]
    seen = {"first_seen": datetime.fromisoformat("2026-11-18T00:03:59+08:00"), "entry": original}
    changed = {**original, "decision": {**DECISION, "if_miss": "改寫"}}
    [record] = evaluate([changed], {original["id"]: seen}, at("2026-11-20"))
    assert record["status"] == "void" and "decision" in record["reason"]


def test_the_page_lists_each_rule_under_its_reasoning():
    held = entry("P-20261117-37837", HELD_LOW, 10, decision=DECISION)
    _, result, _, _ = run([held], at("2026-11-20"), {"TAIEX": bars(UP_WEEK[:5], lows=held_lows(38000.0))})
    page = render_page(result["records"], [held], result["as_of"], "https://example.invalid/run/1")
    assert ("### P-20261117-37837\n\nr\n\n- 對應規則：0050 停止加碼：收盤跌破 37,837\n- 命中時：停止加碼維持\n"
            "- 未命中時：被迫賣出還有下一段，不提前分批\n") in page
    body, _ = render_markdown(page, LinkMapper({"README.md", "predictions.md"}))
    assert "<li>對應規則：0050 停止加碼：收盤跌破 37,837</li>" in body

