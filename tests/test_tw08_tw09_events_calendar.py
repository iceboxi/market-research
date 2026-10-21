"""TW08 (disclosures & news) and TW09 (calendar schedule & revisions) tests."""
from datetime import datetime, timezone

import pytest

from market_research.event_risk import (
    TW_DIVIDEND_SCHEDULE_URL,
    TW_MATERIAL_URL,
    TW_SHAREHOLDER_ANNOUNCE_URL,
    TW_SHAREHOLDER_MEETING_URL,
    build_tw_calendar_schedule,
    build_tw_disclosures_and_news,
    compare_calendar_schedules,
    normalize_event_timezone,
    normalize_headline_key,
    parse_tw_disclosures,
)
from market_research.research_comparison import compare_snapshots, render_comparison
from market_research.research_snapshot import prepare_snapshot, validate_snapshot
from scripts.company_report import run
from test_tw_2330_full_research import NOW, Prices2330, make_http_router


def test_headline_normalization_and_syndicated_news_deduplication():
    h1 = "台積電拍板2026年第2季每股配息7元 - 經濟日報"
    h2 = "台積電拍板2026年第2季每股配息7元｜Yahoo奇摩股市"
    h3 = "【台積電拍板】2026年第2季每股配息7元 — 中央社"
    assert normalize_headline_key(h1) == normalize_headline_key(h2) == normalize_headline_key(h3)

    now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)  # 16:00 Asia/Taipei
    news_payload = [
        {"date": "2026-10-18 09:30:00", "stock_id": "2330", "source": "經濟日報", "title": h1, "link": "https://money.udn.com/story/1"},
        {"date": "2026-10-18 09:45:00", "stock_id": "2330", "source": "Yahoo股市", "title": h2, "link": "https://tw.stock.yahoo.com/news/2"},
        {"date": "2026-10-18 10:00:00", "stock_id": "2330", "source": "中央社", "title": h3, "link": "https://www.cna.com.tw/news/3"},
        # Future news after evaluation cutoff (2026-10-19 18:00 Taipei > 16:00 Taipei) must be excluded (no-lookahead)
        {"date": "2026-10-19 18:00:00", "stock_id": "2330", "source": "工商時報", "title": "未來新聞不可洩漏 - 工商時報", "link": "https://ctee.com.tw/future"},
        # Other stock_id must be ignored
        {"date": "2026-10-18 08:00:00", "stock_id": "2317", "source": "中央社", "title": "鴻海新聞", "link": "https://www.cna.com.tw/other"},
    ]
    res = build_tw_disclosures_and_news("2330.TW", now, finmind_news=news_payload)
    assert res["deduplicated_repost_count"] == 2
    assert len(res["news_references"]) == 1
    item = res["news_references"][0]
    assert item["sources"] == ["經濟日報", "Yahoo股市", "中央社"]
    assert item["syndicated_count"] == 3
    assert item["source_class"] == "third_party_news_index_not_official_filing"
    assert item["summary_status"] == "headline_and_link_only_full_text_not_fetched"
    assert item["sentiment_score"] == "not_evaluated"
    assert item["event_date"] is None


def test_official_disclosures_vs_news_and_source_degradation_statuses():
    now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
    mat_feed = parse_tw_disclosures([
        {"出表日期": "1151019", "發言日期": "1151018", "發言時間": "153000", "公司代號": "2317", "主旨": "他公司重訊"},
    ], "2330.TW", now)
    agm_rows = [
        {"出表日期": "1151019", "公司代號": "2330", "股東常(臨時)會日期-常或臨時": "常會", "股東常(臨時)會日期-日期": "1150604", "公告日期": "1150417", "公告時間": "162154"},
        # Future announcement after cutoff must be excluded
        {"出表日期": "1151025", "公司代號": "2330", "股東常(臨時)會日期-常或臨時": "臨時會", "股東常(臨時)會日期-日期": "1151201", "公告日期": "1151025", "公告時間": "100000"},
    ]
    res = build_tw_disclosures_and_news(
        "2330.TW", now,
        material_feed=mat_feed,
        shareholder_announce=agm_rows,
        dividend_rows=[],
        finmind_news=None,
        source_errors={"finmind_news": "ReadTimeout"},
    )
    assert res["status"] == "partial"
    assert res["source_statuses"]["twse_material_t187ap04_L"] == "available_no_matching_events"
    assert res["source_statuses"]["twse_shareholder_t187ap38_L"] == "available_with_events"
    assert res["source_statuses"]["twse_dividend_t187ap45_L"] == "available_no_matching_events"
    assert res["source_statuses"]["finmind_news"] == "source_unavailable"
    assert len(res["official_disclosures"]) == 1
    od = res["official_disclosures"][0]
    assert od["event_date"] == "2026-06-04"
    assert od["published_at"] == "2026-04-17T16:21:54+08:00"
    assert od["reported_at"] == "2026-10-19"


def test_calendar_schedule_unknown_upcoming_revision_cancellation_and_fallback():
    now = datetime(2026, 10, 19, 8, 0, tzinfo=timezone.utc)
    agm_ann = [{"出表日期": "1151019", "公司代號": "2330", "股東常(臨時)會日期-常或臨時": "常會", "股東常(臨時)會日期-日期": "1150604", "公告日期": "1150417", "公告時間": "162154"}]
    agm_loc = [{"出表日期": "1151019", "公司代號": "2330", "股東常(臨時)會": "常會", "開會日期": "1150604", "開會地點": "新竹喜來登", "是否採電子投票": "強制"}]
    divs = [{"出表日期": "1151019", "公司代號": "2330", "年度": "115", "季別": "第2季", "董事會（擬議）股利分派日": "1150811", "現金股利(元/股)": "7.0"}]

    # 1. Baseline schedule: investor_conference and earnings_release are unknown (never guessed from prior year)
    cal1 = build_tw_calendar_schedule(
        "2330.TW", now,
        shareholder_announce=agm_ann,
        shareholder_meeting=agm_loc,
        dividend_rows=divs,
        material_feed={"status": "available", "events": []},
    )
    assert cal1["status"] == "available"
    by_id1 = {e["schedule_id"]: e for e in cal1["events"]}
    assert by_id1["2330-shareholder_meeting-2026"]["scheduled_date"] == "2026-06-04"
    assert by_id1["2330-shareholder_meeting-2026"]["confirmation_status"] == "confirmed"
    assert by_id1["2330-board_meeting-2026Q2"]["scheduled_date"] == "2026-08-11"
    assert by_id1["2330-investor_conference-upcoming"]["confirmation_status"] == "unknown"
    assert by_id1["2330-investor_conference-upcoming"]["scheduled_date"] is None
    assert by_id1["2330-earnings_release-upcoming"]["confirmation_status"] == "unknown"
    assert by_id1["2330-statutory_filing_deadline-tw_ifrs"]["event_type"] == "statutory_filing_deadline"

    # 2. Schedule revision & new conference observation
    agm_ann_revised = [{"出表日期": "1151019", "公司代號": "2330", "股東常(臨時)會日期-常或臨時": "常會", "股東常(臨時)會日期-日期": "1150610", "公告日期": "1150420", "公告時間": "162154"}]
    mat_with_conf = {
        "status": "available", "snapshot_date": "2026-10-19",
        "events": [{"event_id": "tw-mat-1", "title": "公告本公司召開2026年第3季法人說明會", "published_at": "2026-10-18T14:00:00+08:00", "event_date": "1151017"}],
    }
    cal2 = build_tw_calendar_schedule(
        "2330.TW", now,
        shareholder_announce=agm_ann_revised,
        shareholder_meeting=agm_loc,
        dividend_rows=divs,
        material_feed=mat_with_conf,
        previous_schedule=cal1,
    )
    changes = {c["schedule_id"]: c for c in cal2["schedule_changes"]}
    assert changes["2330-shareholder_meeting-2026"]["change_kind"] == "schedule_revised"
    assert changes["2330-shareholder_meeting-2026"]["old_date"] == "2026-06-04"
    assert changes["2330-shareholder_meeting-2026"]["new_date"] == "2026-06-10"
    assert changes["2330-investor_conference-2026-10"]["change_kind"] == "new_schedule"

    # 3. Schedule cancellation
    mat_cancelled = {
        "status": "available", "snapshot_date": "2026-10-19",
        "events": [{"event_id": "tw-mat-2", "title": "公告取消召開2026年第3季法人說明會", "published_at": "2026-10-19T09:00:00+08:00", "event_date": "1151017"}],
    }
    cal3 = build_tw_calendar_schedule(
        "2330.TW", now,
        shareholder_announce=agm_ann_revised,
        shareholder_meeting=agm_loc,
        dividend_rows=divs,
        material_feed=mat_cancelled,
        previous_schedule=cal2,
    )
    changes3 = {c["schedule_id"]: c for c in cal3["schedule_changes"]}
    assert changes3["2330-investor_conference-2026-10"]["change_kind"] == "schedule_cancelled"

    # 4. Source failure preserves previous confirmed schedule without losing evidence
    cal4 = build_tw_calendar_schedule(
        "2330.TW", now,
        shareholder_announce=None,
        shareholder_meeting=None,
        dividend_rows=None,
        material_feed={"status": "unavailable", "events": []},
        previous_schedule=cal2,
        source_errors={"shareholder_announce": "Timeout", "shareholder_meeting": "Timeout", "dividends": "Timeout"},
    )
    assert cal4["status"] == "partial"
    assert "2330-shareholder_meeting-2026" in cal4["retained_from_previous_ids"]
    assert "2330-board_meeting-2026Q2" in cal4["retained_from_previous_ids"]


def test_cross_day_timezone_conversion_to_taipei():
    # 2026-10-18 22:30 UTC is 2026-10-19 06:30 Asia/Taipei (cross-day boundary)
    norm = normalize_event_timezone("2026-10-18T22:30:00Z", "Asia/Taipei")
    assert norm["scheduled_date"] == "2026-10-19"
    assert norm["scheduled_at"] == "2026-10-19T06:30:00+08:00"
    assert norm["timezone"] == "Asia/Taipei"
    with pytest.raises(ValueError, match="timezone"):
        normalize_event_timezone("2026-10-18T22:30:00")


def test_company_report_and_snapshot_comparison_with_tw08_tw09(tmp_path):
    router = make_http_router()
    res1 = run("2330.TW", out=tmp_path / "r1", now=NOW, clock=lambda: NOW, provider=Prices2330(), facts_get=router, financial_get=router)
    fr1 = res1["financial_research"]
    assert fr1["disclosure_and_news"]["status"] == "available"
    assert fr1["disclosure_and_news"]["deduplicated_repost_count"] == 1
    assert fr1["calendar_schedule"]["status"] == "available"

    md = (tmp_path / "r1" / "report.md").read_text()
    assert "重大公告與外部新聞索引（TW08" in md
    assert "財報、法說會、董事會與股東會重要行程（TW09" in md
    assert "新竹喜來登大飯店" in md

    snap1 = prepare_snapshot(res1, {
        "repository": "owner/repo", "run_id": "301", "run_attempt": 1,
        "code_sha": "b" * 40, "observed_at_utc": "2026-10-19T12:01:00+00:00",
    })
    validate_snapshot(snap1)
    # Third-party news headlines/links must be stripped from compact Git snapshot
    assert snap1["financial_research"]["disclosure_and_news"]["news_references"] == []

    # Simulate a schedule date revision on run 2
    def router_revised(url):
        if url == TW_SHAREHOLDER_ANNOUNCE_URL:
            return [{
                "出表日期": "1151019", "公司代號": "2330", "公司名稱": "台積電",
                "股東常(臨時)會日期-常或臨時": "常會", "股東常(臨時)會日期-日期": "1150612",
                "公告日期": "1150418", "公告時間": "162154",
            }]
        return router(url)

    now2 = datetime(2026, 10, 19, 12, 10, tzinfo=timezone.utc)
    res2 = run("2330.TW", out=tmp_path / "r2", now=now2, clock=lambda: now2, provider=Prices2330(), facts_get=router_revised, financial_get=router_revised)
    snap2 = prepare_snapshot(res2, {
        "repository": "owner/repo", "run_id": "302", "run_attempt": 1,
        "code_sha": "b" * 40, "observed_at_utc": "2026-10-19T12:11:00+00:00",
    })
    delta = compare_snapshots(snap1, snap2)
    assert "revision" in delta["categories"]
    assert any(c["component"] == "calendar_schedule" and c["reason"] == "schedule_date_changed" for c in delta["changes"])
    rendered = render_comparison(delta, {snap1["id"]: snap1, snap2["id"]: snap2})
    assert "公司重要行程" in rendered
    assert "已公告行程日期更正" in rendered
