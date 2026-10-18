from datetime import date
from market_research.company_analysis import compare_financials, research_status, render_financial_research

def fact(value, filed="2026-02-01", start="2025-01-01"):
    return {"period_start": start, "period_end": "2025-12-31", "filed": filed,
            "value": value, "source": "SEC", "accession": "0001"}

def issuer():
    return {"market": "us", "financial_history": {
        "currency": "USD", "period_type": "annual_10k", "source": "SEC",
        "annual_revenue": [fact(100)], "annual_net_income": [fact(20)],
        "annual_operating_cash_flow": [fact(30)], "annual_capex": [fact(10)],
        "annual_free_cash_flow": [fact(20)], "annual_diluted_shares": [fact(5)]}}

def test_comparison_margins_sources_and_output():
    c = compare_financials(issuer(), date(2026, 10, 18))
    assert c["rows"][0]["net_margin_pct"] == 20
    assert c["rows"][0]["fcf_margin_pct"] == 20
    assert c["rows"][0]["filing_provenance"]["annual_revenue"]["filed"] == "2026-02-01"
    assert "2025-12-31" in "\n".join(render_financial_research(c, research_status(c, {"status":"not_evaluated"}, {})))

def test_no_lookahead_and_no_mixed_fiscal_period():
    item = issuer()
    item["financial_history"]["annual_revenue"] = [fact(100, filed="2027-01-01")]
    item["financial_history"]["annual_capex"] = [fact(10, start="2025-04-01")]
    c = compare_financials(item, date(2026, 10, 18))
    assert c["rows"][0]["metrics"]["annual_revenue"] is None
    assert c["rows"][0]["metrics"]["annual_capex"] is None

def test_taiwan_monthly_revenue_stays_preliminary():
    c = compare_financials({"market":"tw","facts":[{"metric":"monthly_reported_revenue","value":100}]}, date(2026,10,18))
    assert c["status"] == "unavailable"

def test_active_pattern_is_not_a_trade_recommendation():
    r = research_status({"status":"available"}, {"status":"illustrative_only"},
                        {"status":"available","observations":[
                            {"strategy_id":"sakata_three_soldiers","active":True,"matched":True},
                            {"strategy_id":"sakata_morning_star","active":False,"matched":True}]})
    assert r["active_pattern_observations"] == ["sakata_three_soldiers"]
    assert r["investment_recommendation"] == "not_available"
