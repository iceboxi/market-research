"""#142, #143: industry-watch tier — price position, P/B review zone, revenue momentum."""
from datetime import date, datetime, timezone
import json
from pathlib import Path

import httpx
import pytest

from market_research.industry_watch import (
    evaluate_pb_zone, evaluate_revenue_momentum, industry_summary_row, load_industry_watch,
    load_industry_watch_rows, momentum_summary_row,
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


# ---------------------------------------------------------------- revenue momentum

MOMENTUM = {"consecutive_months": 3}
# Apr..Sep 2026 against a flat 100 a year earlier: rolling YoY Jun..Sep
# 200.0 → 233.3 → 216.7 → 196.7%, two strict declines after the July peak.
PEAKED = (300, 300, 300, 400, 250, 240)


def revenue_rows(code="2408", recent=PEAKED, prior=100.0, created=""):
    """2025-01..2026-09; `recent` are Apr..Sep 2026, every other month is `prior`."""
    months = [(2025, m) for m in range(1, 13)] + [(2026, m) for m in range(1, 10)]
    values = [prior] * 15 + list(recent)
    return [{"date": "", "stock_id": code, "revenue_year": y, "revenue_month": m,
             "revenue": v, "create_time": created} for (y, m), v in zip(months, values)]


def momentum(rows, cutoff=LAST, months=3):
    return evaluate_revenue_momentum("2408.TW", cutoff, {"consecutive_months": months},
                                     {"source": "finmind-revenue-url", "rows": rows})


@pytest.mark.parametrize("recent, status, declining, reason", [
    (PEAKED, "ok", 2, "3 個月滾動年增率連續下降 2 個月（門檻 3）"),
    ((400, 380, 360, 340, 320, 300), "slowing", 3, "3 個月滾動年增率連續下降 3 個月（門檻 3）"),
    ((200,) * 6, "ok", 0, "3 個月滾動年增率連續下降 0 個月（門檻 3）"),  # equal is not a decline
    # Below zero wins over three declines.
    ((130, 120, 110, 100, 90, 80), "contracting", 3, "3 個月滾動年增率 -10.00%，低於 0"),
])
def test_rolling_yoy_momentum_states(recent, status, declining, reason):
    result = momentum(revenue_rows(recent=recent))
    assert (result["status"], result["declining_months"], result["reason"]) == (status, declining, reason)
    assert [m["period"] for m in result["months"]] == ["2026-06", "2026-07", "2026-08", "2026-09"]
    assert result["latest_period"] == "2026-09" and result["dataset"] == "TaiwanStockMonthRevenue"


def test_months_carry_single_month_yoy_mom_and_rolling_yoy():
    result = momentum(revenue_rows())
    assert [(m["yoy_pct"], m["mom_pct"], m["rolling_3m_yoy_pct"]) for m in result["months"]] == [
        (200.0, 0.0, 200.0), (300.0, 33.33, 233.33), (150.0, -37.5, 216.67), (140.0, -4.0, 196.67)]
    assert result["source"] == "finmind-revenue-url" and result["latest_published"] is None


def test_consecutive_months_setting_changes_the_bar():
    assert momentum(revenue_rows(), months=2)["status"] == "slowing"
    assert momentum(revenue_rows(), months=1)["status"] == "slowing"
    four = momentum(revenue_rows(recent=(400, 380, 360, 340, 320, 300)), months=4)
    assert (four["status"], len(four["months"]), four["months"][0]["period"]) == ("ok", 5, "2026-05")


def test_real_2408_rolling_yoy_peaked_in_july_and_fell_twice_by_september():
    # FinMind TaiwanStockMonthRevenue for 2408, fetched 2026-10-31.
    fixture = json.loads((ROOT / "tests" / "fixtures" / "finmind_month_revenue_2408.json").read_text())
    rows = [dict(zip(fixture["fields"], r), stock_id="2408") for r in fixture["rows"]]
    result = momentum(rows, cutoff=date(2026, 10, 30))
    assert (result["status"], result["declining_months"]) == ("ok", 2)
    # Expected values computed independently from the raw FinMind response.
    assert [m["rolling_3m_yoy_pct"] for m in result["months"]] == [684.23, 690.98, 628.56, 611.7]
    assert (result["latest_period"], result["latest_published"]) == ("2026-09", "2026-10-06")
    assert (result["months"][-1]["yoy_pct"], result["months"][-1]["mom_pct"]) == (576.62, 0.9)
    # On 2026-10-05 September (published 10/06) was not yet public: May..August.
    before = momentum(rows, cutoff=date(2026, 10, 5))
    assert [m["rolling_3m_yoy_pct"] for m in before["months"]] == [674.93, 684.23, 690.98, 628.56]
    assert before["latest_period"] == "2026-08" and before["declining_months"] == 1


def test_months_before_their_publication_are_never_read():
    rows = revenue_rows()
    rows[-1]["create_time"] = "2026-10-06"  # September published on 10/06
    assert momentum(rows, cutoff=date(2026, 10, 6))["latest_period"] == "2026-09"
    before = momentum(rows, cutoff=date(2026, 10, 5))
    assert before["latest_period"] == "2026-08" and before["months"][-1]["period"] == "2026-08"
    assert before == momentum(rows[:-1], cutoff=date(2026, 10, 5))  # as if September did not exist
    # Without create_time a month is public from the 10th of the next month.
    undated = revenue_rows()
    assert momentum(undated, cutoff=date(2026, 10, 10))["latest_period"] == "2026-09"
    assert momentum(undated, cutoff=date(2026, 10, 9))["latest_period"] == "2026-08"


@pytest.mark.parametrize("edit, reason", [
    (lambda rows: [r for r in rows if (r["revenue_year"], r["revenue_month"]) != (2025, 5)],
     "缺月營收：2025-05"),
    # After the 10th September is due; an older latest month is not evaluated instead.
    (lambda rows: rows[:-1], "缺月營收：2026-09"),
    (lambda rows: [dict(r, revenue=0) if r["revenue_year"] == 2025 and 4 <= r["revenue_month"] <= 6
                   else r for r in rows], "去年同期營收合計小於等於 0：2025-06"),
    (lambda rows: None, "FinMind TaiwanStockMonthRevenue unavailable"),
    (lambda rows: revenue_rows(code="2344"), "foreign stock_id 2344 in TaiwanStockMonthRevenue"),
])
def test_gaps_are_not_evaluated_never_zero_filled(edit, reason):
    rows = edit(revenue_rows())
    result = (evaluate_revenue_momentum("2408.TW", LAST, MOMENTUM, None) if rows is None
              else momentum(rows))
    assert result["status"] == "not_evaluated" and result["reason"] == reason
    assert result["months"] == [] and result["declining_months"] is None


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
    assert group["revenue_momentum"] == {"consecutive_months": 3} and group["overrides"] == {}
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
    (GROUP + "    revenue_momentum:\n      consecutive_months: 0\n", "integer from 1 to 12"),
    (GROUP + "    revenue_momentum:\n      consecutive_months: 13\n", "integer from 1 to 12"),
    (GROUP + "    revenue_momentum:\n      consecutive_months: true\n", "integer from 1 to 12"),
    (GROUP + "    revenue_momentum:\n      yoy_below_pct: 0\n", "unknown revenue_momentum keys"),
    (GROUP.replace("2408.TW: 南亞科", "2408.TW:\n        name: 南亞科\n        thesis: x"),
     "2408.TW: unknown keys"),
    (GROUP.replace("2408.TW: 南亞科", "2408.TW:\n        revenue_momentum:\n"
                   "          consecutive_months: 2"), "company name must be text"),
])
def test_invalid_groups_fail_when_the_config_loads(tmp_path, groups, match):
    with pytest.raises(ValueError, match=match):
        load_industry_watch(config(tmp_path, groups))


def test_custom_percentiles_are_kept(tmp_path):
    [group] = load_industry_watch(config(tmp_path, GROUP + "    pb_zone:\n      percentiles: [10, 50, 90]\n"))
    assert group["pb_zone"] == {"percentiles": (10, 50, 90)}


def test_momentum_months_override_by_group_and_by_stock(tmp_path):
    groups = GROUP.replace("2408.TW: 南亞科", "2408.TW:\n        name: 南亞科\n        revenue_momentum:\n"
                           "          consecutive_months: 2\n      2344.TW: 華邦電")
    [group] = load_industry_watch(config(tmp_path, groups + "    revenue_momentum:\n"
                                                            "      consecutive_months: 4\n"))
    assert group["symbols"] == {"2408.TW": "南亞科", "2344.TW": "華邦電"}
    assert group["revenue_momentum"] == {"consecutive_months": 4}
    assert group["overrides"] == {"2408.TW": {"revenue_momentum": {"consecutive_months": 2}}}


# ---------------------------------------------------------------- loader

GROUPS = [{"id": "memory", "name": "記憶體", "rationale": "理由",
           "symbols": {"2408.TW": "南亞科", "2344.TW": "華邦電"}, "pb_zone": SETTING,
           "revenue_momentum": MOMENTUM, "overrides": {}}]


def finmind(fail=()):
    """FinMind by dataset; a URL containing any `fail` text raises."""
    def get(url):
        get.urls.append(url)
        code = url.split("data_id=")[1].split("&")[0]
        if any(text in url for text in fail):
            raise httpx.ConnectError("FinMind unreachable")
        if "TaiwanStockMonthRevenue" in url:
            return {"status": 200, "data": revenue_rows(code)}
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
    result = load_industry_watch_rows(GROUPS, EVENING, provider=provider(), get=get)
    assert result["status"] == "complete" and result["cutoff"] == "2026-10-29"
    assert [g["symbols"] for g in result["groups"]] == [["2408.TW", "2344.TW"]]
    row = result["rows"][0]
    assert (row["symbol"], row["name"], row["group"], row["status"]) == ("2408.TW", "南亞科", "memory", "available")
    assert row["price_position"]["session"] == "2026-10-29" and "kind" not in row["price_position"]
    assert row["pb_zone"]["zone"] == "fair" and row["pb_zone"]["pbr_history"]["source"] == get.urls[0]
    assert get.urls[0].endswith("dataset=TaiwanStockPER&data_id=2408&start_date=2021-10-29")
    mom = row["revenue_momentum"]
    assert (mom["status"], mom["declining_months"], mom["source"]) == ("ok", 2, get.urls[1])
    assert get.urls[1].endswith("dataset=TaiwanStockMonthRevenue&data_id=2408&start_date=2023-10-01")


def test_failed_revenue_leaves_price_and_zone_alone():
    result = load_industry_watch_rows(GROUPS, EVENING, provider=provider(),
                                      get=finmind(fail=("TaiwanStockMonthRevenue",)))
    assert result["status"] == "partial"
    for row in result["rows"]:
        assert row["status"] == "partial"
        assert row["price_position"]["status"] == row["pb_zone"]["status"] == "available"
        assert row["revenue_momentum"]["status"] == "not_evaluated"
        assert row["revenue_momentum"]["reason"] == "FinMind TaiwanStockMonthRevenue unavailable: ConnectError"


def test_stock_override_applies_to_that_stock_only():
    groups = [dict(GROUPS[0], overrides={"2408.TW": {"revenue_momentum": {"consecutive_months": 2}}})]
    nanya, winbond = load_industry_watch_rows(groups, EVENING, provider=provider(), get=finmind())["rows"]
    assert (nanya["revenue_momentum"]["status"], winbond["revenue_momentum"]["status"]) == ("slowing", "ok")


def test_one_failed_source_stays_in_its_own_row():
    result = load_industry_watch_rows(GROUPS, EVENING, provider=provider(failing=("2408.TW",)),
                                      get=finmind(fail=("2344",)))
    nanya, winbond = result["rows"]
    assert result["status"] == "partial"
    assert nanya["price_position"]["status"] == "failed"
    assert nanya["pb_zone"]["reason"] == "Verified close unavailable: ReadTimeout"
    assert winbond["price_position"]["status"] == "available"
    assert winbond["pb_zone"]["reason"] == "FinMind TaiwanStockPER unavailable: ConnectError"


def test_stale_bars_are_never_priced():
    next_evening = datetime(2026, 10, 30, 12, 0, tzinfo=timezone.utc)
    result = load_industry_watch_rows(GROUPS, next_evening, provider=provider(), get=finmind())
    for row in result["rows"]:
        assert row["price_position"]["error_type"] == "StaleMarketData"
        assert row["pb_zone"]["status"] == "not_evaluated"


# ---------------------------------------------------------------- daily outputs

def loaded(groups, now):
    return load_industry_watch_rows(groups, EVENING, provider=provider(), get=finmind())


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
    assert receipt["industry_watch"]["rows"][0]["revenue_momentum"]["status"] == "ok"
    assert ("| 2408.TW 南亞科 | 未放緩：3 個月滾動年增率連續下降 2 個月（門檻 3） | 2026-06～2026-09 "
            "| +200.0%／+300.0%／+150.0%／+140.0% | +0.0%／+33.3%／-37.5%／-4.0% "
            "| +200.0% → +233.3% → +216.7% → +196.7% | 2026-09（依法定期限） |") in summary


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


def test_unevaluated_momentum_row_names_its_gap():
    row = {"symbol": "2408.TW", "name": "南亞科",
           "revenue_momentum": momentum(revenue_rows()[:-1])}
    assert momentum_summary_row(row) == (
        "| 2408.TW 南亞科 | not_evaluated：缺月營收：2026-09 | — | — | — | — | — |")
