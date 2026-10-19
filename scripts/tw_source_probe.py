"""Bounded 2330 source-adoption probe; never exports source numeric values."""
import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
from decimal import Decimal, InvalidOperation

import httpx

FINMIND = "https://api.finmindtrade.com/api/v4/data"
DATASETS = {"income": "TaiwanStockFinancialStatements",
            "balance": "TaiwanStockBalanceSheet",
            "cashflow": "TaiwanStockCashFlowsStatement"}
IR = {
    "annual_ir": "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-02/cb73d5f4e019a8f6d7a494a0f8f6c6da2dfc4ee2/FS.pdf",
    "interim_ir": "https://investor.tsmc.com/english/encrypt/files/encrypt_file/reports/2026-07/114aaca0fea2050e96b91fffbab9ed04ba09cd92/FS.pdf",
}
OPEN_DATA = {"twse_income": "https://openapi.twse.com.tw/v1/opendata/t187ap06_L_ci",
             "twse_balance": "https://openapi.twse.com.tw/v1/opendata/t187ap07_L_ci"}
MAX_BYTES = 5_000_000
PERIODS = {"2025-FY": ("annual_ir", ("2025-03-31", "2025-06-30", "2025-09-30", "2025-12-31")),
           "2026-H1": ("interim_ir", ("2026-03-31", "2026-06-30"))}
METRICS = {"cash": ("balance", "CashAndCashEquivalents"), "assets": ("balance", "TotalAssets"),
           "revenue": ("income", "Revenue"), "net_income": ("income", "IncomeAfterTaxes"),
           "cfo": ("cashflow", "CashFlowsFromOperatingActivities"),
           "capex": ("cashflow", "PropertyAndPlantAndEquipment")}


def http_get(url, params):
    with httpx.Client(timeout=20, follow_redirects=True) as client:
        with client.stream("GET", url, params=params) as response:
            chunks, size = [], 0
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("response exceeds probe size limit")
                chunks.append(chunk)
            return response.status_code, b"".join(chunks)


def fetch(url, params, get):
    entry = {"url": url, "status": "unavailable", "attempts": 0, "http_status": None}
    for attempt in range(2):
        entry["attempts"] += 1
        try:
            status, content = get(url, params)
            entry.update(http_status=status, content_sha256=hashlib.sha256(content).hexdigest())
            if len(content) > MAX_BYTES:
                entry["status"] = "oversized"
            elif status == 200:
                entry["status"] = "available"
                return entry, content
            else:
                entry["status"] = {402: "quota_exceeded", 403: "forbidden", 429: "rate_limited"}.get(status, "http_error")
                if status in (502, 503, 504) and attempt == 0:
                    continue
            return entry, None
        except httpx.TimeoutException:
            entry["status"] = "timeout"
        except (httpx.HTTPError, OSError):
            entry["status"] = "transport_error"
            break
        except ValueError:
            entry["status"] = "oversized"
            break
    return entry, None


def finmind_rows(body, cutoff):
    if not isinstance(body, dict) or body.get("status") != 200:
        raise ValueError("unexpected API status")
    rows = body.get("data")
    if not isinstance(rows, list):
        raise ValueError("data must be a list")
    selected, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or set(("date", "stock_id", "type", "value", "origin_name")) - row.keys()
                or row["stock_id"] != "2330" or not isinstance(row["type"], str)
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]{0,119}", row["type"])):
            raise ValueError("unverified issuer or schema")
        period = datetime.strptime(row["date"], "%Y-%m-%d").date()
        if not ("2025-01-01" <= row["date"] <= "2026-06-30") or period > cutoff.date():
            continue
        key = row["date"], row["type"]
        if key in seen:
            raise ValueError("duplicate period/concept")
        if isinstance(row["value"], bool) or not Decimal(str(row["value"])).is_finite():
            raise ValueError("nonfinite monetary value")
        seen.add(key)
        selected.append(row)
    return selected


def pdf_pages(content):
    from pypdf import PdfReader
    from pypdf.errors import PyPdfError
    if not content.startswith(b"%PDF-"):
        raise ValueError("not a PDF")
    try:
        reader = PdfReader(io.BytesIO(content), strict=True)
        if len(reader.pages) != 4:
            raise ValueError("expected four-page condensed statements")
        return [page.extract_text(extraction_mode="layout") for page in reader.pages]
    except (PyPdfError, OSError) as error:
        raise ValueError("unreadable PDF") from error


def oracle(pages, period):
    if len(pages) != 4:
        raise ValueError("wrong page count")
    for page in pages:
        if ("TAIWAN SEMICONDUCTOR MANUFACTURING COMPANY LIMITED AND SUBSIDIARIES" not in page or
                "Millions of New Taiwan Dollars" not in page or
                not re.search(r"(?m)^\s*USD[ \t]+NTD(?:[ \t]|$)", page)):
            raise ValueError("unverified issuer, scope, unit or currency columns")
    end = "December 31, 2025" if period == "2025-FY" else "June 30, 2026"
    duration = "For the Years Ended December 31" if period == "2025-FY" else "For the Six Months Ended June 30"
    if end not in pages[0] or duration not in pages[2] or end not in pages[3]:
        raise ValueError("unverified statement period")

    def row(text, label, column=1):
        matches = []
        for line in text.splitlines():
            normalized = re.sub(r"\s+", " ", line.strip()).replace("\u2019", "'").replace("\u2018", "'")
            match = re.match(re.escape(label) + r"\s+(.*)$", normalized, re.I)
            if match:
                tokens = re.findall(r"\(?-?\d[\d,]*(?:\.\d+)?\)?|(?<!\S)-(?!\S)", match[1])
                if len(tokens) <= column or tokens[column] == "-":
                    raise ValueError("missing numeric column")
                token = tokens[column].replace(",", "")
                matches.append(-Decimal(token[1:-1]) if token.startswith("(") else Decimal(token))
        if len(matches) != 1:
            raise ValueError("missing or ambiguous metric label")
        return matches[0]

    # Restrict CAPEX to acquisitions; disposal proceeds have the same row label.
    cf = pages[3].split("Acquisitions of:")
    if len(cf) != 2 or "Proceeds from Disposal" not in cf[1]:
        raise ValueError("unverified CAPEX section")
    acquisitions = cf[1].split("Proceeds from Disposal")[0]
    values = {"cash": row(pages[0], "Cash and Cash Equivalents"),
              "assets": row(pages[0], "Total Assets"), "revenue": row(pages[2], "Net Revenue"),
              "net_income": row(pages[2], "Net Income"),
              "cfo": row(pages[3], "Net Cash Generated by Operating Activities"),
              "capex": row(acquisitions, "Property, Plant and Equipment")}
    values["diluted_eps"] = row(pages[1], "Earnings per Share - Diluted")
    values["diluted_shares"] = row(pages[1], "Weighted Average Outstanding Shares - Diluted ('M)", 0)
    return values


def reconcile(inputs, values, period):
    dates = PERIODS[period][1]
    checks = {}
    for metric, (dataset, concept) in METRICS.items():
        rows = {row["date"]: Decimal(str(row["value"])) for row in inputs.get(dataset, [])
                if row["type"] == concept and row["date"] in dates}
        candidates = {}
        if dates[-1] in rows:
            candidates["instant" if dataset == "balance" else "reported_ytd"] = rows[dates[-1]]
        if dataset != "balance" and all(date in rows for date in dates):
            candidates["sum_quarters"] = sum(rows[date] for date in dates)
        matches = [basis for basis, amount in candidates.items()
                   if abs(amount - values[metric] * 1_000_000) <= 500_000 and
                   (metric != "capex" or (amount < 0 and values[metric] < 0))]
        checks[metric] = {"status": "matched" if len(matches) == 1 else "not_verified",
                          "dataset": DATASETS[dataset], "concept": concept,
                          "aggregation": matches[0] if len(matches) == 1 else None,
                          "finmind_unit": "TWD" if len(matches) == 1 else "not_verified",
                          "oracle_unit": "TWD_millions", "oracle_page":
                          1 if dataset == "balance" else 3 if dataset == "income" else 4}
        if metric == "capex":
            checks[metric]["sign"] = "cash_outflow_negative"
    return {"status": "matched" if all(row["status"] == "matched" for row in checks.values()) else "not_verified",
            "scope": "consolidated_issuer_document", "period_end": dates[-1],
            "assurance": "audited_columns_in_condensed_release" if period == "2025-FY" else "unaudited_condensed_release",
            "metrics": checks,
            "eps": {"status": "not_comparable_basic_vs_diluted", "oracle_page": 2, "unit": "TWD_per_ordinary_share"},
            "shares": {"status": "unsupported_diluted_average_shares", "oracle_page": 2, "unit": "million_ordinary_shares"}}


def probe(get=None, now=None, read_pdf=None):
    cutoff = now or datetime.now(timezone.utc)
    if cutoff.tzinfo is None:
        raise ValueError("timezone-aware cutoff required")
    cutoff = cutoff.astimezone(timezone.utc)
    sources, inputs, oracles = {}, {}, {}
    for name, url in {**dict.fromkeys(DATASETS, FINMIND), **IR, **OPEN_DATA}.items():
        params = {"dataset": DATASETS[name], "data_id": "2330", "start_date": "2025-01-01",
                  "end_date": "2026-06-30"} if name in DATASETS else None
        entry, content = fetch(url, params, get or http_get)
        sources[name] = entry
        if name in DATASETS:
            entry["dataset"] = DATASETS[name]
        if content is None:
            continue
        try:
            if name in DATASETS:
                body = json.loads(content)
                if isinstance(body, dict) and body.get("status") in (402, 403, 429):
                    entry["status"] = {402: "quota_exceeded", 403: "forbidden", 429: "rate_limited"}[body["status"]]
                    continue
                rows = finmind_rows(body, cutoff)
                entry.update(status="available" if rows else "empty",
                             row_count=len(rows), periods=sorted({row["date"] for row in rows}),
                             concepts=sorted({row["type"] for row in rows}))
                inputs[name] = rows
            elif name in IR:
                period = next(period for period, (document, _) in PERIODS.items() if document == name)
                if PERIODS[period][1][-1] > cutoff.date().isoformat():
                    entry["status"] = "future_period"
                    continue
                oracles[period] = oracle((read_pdf or pdf_pages)(content), period)
                entry.update(period=period, page_count=4, document_kind="issuer_condensed_release")
            else:
                rows = json.loads(content)
                if not isinstance(rows, list):
                    raise ValueError("TWSE dataset must be list")
                matched = [r for r in rows if isinstance(r, dict) and str(r.get("公司代號")) == "2330"]
                entry.update(status="issuer_found" if len(matched) == 1 else "not_found",
                             issuer_rows=len(matched), reuse="OGDL-1.0", unit="not_verified")
        except ModuleNotFoundError:
            entry["status"] = "parser_unavailable"
        except (ValueError, TypeError, KeyError, InvalidOperation):
            entry["status"] = "format_changed"
    comparisons = {period: reconcile(inputs, values, period) for period, values in oracles.items()}
    stamp = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()
    return {"schema_version": 1, "symbol": "2330.TW", "first_seen_at_utc": stamp,
            "sources": sources, "reconciliation": comparisons,
            "current_source_acceptance": "reconciled_current_sample" if len(comparisons) == 2 and
            all(c["status"] == "matched" for c in comparisons.values()) else "not_verified",
            "public_numeric_export": "not_verified", "production_readiness": "needs_info",
            "historical_point_in_time": "not_verified", "published_at": None,
            "availability_basis": "first_seen_only",
            "authentication": "none", "raw_retention": "memory_only",
            "export_policy": "metadata_and_comparison_status_only_no_values_or_differences",
            "source_contract": "docs/TW_FINANCIAL_SOURCE_CONTRACT.md"}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=Path("source_adoption_output"))
    args = parser.parse_args()
    result = probe()
    lines = ["# 2330 免費財報來源驗證", "",
             "觀測時間 (UTC)：" + result["first_seen_at_utc"],
             "FinMind／TWSE／TSMC IR 的有限取樣；probe 執行成功與來源採用分開。", "",
             "當下樣本對帳：**" + result["current_source_acceptance"] + "**",
             "正式導入：needs_info；公開數值出口：not_verified；歷史 point-in-time：not_verified。", "",
             "| 來源 | HTTP | 狀態 | 次數 | 期別 |",
             "| --- | --- | --- | --- | --- |"]
    for name, entry in result["sources"].items():
        periods = ", ".join(entry.get("periods", [])) or entry.get("period", "—")
        lines.append(f"| {name} | {entry['http_status']} | {entry['status']} | {entry['attempts']} | {periods} |")
    for period, checks in result["reconciliation"].items():
        lines += ["", f"## {period}：{checks['status']}", "",
                  "| 代表性科目 | 對帳 | FinMind 期別語意 | IR 頁碼 |",
                  "| --- | --- | --- | --- |"]
        for metric, check in checks["metrics"].items():
            lines.append(f"| {metric} | {check['status']} | {check['aggregation']} | {check['oracle_page']} |")
        lines += ["", "EPS：basic 與 diluted 不直接比較；FinMind 未提供本票已確認的 diluted weighted-average shares mapping。"]
    lines += ["", "## 採用邊界", "",
              "只取樣 2025 全年與 2026 上半年；不是最新所有季度或三年完整財報 coverage。",
              "IR 年度摘要的 audited 欄與期中 unaudited 摘要保留差異；沒有冒充完整核閱報告。",
              "raw JSON／PDF／全文僅留記憶體；輸出只含 hash、metadata 與不含原值／差額的對帳結果。",
              "FinMind 精簡數值／衍生值與 IR 數值的公開出口仍未確認；TWSE 開放資料的授權不擴張到其他來源。",
              "403／402／429 不重試；timeout／502／503／504 最多兩次，不繞過封鎖。",
              "未知歷史公開時間不妨礙 first_seen 之後的當下研究；本次不證明歷史回放或修訂 lineage。",
              "來源未成立時，下游財報導入保持 needs-info；其他 workflow 能力可獨立交付。"]
    markdown = "\n".join(lines) + "\n"
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "source_adoption.json").write_text(
        json.dumps(result, indent=2, ensure_ascii=False, allow_nan=False) + "\n", encoding="utf-8")
    (args.out / "source_adoption.md").write_text(markdown, encoding="utf-8")
    print(markdown)


if __name__ == "__main__":
    main()
