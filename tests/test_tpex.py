"""#144: TPEx (.TWO) daily bars from FinMind TaiwanStockPrice, no reference price."""
from datetime import date, datetime, timezone
import json
import math
from pathlib import Path

import pytest

from market_research.price_watch import evaluate_price_watch, load_price_watch, price_watch_notes
from market_research.provider import RoutedDailyProvider
from market_research.tpex import FinMindTpexDailyProvider, parse_finmind_price
from market_research.twse import COLUMNS, TAIEX, TwseDailyProvider, TwseIndexProvider
from test_price_watch import LAST, FrameProvider, bars, sessions

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "finmind_taiwan_stock_price_raw_ohlcv"


def payload(code, days, closes, volume=1000):
    return {"status": 200, "msg": "success", "data": [
        {"date": d.isoformat(), "stock_id": code, "Trading_Volume": volume, "Trading_money": 0,
         "open": c, "max": c * 1.01, "min": c * 0.99, "close": c, "spread": 0.0,
         "Trading_turnover": 1} for d, c in zip(days, closes)]}


def fixture_payload():
    # FinMind TaiwanStockPrice for 8299, fetched 2026-10-31.
    fixture = json.loads((ROOT / "tests" / "fixtures" / "finmind_price_8299.json").read_text())
    return {"status": 200, "data": [dict(zip(fixture["fields"], r), stock_id="8299")
                                    for r in fixture["rows"]]}


# ---------------------------------------------------------------- routing

def test_router_sends_two_to_the_tpex_provider_and_leaves_the_rest():
    stock, index, otc, us = TwseDailyProvider(), TwseIndexProvider(), FinMindTpexDailyProvider(), object()
    router = RoutedDailyProvider(taiwan=stock, taiwan_index=index, united_states=us, taiwan_otc=otc)
    assert router.provider_for("8299.TWO") is otc
    assert router.provider_for("2408.TW") is stock and router.provider_for("0050.TW") is stock
    assert router.provider_for(TAIEX) is index
    assert router.provider_for("AAPL") is us and router.provider_for("SNDK") is us
    assert RoutedDailyProvider().provider_for("8299.TWO").source == SOURCE


# ---------------------------------------------------------------- provider

def test_provider_requests_thirteen_months_of_raw_bars_without_reference():
    urls = []

    def get(url):
        urls.append(url)
        days = sessions("2026-10-27", "2026-10-29")
        body = payload("8299", days, [100.0, 104.0, 102.0])
        body["data"][1]["Trading_Volume"] = 0  # suspended: excluded, never priced
        return body

    frame = FinMindTpexDailyProvider(get=get, today=date(2026, 10, 31)).load("8299.TWO")
    assert urls == ["https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockPrice"
                    "&data_id=8299&start_date=2025-10-01"]
    assert list(frame.columns) == COLUMNS
    assert [d.isoformat() for d in frame.index] == ["2026-10-27", "2026-10-29"]
    assert (frame["high"].iloc[-1], frame["low"].iloc[-1]) == (102.0 * 1.01, 102.0 * 0.99)
    assert frame["reference_price"].isna().all() and frame["adj_close"].isna().all()
    assert (frame["execution_open"] == frame["open"]).all()


@pytest.mark.parametrize("body, symbol, match", [
    (payload("8299", [LAST], [100.0]), "8299.TW", "supports .TWO tickers"),
    (payload("2408", [LAST], [100.0]), "8299.TWO", "foreign stock_id 2408"),
    ({"status": 402, "msg": "limit"}, "8299.TWO", "invalid response shape"),
    (payload("8299", [LAST, LAST], [100.0, 100.0]), "8299.TWO", "duplicate trading dates"),
    (payload("8299", [], []), "8299.TWO", "no daily candles"),
])
def test_bad_payloads_fail_closed(body, symbol, match):
    with pytest.raises(ValueError, match=match):
        FinMindTpexDailyProvider(get=lambda url: body, today=LAST).load(symbol)


# ---------------------------------------------------------------- price position

def test_real_8299_position_is_computed_on_unadjusted_bars():
    frame = parse_finmind_price(fixture_payload(), "8299.TWO")
    row = evaluate_price_watch("8299.TWO", frame, source=SOURCE)
    # Expected values computed independently from the raw FinMind rows.
    assert (row["status"], row["session"], row["close"]) == ("available", "2026-10-30", 1930.0)
    assert (row["drawdown_52w"]["pct"], row["drawdown_52w"]["high"],
            row["drawdown_52w"]["high_date"]) == (-32.99, 2880.0, "2026-05-14")
    assert (row["ma_200"]["pct"], row["ma_200"]["average"]) == (-4.78, 2026.8)
    assert row["adjustments"] == {"reference_breaks": [], "unadjusted_dates": [],
                                  "no_reference_price": True}
    assert price_watch_notes(row) == "無參考價，未還原（每日比照不比價日）"


def test_gap_beyond_the_split_ratio_blocks_the_windows_containing_it():
    days = sessions("2025-09-01", LAST)
    split = days.index(date(2026, 3, 31))
    closes = [400.0] * split + [180.0] * (len(days) - split)  # 1:2.2 without a reference
    frame = parse_finmind_price(payload("8299", days, closes), "8299.TWO")
    row = evaluate_price_watch("8299.TWO", frame, source=SOURCE)
    assert row["status"] == "partial" and row["close"] == 180.0
    assert row["drawdown_52w"]["reason"] == "無參考價，價格斷層無法還原：2026-03-31"
    assert row["ma_200"]["reason"] == "無參考價，價格斷層無法還原：2026-03-31"
    # A limit-sized 10% move is a price change, not a gap.
    closes = [400.0] * split + [360.0] * (len(days) - split)
    moved = evaluate_price_watch("8299.TWO", parse_finmind_price(payload("8299", days, closes), "8299.TWO"),
                                 source=SOURCE)
    assert moved["status"] == "available"
    assert moved["drawdown_52w"]["pct"] == round((360 / (400 * 1.01) - 1) * 100, 2)  # high = 1.01 x close


def test_tpex_bars_not_on_the_latest_session_are_never_priced():
    days = sessions("2025-09-01", LAST)
    otc = FinMindTpexDailyProvider(get=lambda url: payload("8299", days, [100.0] * len(days)),
                                   today=date(2026, 10, 30))
    # TWSE closures check is stubbed out: a provider without unscheduled_closures.
    router = RoutedDailyProvider(taiwan=FrameProvider({}), taiwan_otc=otc, united_states=object(),
                                 taiwan_index=object())
    evening = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    [fresh] = load_price_watch(["8299.TWO"], evening, provider=router)
    assert (fresh["status"], fresh["source"], fresh["session"]) == ("available", SOURCE, "2026-10-29")
    next_evening = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    [stale] = load_price_watch(["8299.TWO"], next_evening, provider=router)
    assert stale["status"] == "failed" and stale["error_type"] == "StaleMarketData"
    assert "2026-10-29" in stale["reason"]


def test_listed_frames_keep_their_x_day_wording():
    days = sessions("2025-09-01", LAST)
    closes = [100.0] * len(days)
    reference = closes[:1] + closes[:-1]
    reference[-5] = math.nan  # one 'X' day among published references
    row = evaluate_price_watch("0050.TW", bars(days, closes, reference=reference),
                               source="twse_stock_day_official_raw_ohlcv")
    assert "no_reference_price" not in row["adjustments"]
    assert row["adjustments"]["unadjusted_dates"] == [days[-5].isoformat()]
