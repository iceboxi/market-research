"""TWSE profile outage falls back to FinMind TaiwanStockInfo identity with provenance."""
import json
from datetime import datetime, timezone

import pandas as pd
import pytest

from market_research.event_risk import TW_MATERIAL_URL
from market_research.fundamentals import (
    FINMIND_URL, TW_PROFILE, TW_REVENUE, twse_fundamentals,
)
from market_research.research_snapshot import prepare_snapshot
from scripts.company_report import run

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
STOCK_INFO = f"{FINMIND_URL}?dataset=TaiwanStockInfo&data_id="
# Natural run 40706446471: TWSE answered t187ap03_L with an HTML security page.
BLOCKED = json.JSONDecodeError("Expecting value", "<html>因為安全性考量</html>", 0)


def info(ticker, *categories, name="台積電", date="2026-10-19"):
    return {"status": 200, "msg": "success", "data": [
        {"industry_category": c, "stock_id": ticker, "stock_name": name,
         "type": "twse", "date": date} for c in categories]}


def official(url):
    if url == TW_PROFILE:
        raise BLOCKED
    if url == TW_REVENUE:
        return [{"公司代號": "2330", "當月營收": "1,000",
                 "資料年月": "11509", "出表日期": "1151010"}]
    if url == TW_MATERIAL_URL:
        return []
    raise ValueError(f"fixture has no {url}")


def external(answers):
    calls = []
    def get(url):
        calls.append(url)
        if url in answers:
            return answers[url]
        raise ValueError(f"fixture has no {url}")
    return get, calls


def test_blocked_twse_profile_uses_finmind_identity_and_keeps_revenue():
    fin_get, _ = external({STOCK_INFO + "2330": info("2330", "半導體業", "電子工業")})
    issuer = twse_fundamentals("2330.TW", official, financial_get=fin_get,
                               asof=NOW.date())
    assert issuer["company_name"] == "台積電"
    assert issuer["industry_code"] == "24"
    assert issuer["profile"] == {
        "source": STOCK_INFO + "2330", "reported_at": "20261019",
        "fallback_for": TW_PROFILE, "primary_error": "JSONDecodeError"}
    assert "issued_shares" not in issuer
    assert issuer["facts"][0]["source"] == TW_REVENUE
    assert any("FinMind TaiwanStockInfo" in w for w in issuer["warnings"])


def test_finmind_financial_sector_keeps_the_sector_17_gate():
    fin_get, calls = external({STOCK_INFO + "2881": info("2881", "金融保險", name="富邦金")})
    def get(url):
        if url == TW_PROFILE:
            raise BLOCKED
        return []
    issuer = twse_fundamentals("2881.TW", get, financial_get=fin_get, asof=NOW.date())
    assert issuer["industry_code"] == "17"
    assert calls == [STOCK_INFO + "2881"]


@pytest.mark.parametrize("answer", [
    info("2330", "電子工業"),                       # umbrella group only
    info("2330", "半導體業", "光電業"),             # two specific sectors
    {"status": 402, "msg": "quota", "data": []},
])
def test_unresolved_fallback_keeps_the_original_twse_failure(answer):
    fin_get, _ = external({STOCK_INFO + "2330": answer})
    with pytest.raises(json.JSONDecodeError):
        twse_fundamentals("2330.TW", official, financial_get=fin_get, asof=NOW.date())


def test_injected_sources_without_external_fetcher_never_call_finmind():
    with pytest.raises(json.JSONDecodeError):
        twse_fundamentals("2330.TW", official, asof=NOW.date())


class Prices:
    source = "fixture_daily"

    def load(self, symbol, period):
        days = pd.bdate_range(end="2026-10-19", periods=160).date
        return pd.DataFrame({"open": 100.0, "high": 102.0, "low": 98.0,
                             "close": 100.0, "volume": 1000},
                            index=pd.Index(days, name="date"))


def test_report_and_public_snapshot_carry_finmind_identity(tmp_path):
    fin_get, _ = external({STOCK_INFO + "2330": info("2330", "半導體業", "電子工業")})
    result = run("2330.TW", out=tmp_path, now=NOW, provider=Prices(),
                 facts_get=official, financial_get=fin_get, clock=lambda: NOW)
    assert result["complete"] is True
    assert result["instrument_eligibility"]["status"] == "candidate_for_nonfinancial_research"
    coverage = result["run_receipt"]["source_coverage"]["issuer_profile"]
    assert coverage["status"] == "available"
    assert coverage["source"] == STOCK_INFO + "2330"

    snapshot = prepare_snapshot(result, {"repository": "owner/repo", "run_id": "1",
                                         "run_attempt": 1, "code_sha": "a" * 40,
                                         "observed_at_utc": "2026-10-19T12:01:00+00:00"})
    assert snapshot["issuer"] == {"company_name": "台積電",
                                  "source": "https://api.finmindtrade.com/api/v4/data",
                                  "reported_at": "20261019",
                                  "policy": "finmind_stock_info_v1"}
    assert "invalid_or_future_profile_omitted" not in snapshot["comparison_limits"]
