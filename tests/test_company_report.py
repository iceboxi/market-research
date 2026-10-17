from datetime import date
import pytest
from market_research.fundamentals import twse_fundamentals, annual_filing_fact, sec_fundamentals
from scripts.company_report import classify

def test_twse_profile_and_missing_revenue():
    def get(url):
        if "t187ap03" in url:
            return [{"公司代號":"2330","公司名稱":"台灣積體電路"}]
        return []
    data=twse_fundamentals("2330.TW",get)
    assert data["company_name"]=="台灣積體電路"
    assert data["facts"]==[]

def test_sec_10k_no_lookahead():
    data={"facts":{"us-gaap":{"NetIncomeLoss":{"units":{"USD":[
        {"form":"10-K","start":"2024-01-01","end":"2024-12-31","filed":"2025-02-01","val":90},
        {"form":"10-K","start":"2025-01-01","end":"2025-12-31","filed":"2026-02-01","val":100}
    ]}}}}}
    assert annual_filing_fact(data,["NetIncomeLoss"],"USD",date(2025,12,31))["value"]==90
    assert annual_filing_fact(data,["NetIncomeLoss"],"USD",date(2026,10,18))["value"]==100

def test_sec_contact_and_mapping():
    with pytest.raises(ValueError,match="SEC_USER_AGENT"):
        sec_fundamentals("AAPL",date(2026,10,18),user_agent="")
    def get(url,user_agent):
        if "tickers" in url:
            return {"0":{"cik_str":320193,"ticker":"AAPL","title":"Apple Inc."}}
        return {"cik":320193,"entityName":"Apple Inc.","facts":{}}
    assert sec_fundamentals("AAPL",date(2026,10,18),get,user_agent="research user@example.org")["facts"]==[]

def test_unsafe_symbols_rejected():
    for symbol in ("2330.TWO","../../etc/passwd","AAPL;echo"):
        with pytest.raises(ValueError):
            classify(symbol)
