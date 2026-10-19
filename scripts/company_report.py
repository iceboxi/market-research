"""Source-grounded, on-demand company snapshot. Never generates price targets."""
import argparse
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import re

import yaml

from market_research.fundamentals import sec_fundamentals, twse_fundamentals
from market_research.market_data import load_daily_bars
from market_research.provider import RoutedDailyProvider
from market_research.strategies import get_strategy
from market_research.valuation import evaluate_valuation
from market_research.company_analysis import compare_financials, research_status, render_financial_research
from market_research.price_context import analyze_price_context, render_price_context
from market_research.event_risk import tw_material_events, evaluate_events, render_events
from market_research.source_evidence import (instrument_eligibility, build_source_evidence,
                                             validate_valuation_inputs, render_evidence)

ROOT = Path(__file__).resolve().parents[1]

def classify(symbol):
    symbol = symbol.strip().upper()
    if re.fullmatch(r"[0-9]{4,6}\.TW", symbol):
        return symbol, "tw"
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
        return symbol, "us"
    raise ValueError("Provide TWSE-listed 2330.TW or US ticker such as AAPL")

def run(symbol, out=Path("company_output"), now=None, provider=None,
        facts_get=None, sec_user_agent=None, config_dir=ROOT/"config"):
    symbol, market = classify(symbol)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("now requires timezone")
    if market == "tw":
        kwargs = {"get":facts_get} if facts_get else {}
        issuer = twse_fundamentals(symbol, **kwargs)
    else:
        kwargs = {"user_agent":sec_user_agent, "evaluated_at":now}
        if facts_get:
            kwargs["get"] = facts_get
        # SEC filingDate has day precision only. At evaluation cutoff, do not
        # include records filed on the *current New York calendar day*:
        # their actual public availability within the day is unverified.
        sec_day = now.astimezone(ZoneInfo("America/New_York")).date()
        annual_cutoff = sec_day - timedelta(days=1)
        issuer = sec_fundamentals(symbol, annual_cutoff, **kwargs)
    market_cfg = yaml.safe_load((Path(config_dir)/"markets.yaml").read_text())["markets"]
    strategy_cfg = yaml.safe_load((Path(config_dir)/"strategies.yaml").read_text())["strategies"]
    technical = {"status":"unavailable","observations":[],"errors":[],"price_context":None}
    try:
        daily = load_daily_bars(provider or RoutedDailyProvider(),market,symbol,"6mo",
                                now,market_cfg[market]["timezone"],strict_freshness=False)
        technical = {"status":"available",
            "last_session":daily.metadata["last_date"],
            "analytical_close":round(float(daily.frame.close.iloc[-1]),6),
            "currency":"TWD" if market=="tw" else "USD",
            "price_basis":daily.metadata["price_basis"],
            "source":daily.metadata["source"],
            "input_sha256":daily.metadata["input_sha256"],
            "warnings":list(daily.warnings),"observations":[],"errors":[],
            "price_context":analyze_price_context(daily,market)}
        for entry in strategy_cfg:
            if not entry["id"].startswith("sakata_"):
                continue
            strat = get_strategy(entry["id"])
            try:
                r = strat.scan(market,symbol,daily.frame,entry.get("params",{}))
                technical["observations"].append({
                    "strategy_id":r.strategy_id,"strategy_version":r.strategy_version,
                    "matched":bool(r.matched),"active":bool(entry["enabled"]),
                    "as_of_session":r.trade_date,
                    "observation_state":r.metrics.get("observation")})
            except Exception as exc:
                technical["errors"].append({"strategy_id":entry["id"],"type":type(exc).__name__})
        if technical["errors"]:
            technical["status"]="partial"
    except Exception as exc:
        technical["errors"].append({"type":type(exc).__name__,"detail":str(exc)})
    if market == "tw":
        from market_research.fundamentals import json_get
        event_feed = tw_material_events(symbol, now, facts_get or json_get)
    else:
        from market_research.fundamentals import SEC_SUBMISSIONS
        from market_research.event_risk import unknown
        event_feed = issuer.get("event_feed") or unknown(
            SEC_SUBMISSIONS.format(cik=int(issuer["cik"])), "SEC filing feed not retrieved"
        )
    event_risk = evaluate_events(event_feed, now)
    eligibility = instrument_eligibility(issuer)
    evidence = build_source_evidence(issuer, now)
    source_gate = validate_valuation_inputs(issuer, now)
    valuation = evaluate_valuation(issuer, annual_cutoff if market == "us" else now.date())
    if valuation["status"] == "illustrative_only" and (
        eligibility["status"] != "candidate_for_nonfinancial_research" or
        source_gate["status"] != "date_only_prior_filing"
    ):
        valuation = {
            "status": "not_evaluated", "method": None, "fair_value_scenarios": None,
            "entry_zone": None, "stop_loss": None, "target_price": None,
            "why": "Research eligibility or source provenance gate incomplete",
        }
    financial = compare_financials(issuer, annual_cutoff if market == "us" else now.date())
    readiness = research_status(financial, valuation, technical)
    readiness["instrument_status"] = eligibility["status"]
    readiness["source_evidence_status"] = evidence["status"]
    readiness["valuation_source_gate"] = source_gate["status"]
    readiness["trade_plan_status"] = "not_evaluated"
    readiness["source_ready_for_recommendation"] = False
    result={"schema_version":4,"report_type":"preliminary_company_research",
        "symbol":symbol,"market":market,"generated_utc":now.astimezone(timezone.utc).isoformat(),
        "issuer":issuer,"technical":technical,
        "instrument_eligibility":eligibility,
        "source_evidence":evidence,
        "financial_comparison":financial,"research_readiness":readiness,
        "official_events":event_feed, "event_risk":event_risk,
        "valuation":valuation,
        "decision":"no_buy_or_sell_recommendation",
        "complete":bool(issuer.get("company_name")) and technical["status"]=="available",
        "limitations":["TW latest monthly revenue is not audited annual profit or TTM revenue",
           "US SEC annual XBRL tag conventions vary by issuer",
           "Analytical closes and pattern matches are not executable trading prices",
           "No company competitive-analysis, validated intrinsic valuation or independent forward strategy evidence"]}
    out=Path(out)
    out.mkdir(parents=True,exist_ok=True)
    (out/"report.json").write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n")
    lines=[f"# {issuer.get('company_name') or symbol} — {symbol}","",
       "Preliminary source-grounded research, **not an investment recommendation**.","",
       f"Generated (UTC): {result['generated_utc']}",
       f"Company source: {issuer['profile']['source']}","","## Reported fundamentals","",
       "| Metric | Value and original unit | Period | Source |",
       "| --- | ---: | --- | --- |"]
    for fact in issuer["facts"]:
        period=fact.get("period_end") or fact.get("period") or "not available"
        lines.append(f"| {fact['metric']} | {fact['value']:,.2f} {fact['unit']} | {period} | {fact['source']} |")
    if not issuer["facts"]:
        lines.append("| Unavailable | — | — | — |")
    lines += ["","## Technical patterns","",f"Data status: {technical['status']}"]
    if technical["status"] in ("available","partial"):
        lines += [f"Latest complete date: {technical['last_session']}",
                  f"Analytical close: {technical['analytical_close']} {technical['currency']}",
                  "","| Pattern | Observed | Status |","| --- | --- | --- |"]
        for row in technical["observations"]:
            lines.append(f"| {row['strategy_id']} | {'yes' if row['matched'] else 'no'} | {'active' if row['active'] else 'research-only'} |")
    if technical["errors"]:
        lines.append("Some technical checks failed; refer to report.json.")
    if technical.get("price_context"):
        lines.extend(render_price_context(technical["price_context"]))
    lines.extend(render_financial_research(financial, readiness))
    lines.extend(render_events(event_feed, event_risk))
    lines.extend(render_evidence(eligibility, evidence, source_gate))
    lines += ["","## Valuation and entry/exit plan",""]
    v = result["valuation"]
    if v["status"] == "illustrative_only":
        lines += ["**Illustrative historical P/FCF sensitivity only — NOT a buy/target price.**",
                  "Historical 3-year median FCF: {:,.0f} USD".format(v["normalized_annual_fcf_usd"]),
                  "Latest diluted annual average shares: {:,.0f}".format(v["denominator"]["value"]),
                  "", "| Scenario | Assumed multiple | Illustrative USD/share |",
                  "| --- | ---: | ---: |"]
        for name, row in v["fair_value_scenarios"].items():
            lines.append(f"| {name} | {row['fcf_multiple']}x | {row['indicative_usd_per_share']:,.2f} |")
        lines += ["", "No forward FCF or net debt reconciliation. No buy, stop-loss or target."]
    else:
        lines.append("**Not evaluated.** " + v["why"])
    lines += ["","## Limitations",""]
    lines.extend("- "+w for w in issuer["warnings"]+result["limitations"])
    (out/"report.md").write_text("\n".join(lines)+"\n",encoding="utf-8")
    return result

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--symbol",required=True)
    p.add_argument("--out",type=Path,default=Path("company_output"))
    a=p.parse_args()
    result=run(a.symbol,a.out)
    print((a.out/"report.md").read_text(encoding="utf-8"))
    if not result["complete"]:
        raise SystemExit("Incomplete report, see JSON warnings")
if __name__=="__main__":
    main()
