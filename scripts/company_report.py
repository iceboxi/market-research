"""Source-grounded, on-demand company snapshot. Never generates price targets."""
import argparse
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import re

import httpx
import yaml

from market_research.fundamentals import TW_PROFILE, sec_fundamentals, twse_fundamentals, tw_report_date
from market_research.market_data import load_daily_bars
from market_research.provider import RoutedDailyProvider
from market_research.strategies import get_strategy
from market_research.company_analysis import (
    build_financial_research_summary, render_financial_research, render_tw_full_research_sections,
)
from market_research.research_engine import RESEARCH_CONTRACT_VERSION, compute_research
from market_research.research_snapshot import fingerprint
from market_research.price_context import analyze_price_context, render_price_context
from market_research.event_risk import tw_material_events, render_events
from market_research.source_evidence import render_evidence

ROOT = Path(__file__).resolve().parents[1]


def _current_tw(symbol, out, provider, facts_get, config_dir, started, clock, financial_get=None):
    """Acquire one in-memory input batch, then evaluate it at a fixed cutoff."""
    from market_research.fundamentals import json_get
    actual_get = facts_get or json_get
    actual_fin_get = financial_get or (json_get if facts_get is None else None)
    captured = {}
    def get(url):
        if url not in captured:
            try:
                captured[url] = (actual_get(url), None)
            except Exception as error:
                captured[url] = (None, error)
        value, error = captured[url]
        if error is not None:
            raise error
        return value

    def fin_get(url):
        if url not in captured:
            try:
                captured[url] = (actual_fin_get(url), None)
            except Exception as error:
                captured[url] = (None, error)
        value, error = captured[url]
        if error is not None:
            raise error
        return value

    use_fin_get = fin_get if actual_fin_get is not None else None
    actual = provider or RoutedDailyProvider()
    selected = actual.provider_for(symbol) if hasattr(actual, "provider_for") else actual
    class Prices:
        source = getattr(selected, "source", "unknown")
        records = getattr(selected, "records", {})
        fetched = False
        value = error = None
        def load(self, requested, period):
            if requested != symbol or period != "6mo":
                raise ValueError("Input batch identity changed")
            if not self.fetched:
                self.fetched = True
                try:
                    self.value = actual.load(requested, period)
                except Exception as error:
                    self.error = error
            if self.error is not None:
                raise self.error
            return self.value
    prices = Prices()
    try:
        twse_fundamentals(
            symbol, get=get, financial_get=use_fin_get,
            asof=started.astimezone(ZoneInfo("Asia/Taipei")).date(),
        )
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError):
        pass  # Replayed below through the existing partial-report boundary.
    try:
        prices.load(symbol, "6mo")
    except Exception:
        pass
    tw_material_events(symbol, started, get)
    cutoff = clock()
    if cutoff.tzinfo is None or cutoff < started:
        raise ValueError("Current evaluation clock must advance with timezone")
    return run(symbol, out, now=cutoff, provider=prices, facts_get=get,
               config_dir=config_dir, clock=lambda: started, financial_get=use_fin_get)

def classify(symbol):
    symbol = symbol.strip().upper()
    if re.fullmatch(r"[0-9]{4,6}\.TW", symbol):
        return symbol, "tw"
    if re.fullmatch(r"[A-Z][A-Z0-9.-]{0,9}", symbol):
        return symbol, "us"
    raise ValueError("Provide TWSE-listed 2330.TW or US ticker such as AAPL")

def build_run_receipt(result):
    issuer, technical = result["issuer"], result["technical"]
    feed = result["official_events"]
    identified = bool(issuer.get("company_name"))
    facts = issuer.get("facts", [])
    stale = any(w.get("reason") == "stale_history_allowed_for_research"
                for w in technical.get("warnings", []))
    return {
        "schema_version": 1, "symbol": result["symbol"], "market": result["market"],
        "evaluation_cutoff_utc": result["generated_utc"],
        "started_utc": result["started_utc"],
        "execution": {"status": "completed" if result["complete"] else "partial",
                      "legacy_complete": result["complete"]},
        "source_coverage": {
            "issuer_profile": {
                "status": "available" if identified else "unavailable",
                "source": issuer["profile"]["source"],
                "date": issuer["profile"].get("reported_at"),
                "error_type": (issuer.get("source_error") or {}).get("type"),
                "reason": None if identified else "公司身分未確認；請檢查 TWSE 公司資料來源後重跑。",
            },
            "reported_fundamentals": {
                "status": "available" if facts else "unavailable" if identified else "not_attempted",
                "periods": sorted({str(f.get("period_end") or f.get("period"))
                                   for f in facts if f.get("period_end") or f.get("period")}),
                "warnings": issuer.get("warnings", []),
                "reason": None if facts else "本次沒有可用的基本資料數值；請核對來源與資料期別。",
            },
            "technical": {
                "status": technical["status"], "source": technical.get("source"),
                "session": technical.get("last_session"),
                "freshness": "stale" if stale else "unknown" if technical["status"] == "unavailable" else "current",
                "warnings": technical.get("warnings", []), "errors": technical["errors"],
                "reason": "行情資料過期；請核對最新完成交易日與來源更新狀態。" if stale else
                          "部分行情或技術檢查失敗；請核對來源與資料日期後重跑。"
                          if technical["status"] != "available" else None,
            },
            "official_events": {
                "status": feed["status"], "source": feed.get("source"),
                "snapshot_date": feed.get("snapshot_date"), "coverage": feed["coverage"],
                "reason": feed.get("reason"),
            },
        },
        "research_readiness": result["research_readiness"]["components"],
        "persistence": {"status": "not_attempted"},
        "delivery": {"status": "not_attempted"},
        "artifacts": {"report_json": "report.json", "report_markdown": "report.md",
                      "run_receipt": "run_receipt.json"},
    }


def render_run_summary(receipt):
    def cell(value):
        return str(value if value is not None else "—").replace("|", "/").replace("\n", " ")
    sources = receipt["source_coverage"]
    rows = (
        ("公司身分", "issuer_profile", sources["issuer_profile"]["date"]),
        ("基本資料數值", "reported_fundamentals", ", ".join(sources["reported_fundamentals"]["periods"]) or None),
        ("行情與技術", "technical", sources["technical"]["session"]),
        ("官方事件", "official_events", sources["official_events"]["snapshot_date"] or sources["official_events"]["coverage"]),
    )
    lines = ["", "## 執行摘要", "",
             "本次資料流程：**" + receipt["execution"]["status"] + "**",
             "評估時間 (UTC)：" + receipt["evaluation_cutoff_utc"], "",
             "| 資料項目 | 狀態 | 日期／範圍 | 原因與下一步 |",
             "| --- | --- | --- | --- |"]
    for label, key, period in rows:
        source = sources[key]
        lines.append(f"| {label} | {source['status']} | {cell(period)} | {cell(source['reason'])} |")
    lines += ["", "| 研究項目 | 準備度 | 原因 |", "| --- | --- | --- |"]
    for label, key in (("年度財報", "financial"), ("估值", "valuation"), ("交易計畫", "trade_plan")):
        state = receipt["research_readiness"][key]
        lines.append(f"| {label} | {state['status']} | {cell(state['reason'])} |")
    lines += ["", "長期研究保存：not_attempted；通知投遞：not_attempted。",
              "本次結果保存在報告檔與執行紀錄；後續比較與通知需另行完成。"]
    return lines


def run(symbol, out=Path("company_output"), now=None, provider=None,
        facts_get=None, sec_user_agent=None, config_dir=ROOT/"config", clock=None,
        financial_get=None):
    symbol, market = classify(symbol)
    clock = clock or (lambda: datetime.now(timezone.utc))
    started = clock()
    if started.tzinfo is None:
        raise ValueError("Execution start requires timezone")
    if now is None and market == "tw":
        return _current_tw(symbol, out, provider, facts_get, config_dir, started, clock,
                           financial_get=financial_get)
    now = now or started
    if now.tzinfo is None:
        raise ValueError("now requires timezone")
    if market == "tw":
        kwargs = {"get":facts_get} if facts_get else {}
        if financial_get is not None:
            kwargs["financial_get"] = financial_get
        kwargs["asof"] = now.astimezone(ZoneInfo("Asia/Taipei")).date()
        try:
            issuer = twse_fundamentals(symbol, **kwargs)
            profile_date = tw_report_date(issuer["profile"].get("reported_at"))
            if profile_date and profile_date > now.astimezone(ZoneInfo("Asia/Taipei")).date():
                raise ValueError("TWSE profile export date is after evaluation cutoff")
        except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError) as exc:
            # The requested ticker is known; issuer identity was not verified.
            issuer = {
                "symbol": symbol, "market": market, "company_name": None,
                "profile": {"source": TW_PROFILE}, "facts": [],
                "source_error": {"type": type(exc).__name__},
                "warnings": ["TWSE company profile unavailable: " + type(exc).__name__],
            }
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
    model_identity = fingerprint({
        "research_contract": RESEARCH_CONTRACT_VERSION, "report_schema": 4,
        "market_config": market_cfg[market],
        "strategies": [{"id": entry["id"], "version": get_strategy(entry["id"]).version,
                        "enabled": entry["enabled"], "params": entry.get("params", {})}
                       for entry in strategy_cfg if entry["id"].startswith("sakata_")],
    })
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
        from market_research.event_risk import build_tw_calendar_schedule, build_tw_disclosures_and_news
        event_feed = tw_material_events(symbol, now, facts_get or json_get)
        raw_ev_cal = issuer.pop("event_calendar_raw", None)
        if raw_ev_cal is not None or "financial_history" in issuer:
            raw_ev_cal = raw_ev_cal or {}
            div_source = raw_ev_cal.get("dividends")
            if div_source is None:
                div_source = (issuer.get("financial_history") or {}).get("dividend_schedule")
            issuer["disclosure_and_news"] = build_tw_disclosures_and_news(
                symbol, now,
                material_feed=event_feed,
                shareholder_announce=raw_ev_cal.get("shareholder_announce"),
                dividend_rows=div_source,
                finmind_news=raw_ev_cal.get("finmind_news"),
                source_errors=raw_ev_cal.get("source_errors"),
            )
            issuer["calendar_schedule"] = build_tw_calendar_schedule(
                symbol, now,
                shareholder_announce=raw_ev_cal.get("shareholder_announce"),
                shareholder_meeting=raw_ev_cal.get("shareholder_meeting"),
                dividend_rows=div_source,
                material_feed=event_feed,
                source_errors=raw_ev_cal.get("source_errors"),
            )
    else:
        from market_research.fundamentals import SEC_SUBMISSIONS
        from market_research.event_risk import unknown
        event_feed = issuer.get("event_feed") or unknown(
            SEC_SUBMISSIONS.format(cik=int(issuer["cik"])), "SEC filing feed not retrieved"
        )
    research = compute_research(
        issuer=issuer, technical=technical, event_feed=event_feed,
        symbol=symbol, market=market, now=now,
    )
    event_risk = research["event_risk"]
    eligibility = research["instrument_eligibility"]
    evidence = research["source_evidence"]
    source_gate = research["valuation_source_gate"]
    valuation = research["valuation"]
    financial = research["financial_comparison"]
    readiness = research["research_readiness"]
    result={"schema_version":4,"report_type":"preliminary_company_research",
        "symbol":symbol,"market":market,"generated_utc":now.astimezone(timezone.utc).isoformat(),
        "started_utc":started.astimezone(timezone.utc).isoformat(),
        "model_identity":model_identity,
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
    fin_research = build_financial_research_summary(result)
    if fin_research is not None:
        result["financial_research"] = fin_research
    result["run_receipt"] = build_run_receipt(result)
    out=Path(out)
    out.mkdir(parents=True,exist_ok=True)
    lines=[f"# {issuer.get('company_name') or symbol} — {symbol}","",
       "Preliminary source-grounded research, **not an investment recommendation**."] + render_run_summary(result["run_receipt"]) + ["",
       f"Generated (UTC): {result['generated_utc']}",
       f"Company source: {issuer['profile']['source']}","","## Reported fundamentals","",
       "| Metric | Value and original unit | Period | Source |",
       "| --- | ---: | --- | --- |"]
    shares = issuer.get("issued_shares")
    if shares is not None and market == "tw":
        lines += ["", "## 已發行普通股數（官方現況快照）", "",
                  f"已發行普通股數：{shares['value']:,} 股；出表日期：{shares['reported_at'] or '未知'}。",
                  f"資料來源：[TWSE 上市公司基本資料]({shares['source']})（政府資料開放授權條款第 1.0 版）。",
                  "此為本次取得的已發行股數快照，不是流通股數、基本／稀釋加權平均股數或歷史股數；"
                  "出表日並非公開時間，未經公司行動與財報分母核對，不可用於每股估值。"]
    elif market == "tw":
        lines += ["", "## 已發行普通股數", "",
                  "本次未取得可用的官方已發行股數快照；不補零、不推估估值分母。"]
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
    if result.get("financial_research"):
        lines.extend(render_tw_full_research_sections(result["financial_research"]))
    lines.extend(render_financial_research(financial, readiness))
    lines.extend(render_events(event_feed, event_risk))
    lines.extend(render_evidence(eligibility, evidence, source_gate))
    lines += ["","## Valuation and entry/exit plan",""]
    v = result["valuation"]
    if v["status"] == "illustrative_only" and v.get("currency") == "TWD":
        lines += ["**Illustrative EV-bridged P/FCF and TTM P/E sensitivity only — NOT a buy/target price.**",
                  "Historical 3-year median FCF: {:,.0f} TWD".format(v["normalized_annual_fcf_twd"]),
                  "Latest verified balance-sheet net cash: {:,.0f} TWD".format(v["net_cash_twd"]),
                  "Latest ordinary shares (from par 10 capital stock): {:,.0f}".format(v["denominator"]["value"]),
                  "", "| Scenario | Assumed FCF multiple | Illustrative 3yr-Median FCF TWD/share | Illustrative TTM FCF TWD/share |",
                  "| --- | ---: | ---: | ---: |"]
        for name, row in v["fair_value_scenarios"].items():
            ttm_val = f"{row['indicative_ttm_fcf_twd_per_share']:,.2f}" if row.get("indicative_ttm_fcf_twd_per_share") is not None else "—"
            lines.append(f"| {name} | {row['fcf_multiple']}x | {row['indicative_twd_per_share']:,.2f} | {ttm_val} |")
        lines += ["", "No executable entry, stop-loss or target price. No buy or sell recommendation."]
    elif v["status"] == "illustrative_only":
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
    (out/"report.json").write_text(json.dumps(result,indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    (out/"run_receipt.json").write_text(json.dumps(result["run_receipt"],indent=2,ensure_ascii=False,allow_nan=False)+"\n",encoding="utf-8")
    if symbol == "2330.TW":
        from market_research.research_site import write_research_site
        write_research_site(out, latest_report=result)
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
