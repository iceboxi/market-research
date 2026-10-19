"""F05 discovery fail-closed parsing without any external network dependency."""
import json

from scripts.tw_ifrs_discovery import discover, SOURCES


def response(url):
    if "swagger" in url:
        data = {"paths": {"/opendata/t187ap06_L_ci": {},
                          "/opendata/t187ap07_L_ci": {}}}
        return 200, json.dumps(data).encode(), "application/json"
    if "t187ap06" in url:
        data = [{"公司代號": "2330", "本期淨利": "DO_NOT_PERSIST", "年度": "113"}]
        return 200, json.dumps(data).encode(), "application/json"
    if "t187ap07" in url:
        data = [{"公司代號": "2330", "資產總額": "DO_NOT_PERSIST"}]
        return 200, json.dumps(data).encode(), "application/json"
    return 200, b"<html><form><input name='code'></form>現金流量表</html>", "text/html"


def test_current_openapi_rows_are_not_claimed_as_full_three_statement_history():
    result = discover(get=response)
    assert result["verdict"] == "discovery_incomplete"
    assert result["sources"]["income"]["issuer_verified"] is True
    assert result["sources"]["balance"]["issuer_verified"] is True
    assert result["sources"]["cashflow_mops"]["status"] == "query_landing_only"
    assert not result["gates"]["three_statements_same_fiscal_period_verified"]
    assert result["sources"]["swagger"]["openapi_income_path"]
    assert result["sources"]["swagger"]["openapi_balance_path"]
    assert result["sources"]["swagger"]["openapi_cashflow_paths"] == []
    assert "DO_NOT_PERSIST" not in json.dumps(result)


def test_official_page_200_is_not_evidence_of_cashflow_contents():
    report = discover(get=response)
    assert report["sources"]["cashflow_mops"]["statement_verified"] is False
    assert report["sources"]["cashflow_mops"]["publication_at"] is None


def test_200_nonmatching_issuer_fails_closed():
    def bad(url):
        if "t187ap" in url:
            return 200, b'[{"\\u516c\\u53f8\\u4ee3\\u865f":"2317"}]', "application/json"
        return 403, b"Forbidden", "text/plain"
    report = discover(get=bad)
    assert report["sources"]["income"]["status"] == "not_found"
    assert report["sources"]["balance"]["issuer_verified"] is False
    assert report["sources"]["cashflow_mops"]["status"] == "unverified"


def test_http_failures_do_not_turn_into_no_financial_event():
    def error(url):
        raise ValueError("blocked")
    result = discover(get=error)
    assert all(r["status"] == "unavailable" for r in result["sources"].values())
    assert not result["gates"]["automated_redistribution_rights_verified"]
