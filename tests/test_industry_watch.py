"""#142: industry-watch tier — price position and P/B review zone, no company research."""
from datetime import date, datetime, timezone
import json
from pathlib import Path

import httpx
import pytest

from market_research.industry_watch import (
    evaluate_pb_zone, industry_summary_row, load_industry_watch, load_industry_watch_rows,
)
from market_research.valuation_zone import per_window_start
from scripts.daily_research import execute
from test_company_report_feedback import NOW, source_clock  # noqa: F401
from test_daily_research import Sources, delivered
from test_price_watch import LAST, FrameProvider, bars, sessions, watch_rows
from test_scan_company_research import artifacts

ROOT = Path(__file__).resolve().parents[1]
SETTING = {"percentiles": (20, 50, 80)}
EVENING = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)  # 20:00 Taipei, 10/29 complete


def pbr_rows(code, days, values):
    return [{"date": d.isoformat(), "stock_id": code, "PER": 10.0, "PBR": v, "dividend_yield": 1.0}
            for d, v in zip(days, values)]


def ladder(latest):
    """1,001 evenly spaced P/B values 1.000..5.000 ending on `latest`.

    np.percentile interpolates linearly over 1,000 gaps, so P20/P50/P80 are exactly the
    200th/500th/800th values: 1.8 / 3.0 / 4.2, whatever order the days come in.
    """
    days = sessions(per_window_start(LAST), LAST)[-1001:]
    values = [round(1.0 + 0.004 * j, 3) for j in range(1001)]
    values.remove(latest)
    return days, values + [latest]


def history(code="2408", latest=3.0):
    days, values = ladder(latest)
    return {"source": "finmind-url", "rows": pbr_rows(code, days, values)}, days


def price(close, session=LAST):
    return {"close": close, "session": session.isoformat(), "source": "twse_stock_day_official_raw_ohlcv"}


# ---------------------------------------------------------------- P/B review zone

@pytest.mark.parametrize("latest, zone", [(1.2, "below_low"), (3.0, "fair"), (4.6, "above_high")])
def test_band_is_the_stocks_own_pbr_percentiles_times_implied_book_value(latest, zone):
    per, days = history(latest=latest)
    result = evaluate_pb_zone("2408.TW", LAST, SETTING, per, price(latest * 100))
    assert result["status"] == "available" and result["zone"] == zone
    assert result["pb_band"] == {"low": 1.8, "mid": 3.0, "high": 4.2}
    assert result["book_value_per_share"] == 100.0  # close / P/B of the same day
    assert result["review_prices_twd"] == {"low": 180.0, "mid": 300.0, "high": 420.0}
    assert result["pbr_history"]["samples"] == 1001
    assert result["pbr_history"]["first_date"] == days[0].isoformat()
    assert result["disclaimer"] == "檢視區，非買賣建議"


def test_real_2408_rows_on_2026_10_30_sit_above_the_high_review_price():
    # FinMind TaiwanStockPER for 2408, fetched 2026-10-31; close 454.50 (TWSE, 2026-10-30).
    fixture = json.loads((ROOT / "tests" / "fixtures" / "finmind_pbr_2408.json").read_text())
    rows = [{"date": d, "stock_id": "2408", "PBR": v} for d, v in fixture["rows"]]
    cutoff = date(2026, 10, 30)
    result = evaluate_pb_zone("2408.TW", cutoff, SETTING, {"source": fixture["source"], "rows": rows},
                              price(454.5, cutoff))
    assert result["status"] == "available" and result["zone"] == "above_high"
    hist = result["pbr_history"]
    assert (hist["samples"], hist["first_date"], hist["latest_pbr"]) == (1212, "2021-11-01", 4.86)
    assert round(hist["latest_percentile_rank"]) == 89
    assert result["book_value_per_share"] == 93.52


def test_rows_after_the_cutoff_and_non_positive_pbr_are_never_read():
    per, _ = history()
    per["rows"] += pbr_rows("2408", [date(2026, 10, 30)], [99.0])  # after the cutoff
    per["rows"][0]["PBR"] = -0.5  # negative equity is excluded, not zero-filled
    result = evaluate_pb_zone("2408.TW", LAST, SETTING, per, price(300.0))
    assert result["pbr_history"]["latest_pbr"] == 3.0
    assert result["pbr_history"]["samples"] == 1000
    assert result["status"] == "available"


def test_too_few_samples_is_not_evaluated_with_the_count():
    days, values = ladder(3.0)
    per = {"source": "u", "rows": pbr_rows("2408", days[-719:], values[-719:])}
    result = evaluate_pb_zone("2408.TW", LAST, SETTING, per, price(300.0))
    assert result["status"] == "not_evaluated" and result["review_prices_twd"] is None
    assert result["reason"] == "Only 719 PBR samples in the 5-year window; need 720"
    assert result["pbr_history"]["samples"] == 719


def test_pbr_and_close_from_different_days_cannot_imply_book_value():
    per, days = history()
    result = evaluate_pb_zone("2408.TW", LAST, SETTING, {"source": "u", "rows": per["rows"][:-1]},
                              price(300.0))
    assert result["status"] == "not_evaluated"
    assert result["reason"].startswith(f"Latest PBR is dated {days[-2]}, the close {LAST}")


@pytest.mark.parametrize("per, close, reason", [
    (None, price(300.0), "FinMind TaiwanStockPER unavailable"),
    ("history", None, "Verified close unavailable"),
    ("foreign", price(300.0), "foreign stock_id 2344 in TaiwanStockPER"),
])
def test_missing_or_foreign_inputs_are_not_evaluated(per, close, reason):
    if per == "history":
        per, _ = history()
    elif per == "foreign":
        per, _ = history(code="2344")
    result = evaluate_pb_zone("2408.TW", LAST, SETTING, per, close)
    assert result["status"] == "not_evaluated" and result["reason"] == reason


# ---------------------------------------------------------------- configuration

MARKETS = "markets:\n  tw:\n    symbols: [2330.TW, 0050.TW]\n"


def config(tmp_path, groups):
    (tmp_path / "markets.yaml").write_text(MARKETS)
    (tmp_path / "watchlist.yaml").write_text(
        "satellites:\n  2330.TW:\n    thesis: null\nindustry_watch:\n" + groups, encoding="utf-8")
    return tmp_path


GROUP = "  memory:\n    name: 記憶體\n    rationale: 理由\n    symbols:\n      2408.TW: 南亞科\n"


def test_repository_memory_group_defaults_to_p20_p50_p80():
    [group] = load_industry_watch(ROOT / "config")
    assert group["id"] == "memory" and group["name"] == "記憶體"
    assert group["symbols"] == {"2408.TW": "南亞科", "2344.TW": "華邦電"}
    assert group["pb_zone"] == {"percentiles": (20, 50, 80)}
    assert "Sandisk" in group["rationale"] and "2026-10-29" in group["rationale"]


@pytest.mark.parametrize("groups, match", [
    (GROUP.replace("2408.TW", "2330.TW"), "already scanned in markets.yaml or a satellite"),
    (GROUP.replace("2408.TW", "8299.TWO"), "stock codes end in .TW"),
    (GROUP.replace("2408.TW", "2408"), "stock codes end in .TW"),
    (GROUP.replace("2408.TW", "0056.TW"), "ETF/ETN codes are price-only"),
    (GROUP + GROUP.replace("memory", "dram"), "listed in more than one group"),
    (GROUP.replace("    name: 記憶體\n", ""), "name must be text"),
    (GROUP + "    pb_zone:\n      percentiles: [80, 50, 20]\n", "three increasing numbers"),
    (GROUP + "    pb_zone:\n      pe_multiples: [5, 10, 15]\n", "unknown pb_zone keys"),
    (GROUP + "    thesis: x\n", "unknown keys"),
])
def test_invalid_groups_fail_when_the_config_loads(tmp_path, groups, match):
    with pytest.raises(ValueError, match=match):
        load_industry_watch(config(tmp_path, groups))


def test_custom_percentiles_are_kept(tmp_path):
    [group] = load_industry_watch(config(tmp_path, GROUP + "    pb_zone:\n      percentiles: [10, 50, 90]\n"))
    assert group["pb_zone"] == {"percentiles": (10, 50, 90)}


# ---------------------------------------------------------------- loader

GROUPS = [{"id": "memory", "name": "記憶體", "rationale": "理由",
           "symbols": {"2408.TW": "南亞科", "2344.TW": "華邦電"}, "pb_zone": SETTING}]


def finmind(fail=()):
    def get(url):
        get.urls.append(url)
        code = url.split("data_id=")[1].split("&")[0]
        if code in fail:
            raise httpx.ConnectError("FinMind unreachable")
        days, values = ladder(3.0)
        return {"status": 200, "data": pbr_rows(code, days, values)}
    get.urls = []
    return get


def provider(failing=()):
    dates = sessions("2025-09-01", LAST)
    return FrameProvider({s: bars(dates, [100.0] * len(dates)) for s in ("2408.TW", "2344.TW")},
                         failing=failing)


def test_every_stock_gets_its_price_position_and_zone():
    get = finmind()
    result = load_industry_watch_rows(GROUPS, EVENING, provider=provider(), per_get=get)
    assert result["status"] == "complete" and result["cutoff"] == "2026-10-29"
    assert [g["symbols"] for g in result["groups"]] == [["2408.TW", "2344.TW"]]
    row = result["rows"][0]
    assert (row["symbol"], row["name"], row["group"], row["status"]) == ("2408.TW", "南亞科", "memory", "available")
    assert row["price_position"]["session"] == "2026-10-29" and "kind" not in row["price_position"]
    assert row["pb_zone"]["zone"] == "fair" and row["pb_zone"]["pbr_history"]["source"] == get.urls[0]
    assert get.urls[0].endswith("dataset=TaiwanStockPER&data_id=2408&start_date=2021-10-29")


def test_one_failed_source_stays_in_its_own_row():
    result = load_industry_watch_rows(GROUPS, EVENING, provider=provider(failing=("2408.TW",)),
                                      per_get=finmind(fail=("2344",)))
    nanya, winbond = result["rows"]
    assert result["status"] == "partial"
    assert nanya["price_position"]["status"] == "failed"
    assert nanya["pb_zone"]["reason"] == "Verified close unavailable: ReadTimeout"
    assert winbond["price_position"]["status"] == "available"
    assert winbond["pb_zone"]["reason"] == "FinMind TaiwanStockPER unavailable: ConnectError"


def test_stale_bars_are_never_priced():
    next_evening = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    result = load_industry_watch_rows(GROUPS, next_evening, provider=provider(), per_get=finmind())
    for row in result["rows"]:
        assert row["price_position"]["error_type"] == "StaleMarketData"
        assert row["pb_zone"]["status"] == "not_evaluated"


# ---------------------------------------------------------------- daily outputs

def loaded(groups, now):
    return load_industry_watch_rows(groups, EVENING, provider=provider(), per_get=finmind())


def test_daily_summary_lists_the_group_after_the_satellites(tmp_path):
    result = execute(artifacts(tmp_path), tmp_path / "out", research_fn=Sources().research,
                     publication_fn=delivered, now=NOW, price_watch_fn=watch_rows(),
                     symbols=["2330.TW"], benchmarks=[], industry_groups=GROUPS,
                     industry_watch_fn=loaded)
    assert result["status"] == "complete" and result["industry_watch"]["status"] == "complete"
    receipt = json.loads((tmp_path / "out" / "daily_receipt.json").read_text())
    assert [r["symbol"] for r in receipt["industry_watch"]["rows"]] == ["2408.TW", "2344.TW"]
    summary = (tmp_path / "out" / "daily_summary.md").read_text()
    assert "### 產業觀察（檢視區，非買賣建議）" in summary and "#### 記憶體" in summary
    first = ladder(3.0)[0][0]
    # Close 100 / P/B 3.0 = book value 33.33; x 1.8 / 3.0 / 4.2.
    assert (f"| 2408.TW 南亞科 | 100.00（2026-10-29） | +0.00% | +0.00% | 3.00（P50） | 60.00 "
            f"| 100.00 | 140.00 | 合理區間 | 1001 筆（{first}～2026-10-29） | — |") in summary


def test_industry_failure_never_changes_the_run_or_the_satellites(tmp_path):
    def broken(groups, now):
        raise httpx.ConnectError("unreachable")
    result = execute(artifacts(tmp_path), tmp_path / "out", research_fn=Sources().research,
                     publication_fn=delivered, now=NOW, price_watch_fn=watch_rows(),
                     symbols=["2330.TW"], benchmarks=[], industry_groups=GROUPS,
                     industry_watch_fn=broken)
    assert result["industry_watch"] == {"status": "failed", "error_type": "ConnectError",
                                        "reason": "unreachable"}
    assert result["fixed_research"]["status"] == "complete" and result["status"] == "complete"
    assert "取得失敗：ConnectError：unreachable" in (tmp_path / "out" / "daily_summary.md").read_text()


def test_explicit_symbols_run_no_industry_watch(tmp_path):
    def never(groups, now):
        raise AssertionError("industry watch must not run")
    result = execute(artifacts(tmp_path), tmp_path / "out", research_fn=Sources().research,
                     publication_fn=delivered, now=NOW, price_watch_fn=watch_rows(),
                     symbols=["2330.TW"], benchmarks=[], industry_watch_fn=never)
    assert result["industry_watch"] is None
    assert "產業觀察" not in (tmp_path / "out" / "daily_summary.md").read_text()


def test_failed_price_row_shows_its_error_and_no_zone():
    row = {"symbol": "2408.TW", "name": "南亞科", "group": "memory", "status": "partial",
           "price_position": {"status": "failed", "error_type": "StaleMarketData", "reason": "stale"},
           "pb_zone": {"status": "not_evaluated", "zone": "not_evaluated",
                       "reason": "Verified close unavailable: StaleMarketData",
                       "pbr_history": None, "review_prices_twd": None}}
    assert industry_summary_row(row) == (
        "| 2408.TW 南亞科 | — | — | — | — | — | — | — "
        "| not_evaluated：Verified close unavailable: StaleMarketData | — "
        "| 行情取得失敗：StaleMarketData：stale |")
