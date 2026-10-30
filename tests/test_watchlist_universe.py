"""#112: the scan universe is three stocks plus price-only TWSE ETFs."""
from datetime import date
from pathlib import Path

import pytest
import yaml

from market_research.twse import TwseDailyProvider
from scripts.daily_research import execute, get_pilot_symbols
from test_company_report_feedback import NOW, source_clock  # noqa: F401
from test_daily_research import Sources, delivered
from test_price_watch import watch_rows
from test_scan_company_research import artifacts

ROOT = Path(__file__).resolve().parents[1]


def test_config_universe_is_the_agreed_watchlist():
    markets = yaml.safe_load((ROOT / "config/markets.yaml").read_text(encoding="utf-8"))
    assert markets["markets"]["tw"]["symbols"] == [
        "2330.TW", "2317.TW", "2454.TW", "2356.TW", "3017.TW", "0050.TW", "00631L.TW"]
    assert get_pilot_symbols("tw") == markets["markets"]["tw"]["symbols"]


def stock_day(requested):
    def get(url, **kwargs):
        requested.append(kwargs["params"]["stockNo"])
        month = kwargs["params"]["date"]
        class Response:
            def raise_for_status(self):
                pass
            def json(self):
                roc = int(month[:4]) - 1911
                return {"stat": "OK",
                        "fields": ["日期", "成交股數", "開盤價", "最高價", "最低價", "收盤價"],
                        "data": [[f"{roc}/{month[4:6]}/15", "9,876", "250.00", "255.00",
                                  "248.00", "252.50"]]}
        return Response()
    return get


def test_twse_provider_loads_leveraged_etf_code():
    requested = []
    provider = TwseDailyProvider(get=stock_day(requested), today=date(2026, 10, 17),
                                 request_pause_seconds=0)
    frame = provider.load("00631L.TW", "3mo")
    assert set(requested) == {"00631L"}
    assert frame["close"].iloc[-1] == 252.5


@pytest.mark.parametrize("symbol", ["2330A1.TW", "ABCD.TW", "00631L.TWO", "063L.TW"])
def test_twse_provider_still_rejects_non_twse_codes(symbol):
    provider = TwseDailyProvider(get=stock_day([]), today=date(2026, 10, 17),
                                 request_pause_seconds=0)
    with pytest.raises(ValueError, match="TWSE provider"):
        provider.load(symbol, "3mo")


def test_etf_is_price_only_and_never_reaches_company_sources(tmp_path):
    sources = Sources()
    price_watch = watch_rows()
    result = execute(artifacts(tmp_path), tmp_path / "out", research_fn=sources.research,
                     publication_fn=delivered, now=NOW, price_watch_fn=price_watch,
                     symbols=["2330.TW", "0050.TW", "00631L.TW"])
    coverage = result["pilot_coverage"]
    assert sources.prices == ["2330.TW"]
    assert price_watch.requested == ["0050.TW", "00631L.TW"]  # explicit symbols add no benchmark
    assert coverage["price_only_count"] == 2
    assert coverage["failed_count"] == 0
    assert coverage["symbols"]["00631L.TW"]["status"] == "price_only"
    assert result["fixed_research"]["status"] == "complete"
    assert "price_only" in (tmp_path / "out" / "daily_summary.md").read_text()
