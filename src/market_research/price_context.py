"""Research-only technical price observations, NOT executable trading levels.

Uses completed analysis OHLCV from the shared DailyBars data contract.
Prior support/resistance excludes the signal-day candle; ATR includes it.
"""
import math
import numpy as np
from .market_data import PRICE_BASIS

VERSION = "1.0.0"
LOOKBACKS = (20, 60)
ATR_PERIOD = 14
UNEXPLAINED_GAP_THRESHOLD_PCT = 20.0


def _blocked(why, metadata):
    return {
        "status": "not_evaluated", "method_version": VERSION,
        "why": why, "levels": None, "atr": None,
        "reference_state": None, "volume_ratio_20": None,
        "entry_zone": None, "stop_loss": None, "target_price": None,
        "executable": False, "input_sha256": metadata.get("input_sha256"),
        "price_basis": metadata.get("price_basis"),
        "last_session": metadata.get("last_date"),
    }


def analyze_price_context(daily, market):
    """Return source-linked price references or an explicit non-actionable block."""
    m = daily.metadata
    if market not in PRICE_BASIS or m.get("price_basis") != PRICE_BASIS.get(market):
        return _blocked("Unverified analytical OHLC price basis", m)
    if (not m.get("input_sha256") or m.get("last_date") is None or
            m.get("last_date") != m.get("expected_completed_session")):
        return _blocked("Latest completed market session and checksum not verified", m)
    if any(w.get("reason") == "stale_history_allowed_for_research" for w in daily.warnings):
        return _blocked("Source market prices are stale", m)
    frame = daily.frame
    if len(frame) < 61:
        return _blocked("At least 61 completed trading sessions required", m)
    if str(frame.index[-1]) != m["last_date"]:
        return _blocked("Market session metadata is inconsistent with price history", m)
    try:
        o = frame["open"].to_numpy(dtype=float)
        h = frame["high"].to_numpy(dtype=float)
        l = frame["low"].to_numpy(dtype=float)
        c = frame["close"].to_numpy(dtype=float)
        v = frame["volume"].to_numpy(dtype=float)
    except (KeyError, TypeError, ValueError):
        return _blocked("Incomplete numeric OHLCV series", m)
    if not all(np.isfinite(a).all() for a in (o, h, l, c, v)):
        return _blocked("Nonfinite OHLCV observations", m)
    if (np.minimum.reduce((o, h, l, c)) <= 0).any() or (v < 0).any():
        return _blocked("Invalid negative volume or nonpositive price", m)
    if ((h < np.maximum.reduce((o, c, l))) |
            (l > np.minimum.reduce((o, c, h)))).any():
        return _blocked("Invalid OHLC candle ranges", m)

    # Compare open to the previous close. Large unexplained moves might be
    # splits, ex-rights events, uncorrected corporate actions or true gaps.
    # Never assert the cause from OHLC alone; suppress price observations.
    gaps = np.abs(o[-60:] / c[-61:-1] - 1) * 100
    if float(np.max(gaps)) >= UNEXPLAINED_GAP_THRESHOLD_PCT:
        return _blocked("At least one >=20% opening gap requires corporate-action/event review", m)

    previous = c[-15:-1]
    tr = np.maximum.reduce((
        h[-14:] - l[-14:],
        np.abs(h[-14:] - previous),
        np.abs(l[-14:] - previous),
    ))
    atr = float(np.mean(tr))
    close = float(c[-1])
    if not math.isfinite(atr) or atr <= 0:
        return _blocked("ATR is zero or not calculable; volatility zone unavailable", m)
    supports = {days: float(np.min(l[-(days + 1):-1])) for days in LOOKBACKS}
    resistances = {days: float(np.max(h[-(days + 1):-1])) for days in LOOKBACKS}
    prior_volume = float(np.mean(v[-21:-1]))
    volume_ratio = float(v[-1] / prior_volume) if prior_volume > 0 else None

    def rounded(value):
        return round(float(value), 4)

    def band(mid):
        return {
            "lower": rounded(max(0, mid - 0.5 * atr)),
            "upper": rounded(mid + 0.5 * atr),
            "construction": "prior_20_session_extreme_plus_minus_half_ATR14",
        }
    support, resistance = supports[20], resistances[20]
    state = ("above_prior_20d_range" if close > resistance else
             "below_prior_20d_range" if close < support else "inside_prior_20d_range")
    return {
        "status": "observation_only",
        "method_version": VERSION,
        "why": "Price references from observed completed daily OHLCV; no forecast or order levels",
        "last_session": m["last_date"],
        "input_sha256": m["input_sha256"],
        "source": m.get("source"),
        "price_basis": m["price_basis"],
        "execution_price_basis": m.get("execution_price_basis"),
        "currency": "TWD" if market == "tw" else "USD",
        "latest_analytical_close": rounded(close),
        "atr": {
            "method": "simple_mean_of_last_14_true_ranges_including_latest_completed_candle",
            "absolute": rounded(atr), "percentage_of_close": round(100 * atr / close, 3),
            "period": ATR_PERIOD,
        },
        "levels": {
            "support_20d": rounded(support),
            "resistance_20d": rounded(resistance),
            "support_60d": rounded(supports[60]),
            "resistance_60d": rounded(resistances[60]),
            "support_observation_band": band(support),
            "resistance_observation_band": band(resistance),
            "structural_invalidation_reference": rounded(max(0, support - atr)),
        },
        "reference_state": state,
        "volume_ratio_20": round(volume_ratio, 3) if volume_ratio is not None else None,
        "entry_zone": None, "stop_loss": None, "target_price": None,
        "executable": False,
        "warnings": [
            "All bands, including invalidation reference, are research annotations, not actionable entry/stop/target orders.",
            "TWSE unadjusted history requires corporate-action review before execution; Yahoo dividend-adjusted OHLC is not an executable US quote.",
            "Trading costs, liquidity, split/dividend reconciliation and validated strategy efficacy are not assessed.",
        ],
    }


def render_price_context(context):
    lines = ["", "## Technical price context (research only)", ""]
    if context["status"] != "observation_only":
        lines.append("**Not evaluated.** " + context["why"])
        return lines
    levels = context["levels"]
    atr = context["atr"]
    lines += [
        f"Completed session: {context['last_session']}; basis: {context['price_basis']}",
        f"Analytical close: {context['latest_analytical_close']:,.4f} {context['currency']}",
        f"ATR(14): {atr['absolute']:,.4f} ({atr['percentage_of_close']:.3f}% of close)",
        f"Position relative to preceding 20 trading sessions: {context['reference_state']}",
        "",
        "| Historical observation | Analytical price reference |",
        "| --- | ---: |",
        f"| Prior 20-session low / high | {levels['support_20d']:,.4f} / {levels['resistance_20d']:,.4f} |",
        f"| Prior 60-session low / high | {levels['support_60d']:,.4f} / {levels['resistance_60d']:,.4f} |",
        f"| Support observation band (20d low ± 0.5 ATR) | {levels['support_observation_band']['lower']:,.4f}–{levels['support_observation_band']['upper']:,.4f} |",
        f"| Resistance observation band (20d high ± 0.5 ATR) | {levels['resistance_observation_band']['lower']:,.4f}–{levels['resistance_observation_band']['upper']:,.4f} |",
        f"| Structural invalidation reference (20d low − 1 ATR) | {levels['structural_invalidation_reference']:,.4f} |",
        "",
        "**These are NOT buy prices, stop-loss orders, fair values or price targets.**",
        "No action can be inferred from proximity to a band without validated strategies, costs, price basis and risk rules.",
    ]
    return lines
