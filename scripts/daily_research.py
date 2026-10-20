"""Fixed TW research plus verified candidates, sharing one computation per ticker."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import tempfile

from scripts.company_report import run
from scripts.research_publication import execute as publish_report
from scripts.scan_company_research import execute as candidate_research


def execute(scan_dir, out, *, market="tw", mode="validation", max_candidates=3,
            research_fn=run, publication_fn=publish_report, sec_user_agent=None, now=None):
    if market not in ("tw", "both"):
        raise ValueError("Daily fixed research requires TW coverage")
    if not 1 <= max_candidates <= 20 or now is not None and now.tzinfo is None:
        raise ValueError("Use 1..20 candidates and a timezone-aware cutoff")
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    result = {"schema_version": 1, "market": market, "status": "partial",
              "generated_utc": datetime.now(timezone.utc).isoformat(),
              "fixed_research": {"symbol": "2330.TW", "status": "failed",
                                 "scope": "independent_current_research_not_a_scan_candidate",
                                 "publication": {"status": "not_attempted"}},
              "candidates": None}
    fixed = result["fixed_research"]
    with tempfile.TemporaryDirectory(prefix="daily-research-inputs-") as temp:
        temp = Path(temp)
        reports, errors = {}, {}

        def research(symbol, out, now, sec_user_agent):
            target = temp / "companies" / symbol
            if symbol not in reports and symbol not in errors:
                try:
                    # Current TW fixes cutoff after acquisition; explicit historical
                    # cutoffs and the legacy US candidate time contract are retained.
                    cutoff = evaluation_time if symbol.endswith(".TW") else now
                    reports[symbol] = research_fn(symbol, out=target, now=cutoff,
                                                  sec_user_agent=sec_user_agent)
                except Exception as error:
                    errors[symbol] = error
            if symbol in errors:
                raise errors[symbol]
            if target.exists() and Path(out) != target:
                shutil.copytree(target, out, dirs_exist_ok=True)
            return reports[symbol]

        evaluation_time = now
        try:
            report = research("2330.TW", temp / "companies" / "2330.TW", now, sec_user_agent)
            technical = report["technical"]
            fixed.update(status="complete" if report["complete"] else "partial",
                         session=technical.get("last_session"),
                         input_sha256=technical.get("input_sha256"),
                         evaluation_cutoff_utc=report["generated_utc"],
                         source_coverage=report["run_receipt"]["source_coverage"],
                         readiness=report["research_readiness"]["components"])
        except Exception as error:
            fixed["error_type"] = type(error).__name__
        candidates_out = temp / "candidates"
        candidates = candidate_research(scan_dir, candidates_out, max_candidates,
                                        research_fn=research, sec_user_agent=sec_user_agent, now=now)
        shutil.copytree(candidates_out, out, dirs_exist_ok=True)
        result["candidates"] = candidates
        if "2330.TW" in reports:
            try:
                receipt = publication_fn(mode, False, out / "fixed_research",
                                         report=reports["2330.TW"], daily=True)
                fixed["publication"] = receipt["publication"]
                fixed["snapshot_id"] = receipt["snapshot_id"]
                fixed["state_commit"] = receipt.get("fresh_read_commit")
            except Exception as error:
                fixed["publication"] = {"status": "failed", "error_type": type(error).__name__}
        if (fixed["status"] == "complete" and
                fixed["publication"]["status"] in ("published", "already_current") and
                candidates["status"] in ("complete", "no_candidates")):
            result["status"] = "complete"
    (out / "daily_receipt.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    lines = ["## 每日固定研究與候選摘要", "", f"整體：{result['status']}",
             f"掃描：{candidates['status']}；候選 {candidates['candidate_count']}；嘗試 {candidates['attempted_count']}",
             f"固定 2330：{fixed['status']}；行情 session：{fixed.get('session') or '未知'}",
             f"固定研究 cutoff：{fixed.get('evaluation_cutoff_utc') or '未完成'}",
             f"行情時效：{fixed.get('source_coverage', {}).get('technical', {}).get('freshness', 'unknown')}",
             f"固定發布：{fixed['publication']['status']}",
             f"固定入口：{fixed['publication'].get('issue_url', '未確認；請看 receipt')}", "",
             "固定研究採自身本次資料；只有通過 scan session／hash gate 才能關聯技術候選。",
             "來源缺口與本次執行結果見 daily_receipt.json；發布成功時可由固定入口閱讀。",
             "資料流程完成不等於財報、估值或買賣建議完成；自然 schedule 另行驗收。", ""]
    for label, key in (("年度財報", "financial"), ("估值", "valuation"), ("交易計畫", "trade_plan")):
        readiness = fixed.get("readiness", {}).get(key, {})
        lines.append(f"- {label}：{readiness.get('status', 'unknown')}")
    (out / "daily_summary.md").write_text("\n".join(lines), encoding="utf-8")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--scan-dir", type=Path, default=Path("output"))
    parser.add_argument("--out", type=Path, default=Path("output/candidate_research"))
    parser.add_argument("--market", choices=("tw", "both"), default="tw")
    parser.add_argument("--mode", choices=("validation", "production"), default="validation")
    parser.add_argument("--max-candidates", type=int, default=3)
    args = parser.parse_args()
    result = execute(args.scan_dir, args.out, market=args.market, mode=args.mode,
                     max_candidates=args.max_candidates, sec_user_agent=os.getenv("SEC_USER_AGENT"))
    print((args.out / "daily_summary.md").read_text())
    if result["status"] != "complete":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
