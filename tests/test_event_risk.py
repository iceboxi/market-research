"""No-lookahead and source coverage tests for official event risk."""
from datetime import datetime, timezone

from market_research.event_risk import (
    parse_tw_disclosures, sec_filing_events, evaluate_events, unknown,
    tw_material_events, render_events,
)


def test_tw_material_speech_time_not_fact_date_and_future_exclusion():
    now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
    payload = [
        {"出表日期": "1151019", "發言日期": "1151018", "發言時間": "124530",
         "公司代號": "2330", "主旨 ": "公告董事會決議通過財務報告",
         "事實發生日": "1151017"},
        {"出表日期": "1151019", "發言日期": "1151019", "發言時間": "180000",
         "公司代號": "2330", "主旨 ": "future filing", "事實發生日": "1151019"},
        {"出表日期": "1151019", "發言日期": "1151018", "發言時間": "113000",
         "公司代號": "2317", "主旨 ": "another issuer"},
    ]
    feed = parse_tw_disclosures(payload, "2330.TW", now)
    assert feed["status"] == "available"
    assert len(feed["events"]) == 1
    assert feed["events"][0]["published_at"].startswith("2026-10-18T12:45:30")
    assert feed["events"][0]["event_date"] == "1151017"
    risk = evaluate_events(feed, now)
    assert risk["review_required"] is True
    assert risk["status"] == "manual_review_required"
    assert risk["trade_recommendation_allowed"] is False


def test_tw_daily_snapshot_lag_and_historical_replay_block():
    now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
    old = [{"出表日期": "1151001", "發言日期": "1151001",
            "發言時間": "090000", "公司代號": "2330", "主旨 ": "old"}]
    assert parse_tw_disclosures(old, "2330.TW", now)["status"] == "unavailable"
    past = tw_material_events("2330.TW", datetime(2024, 10, 1, tzinfo=timezone.utc),
                              lambda url: (_ for _ in ()).throw(AssertionError("must not fetch")))
    assert past["status"] == "unavailable"


def test_tw_empty_or_bad_snapshot_never_means_clean():
    now = datetime(2026, 10, 19, tzinfo=timezone.utc)
    feed = parse_tw_disclosures([], "2330.TW", now)
    assert feed["status"] == "unavailable"
    assert evaluate_events(feed, now)["status"] == "coverage_incomplete"


def test_sec_metadata_reliably_classifies_filing_not_earnings_surprise():
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    payload = {"filings": {"recent": {
        "form": ["10-Q", "8-K", "10-K", "10-K"],
        "filingDate": ["2026-10-16", "2026-10-19", "2026-10-19", "2026-04-01"],
        "accessionNumber": ["0000320193-26-000111", "0000320193-26-000112",
                            "0000320193-26-000113", "0000320193-26-000114"],
        "acceptanceDateTime": ["2026-10-16T15:05:00Z",
                               "2026-10-19T18:00:00Z",
                               "2026-10-19T08:00:00Z",
                               "2026-04-01T12:00:00Z"],
    }}}
    feed = sec_filing_events(payload, now, "https://data.sec.gov/submissions/sample")
    assert [e["form"] for e in feed["events"]] == ["10-Q"]
    assert feed["events"][0]["kind"] == "quarterly_report"
    assert evaluate_events(feed, now)["review_required"] is True
    assert feed["upcoming_earnings"] == "not_verified"


def test_sec_date_only_same_day_is_not_assumed_known():
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    x = {"filings": {"recent": {
        "form": ["8-K"], "filingDate": ["2026-10-19"],
        "accessionNumber": ["0000320193-26-000112"]}}}
    assert sec_filing_events(x, now, "sec")["events"] == []


def test_unavailable_feed_is_not_low_risk_and_no_targets():
    now = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
    feed = unknown("sec", "offline")
    risk = evaluate_events(feed, now)
    assert risk["status"] == "coverage_incomplete"
    assert "not verified" in "\n".join(render_events(feed, risk)).lower()
    assert risk["trade_recommendation_allowed"] is False
