"""#113: TAIEX provider and the core ETF / benchmark price watch (display only)."""
from datetime import date, datetime, timedelta, timezone
import json
import math

import exchange_calendars as xcals
import httpx
import pandas as pd
import pytest

from market_research.price_watch import evaluate_price_watch, load_price_watch
from market_research.provider import RoutedDailyProvider
from market_research.research_site import _report_records, render_research_site_html
from market_research.twse import (
    TAIEX, TWSE_INDEX_URL, TWSE_MARKET_URL, TwseDailyProvider, TwseIndexProvider,
    merge_index_month, parse_index_history, parse_market_turnover, parse_stock_day,
)
from scripts.daily_research import execute, get_benchmarks
from test_company_report_feedback import NOW, source_clock  # noqa: F401
from test_daily_research import Sources, delivered
from test_research_site import _sample_report
from test_scan_company_research import artifacts

INDEX_FIELDS = ["日期", "開盤指數", "最高指數", "最低指數", "收盤指數"]
MARKET_FIELDS = ["日期", "成交股數", "成交金額", "成交筆數", "發行量加權股價指數", "漲跌點數"]
CAL = xcals.get_calendar("XTAI")
SOURCE = "twse_stock_day_official_raw_ohlcv"


# ---------------------------------------------------------------- TWSE parsing

def test_index_month_parses_roc_dates_and_thousands_separators():
    frame = parse_index_history({"stat": "OK", "fields": INDEX_FIELDS, "data": [
        ["115/10/28", "46,402.79", "47,060.46", "46,402.79", "47,035.58"],
        ["115/10/29", "47,014.87", "47,015.45", "46,055.07", "46,368.33"]]})
    assert list(frame["date"]) == [date(2026, 10, 28), date(2026, 10, 29)]
    assert frame.iloc[1][["open", "high", "low", "close"]].tolist() == [
        47014.87, 47015.45, 46055.07, 46368.33]


def test_empty_index_month_is_empty_not_an_error():
    assert parse_index_history({"stat": "OK", "fields": INDEX_FIELDS, "data": []}).empty
    assert parse_market_turnover({"stat": "OK", "fields": MARKET_FIELDS, "data": []}).empty


@pytest.mark.parametrize("payload, match", [
    ({"stat": "OK", "fields": INDEX_FIELDS,
      "data": [["115/10/29", "47,014.87", "--", "46,055.07", "46,368.33"]]}, "missing index values"),
    ({"stat": "查詢日期大於今日，請重新查詢!"}, "查詢日期大於今日"),
])
def test_missing_index_values_or_status_fail_closed(payload, match):
    with pytest.raises(ValueError, match=match):
        parse_index_history(payload)


def test_market_turnover_gives_volume_and_previous_close_reference():
    frame = parse_market_turnover({"stat": "OK", "fields": MARKET_FIELDS, "data": [
        ["115/10/29", "10,121,315,552", "823,812,748,529", "4,702,463", "46,368.33", "-667.25"]]})
    row = frame.iloc[0]
    assert row["volume"] == 10_121_315_552
    assert row["reference_price"] == 47035.58  # 10/28 close


def test_index_and_market_reports_must_agree():
    index = parse_index_history({"stat": "OK", "fields": INDEX_FIELDS, "data": [
        ["115/10/29", "47,014.87", "47,015.45", "46,055.07", "46,368.33"]]})
    shifted = parse_market_turnover({"stat": "OK", "fields": MARKET_FIELDS, "data": [
        ["115/10/28", "1", "1", "1", "46,368.33", "0"]]})
    other_close = parse_market_turnover({"stat": "OK", "fields": MARKET_FIELDS, "data": [
        ["115/10/29", "1", "1", "1", "46,368.30", "0"]]})
    with pytest.raises(ValueError, match="trading dates differ"):
        merge_index_month(index, shifted)
    with pytest.raises(ValueError, match="closes differ"):
        merge_index_month(index, other_close)


def test_stock_day_keeps_twse_reference_price():
    fields = ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差",
              "成交筆數", "註記"]
    frame = parse_stock_day({"stat": "OK", "fields": fields, "data": [
        ["115/03/30", "1", "1", "440.00", "445.00", "439.00", "443.15", "+3.15", "1", ""],
        ["115/03/31", "1", "1", "20.10", "20.20", "19.20", "19.26", "-0.88", "1", ""],
        ["115/07/21", "1", "1", "102.00", "103.00", "101.00", "102.50", "X0.00", "1", ""],
        ["115/07/22", "1", "1", "102.00", "103.00", "101.00", "102.50", " 0.00", "1", ""]]},
        "00631L.TW")
    assert frame["reference_price"].iloc[0] == 440.0
    assert frame["reference_price"].iloc[1] == 20.14  # split: 443.15 / 22, rounded by TWSE
    assert math.isnan(frame["reference_price"].iloc[2])  # 'X' = 不比價
    assert frame["reference_price"].iloc[3] == 102.5


def index_get(calls, empty_month=None, broken_market_month=None):
    def get(url, **kwargs):
        month = kwargs["params"]["date"]
        calls.append((url, month))
        roc, mm = int(month[:4]) - 1911, month[4:6]
        if url == TWSE_INDEX_URL:
            data = [[f"{roc}/{mm}/15", "20,000.00", "20,100.00", "19,900.00", "20,050.00"]]
            payload = {"stat": "OK", "fields": INDEX_FIELDS, "data": data}
        else:
            assert url == TWSE_MARKET_URL
            if month == broken_market_month:
                raise httpx.ConnectError("fixture")
            data = [[f"{roc}/{mm}/15", "5,000,000,000", "1", "1", "20,050.00", "50.00"]]
            payload = {"stat": "OK", "fields": MARKET_FIELDS, "data": data}
        if month == empty_month:
            payload["data"] = []

        class Response:
            def raise_for_status(self):
                pass

            def json(self):
                return payload
        return Response()
    return get


def test_index_provider_merges_both_official_reports_per_month():
    calls = []
    provider = TwseIndexProvider(get=index_get(calls, empty_month="20261001"),
                                 today=date(2026, 10, 1), request_pause_seconds=0)
    frame = provider.load(TAIEX, "3mo")
    assert [m for _, m in calls] == [m for m in ("20260701", "20260801", "20260901", "20261001")
                                     for _ in range(2)]
    assert len(frame) == 3  # the current month has no session yet
    assert frame["volume"].iloc[-1] == 5_000_000_000
    assert frame["reference_price"].iloc[-1] == 20000.0
    assert list(frame.columns) == ["open", "high", "low", "close", "volume", "adj_close",
                                   "execution_open", "reference_price"]


def test_index_provider_fails_closed_when_one_report_fails():
    provider = TwseIndexProvider(get=index_get([], broken_market_month="20260801"),
                                 today=date(2026, 10, 17), request_pause_seconds=0,
                                 timeout_retries=0)
    with pytest.raises(ValueError, match="TWSE TAIEX: failed months: 2026-08-01"):
        provider.load(TAIEX, "3mo")
    with pytest.raises(ValueError, match="supports TAIEX"):
        provider.load("0050.TW", "3mo")


def test_router_sends_taiex_to_the_index_provider():
    index, stock = TwseIndexProvider(), TwseDailyProvider()
    router = RoutedDailyProvider(taiwan=stock, taiwan_index=index, united_states=object())
    assert router.provider_for(TAIEX) is index
    assert router.provider_for("0050.TW") is stock


# ---------------------------------------------------------------- evaluation

def sessions(first, last):
    return [s.date() for s in CAL.sessions_in_range(pd.Timestamp(first), pd.Timestamp(last))]


def bars(dates, closes, highs=None, reference=None):
    closes = [float(c) for c in closes]
    highs = [float(h) for h in (highs or closes)]
    if reference is None:
        reference = closes[:1] + closes[:-1]
    return pd.DataFrame({
        "open": closes, "high": highs, "low": [c * 0.99 for c in closes], "close": closes,
        "volume": 1000, "adj_close": float("nan"), "execution_open": closes,
        "reference_price": reference}, index=pd.Index(dates, name="date"))


LAST = date(2026, 10, 29)
WINDOW_START = LAST - timedelta(weeks=52)


def test_drawdown_and_moving_average_use_their_own_windows():
    dates = sessions("2025-09-01", LAST)
    closes = [100.0] * (len(dates) - 100) + [120.0] * 100
    highs = list(closes)
    outside = max(i for i, d in enumerate(dates) if d < WINDOW_START)
    highs[outside] = 300.0  # one session before the window: ignored
    peak = dates.index(date(2026, 3, 2))
    highs[peak] = 150.0
    row = evaluate_price_watch("0050.TW", bars(dates, closes, highs), source=SOURCE)
    assert row["status"] == "available"
    assert row["session"] == "2026-10-29" and row["close"] == 120.0
    assert row["drawdown_52w"] == {"status": "available", "pct": -20.0, "high": 150.0,
                                   "high_date": "2026-03-02", "window_start": "2025-10-30"}
    assert row["ma_200"]["pct"] == round((120 / 110 - 1) * 100, 2)  # 100 x 100 + 100 x 120
    assert row["ma_200"]["first_date"] == dates[-200].isoformat()
    assert row["name"] == "元大台灣50" and row["kind"] == "etf"


def test_short_history_is_not_evaluated_not_shortened():
    dates = sessions("2026-04-01", LAST)
    row = evaluate_price_watch("0050.TW", bars(dates, [100] * len(dates)), source=SOURCE)
    assert row["status"] == "partial"
    assert row["drawdown_52w"]["status"] == "not_evaluated"
    assert "資料不足 52 週" in row["drawdown_52w"]["reason"]
    assert row["ma_200"] == {"status": "not_evaluated",
                             "reason": f"只有 {len(dates)} 個交易日，需要 200"}


def test_window_starting_on_a_closed_day_is_still_covered():
    # 2025-01-28 was inside the Lunar New Year closure; 2025-02-03 was the next session.
    last = date(2026, 1, 27)
    dates = sessions("2025-02-03", last)
    covered = evaluate_price_watch("0050.TW", bars(dates, [100] * len(dates)), source=SOURCE)
    assert covered["drawdown_52w"]["status"] == "available"
    missing_first = dates[1:]
    short = evaluate_price_watch("0050.TW", bars(missing_first, [100] * len(missing_first)),
                                 source=SOURCE)
    assert short["drawdown_52w"]["status"] == "not_evaluated"


def split_series():
    """00631L-like: 1-for-22 split on 2026-03-31 (443.15 -> reference 20.14)."""
    dates = sessions("2025-09-01", LAST)
    split = dates.index(date(2026, 3, 31))
    after = [20.14 * (1 + 0.002 * i) for i in range(len(dates) - split)]
    before = [443.15 * (1 + 0.001 * (i - split + 1)) for i in range(split)]
    closes = before + after
    reference = closes[:1] + closes[:-1]
    reference[split] = 20.14
    return dates, closes, reference, split


def test_split_is_rescaled_by_the_published_reference_price():
    dates, closes, reference, split = split_series()
    row = evaluate_price_watch("00631L.TW", bars(dates, closes, reference=reference), source=SOURCE)
    factor = 20.14 / 443.15
    same_units = [c * factor for c in closes[:split]] + closes[split:]
    oracle = evaluate_price_watch("00631L.TW", bars(dates, same_units), source=SOURCE)
    assert row["status"] == "available"
    assert row["drawdown_52w"]["pct"] == oracle["drawdown_52w"]["pct"]
    assert row["ma_200"]["pct"] == oracle["ma_200"]["pct"]
    assert row["adjustments"]["reference_breaks"] == [{
        "date": "2026-03-31", "previous_close": round(closes[split - 1], 4),
        "reference_price": 20.14, "factor": round(20.14 / closes[split - 1], 6)}]
    assert row["note"] == "每日 2 倍槓桿，盤整時有波動侵蝕"
    unadjusted = evaluate_price_watch("00631L.TW", bars(dates, closes, reference=closes[:1] + closes[:-1]),
                                      source=SOURCE)
    assert unadjusted["drawdown_52w"]["pct"] < -90  # what the raw series would claim


def test_ex_dividend_day_stays_unadjusted_and_listed():
    dates = sessions("2025-09-01", LAST)
    closes = [100.0] * len(dates)
    ex = dates.index(date(2026, 7, 21))
    closes[ex:] = [98.0] * (len(dates) - ex)
    reference = closes[:1] + closes[:-1]
    reference[ex] = float("nan")
    row = evaluate_price_watch("0050.TW", bars(dates, closes, reference=reference), source=SOURCE)
    assert row["status"] == "available"
    assert row["drawdown_52w"]["pct"] == -2.0
    assert row["adjustments"] == {"reference_breaks": [], "unadjusted_dates": ["2026-07-21"]}


def test_unexplained_gap_on_an_x_day_blocks_only_the_windows_containing_it():
    dates, closes, reference, split = split_series()
    reference[split] = float("nan")  # no published reference: cannot rescale
    row = evaluate_price_watch("00631L.TW", bars(dates, closes, reference=reference), source=SOURCE)
    assert row["status"] == "partial"
    assert row["drawdown_52w"]["reason"] == "不比價日價格斷層無法還原：2026-03-31"
    assert row["ma_200"]["reason"] == "不比價日價格斷層無法還原：2026-03-31"
    old = sessions("2024-09-02", LAST)
    early = len(old) - len(dates) + 5  # a gap before both windows is irrelevant
    closes = [400.0] * early + [20.0] * (len(old) - early)
    reference = closes[:1] + closes[:-1]
    reference[early] = float("nan")
    clean = evaluate_price_watch("00631L.TW", bars(old, closes, reference=reference), source=SOURCE)
    assert clean["status"] == "available" and clean["adjustments"]["unadjusted_dates"] == []


def test_frame_without_reference_prices_cannot_claim_adjusted_measures():
    dates = sessions("2025-09-01", LAST)
    frame = bars(dates, [100] * len(dates)).drop(columns="reference_price")
    row = evaluate_price_watch("0050.TW", frame, source="checksummed_local_replay")
    assert row["status"] == "partial" and row["close"] == 100.0
    assert row["drawdown_52w"]["reason"] == "無 TWSE 參考價，無法確認分割等價格斷層"


class FrameProvider:
    source = SOURCE

    def __init__(self, frames, failing=()):
        self.frames, self.failing, self.loaded = frames, failing, []

    def load(self, symbol, period="1y"):
        self.loaded.append((symbol, period))
        if symbol in self.failing:
            raise httpx.ReadTimeout("fixture")
        return self.frames[symbol]


def test_unfinished_session_is_never_used_and_stale_data_fails():
    dates = sessions("2025-09-01", LAST)
    closes = [100.0] * (len(dates) - 1) + [500.0]  # 10/29 intraday bar
    provider = FrameProvider({"0050.TW": bars(dates, closes)})
    intraday = datetime(2026, 10, 29, 2, 0, tzinfo=timezone.utc)  # 10:00 Taipei
    [row] = load_price_watch(["0050.TW"], intraday, provider=provider)
    assert row["session"] == "2026-10-28" and row["close"] == 100.0
    assert row["drawdown_52w"]["pct"] == 0.0
    assert provider.loaded == [("0050.TW", "1y")]
    next_evening = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    [stale] = load_price_watch(["0050.TW"], next_evening, provider=provider)
    assert stale["status"] == "failed" and stale["error_type"] == "StaleMarketData"


def test_one_source_failure_leaves_the_other_rows():
    dates = sessions("2025-09-01", LAST)
    provider = FrameProvider({"0050.TW": bars(dates, [100] * len(dates))}, failing=("00631L.TW",))
    evening = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)
    rows = load_price_watch(["0050.TW", "00631L.TW"], evening, provider=provider)
    assert [r["status"] for r in rows] == ["available", "failed"]
    assert rows[1]["error_type"] == "ReadTimeout" and rows[1]["name"] == "元大台灣50正2"


# ---------------------------------------------------------------- daily outputs

def watch_rows(status="available"):
    def row(symbol, pct):
        return {"symbol": symbol, "name": {"TAIEX": "發行量加權股價指數"}.get(symbol), "kind": "etf",
                "note": None, "status": status, "source": SOURCE, "session": "2026-10-19",
                "first_date": "2025-10-01", "close": 100.0,
                "drawdown_52w": {"status": "available", "pct": pct, "high": 110.0,
                                 "high_date": "2026-10-06", "window_start": "2025-10-20"},
                "ma_200": {"status": "available", "pct": 5.5, "average": 94.79,
                           "first_date": "2026-01-02", "sessions": 200},
                "adjustments": {"reference_breaks": [], "unadjusted_dates": []}}
    def fn(symbols, now):
        fn.requested = list(symbols)
        return [row(s, -9.09) for s in symbols]
    return fn


def test_daily_summary_shows_etf_and_benchmark_rows(tmp_path):
    watch = watch_rows()
    result = execute(artifacts(tmp_path), tmp_path / "out", research_fn=Sources().research,
                     publication_fn=delivered, now=NOW, price_watch_fn=watch,
                     symbols=["2330.TW", "0050.TW", "00631L.TW"], benchmarks=["TAIEX"])
    assert watch.requested == ["0050.TW", "00631L.TW", "TAIEX"]
    assert [r["symbol"] for r in result["price_watch"]] == watch.requested
    assert result["pilot_coverage"]["symbols"]["0050.TW"]["price_watch"] == "available"
    assert result["status"] == "complete"
    summary = (tmp_path / "out" / "daily_summary.md").read_text()
    assert "### 核心 ETF 與加權指數（僅顯示價格位置，非訊號或買賣建議）" in summary
    assert ("| TAIEX 發行量加權股價指數 | 100.00（2026-10-19） | -9.09% | 110.00（2026-10-06） "
            "| +5.50% | 94.79 | — |") in summary
    receipt = json.loads((tmp_path / "out" / "daily_receipt.json").read_text())
    assert len(receipt["price_watch"]) == 3


def test_price_watch_failure_is_reported_and_marks_the_run_partial(tmp_path):
    def broken(symbols, now):
        raise httpx.ConnectError("TWSE unreachable")
    result = execute(artifacts(tmp_path), tmp_path / "out", research_fn=Sources().research,
                     publication_fn=delivered, now=NOW, price_watch_fn=broken,
                     symbols=["2330.TW", "0050.TW"], benchmarks=["TAIEX"])
    assert result["fixed_research"]["status"] == "complete"
    assert [r["status"] for r in result["price_watch"]] == ["failed", "failed"]
    assert result["status"] == "partial"
    assert "| 0050.TW | — | 取得失敗 | — | — | — | ConnectError：TWSE unreachable |" in (
        tmp_path / "out" / "daily_summary.md").read_text()


def test_configured_benchmark_is_taiex():
    assert get_benchmarks("tw") == ["TAIEX"]


def test_published_page_gains_the_watchlist_overview(tmp_path):
    def publish(mode, bootstrap, out, *, report, daily):
        out.mkdir(parents=True, exist_ok=True)
        (out / "index.html").write_text("published without overview", encoding="utf-8")
        (out / "research_state.json").write_text(
            json.dumps({"records": _report_records(report)}), encoding="utf-8")
        return {"publication": {"status": "published"}, "snapshot_id": "a" * 64,
                "state_branch": "research-state-validation"}
    result = execute(artifacts(tmp_path), tmp_path / "out", research_fn=Sources().research,
                     publication_fn=publish, now=NOW, price_watch_fn=watch_rows(),
                     symbols=["2330.TW", "0050.TW"], benchmarks=["TAIEX"])
    assert result["watchlist_site"] == {"status": "rendered", "latest_only": [], "skipped": {}}
    html = (tmp_path / "out" / "fixed_research" / "index.html").read_text()
    assert 'id="watchlist"' in html and '<a href="#watchlist">觀察名單</a>' in html
    assert "發行量加權股價指數" in html and "-9.09%" in html
    assert "research-state-validation" in html


def test_site_without_daily_overview_is_unchanged():
    html = render_research_site_html(latest_report=_sample_report())
    assert 'id="watchlist"' not in html and "#watchlist" not in html


def test_overview_lists_satellite_zones_with_names():
    zones = {"2317.TW": {"status": "not_evaluated", "zone": "not_evaluated",
                         "reason": "TTM EPS is not positive",
                         "price": {"close": 251.5, "session": "2026-10-28"}},
             "2454.TW": {"status": "available", "zone": "above_high",
                         "review_prices_twd": {"low": 657.27, "mid": 1190.74, "high": 1391.01},
                         "price": {"close": 4235.0, "session": "2026-10-28"}}}
    html = render_research_site_html(latest_report=_sample_report(), watchlist={
        "price_watch": [], "valuation_zones": zones, "names": {"2454.TW": "聯發科"}})
    overview = html[html.index('<section id="watchlist"'):html.index("</section>")]
    assert "核心 ETF 與加權指數" not in overview
    assert "2454.TW<span class=\"unit\">聯發科</span>" in overview
    assert "1,391.01" in overview and "高於偏高價" in overview
    assert "未評估：TTM EPS is not positive" in overview
