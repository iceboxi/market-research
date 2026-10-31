"""#157: the current month before its first published session.

TWSE answers STOCK_DAY, MI_5MINS_HIST and FMTQIK for a month without a session
with stat '很抱歉，沒有符合條件的資料!', exactly as STOCK_DAY answers an unknown
stock code (checked live 2026-11-01). Only the current month with no XTAI session
before today may be empty; anything else still fails closed. Push runs 41228168596
and 41228168626 failed every TW symbol on 2026-11-01 02:12 Taipei.
"""
from datetime import date, datetime, timedelta, timezone
import json

import exchange_calendars as xcals
import pandas as pd
import pytest

from market_research.market_calendar import StaleMarketData
from market_research.market_data import load_daily_bars
from market_research.snapshots import write_index
from market_research.twse import TAIEX, TWSE_URL, TwseDailyProvider, TwseIndexProvider
from test_price_watch import NO_DATA, index_get

FIELDS = ["日期", "成交股數", "成交金額", "開盤價", "最高價", "最低價", "收盤價", "漲跌價差",
          "成交筆數", "註記"]
SUNDAY_NIGHT = datetime(2026, 10, 31, 18, 12, tzinfo=timezone.utc)  # 11-01 02:12 Taipei


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def stock_day(published_through, no_data_months=()):
    """STOCK_DAY with every XTAI session of the month up to `published_through`."""
    calendar = xcals.get_calendar("XTAI")

    def get(url, params=None, timeout=None):
        assert url == TWSE_URL
        get.calls.append(params["date"])
        month = datetime.strptime(params["date"], "%Y%m%d").date()
        end = min((month + timedelta(days=32)).replace(day=1) - timedelta(days=1),
                  published_through)
        days = calendar.sessions_in_range(pd.Timestamp(month), pd.Timestamp(end)) \
            if month <= end else []
        if not len(days) or params["date"] in no_data_months:
            return Response(dict(NO_DATA))
        rows = [[f"{d.year - 1911}/{d.month:02d}/{d.day:02d}", "1,000", "1", "100.00", "101.00",
                 "99.00", "100.00", " 0.00", "1", ""] for d in days]
        return Response({"stat": "OK", "fields": FIELDS, "data": rows})
    get.calls = []
    return get


def provider(today, published_through=date(2026, 10, 30), no_data_months=()):
    return TwseDailyProvider(get=stock_day(published_through, no_data_months), today=today,
                             request_pause_seconds=0)


# ---------------------------------------------------------------- listed stocks

def test_sunday_before_the_first_session_prices_through_friday():
    stocks = provider(date(2026, 11, 1))
    daily = load_daily_bars(stocks, "tw", "2330.TW", "6mo", SUNDAY_NIGHT, "Asia/Taipei",
                            strict_freshness=True)
    assert pd.Timestamp(daily.frame.index[-1]).date() == date(2026, 10, 30)
    assert stocks.get.calls[-1] == "20261101"  # asked, answered with no data


def test_unpublished_first_session_is_stale_never_priced():
    evening = datetime(2026, 11, 2, 12, 0, tzinfo=timezone.utc)  # 20:00 Taipei
    with pytest.raises(StaleMarketData):
        load_daily_bars(provider(date(2026, 11, 2)), "tw", "2330.TW", "6mo", evening,
                        "Asia/Taipei", strict_freshness=True)


def test_no_data_after_the_month_has_sessions_fails_closed():
    # 11-02 and 11-03 are sessions before 11-04: an empty November is a source problem.
    with pytest.raises(ValueError, match="TWSE 2330.TW: failed months: 2026-11-01: "
                                         "TWSE 2330.TW: 很抱歉，沒有符合條件的資料!"):
        provider(date(2026, 11, 4)).load("2330.TW", "3mo")


@pytest.mark.parametrize("no_data, failed", [
    (("20260901",), "2026-09-01"),
    (("20260801", "20260901", "20261001", "20261101"), "2026-08-01"),  # unknown code
])
def test_past_months_without_data_still_fail_closed(no_data, failed):
    with pytest.raises(ValueError, match=f"failed months: {failed}: "):
        provider(date(2026, 11, 1), no_data_months=no_data).load("2330.TW", "3mo")


# ---------------------------------------------------------------- TAIEX

def test_taiex_before_the_first_session_skips_the_empty_month():
    calls = []
    index = TwseIndexProvider(get=index_get(calls, empty_month="20261101"),
                              today=date(2026, 11, 1), request_pause_seconds=0)
    frame = index.load(TAIEX, "3mo")
    assert [pd.Timestamp(d).date().month for d in frame.index] == [8, 9, 10]
    assert calls[-1][1] == "20261101"
    calls = []
    late = TwseIndexProvider(get=index_get(calls, empty_month="20261101"),
                             today=date(2026, 11, 4), request_pause_seconds=0)
    with pytest.raises(ValueError, match="TWSE TAIEX: failed months: 2026-11-01: "
                                         "TWSE MI_5MINS_HIST: 很抱歉，沒有符合條件的資料!"):
        late.load(TAIEX, "3mo")


# ---------------------------------------------------------------- snapshots

def test_an_empty_snapshot_index_is_still_written(tmp_path):
    # Every symbol failed: the research run must stop on its own check, not on a missing folder.
    write_index(tmp_path / "snapshots", [])
    index = json.loads((tmp_path / "snapshots" / "index.json").read_text())
    assert index["symbols"] == []
