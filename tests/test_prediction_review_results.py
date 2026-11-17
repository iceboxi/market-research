"""#183 PL2: due price predictions are judged from official daily bars and announced once."""
from datetime import date, datetime

import pandas as pd
import pytest

from scripts.prediction_review import MARKER, period_since, sync
from tests.test_prediction_review import FakeSink

RUN_URL = "https://github.com/iceboxi/market-research/actions/runs/{}"
SEEN = {"first_seen": datetime.fromisoformat("2026-11-18T00:03:59+08:00")}  # start 11/17
SESSIONS = ["2026-11-16", "2026-11-17", "2026-11-18", "2026-11-19", "2026-11-20", "2026-11-23",
            "2026-11-24", "2026-11-25", "2026-11-26", "2026-11-27", "2026-11-30", "2026-12-01",
            "2026-12-02"]


def at(day):
    return datetime.fromisoformat(f"{day}T16:00:00+08:00")  # after that day's close + 60 minutes


def bars(closes, lows=None, highs=None, dates=SESSIONS, reference=None):
    """Official-looking bars; the reference price is the previous close unless given."""
    dates = dates[:len(closes)]
    lows = lows or [c * 0.99 for c in closes]
    highs = highs or [c * 1.01 for c in closes]
    reference = reference or [closes[0], *closes[:-1]]
    frame = pd.DataFrame({"open": closes, "high": highs, "low": lows, "close": closes,
                          "volume": [1] * len(closes), "reference_price": reference},
                         index=pd.to_datetime(dates))
    return frame


def entry(pid, claim, horizon, trigger="inference", **extra):
    return {"id": pid, "trigger": trigger, "method": "judgment", "reasoning": "r", "claim": claim,
            "horizon_sessions": horizon, "probability": 0.55, **extra}


TAIEX_UP = {"kind": "return", "symbol": "TAIEX", "op": ">", "threshold_pct": 0}
WEEKLY = entry("W-20261117-taiex", TAIEX_UP, 5, trigger="weekly")


def run(entries, now, frames=None, sink=None, run_id="1", fail=()):
    sink = sink or FakeSink()
    calls = []

    def bars_fn(symbol, since):
        calls.append((symbol, since))
        if symbol in fail:
            raise ConnectionError("TWSE 連線中斷")
        return frames[symbol]
    result = sync(sink, entries, {e["id"]: SEEN for e in entries}, now, run_id=run_id,
                  run_url=RUN_URL.format(run_id), bars_fn=bars_fn)
    return sink, result, {r["id"]: r for r in result["records"]}, calls


# 11/16 … 11/24: start 11/17 = 40,092.11, check 11/24 (5th session after)
UP_WEEK = [41040.08, 40092.11, 40500.0, 39500.0, 39900.0, 40300.0, 40500.0]


@pytest.mark.parametrize("check_close, status, pct", [(40500.0, "hit", 1.0174), (39000.0, "miss", -2.7240)])
def test_return_claim(check_close, status, pct):
    _, _, records, calls = run([WEEKLY], at("2026-11-24"), {"TAIEX": bars(UP_WEEK[:-1] + [check_close])})
    record = records["W-20261117-taiex"]
    assert (record["status"], record["check_session"], record["start_close"]) == (status, "2026-11-24", 40092.11)
    assert record["return_pct"] == pytest.approx(pct, abs=1e-4)
    assert calls == [("TAIEX", date(2026, 11, 17))]


@pytest.mark.parametrize("close, status", [(42000.0, "hit"), (43500.0, "miss")])
def test_close_at_check_claim(close, status):
    claim = {"kind": "close_at_check", "symbol": "TAIEX", "op": "<", "level": 43307.54}
    closes = [41040.08, 40092.11] + [41000.0] * 10 + [close]
    _, _, records, _ = run([entry("P-20261117-43307", claim, 11)], at("2026-12-02"), {"TAIEX": bars(closes)})
    record = records["P-20261117-43307"]
    assert (record["status"], record["check_session"], record["check_close"]) == (status, "2026-12-02", close)


HELD_LOW = {"kind": "held", "symbol": "TAIEX", "op": ">", "level": 37837.05, "basis": "intraday"}


@pytest.mark.parametrize("window_low, status", [(38000.0, "hit"), (37800.0, "miss")])
def test_held_intraday_uses_the_lowest_low_after_the_start(window_low, status):
    closes = [41040.08, 40092.11] + [40000.0] * 10
    # The start day's own low (37,000) is outside the window and never counts.
    lows = [40000.0, 37000.0] + [39000.0] * 4 + [window_low] + [39000.0] * 5
    _, _, records, _ = run([entry("P-20261117-37837", HELD_LOW, 10)], at("2026-12-01"),
                           {"TAIEX": bars(closes, lows=lows)})
    record = records["P-20261117-37837"]
    assert (record["status"], record["extreme"], record["extreme_session"]) == (status, window_low, "2026-11-24")
    assert record["check_session"] == "2026-12-01"


def test_held_close_below_uses_the_highest_close():
    claim = {"kind": "held", "symbol": "TAIEX", "op": "<", "level": 41000.0, "basis": "close"}
    closes = [41040.08, 40092.11, 40500.0, 40900.0, 40100.0, 40200.0, 40300.0]
    _, _, records, _ = run([entry("P-20261117-cap", claim, 5)], at("2026-11-24"), {"TAIEX": bars(closes)})
    record = records["P-20261117-cap"]
    assert (record["status"], record["extreme"], record["extreme_session"]) == ("hit", 40900.0, "2026-11-19")


def test_missing_bars_are_not_evaluated_then_judged_and_announced_once():
    short = bars(UP_WEEK[:5])  # bars stop at 11/20; 11/24 is due
    sink, first, records, _ = run([WEEKLY], at("2026-11-24"), {"TAIEX": short}, run_id="1")
    assert records["W-20261117-taiex"]["status"] == "not_evaluated"
    assert "缺 2026-11-24 以前的行情" in records["W-20261117-taiex"]["reason"]
    assert first["comment"] == "not_needed" and sink.comments == {}
    _, second, records, _ = run([WEEKLY], at("2026-11-25"), {"TAIEX": bars(UP_WEEK + [40600.0])},
                                sink=sink, run_id="2")
    assert records["W-20261117-taiex"]["status"] == "hit" and second["comment"] == "posted"
    [comment] = sink.comments[901]
    assert "<!-- prediction-review-run:2 -->" in comment
    assert ("| `W-20261117-taiex` | 加權指數 5 個交易日報酬 > 0% | 0.55 | 2026-11-17 | 2026-11-24 | "
            "命中：報酬 +1.02%；2026-11-17 收 40,092.11 → 2026-11-24 收 40,500.00 |") in comment
    _, third, _, _ = run([WEEKLY], at("2026-11-26"), {"TAIEX": bars(UP_WEEK + [40600.0, 40700.0])},
                         sink=sink, run_id="3")
    assert third["comment"] == "not_needed" and len(sink.comments[901]) == 1


def test_source_failure_leaves_only_that_symbol_not_evaluated():
    etf = entry("P-20261117-0050", {"kind": "return", "symbol": "0050.TW", "op": ">", "threshold_pct": 0}, 5)
    frames = {"0050.TW": bars([92.0, 90.0, 91.0, 92.0, 93.0, 94.0, 95.0])}
    _, _, records, _ = run([WEEKLY, etf], at("2026-11-24"), frames, fail=("TAIEX",))
    assert records["W-20261117-taiex"]["status"] == "not_evaluated"
    assert records["W-20261117-taiex"]["reason"] == "行情取得失敗：ConnectionError：TWSE 連線中斷"
    assert records["P-20261117-0050"]["status"] == "hit"


def test_a_closed_day_delays_the_check_session():
    dates = [d for d in SESSIONS if d != "2026-11-20"]  # typhoon closure
    frame = bars([41040.08, 40092.11, 40500.0, 39500.0, 40300.0, 40500.0], dates=dates)
    _, _, records, _ = run([WEEKLY], at("2026-11-24"), {"TAIEX": frame})
    record = records["W-20261117-taiex"]
    assert record["status"] == "pending" and "休市使檢查日延後（已有 4／5 個交易日）" in record["reason"]


def test_a_split_inside_the_window_is_undone():
    # 1:4 split on 11/19: TWSE publishes reference 25 against the previous close 100.
    closes = [101.0, 100.0, 100.0, 25.5, 25.6, 25.8, 26.0]
    reference = [101.0, 101.0, 100.0, 25.0, 25.5, 25.6, 25.8]
    etf = entry("P-20261117-0050", {"kind": "return", "symbol": "0050.TW", "op": ">", "threshold_pct": 0}, 5)
    _, _, records, _ = run([etf], at("2026-11-24"), {"0050.TW": bars(closes, reference=reference)})
    record = records["P-20261117-0050"]
    assert (record["status"], record["start_close"]) == ("hit", 100.0)
    assert record["return_pct"] == pytest.approx(4.0)  # 26.0 × 4 ÷ 100 − 1, not −74%


def test_a_gap_without_reference_prices_is_not_judged():
    otc = entry("P-20261117-8299", {"kind": "return", "symbol": "8299.TWO", "op": ">", "threshold_pct": 0}, 5)
    frame = bars([1600.0, 1635.0, 1640.0, 820.0, 830.0, 840.0, 850.0]).drop(columns="reference_price")
    _, _, records, _ = run([otc], at("2026-11-24"), {"8299.TWO": frame})
    assert records["P-20261117-8299"]["status"] == "not_evaluated"
    assert records["P-20261117-8299"]["reason"] == "價格斷層無法還原：2026-11-19"


def test_manual_claim_awaits_review_then_shows_the_written_outcome():
    manual = entry("E-20261117-guide", {"kind": "manual", "text": "輝達第四季營收指引中值高於 1,150 億美元"}, 1,
                   trigger="event", event="輝達財報", event_time="2026-11-17T16:00:00-05:00")
    sink, result, records, calls = run([manual], at("2026-11-18"))
    assert records["E-20261117-guide"]["status"] == "awaiting_review" and calls == []
    assert result["comment"] == "posted" and "待人工判定" in sink.comments[901][0]
    reviewed = {**manual, "review": {"date": "2026-11-19", "cause": "correct", "note": "n",
                                     "action": "keep", "outcome": "hit"}}
    _, result, records, _ = run([reviewed], at("2026-11-19"), sink=sink, run_id="2")
    assert (records["E-20261117-guide"]["status"], records["E-20261117-guide"]["reason"]) == ("hit", "人工判定（2026-11-19）")


def test_first_run_announces_everything_already_due_in_one_comment():
    late = entry("E-20261117-late", TAIEX_UP, 1, trigger="event", event="財報",
                 event_time="2026-11-17T10:00:00-05:00")  # merged after the event
    sink, result, records, _ = run([WEEKLY, late], at("2026-11-24"), {"TAIEX": bars(UP_WEEK)})
    assert result["changes"] == ["W-20261117-taiex", "E-20261117-late"]
    [comment] = sink.comments[901]
    assert "命中" in comment and "作廢：事件發生後才合併" in comment


def test_a_rerun_of_the_same_run_never_comments_twice():
    # The comment landed but the body update did not (state still empty).
    sink = FakeSink([{"number": 7, "body": MARKER, "state": "open"}])
    sink.comments[7] = ["<!-- prediction-review-run:1 --> earlier"]
    _, result, _, _ = run([WEEKLY], at("2026-11-24"), {"TAIEX": bars(UP_WEEK)}, sink=sink, run_id="1")
    assert result["comment"] == "already_posted" and len(sink.comments[7]) == 1
    assert '"announced":{"W-20261117-taiex":"hit"}' in sink.issues[7]["body"]


def test_nothing_due_fetches_no_prices():
    _, result, records, calls = run([WEEKLY], at("2026-11-23"), {})
    assert calls == [] and records["W-20261117-taiex"]["status"] == "pending" and result["comment"] == "not_needed"


@pytest.mark.parametrize("since, period", [(date(2026, 11, 17), "3mo"), (date(2026, 6, 1), "6mo"),
                                           (date(2025, 12, 1), "1y"), (date(2024, 12, 1), "2y")])
def test_period_reaches_back_to_the_earliest_start(since, period):
    assert period_since(since, date(2026, 11, 18)) == period


def test_period_beyond_the_source_fails():
    with pytest.raises(ValueError, match="早於行情來源支援的範圍"):
        period_since(date(2018, 1, 1), date(2026, 11, 18))
