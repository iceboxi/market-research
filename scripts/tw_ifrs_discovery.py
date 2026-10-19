"""Bounded read-only official TW IFRS source discovery. NOT production ingestion.

Output contains structural/source metadata only, no financial statement values,
no raw HTML, no guessed publication time or legal redistribution permission.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

import httpx

TWSE = "https://openapi.twse.com.tw/v1"
SOURCES = {
    "swagger": TWSE + "/swagger.json",
    "income": TWSE + "/opendata/t187ap06_L_ci",
    "balance": TWSE + "/opendata/t187ap07_L_ci",
    "cashflow_mops": "https://mops.twse.com.tw/mops/web/t164sb05",
}
MAX_BYTES = 14_000_000
COMPANY_KEYS = ("公司代號", "公司代碼", "公司名稱", "公司簡稱")
PERIOD_HINTS = ("年度", "季", "日期", "年月", "期別", "year", "quarter")
REQUIRED = ("income", "balance", "cashflow_mops")


def shape(item, source, symbol, fetched_utc):
    """Fail closed: HTTP success and page navigation are not statement coverage."""
    entry = {"source": source, "retrieved_at_utc": fetched_utc,
             "status": "unverified", "issuer_verified": False,
             "period_verified": False, "scope_verified": False,
             "statement_verified": False, "publication_at": None,
             "publication_precision": "unknown",
             "revision_identity": None, "redistribution_rights": "not_verified"}
    if item["http_status"] != 200:
        entry["reason"] = "HTTP non-200"
        return entry
    data = item.get("data")
    if isinstance(data, list):
        entry["shape"] = "json_list"
        entry["row_count"] = len(data)
        entries = [x for x in data if isinstance(x, dict)]
        entry["sample_key_names"] = sorted({str(k) for x in entries[:5] for k in x})[:30]
        selected = [x for x in entries if any(str(x.get(k, "")).strip() == symbol
                    for k in COMPANY_KEYS)]
        entry["matched_issuer_rows"] = len(selected)
        entry["issuer_verified"] = len(selected) == 1
        if selected:
            row = selected[0]
            entry["issuer_key_names"] = sorted(str(k) for k in row)[:50]
            entry["period_hints"] = sorted(
                str(k) for k in row if any(p in str(k) for p in PERIOD_HINTS))[:20]
        entry["status"] = "issuer_found_period_unverified" if selected else "not_found"
        entry["reason"] = "Current aggregate OpenAPI is not a historical fiscal-quarter statement"
    elif isinstance(data, dict) and source.endswith("swagger.json"):
        entry["shape"] = "openapi_spec"
        paths = data.get("paths", {})
        entry["openapi_cashflow_paths"] = [p for p in paths if
                                          "cash" in p.lower() or "現金流" in
                                          json.dumps(paths[p], ensure_ascii=False)][:15]
        entry["openapi_income_path"] = "/opendata/t187ap06_L_ci" in paths
        entry["openapi_balance_path"] = "/opendata/t187ap07_L_ci" in paths
        entry["status"] = "spec_observed"
        entry["reason"] = "OpenAPI listing is discovery, not issuer statement verification"
    elif isinstance(data, str):
        entry["shape"] = "html"
        clean = re.sub(r"<[^>]{0,2048}>", " ", data[:200000])
        entry["has_cashflow_label"] = "現金流量表" in clean
        entry["has_query_controls"] = all(s in data for s in ("form", "input"))
        entry["status"] = "query_landing_only"
        entry["reason"] = "HTML landing page is not authenticated 2330 2024 Q4 cash-flow data"
    else:
        entry["reason"] = "Unrecognized document shape"
    return entry


def discover(get=None, symbol="2330", now=None):
    if not re.fullmatch(r"[0-9]{4,6}", symbol):
        raise ValueError("Use a TWSE numeric ticker")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("Evaluation time must have timezone")
    stamp = now.astimezone(timezone.utc).isoformat()
    observations = {}
    requester = get
    for name, url in SOURCES.items():
        entry = {"url": url, "http_status": None, "data": None}
        try:
            if requester is not None:
                response = requester(url)
                status, content, typ = response
            else:
                with httpx.Client(follow_redirects=True, timeout=17) as client:
                    res = client.get(url, headers={
                        "User-Agent": "MarketResearchSourceDiscovery/1.0 (read-only)"})
                    status, content, typ = res.status_code, res.content, res.headers.get("content-type", "")
            entry["http_status"] = status
            if len(content) > MAX_BYTES:
                raise ValueError("Response exceeds bounded metadata-probe size")
            if status == 200:
                if "json" in typ or content[:1] in (b"{", b"["):
                    entry["data"] = json.loads(content)
                else:
                    entry["data"] = content.decode("utf-8", "replace")
            observations[name] = shape(entry, url, symbol, stamp)
            observations[name]["http_status"] = status
        except (httpx.HTTPError, ValueError, UnicodeError, json.JSONDecodeError) as error:
            observations[name] = {
                "source": url, "retrieved_at_utc": stamp,
                "status": "unavailable", "reason": type(error).__name__,
                "http_status": entry["http_status"], "publication_at": None,
                "revision_identity": None, "redistribution_rights": "not_verified",
            }
    gates = {
        "three_statements_same_fiscal_period_verified": False,
        "three_statements_consolidation_verified": False,
        "fiscal_period": "2024-Q4", "fiscal_period_evidence": "not_verified",
        "historical_version_and_publication_time_verified": False,
        "automated_redistribution_rights_verified": False,
    }
    return {
        "schema_version": 1, "symbol": symbol, "generated_at_utc": stamp,
        "sources": observations, "gates": gates,
        "verdict": "discovery_incomplete",
        "limitations": [
            "Landing pages and aggregate current OpenAPI values are not 2024 Q4 statements",
            "No XBRL/cashflow ingestion API has been approved for automation",
            "As-of public availability, restatements, scope and redistribution remain unverified",
            "No statement values or raw documents are stored",
        ],
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("ifrs_discovery_output"))
    args = p.parse_args()
    result = discover()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "source_probe.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# TW IFRS source discovery (read-only)",
             f"Generated: {result['generated_at_utc']}",
             "Issuer: 2330, intended period: 2024-Q4", "",
             "| Source | HTTP | Shape / status | 2330 rows |",
             "| --- | --- | --- | ---: |"]
    for name, src in result["sources"].items():
        lines.append(f"| {name} | {src.get('http_status')} | {src['status']} | "
                     f"{src.get('matched_issuer_rows', 'N/A')} |")
    lines += ["", "## Gate result", "**discovery_incomplete**",
              "Official-source accessibility is not statement availability or permission to republish.",
              "No current valuation inputs are changed."]
    (args.out / "source_probe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
