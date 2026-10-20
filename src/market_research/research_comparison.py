"""Pure comparisons of retained evidence; omitted inputs are never inferred."""
from html import escape

from .research_snapshot import SnapshotError, utc, validate_snapshot

COMPONENTS = ("issuer", "monthly_revenue", "technical", "events")


def period_key(period):
    return int(period[:-2]), int(period[-2:])


def available(snapshot, component):
    if component == "issuer":
        return bool(snapshot["issuer"]["company_name"])
    if component == "monthly_revenue":
        return bool(snapshot["monthly_revenue"])
    return snapshot[component]["status"] == "available"


def compare_snapshots(previous, current, last_known_good=None):
    validate_snapshot(current)
    if previous is not None:
        validate_snapshot(previous)
    last_known_good = last_known_good or {}
    for candidate in ([previous] if previous else []) + list(last_known_good.values()):
        validate_snapshot(candidate)
        if (candidate["symbol"] != current["symbol"] or candidate["market"] != current["market"] or
                utc(candidate["observed_at_utc"]) > utc(current["observed_at_utc"])):
            raise SnapshotError("Comparison identity/time mismatch")
    if set(last_known_good) - set(COMPONENTS):
        raise SnapshotError("Unknown comparison component")
    if any(not available(candidate, component) for component, candidate in last_known_good.items()):
        raise SnapshotError("Last-known-good reference has no available evidence")
    changes = []
    def change(kind, component, reason, period=None):
        changes.append({"kind": kind, "component": component, "reason": reason, "period": period})
    if previous:
        reversed_cutoff = utc(previous["evaluation_cutoff_utc"]) > utc(current["evaluation_cutoff_utc"])
        if reversed_cutoff:
            change("incomparable", "time", "historical_cutoff_reversed")
        if previous["schema_version"] != current["schema_version"]:
            change("incomparable", "schema", "schema_changed")
        old_model, new_model = previous.get("model_identity"), current.get("model_identity")
        if old_model and new_model and old_model != new_model:
            change("model_change", "model", "model_or_config_changed")
        elif bool(old_model) != bool(new_model):
            change("incomparable", "model", "model_identity_not_retained")
        if any(previous["technical"][key] != current["technical"][key] for key in ("source", "price_basis")):
            change("incomparable", "technical", "source_or_basis_changed")
        if (available(previous, "technical") and available(current, "technical") and
                previous["technical"]["input_sha256"] != current["technical"]["input_sha256"]):
            change("incomparable", "technical", "price_inputs_not_retained")
        if previous["events"]["source"] != current["events"]["source"] or previous["events"]["coverage"] != current["events"]["coverage"]:
            change("coverage_change", "events", "source_or_coverage_changed")
        for key in COMPONENTS:
            if available(previous, key) != available(current, key):
                change("coverage_change", key, "source_restored" if available(current, key) else "source_unavailable")
            elif key in ("technical", "events") and previous[key]["status"] != current[key]["status"]:
                change("coverage_change", key, "source_status_changed")
        issuer_baseline = previous if available(previous, "issuer") else last_known_good.get("issuer", previous)
        if utc(issuer_baseline["evaluation_cutoff_utc"]) > utc(current["evaluation_cutoff_utc"]):
            if available(current, "issuer"):
                change("incomparable", "issuer", "historical_cutoff_reversed")
        elif issuer_baseline["issuer"]["company_name"] and current["issuer"]["company_name"] and issuer_baseline["issuer"]["company_name"] != current["issuer"]["company_name"]:
            change("revision", "issuer", "reported_identity_changed")
        if previous["technical"]["freshness"] != current["technical"]["freshness"]:
            change("coverage_change", "technical", "freshness_changed")
        for key, status in current["readiness"].items():
            if previous["readiness"][key] != status:
                change("coverage_change", "readiness_" + key, "readiness_changed")
        baseline = previous if previous["monthly_revenue"] else last_known_good.get("monthly_revenue", previous)
        if not reversed_cutoff and utc(baseline["evaluation_cutoff_utc"]) > utc(current["evaluation_cutoff_utc"]):
            reversed_cutoff = True
            change("incomparable", "monthly_revenue", "historical_cutoff_reversed")
        old_facts = {period_key(f["period"]): f for f in baseline["monthly_revenue"]}
        if bool(old_facts) != bool(current["monthly_revenue"]):
            change("incomparable", "monthly_revenue", "retained_values_missing")
        for fact in current["monthly_revenue"]:
            if reversed_cutoff:
                continue
            old = old_facts.get(period_key(fact["period"]))
            if not old_facts:
                continue
            if old is None:
                change("new_period", "monthly_revenue", "new_retained_period", fact["period"])
            elif any(old[key] != fact[key] for key in ("source", "unit", "policy", "metric")):
                change("incomparable", "monthly_revenue", "source_or_basis_changed", fact["period"])
            elif fact["value"] != old["value"]:
                change("revision", "monthly_revenue", "reported_value_changed", fact["period"])
    limitations = set(current["comparison_limits"])
    if not current.get("model_identity") or previous and not previous.get("model_identity"):
        limitations.add("model_identity_not_retained")
    return {"schema_version": 1, "previous_snapshot_id": previous["id"] if previous else None,
            "current_snapshot_id": current["id"], "categories": sorted({c["kind"] for c in changes}) if changes else ["unchanged" if previous else "baseline"],
            "changes": changes, "limitations": sorted(limitations),
            "last_known_good": {key: last_known_good[key]["id"] if key in last_known_good else None for key in COMPONENTS}}


def render_comparison(comparison, snapshots):
    labels = {"baseline": "首次 baseline", "unchanged": "無研究變化", "new_period": "新資料期別",
              "revision": "同期間更正", "coverage_change": "來源／readiness 變化",
              "model_change": "模型／設定變更", "incomparable": "無法比較"}
    components = {"issuer": "公司身分", "monthly_revenue": "月營收", "technical": "行情與技術",
                  "events": "官方事件", "schema": "資料格式", "model": "模型／設定", "time": "評估時間"}
    reasons = {"schema_changed": "資料格式版本改變", "model_or_config_changed": "模型版本或設定改變",
               "model_identity_not_retained": "舊版本未保留模型 identity", "source_or_basis_changed": "來源或口徑不同",
               "price_inputs_not_retained": "行情輸入已變但未保留價格數值", "source_or_coverage_changed": "來源或涵蓋範圍改變",
               "source_restored": "來源恢復", "source_unavailable": "來源目前不可用",
               "source_status_changed": "來源狀態改變", "reported_identity_changed": "公司名稱更正",
               "freshness_changed": "資料時效改變", "readiness_changed": "研究準備度改變",
               "retained_values_missing": "缺少可比前值或目前值，未計成長", "new_retained_period": "新增資料期別",
               "reported_value_changed": "相同期別保留數值更正", "historical_cutoff_reversed": "較早的歷史 cutoff 不能用新取得值回填"}
    lines = ["## 前後變化", "", "、".join(labels[key] for key in comparison["categories"]), ""]
    current = snapshots[comparison["current_snapshot_id"]]
    previous = snapshots.get(comparison["previous_snapshot_id"])
    baseline = previous if previous and previous["monthly_revenue"] else snapshots.get(comparison["last_known_good"]["monthly_revenue"])
    for item in comparison["changes"]:
        detail = ""
        used_baseline = None
        if item["component"] == "monthly_revenue" and item["kind"] in ("revision", "new_period"):
            used_baseline = baseline
            new = next(f for f in current["monthly_revenue"] if f["period"] == item["period"])
            old = next((f for f in baseline["monthly_revenue"] if period_key(f["period"]) == period_key(item["period"])), None) if baseline else None
            detail = f"：{old['value']:,} → {new['value']:,} {new['unit']}" if old else f"：{new['value']:,} {new['unit']}"
        elif item["component"] == "issuer" and item["kind"] == "revision":
            used_baseline = previous if previous and available(previous, "issuer") else snapshots[comparison["last_known_good"]["issuer"]]
            names = [escape(s["issuer"]["company_name"]).replace("[", "&#91;").replace("]", "&#93;")
                     for s in (used_baseline, current)]
            detail = f"：{names[0]} → {names[1]}"
        component = components.get(item["component"], item["component"].replace("readiness_", "研究準備度 "))
        lines.append(f"- {labels[item['kind']]}：{component} {item['period'] or ''}{detail}（{reasons[item['reason']]}）")
        if used_baseline and used_baseline != previous:
            lines.append(f"  比較 baseline snapshot `{used_baseline['id']}`")
    for key, identifier in comparison["last_known_good"].items():
        if identifier and not available(current, key):
            previous = snapshots[identifier]
            lines += ["", f"{components[key]} 目前不可用；最近可用：{previous['observed_at_utc']}（非本次資料）。"]
            if key == "monthly_revenue":
                lines += [f"- {fact['period']}：{fact['value']:,} {fact['unit']}；{fact['source']}"
                          for fact in previous["monthly_revenue"]]
            lines.append(f"證據 snapshot `{identifier}`")
    lines += ["", "比較僅適用系統已觀測版本，不回填為歷史當時已知；缺值不補零。",
              "限制：" + ", ".join(comparison["limitations"]),
              f"前次 snapshot `{comparison['previous_snapshot_id'] or 'none'}`", ""]
    return "\n".join(lines)
