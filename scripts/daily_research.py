"""Fixed TW research plus verified candidates, sharing one computation per ticker."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile
import time

from scripts.company_report import run
from scripts.research_publication import execute as publish_report
from scripts.scan_company_research import execute as candidate_research
from market_research.price_watch import load_price_watch, render_price_watch_summary
from market_research.research_site import write_research_site
from market_research.thesis_check import DISCLAIMER as THESIS_DISCLAIMER, thesis_summary_row
from market_research.valuation_zone import zone_summary_row

DEFAULT_TW_PILOT_SYMBOLS = ["2330.TW", "2317.TW", "2454.TW", "0050.TW", "00631L.TW"]
DEFAULT_TW_BENCHMARKS = ["TAIEX"]

FULL_MARKET_PATTERNS = (
    "t187ap03_L",
    "t187ap05_L",
    "t187ap06_L_ci",
    "t187ap07_L_ci",
    "t187ap17_L",
    "t187ap45_L",
    "BWIBBU_ALL",
    "TaiwanStockPriceTick",
    "TaiwanStockInfo",
    "t05st01",
)


def get_pilot_symbols(market="tw", config_path=None):
    path = Path(config_path) if config_path else Path(__file__).resolve().parents[1] / "config" / "markets.yaml"
    if path.exists():
        import yaml
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data.get("markets", {}).get(market, {}).get("symbols", DEFAULT_TW_PILOT_SYMBOLS)
        except Exception:
            pass
    return DEFAULT_TW_PILOT_SYMBOLS


def get_benchmarks(market="tw", config_path=None):
    """Index codes priced alongside the watchlist (markets.yaml `benchmarks`)."""
    path = Path(config_path) if config_path else Path(__file__).resolve().parents[1] / "config" / "markets.yaml"
    if path.exists():
        import yaml
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
            return data.get("markets", {}).get(market, {}).get("benchmarks", DEFAULT_TW_BENCHMARKS)
        except Exception:
            pass
    return DEFAULT_TW_BENCHMARKS


def is_etf(symbol):
    """TWSE ETF/ETN codes start with 00; they have no issuer research."""
    return symbol.split(".")[0].startswith("00")


def is_full_market_endpoint(url):
    return any(pattern in url for pattern in FULL_MARKET_PATTERNS)


def execute(scan_dir, out, *, market="tw", mode="validation", max_candidates=3,
            research_fn=run, publication_fn=publish_report, sec_user_agent=None, now=None,
            pilot=False, symbols=None, price_watch_fn=load_price_watch, benchmarks=None):
    if market not in ("tw", "both"):
        raise ValueError("Daily fixed research requires TW coverage")
    if not 1 <= max_candidates <= 20 or now is not None and now.tzinfo is None:
        raise ValueError("Use 1..20 candidates and a timezone-aware cutoff")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)

    if symbols is not None:
        target_symbols = list(symbols)
    elif pilot:
        target_symbols = get_pilot_symbols(market)
    else:
        target_symbols = ["2330.TW"]

    result = {
        "schema_version": 1,
        "market": market,
        "status": "partial",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "fixed_research": {
            "symbol": "2330.TW",
            "status": "failed",
            "scope": "independent_current_research_not_a_scan_candidate",
            "publication": {"status": "not_attempted"},
        },
        "pilot_coverage": None,
        "candidates": None,
    }
    fixed = result["fixed_research"]

    with tempfile.TemporaryDirectory(prefix="daily-research-inputs-") as temp:
        temp = Path(temp)
        reports, errors = {}, {}

        shared_cache = {}
        shared_stats = {"total_calls": 0, "cache_hits": 0, "shared_endpoints": set()}

        def caching_get(url):
            shared_stats["total_calls"] += 1
            if is_full_market_endpoint(url) and url in shared_cache:
                shared_stats["cache_hits"] += 1
                return shared_cache[url]
            from market_research.fundamentals import json_get
            res = json_get(url)
            if is_full_market_endpoint(url):
                shared_cache[url] = res
                shared_stats["shared_endpoints"].add(url)
            return res

        def research(symbol, out, now, sec_user_agent):
            target = temp / "companies" / symbol
            if symbol not in reports and symbol not in errors:
                try:
                    cutoff = evaluation_time if symbol.endswith(".TW") else now
                    kwargs = {"sec_user_agent": sec_user_agent}
                    if research_fn is run:
                        kwargs["facts_get"] = caching_get
                        kwargs["financial_get"] = caching_get
                    reports[symbol] = research_fn(symbol, out=target, now=cutoff, **kwargs)
                except Exception as error:
                    errors[symbol] = error
            if symbol in errors:
                raise errors[symbol]
            if target.exists() and Path(out) != target:
                shutil.copytree(target, out, dirs_exist_ok=True)
            return reports[symbol]

        evaluation_time = now

        pilot_coverage = {
            "attempted_count": 0,
            "completed_count": 0,
            "partial_count": 0,
            "failed_count": 0,
            "price_only_count": 0,
            "shared_endpoints_cached": 0,
            "cache_hit_count": 0,
            "symbols": {},
        }

        for sym in target_symbols:
            pilot_coverage["attempted_count"] += 1
            t0 = time.perf_counter()
            sym_rec = {
                "symbol": sym,
                "status": "failed",
                "session": None,
                "company_name": None,
                "readiness": None,
                "duration_ms": 0,
                "error_type": None,
            }
            if is_etf(sym):
                sym_rec["status"] = "price_only"
                pilot_coverage["price_only_count"] += 1
                pilot_coverage["symbols"][sym] = sym_rec
                continue
            try:
                rep = research(sym, temp / "companies" / sym, now, sec_user_agent)
                dur = int((time.perf_counter() - t0) * 1000)
                sym_rec["duration_ms"] = dur
                sym_rec["status"] = "complete" if rep.get("complete") else "partial"
                sym_rec["session"] = rep.get("technical", {}).get("last_session")
                sym_rec["company_name"] = rep.get("issuer", {}).get("company_name")
                receipt = rep.get("run_receipt") or {}
                sym_rec["source_coverage"] = receipt.get("source_coverage")
                sym_rec["readiness"] = rep.get("research_readiness", {}).get("components")
                if rep.get("valuation_zone"):
                    sym_rec["valuation_zone"] = rep["valuation_zone"]
                if rep.get("thesis_check"):
                    sym_rec["thesis_check"] = rep["thesis_check"]
                if sym_rec["status"] == "complete":
                    pilot_coverage["completed_count"] += 1
                else:
                    pilot_coverage["partial_count"] += 1
            except Exception as err:
                dur = int((time.perf_counter() - t0) * 1000)
                sym_rec["duration_ms"] = dur
                sym_rec["status"] = "failed"
                sym_rec["error_type"] = type(err).__name__
                sym_rec["error_reason"] = str(err)
                pilot_coverage["failed_count"] += 1
            pilot_coverage["symbols"][sym] = sym_rec

        # Core ETFs and the benchmark are priced, never researched (#113).
        if benchmarks is None:
            benchmarks = get_benchmarks("tw") if pilot and symbols is None else []
        watch_symbols = [sym for sym in target_symbols if is_etf(sym)] + list(benchmarks)
        watch_rows = []
        if watch_symbols:
            try:
                watch_rows = price_watch_fn(watch_symbols, now)
            except Exception as err:
                watch_rows = [{"symbol": sym, "status": "failed", "error_type": type(err).__name__,
                               "reason": str(err)} for sym in watch_symbols]
        result["price_watch"] = watch_rows
        for row in watch_rows:
            if row["symbol"] in pilot_coverage["symbols"]:
                pilot_coverage["symbols"][row["symbol"]]["price_watch"] = row["status"]

        pilot_coverage["shared_endpoints_cached"] = len(shared_stats["shared_endpoints"])
        pilot_coverage["cache_hit_count"] = shared_stats["cache_hits"]
        result["pilot_coverage"] = pilot_coverage

        if "2330.TW" in pilot_coverage["symbols"] and pilot_coverage["symbols"]["2330.TW"]["status"] != "failed":
            rep_2330 = reports.get("2330.TW")
            if rep_2330:
                technical = rep_2330.get("technical", {})
                receipt = rep_2330.get("run_receipt") or {}
                fixed.update(
                    status="complete" if rep_2330.get("complete") else "partial",
                    session=technical.get("last_session"),
                    input_sha256=technical.get("input_sha256"),
                    evaluation_cutoff_utc=rep_2330.get("generated_utc"),
                    source_coverage=receipt.get("source_coverage"),
                    readiness=rep_2330.get("research_readiness", {}).get("components"),
                )
        elif "2330.TW" in pilot_coverage["symbols"]:
            fixed["error_type"] = pilot_coverage["symbols"]["2330.TW"].get("error_type")

        candidates_out = temp / "candidates"
        candidates = candidate_research(
            scan_dir, candidates_out, max_candidates,
            research_fn=research, sec_user_agent=sec_user_agent, now=now,
        )
        shutil.copytree(candidates_out, out, dirs_exist_ok=True)
        result["candidates"] = candidates

        if (temp / "companies").exists():
            shutil.copytree(temp / "companies", out / "companies", dirs_exist_ok=True)

        state_branch = None
        if "2330.TW" in reports:
            try:
                receipt = publication_fn(
                    mode, False, out / "fixed_research",
                    report=reports["2330.TW"], daily=True,
                )
                fixed["publication"] = receipt["publication"]
                fixed["snapshot_id"] = receipt["snapshot_id"]
                fixed["state_commit"] = receipt.get("fresh_read_commit")
                state_branch = receipt.get("state_branch")
            except Exception as error:
                fixed["publication"] = {"status": "failed", "error_type": type(error).__name__}

        # The published page gains the daily overview; the state stays the publication's own.
        state_file = out / "fixed_research" / "research_state.json"
        if (fixed["publication"]["status"] in ("published", "already_current") and state_branch
                and state_file.exists()):
            overview = {"price_watch": watch_rows, "valuation_zones": {
                sym: rec["valuation_zone"] for sym, rec in pilot_coverage["symbols"].items()
                if rec.get("valuation_zone")}, "thesis_checks": {
                sym: rec["thesis_check"] for sym, rec in pilot_coverage["symbols"].items()
                if rec.get("thesis_check")}, "names": {
                sym: rec["company_name"] for sym, rec in pilot_coverage["symbols"].items()
                if rec.get("company_name")}}
            try:
                state = json.loads(state_file.read_text(encoding="utf-8"))
                write_research_site(out / "fixed_research", state["records"],
                                    branch=state_branch, watchlist=overview)
                result["watchlist_site"] = {"status": "rendered"}
            except Exception as error:
                result["watchlist_site"] = {"status": "failed", "error_type": type(error).__name__}

        all_pilot_ok = (pilot_coverage["failed_count"] == 0)
        watch_ok = all(row["status"] != "failed" for row in watch_rows)
        fixed_ok = (fixed["status"] == "complete" and fixed["publication"]["status"] in ("published", "already_current"))
        candidates_ok = candidates["status"] in ("complete", "no_candidates")

        if all_pilot_ok and fixed_ok and candidates_ok and watch_ok:
            result["status"] = "complete"
        elif fixed_ok and candidates_ok:
            result["status"] = "partial"

    (out / "daily_receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    lines = [
        "## 每日固定研究與候選摘要", "",
        f"整體：{result['status']}",
        f"掃描：{candidates['status']}；候選 {candidates['candidate_count']}；嘗試 {candidates['attempted_count']}",
        f"固定 2330：{fixed['status']}；行情 session：{fixed.get('session') or '未知'}",
        f"固定研究 cutoff：{fixed.get('evaluation_cutoff_utc') or '未完成'}",
        f"行情時效：{(fixed.get('source_coverage') or {}).get('technical', {}).get('freshness', 'unknown')}",
        f"固定發布：{fixed['publication']['status']}",
        f"固定入口：{fixed['publication'].get('issue_url', '未確認；請看 receipt')}", "",
        "固定研究採自身本次資料；只有通過 scan session／hash gate 才能關聯技術候選。",
        "來源缺口與本次執行結果見 daily_receipt.json；發布成功時可由固定入口閱讀。",
        "資料流程完成不等於財報、估值或買賣建議完成；自然 schedule 另行驗收。", "",
    ]
    for label, key in (("年度財報", "financial"), ("估值", "valuation"), ("交易計畫", "trade_plan")):
        readiness = (fixed.get("readiness") or {}).get(key, {})
        lines.append(f"- {label}：{readiness.get('status', 'unknown')}")

    if pilot_coverage and len(pilot_coverage["symbols"]) > 1:
        lines += [
            "",
            "### 台股 Pilot 多標的涵蓋與模型適用性",
            "",
            f"標的涵蓋：成功 {pilot_coverage['completed_count']} / 部分 {pilot_coverage['partial_count']} / 失敗 {pilot_coverage['failed_count']} / 僅行情 {pilot_coverage['price_only_count']}（共 {pilot_coverage['attempted_count']} 檔）",
            f"共用快取端點：{pilot_coverage['shared_endpoints_cached']} 個；快取命中：{pilot_coverage['cache_hit_count']} 次",
            "",
            "| 標的代碼 | 公司名稱 | 流程狀態 | 行情 Session | 財務狀態 | 估值狀態 | 耗時 (ms) |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | ---: |",
        ]
        for sym, rec in pilot_coverage["symbols"].items():
            name = rec["company_name"] or "—"
            status = rec["status"]
            sess = rec["session"] or "—"
            fin = (rec.get("readiness") or {}).get("financial", {}).get("status", "—")
            val = (rec.get("readiness") or {}).get("valuation", {}).get("status", "—")
            dur = f"{rec['duration_ms']}ms"
            if sym in ("2881.TW", "2882.TW", "2891.TW") and val == "not_evaluated":
                val = "not_evaluated (金融不適用)"
            lines.append(f"| {sym} | {name} | {status} | {sess} | {fin} | {val} | {dur} |")

    zones = [(sym, rec["valuation_zone"]) for sym, rec in (pilot_coverage or {}).get("symbols", {}).items()
             if rec.get("valuation_zone")]
    if zones:
        lines += [
            "", "### 衛星個股估值檢視區（檢視區，非買賣建議）", "",
            "價位 = 本益比區間 × 近四季 EPS；本益比區間預設為近 5 年每日本益比（FinMind TaiwanStockPER）"
            "第 20／50／80 百分位，設定見 config/watchlist.yaml。", "",
            "| 標的 | 收盤（日期） | 偏低價 | 合理價 | 偏高價 | 目前區間 | 近四季 EPS | 本益比樣本 |",
            "| :--- | ---: | ---: | ---: | ---: | :--- | :--- | :--- |",
        ]
        lines += [zone_summary_row(sym, zone) for sym, zone in zones]
    # Only satellites carry revenue evidence; other stocks are not checked.
    checks = [(sym, rec["thesis_check"]) for sym, rec in (pilot_coverage or {}).get("symbols", {}).items()
              if (rec.get("thesis_check") or {}).get("revenue") is not None]
    if checks:
        lines += [
            "", f"### 衛星個股論點檢查（{THESIS_DISCLAIMER}）", "",
            "月營收年增率連續低於門檻（預設連續 3 個月 < 0%，見 config/watchlist.yaml）或當日有 TWSE 重大公告時"
            "標為「請檢視」；資料不足或來源失敗為「未評估」。", "",
            "| 標的 | 論點狀態 | 月營收年增率 | 當日重大公告 | 依據 |",
            "| :--- | :--- | :--- | ---: | :--- |",
        ]
        lines += [thesis_summary_row(sym, check) for sym, check in checks]
    lines += render_price_watch_summary(result["price_watch"])

    (out / "daily_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-dir", type=Path, default=Path("output"))
    parser.add_argument("--out", type=Path, default=Path("output/candidate_research"))
    parser.add_argument("--market", choices=("tw", "both"), default="tw")
    parser.add_argument("--mode", choices=("validation", "production"), default="validation")
    parser.add_argument("--max-candidates", type=int, default=3)
    parser.add_argument("--pilot", action="store_true", default=False,
                        help="Run full pilot universe for market from config/markets.yaml")
    parser.add_argument("--symbols", nargs="+", default=None,
                        help="Explicit list of symbols to research")
    args = parser.parse_args()
    result = execute(
        args.scan_dir, args.out, market=args.market, mode=args.mode,
        max_candidates=args.max_candidates, sec_user_agent=os.getenv("SEC_USER_AGENT"),
        pilot=args.pilot, symbols=args.symbols,
    )
    print((args.out / "daily_summary.md").read_text(encoding="utf-8"))
    if result["status"] not in ("complete", "partial"):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
