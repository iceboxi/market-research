"""F01 issuer and time-evidence contracts with whole-report regression fixtures."""
from datetime import datetime, timezone

import pandas as pd
import pytest

from market_research.market_data import DailyBars
from market_research.research_evidence import instrument_eligibility, build_source_evidence
from scripts.company_report import run

ASOF = datetime(2026, 10, 19, 11, 0, tzinfo=timezone.utc)


def issuer(sic=3571, entity_type="operating"):
    return {
        "market": "us", "symbol": "AAPL", "company_name": "Apple",
        "industry": {"sic": sic, "source": "https://data.sec.gov/submissions/CIK0000320193.json"},
        "instrument": {"sec_entity_type": entity_type,
                       "source": "https://data.sec.gov/submissions/CIK0000320193.json"},
        "financial_history": {
            "source": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json",
            "currency": "USD", "period_type": "annual_10k",
            "annual_revenue": [
                {"value": 200, "unit": "USD", "period_start": "2024-01-01",
                 "period_end": "2024-12-31", "filed": "2025-02-01",
                 "accession": "0000320193-25-000001",
                 "source": "https://data.sec.gov/api/xbrl/companyfacts/CIK0000320193.json"},
                {"value": 999, "unit": "USD", "period_start": "2024-01-01",
                 "period_end": "2024-12-31", "filed": "2026-10-19",
                 "accession": "0000320193-26-000002"},
            ],
        },
    }


def test_us_operating_financial_and_fund_unknown():
    assert instrument_eligibility(issuer())["status"] == "eligible"
    assert instrument_eligibility(issuer(sic=6021))["status"] == "ineligible"
    assert instrument_eligibility(issuer(sic=6021))["valuation_model"] == "not_evaluated"
    assert instrument_eligibility(issuer(entity_type="other"))["status"] == "unknown"
    assert instrument_eligibility(issuer(entity_type=None))["status"] == "unknown"
    assert instrument_eligibility(issuer(sic=None))["status"] == "unknown"


def test_tw_listed_industry_financial_unknown_and_current_monthly():
    base = {"market": "tw", "company_name": "TW", "industry_code": "24",
            "profile": {"source": "https://openapi.twse.com.tw/v1/opendata/t187ap03_L"}}
    assert instrument_eligibility(base)["status"] == "eligible"
    assert instrument_eligibility({**base, "industry_code": "17"})["status"] == "ineligible"
    assert instrument_eligibility({**base, "industry_code": None})["status"] == "unknown"
    monthly = {**base, "facts": [{
        "metric": "monthly_reported_revenue", "value": 200.0, "unit": "TWD_thousands",
        "period": "11509", "reported_at": "1151015",
        "source": "https://openapi.twse.com.tw/v1/opendata/t187ap05_L"
    }]}
    evidence = build_source_evidence(monthly, ASOF)
    assert evidence["facts"][0]["scale"] == 1000
    assert evidence["facts"][0]["source_publication_at"] is None
    assert evidence["facts"][0]["asof_evidence"] == "not_verified_for_historical_cutoff"
    assert not evidence["historical_replay_verified"]


def test_date_only_same_day_future_excluded_no_midnight_illusion():
    evidence = build_source_evidence(issuer(), ASOF)
    assert [x["value"] for x in evidence["facts"]] == [200]
    f = evidence["facts"][0]
    assert f["source_publication_at"] is None
    assert f["source_filed_date"] == "2025-02-01"
    assert f["source_availability_precision"] == "filing_date_only_not_intraday"
    assert f["source_documents"] == ["0000320193-25-000001"]
    assert f["retrieved_at_utc"] is None
    with pytest.raises(ValueError):
        build_source_evidence(issuer(), datetime(2026, 10, 19))


def fixture_market(market):
    days = pd.bdate_range(end="2026-10-16", periods=81).date
    frame = pd.DataFrame({
        "open": [100.0] * 81, "high": [102.0] * 81,
        "low": [98.0] * 81, "close": [100.0] * 81,
        "volume": [500.0] * 81,
    }, index=pd.Index(days, name="date"))
    basis = ("twse_official_unadjusted" if market == "tw"
             else "yahoo_adj_close_ratio_adjusted_ohlc")
    return DailyBars(frame, {
        "last_date": "2026-10-16", "expected_completed_session": "2026-10-16",
        "price_basis": basis, "execution_price_basis": "fixture_execution_proxy",
        "source": "offline_fixture", "input_sha256": "f" * 64,
    }, ())


def stub_technical(monkeypatch, market):
    monkeypatch.setattr("scripts.company_report.load_daily_bars",
                        lambda *args, **kwargs: fixture_market(market))
    class Strategy:
        def scan(self, m, ticker, frame, params):
            from types import SimpleNamespace
            return SimpleNamespace(strategy_id="fixture", strategy_version="v1",
                                   matched=False, trade_date="2026-10-16",
                                   metrics={"observation": "none"})
    monkeypatch.setattr("scripts.company_report.get_strategy", lambda name: Strategy())


def test_tw_company_report_schema_v4_and_legacy_complete(tmp_path, monkeypatch):
    stub_technical(monkeypatch, "tw")
    def getter(url):
        if "t187ap03" in url:
            return [{"公司代號": "2330", "公司名稱": "台積電", "產業別": "24"}]
        if "t187ap05" in url:
            return [{"公司代號": "2330", "當月營收": "20,000", "資料年月": "11509"}]
        return []
    monkeypatch.setattr("scripts.company_report.tw_material_events",
                        lambda *args: {
                            "status": "unavailable", "coverage": "not_verified",
                            "events": [], "reason": "No live source",
                            "upcoming_earnings": "not_verified",
                        })
    result = run("2330.TW", out=tmp_path, now=ASOF, facts_get=getter)
    assert result["schema_version"] == 4
    assert result["complete"] is True  # legacy pipeline-only flag, not investment readiness
    assert result["issuer_eligibility"]["status"] == "eligible"
    assert result["source_evidence"]["facts"][0]["value"] == 20000
    assert result["source_evidence"]["facts"][0]["source_publication_at"] is None
    assert result["valuation"]["status"] == "not_evaluated"


@pytest.mark.parametrize("entity_type,sic,expected", [
    ("operating", 3571, "eligible"),
    ("operating", 6021, "ineligible"),
    ("other", 3571, "unknown"),
    (None, 3571, "unknown"),
])
def test_sec_company_report_issuer_gate_and_same_day_cutoff(
        tmp_path, monkeypatch, entity_type, sic, expected):
    stub_technical(monkeypatch, "us")
    dates = [
        {"form": "10-K", "start": "2024-01-01", "end": "2024-12-31",
         "filed": "2025-02-01", "val": 200, "accn": "0000320193-25-000001"},
        {"form": "10-K/A", "start": "2024-01-01", "end": "2024-12-31",
         "filed": "2026-10-19", "val": 999, "accn": "0000320193-26-000002"},
    ]
    def getter(url, user_agent=None):
        if "company_tickers" in url:
            return {"0": {"ticker": "AAPL", "title": "Apple Inc.", "cik_str": 320193}}
        if "companyfacts" in url:
            return {"cik": 320193, "entityName": "Apple Inc.", "facts": {
                "us-gaap": {"Revenues": {"units": {"USD": dates}}},
            }}
        return {"sic": str(sic) if sic is not None else "",
                "entityType": entity_type,
                "filings": {"recent": {"form": [], "filingDate": [],
                                       "accessionNumber": []}}}
    r = run("AAPL", out=tmp_path, now=ASOF, facts_get=getter,
            sec_user_agent="Research Person research@example.org")
    assert r["schema_version"] == 4
    assert r["issuer_eligibility"]["status"] == expected
    assert r["complete"] is True
    assert r["valuation"]["status"] == "not_evaluated"
    assert r["source_evidence"]["facts"][0]["value"] == 200
    assert all(f["value"] != 999 for f in r["source_evidence"]["facts"])
