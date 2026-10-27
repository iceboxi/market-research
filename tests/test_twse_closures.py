"""TWSE ad-hoc closures (e.g. typhoon days) missing from the XTAI calendar.

Fixture: 2026-10-23 (Fri) is an XTAI session, but TWSE did not trade; the
official FMTQIK October record goes 10-22 -> 10-27 (10-26 is a scheduled
holiday). Live TW runs 39981712825 and 40369616730 failed 0/10 on this.
"""
from datetime import date, datetime, timezone
import json

import httpx
import pandas as pd
import pytest

from market_research.market_calendar import (
    StaleMarketData, expected_complete_session, require_complete_session)
from market_research.runner import run_scan
from market_research.twse import TwseDailyProvider, twse_unscheduled_closures

TYPHOON_EVENING = datetime(2026, 10, 23, 15, 50, tzinfo=timezone.utc)   # 23:50 Taipei
HOLIDAY_NIGHT = datetime(2026, 10, 26, 17, 32, tzinfo=timezone.utc)     # 10-27 01:32 Taipei
TRADED_OCTOBER = ["115/10/15", "115/10/16", "115/10/19", "115/10/20",
                  "115/10/21", "115/10/22"]


class Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self.payload


def fmtqik(days, stat="OK"):
    calls = []

    def get(url, params=None, timeout=None):
        calls.append((url, params))
        return Response({"stat": stat, "fields": ["日期", "成交股數", "成交金額"],
                         "data": [[d, "1", "1"] for d in days]})
    get.calls = calls
    return get


def test_calendar_skips_only_confirmed_closures():
    assert expected_complete_session("tw", TYPHOON_EVENING) == date(2026, 10, 23)
    assert expected_complete_session(
        "tw", TYPHOON_EVENING, closed_sessions=(date(2026, 10, 23),)) == date(2026, 10, 22)
    session = require_complete_session(
        "tw", "2026-10-22", HOLIDAY_NIGHT, closed_sessions=(date(2026, 10, 23),))
    assert session["status"] == "complete"
    assert session["expected_completed_session"] == "2026-10-22"
    assert session["unscheduled_closures"] == ["2026-10-23"]
    with pytest.raises(StaleMarketData):
        require_complete_session("tw", "2026-10-22", HOLIDAY_NIGHT)


@pytest.mark.parametrize("now", [TYPHOON_EVENING, HOLIDAY_NIGHT])
def test_fmtqik_absence_after_lag_confirms_closure(now):
    get = fmtqik(TRADED_OCTOBER)
    assert twse_unscheduled_closures(now, get=get) == (date(2026, 10, 23),)
    assert get.calls[0][1]["date"] == "20261001"


def test_traded_session_is_never_a_closure():
    get = fmtqik(TRADED_OCTOBER + ["115/10/23"])
    assert twse_unscheduled_closures(TYPHOON_EVENING, get=get) == ()


def test_recent_unpublished_session_is_not_assumed_closed():
    # 15:00 Taipei: past the calendar's post-close lag, but FMTQIK may lag too.
    afternoon = datetime(2026, 10, 23, 7, 0, tzinfo=timezone.utc)
    assert expected_complete_session("tw", afternoon) == date(2026, 10, 23)
    assert twse_unscheduled_closures(afternoon, get=fmtqik(TRADED_OCTOBER)) == ()


@pytest.mark.parametrize("get", [
    fmtqik(TRADED_OCTOBER, stat="很抱歉，沒有符合條件的資料!"),
    fmtqik([]),  # no traded anchor in the lookback window
])
def test_source_problem_keeps_calendar_rule(get):
    assert twse_unscheduled_closures(TYPHOON_EVENING, get=get) == ()


def test_network_failure_keeps_calendar_rule():
    def get(url, params=None, timeout=None):
        raise httpx.ConnectError("down")
    assert twse_unscheduled_closures(TYPHOON_EVENING, get=get) == ()


def test_provider_checks_tw_only():
    provider = TwseDailyProvider(get=fmtqik(TRADED_OCTOBER))
    assert provider.unscheduled_closures("tw", HOLIDAY_NIGHT) == (date(2026, 10, 23),)
    assert provider.unscheduled_closures("us", HOLIDAY_NIGHT) == ()


def frame_through_1022():
    idx = pd.bdate_range(end="2026-10-22", periods=40).date
    return pd.DataFrame({"open": [10.] * 40, "high": [11.] * 40, "low": [9.] * 40,
                         "close": [10.] * 40, "volume": [100] * 40},
                        index=pd.Index(idx, name="date"))


def scan(tmp_path, provider):
    cfg = tmp_path / "config"
    cfg.mkdir()
    (cfg / "markets.yaml").write_text(
        "markets:\n  tw:\n    timezone: Asia/Taipei\n    symbols:\n      - 2330.TW\n")
    (cfg / "strategies.yaml").write_text(
        "strategies:\n  - id: sakata_three_soldiers\n    enabled: true\n    params: {}\n")
    manifest = run_scan("tw", period="6mo", out=tmp_path / "out", config_dir=cfg,
                        provider=provider, now=HOLIDAY_NIGHT, strict_freshness=True)
    return manifest, json.loads((tmp_path / "out" / "data_quality.json").read_text())


def test_strict_scan_without_closure_evidence_still_fails_closed(tmp_path):
    class Plain:
        source = "fixture"
        def load(self, symbol, period="1y"):
            return frame_through_1022()
    manifest, quality = scan(tmp_path, Plain())
    assert manifest["error_count"] == 1
    assert quality["errors"][0]["error_type"] == "StaleMarketData"


def test_strict_scan_accepts_last_traded_session_after_confirmed_closure(tmp_path):
    class WithClosures:
        source = "fixture"
        def load(self, symbol, period="1y"):
            return frame_through_1022()
        def unscheduled_closures(self, market, now):
            return (date(2026, 10, 23),)
    manifest, quality = scan(tmp_path, WithClosures())
    assert manifest["error_count"] == 0 and manifest["scanned_symbols"] == 1
    assert manifest["unscheduled_closures"] == {"tw": ["2026-10-23"]}
    session = quality["symbols"][0]["session"]
    assert session["expected_completed_session"] == "2026-10-22"
    assert session["unscheduled_closures"] == ["2026-10-23"]
    assert "2026-10-23" in (tmp_path / "out" / "summary.md").read_text()
