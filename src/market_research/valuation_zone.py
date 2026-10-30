"""Historical P/E review zone for watchlist satellite stocks (#114).

Percentiles of the stock's own daily P/E over the five years up to the
evaluation cutoff, times trailing four-quarter basic EPS, give low / mid / high
review prices. A review zone asks a person to look again; it is not a fair
value, target, entry or exit price.
"""
from datetime import date, timedelta
import math
from pathlib import Path

import numpy as np
import yaml

from .thesis_check import DEFAULT_RULE, MAX_CONSECUTIVE_MONTHS

PER_DATASET = "TaiwanStockPER"
DEFAULT_PERCENTILES = (20, 50, 80)
WINDOW_YEARS = 5
# A five-year window holds about 1,210 TWSE sessions; require roughly three years.
MIN_PER_SAMPLES = 720
# Q4 is due by 31 March and Q1 by 15 May, so a current TTM ends at most ~136 days
# before any evaluation date; 200 leaves room for FinMind publication lag.
MAX_TTM_AGE_DAYS = 200
DISCLAIMER = "檢視區，非買賣建議"
ASSUMPTIONS = (
    "Review prices = P/E band x trailing four-quarter basic EPS; the band is the stock's own "
    "daily P/E percentiles (linear interpolation) over the five years up to the cutoff, "
    "positive P/E only, unless config/watchlist.yaml fixes the multiples. Historical P/E "
    "uses TWSE trailing EPS at each date; no forward earnings, growth or rate adjustment."
)


def per_window_start(cutoff):
    """First day of the five-year P/E window ending at cutoff."""
    try:
        return cutoff.replace(year=cutoff.year - WINDOW_YEARS)
    except ValueError:  # 29 February
        return cutoff.replace(year=cutoff.year - WINDOW_YEARS, day=28)


def _increasing_triple(values, symbol, field):
    if (not isinstance(values, list) or len(values) != 3 or
            any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                for v in values) or not values[0] < values[1] < values[2]):
        raise ValueError(f"watchlist {symbol}: {field} must be three increasing numbers")
    return values


def load_watchlist(config_dir):
    """Satellite settings by symbol; a strict subset of the scanned TW stocks.

    config/markets.yaml alone decides what is scanned; watchlist.yaml only adds
    thesis, valuation-zone and revenue-check settings for some of those stocks.
    """
    path = Path(config_dir) / "watchlist.yaml"
    if not path.exists():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    markets = yaml.safe_load((Path(config_dir) / "markets.yaml").read_text())["markets"]
    scanned = set((markets.get("tw") or {}).get("symbols") or [])
    if set(raw) - {"satellites"}:
        raise ValueError(f"watchlist: unknown top-level keys {sorted(set(raw) - {'satellites'})}")
    satellites = {}
    for symbol, entry in (raw.get("satellites") or {}).items():
        entry = entry or {}
        if symbol not in scanned:
            raise ValueError(f"watchlist {symbol}: not a scanned tw symbol in markets.yaml")
        if symbol.split(".")[0].startswith("00"):
            raise ValueError(f"watchlist {symbol}: ETF/ETN codes are price-only, not satellites")
        if not isinstance(entry, dict) or set(entry) - {"thesis", "valuation_zone", "revenue_check"}:
            raise ValueError(f"watchlist {symbol}: unknown keys")
        thesis = entry.get("thesis")
        if thesis is not None and not isinstance(thesis, str):
            raise ValueError(f"watchlist {symbol}: thesis must be text or null")
        zone = entry.get("valuation_zone") or {}
        if not isinstance(zone, dict) or set(zone) - {"percentiles", "pe_multiples"}:
            raise ValueError(f"watchlist {symbol}: unknown valuation_zone keys")
        if "percentiles" in zone and "pe_multiples" in zone:
            raise ValueError(f"watchlist {symbol}: use either percentiles or pe_multiples")
        if "pe_multiples" in zone:
            multiples = _increasing_triple(zone["pe_multiples"], symbol, "pe_multiples")
            if multiples[0] <= 0:
                raise ValueError(f"watchlist {symbol}: pe_multiples must be positive")
            setting = {"pe_multiples": tuple(float(v) for v in multiples)}
        else:
            percentiles = _increasing_triple(zone.get("percentiles", list(DEFAULT_PERCENTILES)),
                                             symbol, "percentiles")
            if not (0 < percentiles[0] and percentiles[2] < 100):
                raise ValueError(f"watchlist {symbol}: percentiles must be between 0 and 100")
            setting = {"percentiles": tuple(percentiles)}
        satellites[symbol] = {"thesis": thesis, "valuation_zone": setting,
                              "revenue_check": _revenue_rule(entry.get("revenue_check"), symbol)}
    return satellites


def _revenue_rule(raw, symbol):
    rule = dict(DEFAULT_RULE)
    raw = raw or {}
    if not isinstance(raw, dict) or set(raw) - set(rule):
        raise ValueError(f"watchlist {symbol}: unknown revenue_check keys")
    months = raw.get("consecutive_months", rule["consecutive_months"])
    if isinstance(months, bool) or not isinstance(months, int) or not 1 <= months <= MAX_CONSECUTIVE_MONTHS:
        raise ValueError(f"watchlist {symbol}: consecutive_months must be an integer "
                         f"from 1 to {MAX_CONSECUTIVE_MONTHS}")
    threshold = raw.get("yoy_below_pct", rule["yoy_below_pct"])
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not math.isfinite(threshold):
        raise ValueError(f"watchlist {symbol}: yoy_below_pct must be a number")
    return {"consecutive_months": months, "yoy_below_pct": float(threshold)}


def _per_series(rows, code, cutoff):
    """Positive daily P/E dated within [window start, cutoff]; nothing later is read."""
    start = per_window_start(cutoff)
    by_date = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        if str(row.get("stock_id", "")).strip() != code:
            raise ValueError(f"foreign stock_id {row.get('stock_id')} in {PER_DATASET}")
        try:
            day = date.fromisoformat(str(row.get("date", "")).strip())
        except ValueError:
            continue
        if not start <= day <= cutoff:
            continue
        value = row.get("PER")
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        # Loss-making periods have no meaningful P/E; they are excluded, not zero-filled.
        if not math.isfinite(value) or value <= 0:
            continue
        if day in by_date and by_date[day] != float(value):
            raise ValueError(f"conflicting duplicate {PER_DATASET} rows on {day}")
        by_date[day] = float(value)
    return sorted(by_date.items())


def evaluate_valuation_zone(symbol, cutoff, settings, per_history, ttm, price):
    """Review zone for one satellite at the evaluation cutoff (a Taipei date).

    per_history: {"source": url, "rows": FinMind TaiwanStockPER rows} or None.
    ttm: financial_history["ttm"]. price: {"close", "session", "source"}.
    """
    result = {
        "status": "not_evaluated", "zone": "not_evaluated", "reason": None,
        "method": None, "cutoff": cutoff.isoformat(), "review_prices_twd": None,
        "pe_band": None, "percentiles": None, "per_history": None, "eps": None,
        "price": None, "assumptions": ASSUMPTIONS, "disclaimer": DISCLAIMER,
    }

    def blocked(reason):
        result["reason"] = reason
        return result

    if settings is None:
        return blocked("Not a watchlist satellite (config/watchlist.yaml)")
    ttm = ttm or {}
    eps = ttm.get("basic_eps") if ttm.get("status") == "available" else None
    derivation = ttm.get("eps_derivation")
    if eps is None and ttm.get("status") == "available" and ttm.get("quarter_eps_sum") is not None:
        # TWSE's P/E history divides by the same plain four-quarter sum, so the band and EPS
        # stay on one basis even when the share count moved more than 0.5% (#133).
        eps, derivation = ttm["quarter_eps_sum"], "sum_of_four_quarters_twse_pe_basis"
    if eps is None or isinstance(eps, bool) or not math.isfinite(eps):
        return blocked("TTM EPS unavailable: " + str(ttm.get("reason") or
                       ttm.get("eps_derivation") or "no verified four-quarter EPS"))
    result["eps"] = {"ttm_basic_eps": float(eps), "period_start": ttm.get("period_start"),
                     "period_end": ttm.get("period_end"), "quarters": ttm.get("quarters"),
                     "derivation": derivation}
    if eps <= 0:
        return blocked("TTM EPS is not positive; a P/E band is undefined")
    eps_end = date.fromisoformat(ttm["period_end"])
    if eps_end > cutoff:
        return blocked("TTM EPS period ends after evaluation cutoff")
    if (cutoff - eps_end).days > MAX_TTM_AGE_DAYS:
        return blocked(f"TTM EPS is stale: period ended {eps_end}, "
                       f"over {MAX_TTM_AGE_DAYS} days before cutoff")

    price = price or {}
    close, session = price.get("close"), price.get("session")
    if close is None or isinstance(close, bool) or not math.isfinite(close) or close <= 0 or not session:
        return blocked("Verified close unavailable")
    if date.fromisoformat(str(session)[:10]) > cutoff:
        return blocked("Close session is after evaluation cutoff")
    result["price"] = {"close": float(close), "session": str(session)[:10],
                       "source": price.get("source")}

    setting = settings["valuation_zone"]
    code = symbol.split(".")[0]
    series = []
    if per_history is not None:
        try:
            series = _per_series(per_history.get("rows") or [], code, cutoff)
        except ValueError as error:
            if "pe_multiples" not in setting:
                return blocked(str(error))
        if series:
            result["per_history"] = {
                "dataset": PER_DATASET, "source": per_history.get("source"),
                "window_start": per_window_start(cutoff).isoformat(),
                "first_date": series[0][0].isoformat(), "last_date": series[-1][0].isoformat(),
                "samples": len(series), "latest_per": series[-1][1],
            }

    if "pe_multiples" in setting:
        band = setting["pe_multiples"]
        result["method"] = "configured_pe_multiples_x_ttm_eps"
    else:
        if per_history is None:
            return blocked(f"FinMind {PER_DATASET} unavailable")
        if len(series) < MIN_PER_SAMPLES:
            return blocked(f"Only {len(series)} PER samples in the {WINDOW_YEARS}-year window; "
                           f"need {MIN_PER_SAMPLES}")
        values = np.array([v for _, v in series])
        band = tuple(round(float(np.percentile(values, q)), 4) for q in setting["percentiles"])
        result["method"] = "historical_per_percentile_x_ttm_eps"
        result["percentiles"] = list(setting["percentiles"])

    keys = ("low", "mid", "high")
    prices = {k: round(m * float(eps), 2) for k, m in zip(keys, band)}
    result.update(
        status="available",
        pe_band={k: float(m) for k, m in zip(keys, band)},
        review_prices_twd=prices,
        zone=("below_low" if close < prices["low"] else
              "above_high" if close > prices["high"] else "fair"),
    )
    return result



def compact_zone(zone):
    """Numbers-only zone for the 20,000-byte public snapshot.

    Text that is constant (assumptions, disclaimer) or rebuilt from the symbol and
    window start (FinMind query URL) stays in report.json and the Artifact only.
    """
    compact = {k: v for k, v in zone.items() if k not in ("assumptions", "disclaimer", "cutoff")}
    for key, drop in (("per_history", ("source", "dataset")), ("price", ("source",)),
                      ("eps", ("derivation", "period_start"))):
        if isinstance(compact.get(key), dict):
            compact[key] = {k: v for k, v in compact[key].items() if k not in drop}
    return compact


ZONE_LABELS = {"below_low": "低於偏低價", "fair": "合理區間", "above_high": "高於偏高價"}


def _money(value):
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "—"


def _eps_label(zone):
    eps = zone.get("eps") or {}
    quarters = eps.get("quarters") or []
    if eps.get("ttm_basic_eps") is None:
        return "—"
    period = f"{quarters[0]}–{quarters[-1]} " if quarters else ""
    return f"{period}EPS {eps['ttm_basic_eps']:.2f}"


def _per_label(zone):
    history = zone.get("per_history")
    if not history:
        return "—"
    return f"{history['samples']} 筆（{history['first_date']}～{history['last_date']}）"


def _zone_label(zone):
    if zone.get("status") == "available":
        return ZONE_LABELS[zone["zone"]]
    return f"not_evaluated：{zone.get('reason')}"


def _method_label(zone):
    band = zone.get("pe_band") or {}
    if zone.get("method") == "configured_pe_multiples_x_ttm_eps":
        return ("設定的固定本益比 " + "／".join(f"{band[k]:g}x" for k in ("low", "mid", "high"))
                + " × 近四季基本 EPS（config/watchlist.yaml）")
    p = zone.get("percentiles") or []
    return (f"近 {WINDOW_YEARS} 年每日本益比 " + "／".join(f"P{q}" for q in p)
            + f"（FinMind {PER_DATASET}）× 近四季基本 EPS")


def zone_summary_row(symbol, zone):
    """One daily-summary table row: close, review prices, zone, EPS and P/E sample."""
    price = zone.get("price") or {}
    close = f"{_money(price.get('close'))}（{price.get('session')}）" if price else "—"
    prices = zone.get("review_prices_twd") or {}
    cells = [symbol, close, *(_money(prices.get(k)) for k in ("low", "mid", "high")),
             _zone_label(zone), _eps_label(zone), _per_label(zone)]
    return "| " + " | ".join(cells) + " |"


def render_valuation_zone(zone):
    """Markdown section for the company report."""
    lines = ["", "## 估值檢視區（歷史本益比）", "",
             f"**{DISCLAIMER}。** 價位 = 本益比 × 近四季 EPS；價格進出區間只代表值得重新檢視，"
             "不是合理價、目標價或進出場價格。", ""]
    if zone.get("status") != "available":
        return lines + [f"**not_evaluated**：{zone.get('reason')}"]
    price, eps, band = zone["price"], zone["eps"], zone["pe_band"]
    lines += [f"- 方法：{_method_label(zone)}",
              f"- 收盤：{_money(price['close'])} TWD（{price['session']}，{price.get('source')}）",
              f"- 近四季 EPS：{_eps_label(zone)}（截至 {eps.get('period_end')}）"]
    history = zone.get("per_history")
    if history:
        lines.append(f"- 本益比樣本：{_per_label(zone)}；窗口起點 {history['window_start']}；"
                     f"最新 {history['latest_per']:.2f}x；來源 {history['source']}")
    lines += ["- 本益比區間：" + "／".join(f"{band[k]:.2f}x" for k in ("low", "mid", "high")),
              "", "| 偏低價 | 合理價 | 偏高價 | 目前區間 |", "| ---: | ---: | ---: | --- |",
              "| " + " | ".join(_money(zone["review_prices_twd"][k]) for k in ("low", "mid", "high"))
              + f" | {ZONE_LABELS[zone['zone']]} |"]
    return lines
