"""TW01 coordinator behavior, through report artifacts and injected sources."""
import json
from datetime import datetime, timezone

import httpx
import pandas as pd
import pytest

from market_research import event_risk, source_evidence
from market_research.event_risk import TW_MATERIAL_URL
from market_research.fundamentals import TW_PROFILE, TW_REVENUE
from scripts.company_report import run

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)


class FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)


@pytest.fixture(autouse=True)
def source_clock(monkeypatch):
    # Wall clock is an external dependency; the report and sources share one cutoff.
    monkeypatch.setattr(event_risk, "datetime", FixedClock)
    monkeypatch.setattr(source_evidence, "datetime", FixedClock)


class Prices:
    source = "fixture_daily"

    def load(self, symbol, period):
        days = pd.bdate_range(end="2026-10-19", periods=160).date
        return pd.DataFrame({
            "open": 100.0, "high": 102.0, "low": 98.0,
            "close": 100.0, "volume": 1000,
        }, index=pd.Index(days, name="date"))


def facts_get(url):
    if url == TW_PROFILE:
        return [{"公司代號": "2330", "公司名稱": "Fixture Semiconductor",
                 "產業別": "24", "出表日期": "1151019"}]
    if url == TW_REVENUE:
        return [{"公司代號": "2330", "當月營收": "1,000",
                 "資料年月": "11509", "出表日期": "1151010"}]
    if url == TW_MATERIAL_URL:
        return [{"公司代號": "2330", "出表日期": "1151019",
                 "發言日期": "1151019", "發言時間": "100000",
                 "主旨": "Known fixture disclosure"}]
    raise AssertionError(f"Unexpected external source: {url}")


def test_existing_tw_report_contract_with_missing_annuals(tmp_path):
    result = run("2330.TW", out=tmp_path, now=NOW,
                 provider=Prices(), facts_get=facts_get)
    stored = json.loads((tmp_path / "report.json").read_text())
    markdown = (tmp_path / "report.md").read_text()

    assert stored == result
    assert result["schema_version"] == 4
    assert result["complete"] is True
    assert result["issuer"]["company_name"] == "Fixture Semiconductor"
    assert result["issuer"]["facts"][0]["value"] == 1000
    assert result["issuer"]["facts"][0]["unit"] == "TWD_thousands"
    assert result["technical"]["last_session"] == "2026-10-19"
    assert result["technical"]["analytical_close"] == 100
    assert result["financial_comparison"]["status"] == "unavailable"
    assert result["valuation"]["status"] == "not_evaluated"
    assert result["valuation"]["stop_loss"] is None
    assert result["official_events"]["status"] == "available"
    assert result["event_risk"]["status"] == "manual_review_required"
    evidence = result["source_evidence"]["observations"][0]
    assert evidence["date_evidence"]["published_at"] is None
    assert "Annual financial comparison" in markdown
    assert "Comparable annual statements unavailable" in markdown
    assert "Known fixture disclosure" in markdown


@pytest.mark.parametrize("failure", ["missing", "timeout", "io_error"])
def test_existing_monthly_failure_keeps_identity_and_prices(tmp_path, failure):
    def get(url):
        if url == TW_REVENUE:
            if failure == "timeout":
                raise httpx.ReadTimeout("fixture")
            if failure == "io_error":
                raise OSError("fixture")
            return []
        return facts_get(url)

    result = run("2330.TW", out=tmp_path, now=NOW,
                 provider=Prices(), facts_get=get)
    assert result["complete"] is True
    assert result["issuer"]["company_name"] == "Fixture Semiconductor"
    assert result["issuer"]["facts"] == []
    assert result["issuer"]["warnings"]
    assert result["technical"]["analytical_close"] == 100
    assert result["valuation"]["status"] == "not_evaluated"
    assert "Unavailable" in (tmp_path / "report.md").read_text()


def test_profile_timeout_still_writes_report_without_inventing_identity(tmp_path):
    def get(url):
        if url == TW_PROFILE:
            raise httpx.ReadTimeout("fixture")
        return facts_get(url)

    result = run("2330.TW", out=tmp_path, now=NOW,
                 provider=Prices(), facts_get=get)

    assert result["complete"] is False
    assert result["issuer"]["company_name"] is None
    assert result["issuer"]["facts"] == []
    assert result["instrument_eligibility"]["status"] == "unknown"
    assert result["technical"]["analytical_close"] == 100
    assert result["valuation"]["status"] == "not_evaluated"
    assert json.loads((tmp_path / "report.json").read_text()) == result
    assert "Missing verified issuer identity" in (tmp_path / "report.md").read_text()


def test_run_receipt_separates_pipeline_sources_and_research_readiness(tmp_path):
    result = run("2330.TW", out=tmp_path, now=NOW,
                 provider=Prices(), facts_get=facts_get)
    receipt = json.loads((tmp_path / "run_receipt.json").read_text())

    assert receipt == result["run_receipt"]
    assert receipt["schema_version"] == 1
    assert receipt["execution"]["status"] == "completed"
    assert receipt["execution"]["legacy_complete"] is True
    assert receipt["evaluation_cutoff_utc"] == "2026-10-19T12:00:00+00:00"
    assert receipt["source_coverage"]["issuer_profile"]["status"] == "available"
    assert receipt["source_coverage"]["reported_fundamentals"]["periods"] == ["11509"]
    assert receipt["source_coverage"]["technical"]["session"] == "2026-10-19"
    assert receipt["research_readiness"]["financial"]["status"] == "unavailable"
    assert receipt["research_readiness"]["valuation"]["status"] == "not_evaluated"
    assert receipt["persistence"]["status"] == "not_attempted"
    assert receipt["delivery"]["status"] == "not_attempted"
    markdown = (tmp_path / "report.md").read_text()
    assert "## 執行摘要" in markdown
    assert "年度財報" in markdown
    assert "not_evaluated" in markdown


def test_stale_prices_are_visible_without_changing_legacy_complete(tmp_path):
    class StalePrices(Prices):
        def load(self, symbol, period):
            return super().load(symbol, period).iloc[:-1]

    result = run("2330.TW", out=tmp_path, now=NOW,
                 provider=StalePrices(), facts_get=facts_get)
    technical = result["run_receipt"]["source_coverage"]["technical"]
    assert result["complete"] is True
    assert technical["status"] == "available"
    assert technical["session"] == "2026-10-16"
    assert technical["freshness"] == "stale"
    assert "資料過期" in (tmp_path / "report.md").read_text()
    assert result["technical"]["price_context"]["status"] == "not_evaluated"

@pytest.mark.parametrize("profile", [
    [],
    [{"公司代號": "2330", "公司名稱": "First"},
     {"公司代號": "2330", "公司名稱": "Second"}],
    {"invalid": "shape"},
])
def test_unverified_profile_has_partial_receipt_and_no_identity(tmp_path, profile):
    def get(url):
        return profile if url == TW_PROFILE else facts_get(url)

    result = run("2330.TW", out=tmp_path, now=NOW,
                 provider=Prices(), facts_get=get)
    receipt = json.loads((tmp_path / "run_receipt.json").read_text())
    assert result["issuer"]["company_name"] is None
    assert result["issuer"]["facts"] == []
    assert result["complete"] is False
    assert receipt["execution"]["status"] == "partial"
    assert receipt["source_coverage"]["issuer_profile"]["error_type"] == "ValueError"
    assert receipt["source_coverage"]["reported_fundamentals"]["status"] == "not_attempted"
    assert result["technical"]["analytical_close"] == 100
    assert "公司身分未確認" in (tmp_path / "report.md").read_text()


def test_price_failure_keeps_verified_company_and_fundamentals(tmp_path):
    class UnavailablePrices(Prices):
        def load(self, symbol, period):
            raise httpx.ReadTimeout("fixture")

    result = run("2330.TW", out=tmp_path, now=NOW,
                 provider=UnavailablePrices(), facts_get=facts_get)
    receipt = result["run_receipt"]
    assert result["issuer"]["company_name"] == "Fixture Semiconductor"
    assert result["issuer"]["facts"][0]["value"] == 1000
    assert result["complete"] is False
    assert receipt["source_coverage"]["technical"]["status"] == "unavailable"
    assert receipt["source_coverage"]["technical"]["session"] is None
    assert receipt["source_coverage"]["technical"]["freshness"] == "unknown"
    assert receipt["source_coverage"]["official_events"]["status"] == "available"
    assert json.loads((tmp_path / "run_receipt.json").read_text()) == receipt


def test_event_failure_is_unknown_coverage_not_no_events(tmp_path):
    def get(url):
        if url == TW_MATERIAL_URL:
            raise httpx.ReadTimeout("fixture")
        return facts_get(url)

    result = run("2330.TW", out=tmp_path, now=NOW,
                 provider=Prices(), facts_get=get)
    assert result["complete"] is True
    assert result["issuer"]["facts"][0]["value"] == 1000
    assert result["run_receipt"]["source_coverage"]["official_events"]["status"] == "unavailable"
    assert result["event_risk"]["status"] == "coverage_incomplete"
    assert "ReadTimeout" in (tmp_path / "report.md").read_text()


def test_report_cutoff_excludes_future_prices_and_events(tmp_path):
    class FuturePrices(Prices):
        def load(self, symbol, period):
            frame = super().load(symbol, period)
            frame.loc[datetime(2026, 10, 20).date()] = [9999, 9999, 9999, 9999, 1000]
            return frame

    def get(url):
        rows = facts_get(url)
        if url == TW_MATERIAL_URL:
            return rows + [{"公司代號": "2330", "出表日期": "1151020",
                            "發言日期": "1151020", "發言時間": "100000",
                            "主旨": "Future fixture disclosure"}]
        return rows

    result = run("2330.TW", out=tmp_path, now=NOW,
                 provider=FuturePrices(), facts_get=get)
    assert result["technical"]["last_session"] == "2026-10-19"
    assert result["technical"]["analytical_close"] == 100
    assert result["run_receipt"]["source_coverage"]["technical"]["session"] == "2026-10-19"
    assert [e["title"] for e in result["official_events"]["events"]] == ["Known fixture disclosure"]
    assert "Future fixture disclosure" not in (tmp_path / "report.md").read_text()


def test_current_tw_freezes_cutoff_after_all_inputs_and_fetches_each_source_once(tmp_path):
    from datetime import timedelta
    ticks = [NOW, NOW + timedelta(seconds=10)]
    calls = []
    class Clock:
        def __call__(self):
            calls.append("clock")
            return ticks.pop(0)
    class CountingPrices(Prices):
        def load(self, symbol, period):
            calls.append("prices")
            return super().load(symbol, period)
    def get(url):
        calls.append(url)
        return facts_get(url)
    result = run("2330.TW", out=tmp_path, provider=CountingPrices(), facts_get=get, clock=Clock())
    assert result["started_utc"] == NOW.isoformat()
    assert result["generated_utc"] == "2026-10-19T12:00:10+00:00"
    assert calls == ["clock", TW_PROFILE, TW_REVENUE, "prices", TW_MATERIAL_URL, "clock"]
    assert result["run_receipt"]["evaluation_cutoff_utc"] == result["generated_utc"]
    assert result["technical"]["analytical_close"] == 100


def test_future_profile_is_unavailable_but_prices_and_events_still_report(tmp_path):
    def get(url):
        rows = facts_get(url)
        if url == TW_PROFILE:
            rows[0]["出表日期"] = "1151020"
        return rows
    result = run("2330.TW", out=tmp_path, now=NOW, provider=Prices(), facts_get=get)
    assert result["issuer"]["company_name"] is None
    assert result["instrument_eligibility"]["status"] == "unknown"
    assert result["complete"] is False
    assert result["technical"]["status"] == "available"


@pytest.mark.parametrize("failure", ["profile", "prices", "events"])
def test_current_input_failure_is_replayed_once_into_readable_partial_results(tmp_path, failure):
    calls = []
    def get(url):
        calls.append(url)
        if url == {"profile": TW_PROFILE, "events": TW_MATERIAL_URL}.get(failure):
            raise httpx.ReadTimeout("fixture")
        return facts_get(url)
    class MaybePrices(Prices):
        def load(self, symbol, period):
            calls.append("prices")
            if failure == "prices":
                raise httpx.ReadTimeout("fixture")
            return super().load(symbol, period)
    result = run("2330.TW", out=tmp_path, provider=MaybePrices(), facts_get=get, clock=lambda: NOW)
    assert all(calls.count(key) == 1 for key in set(calls))
    assert result["complete"] is (failure == "events")
    assert json.loads((tmp_path / "report.json").read_text()) == result
    assert "執行摘要" in (tmp_path / "report.md").read_text()


def test_session_freshness_uses_post_fetch_cutoff_at_completion_boundary(tmp_path):
    ticks = iter([datetime(2026, 10, 20, 6, 29, 59, tzinfo=timezone.utc),
                  datetime(2026, 10, 20, 6, 30, 1, tzinfo=timezone.utc)])
    result = run("2330.TW", out=tmp_path, provider=Prices(), facts_get=facts_get, clock=lambda: next(ticks))
    assert result["technical"]["last_session"] == "2026-10-19"
    assert result["run_receipt"]["source_coverage"]["technical"]["freshness"] == "stale"
