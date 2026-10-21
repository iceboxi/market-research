"""Single research owner: compact snapshots, publication outbox and ACK.

All Git I/O stays in GitStateStore. External delivery is injected at publish().
"""
from html import escape
import re

from market_research.company_analysis import render_tw_full_research_sections
from market_research.research_snapshot import (
    READINESS, SnapshotError, encoded, fingerprint, utc, validate_snapshot,
)
from scripts.state_store import GitStateStore, StateError
from market_research.research_comparison import COMPONENTS, available, compare_snapshots, render_comparison

MAX_RECORDS = 2000
MAX_NAMESPACE_BYTES = 5_000_000
SUBJECT = "subjects/tw/2330.TW.json"
CHECKPOINT = "checkpoints/tw/2330.TW.json"
HASH = r"[a-f0-9]{64}"
EVENT_ID_RE = r"[A-Za-z0-9_:-]{3,100}"
SYMBOL_RE = r"[0-9]{4,6}\.TW"


def marker(branch, symbol="2330.TW"):
    if branch not in ("research-state", "research-state-validation"):
        raise StateError("Invalid publication branch")
    return f"<!-- market-research:fixed-report:{branch}:tw:{symbol} -->"


def notification_marker(branch, notification_id, symbol="2330.TW"):
    if branch not in ("research-state", "research-state-validation"):
        raise StateError("Invalid publication branch")
    _id(notification_id)
    return f"<!-- market-research:change-notification:{branch}:tw:{symbol}:{notification_id} -->"


def snapshot_path(identifier, symbol="2330.TW"):
    return f"snapshots/tw/{symbol}/{identifier}.json"


def publication_path(identifier, symbol="2330.TW"):
    return f"publications/tw/{symbol}/{identifier}.json"


def notification_path(identifier, symbol="2330.TW"):
    return f"notifications/tw/{symbol}/{identifier}.json"


def subject_path(symbol="2330.TW", market="tw"):
    return f"subjects/{market}/{symbol}.json"


def checkpoint_path(symbol="2330.TW", market="tw"):
    return f"checkpoints/{market}/{symbol}.json"


def find_snapshot_path(records, identifier, symbol=None):
    if symbol:
        p = snapshot_path(identifier, symbol)
        if p in records:
            return p
    return next((p for p in records if p.endswith(f"/{identifier}.json") and p.startswith("snapshots/")), None)


def find_publication_path(records, identifier, symbol=None):
    if symbol:
        p = publication_path(identifier, symbol)
        if p in records:
            return p
    return next((p for p in records if p.endswith(f"/{identifier}.json") and p.startswith("publications/")), None)


def find_notification_path(records, identifier, symbol=None):
    if symbol:
        p = notification_path(identifier, symbol)
        if p in records:
            return p
    return next((p for p in records if p.endswith(f"/{identifier}.json") and p.startswith("notifications/")), None)


def _fields(value, keys):
    if not isinstance(value, dict) or set(value) != set(keys.split()):
        raise StateError("Unexpected research state fields")


def _id(value, nullable=False):
    if nullable and value is None:
        return
    if not isinstance(value, str) or not re.fullmatch(HASH, value):
        raise StateError("Invalid research reference")


def _issue(value):
    if value is not None and (type(value) is not int or not 0 < value < 10**10):
        raise StateError("Invalid fixed Issue identity")


def _publication_identity(value):
    keys = ["schema_version", "kind", "renderer_version", "symbol", "snapshot_id", "last_success_id"]
    if value["schema_version"] == 2:
        keys.append("comparison")
    return {k: value[k] for k in keys}


def _notification_identity(value):
    keys = ["schema_version", "kind", "renderer_version", "symbol", "publication_id", "snapshot_id", "comparison"]
    return {k: value[k] for k in keys}


def _meaningful_change(delta):
    """Return True if comparison has genuine research changes (never baseline, unchanged, or price-input-only)."""
    cats = set(delta.get("categories") or [])
    if not cats or cats <= {"baseline", "unchanged"}:
        return False
    for ch in delta.get("changes") or []:
        if ch.get("reason") == "price_inputs_not_retained" and ch.get("component") == "technical":
            continue
        return True
    return False


def validate_records(records, branch):
    if not isinstance(records, dict) or len(records) > MAX_RECORDS:
        raise StateError("Research record budget exceeded")
    try:
        if len(encoded(records)) > MAX_NAMESPACE_BYTES:
            raise StateError("Research namespace byte budget exceeded")
        for path, value in records.items():
            if m := re.fullmatch(r"snapshots/tw/([0-9]{4,6}\.TW)/" + HASH + r"\.json", path):
                sym = m.group(1)
                validate_snapshot(value)
                if path != snapshot_path(value["id"], sym) or value["symbol"] != sym:
                    raise StateError("Snapshot identity/path mismatch")
            elif m := re.fullmatch(r"publications/tw/([0-9]{4,6}\.TW)/" + HASH + r"\.json", path):
                sym = m.group(1)
                keys = "schema_version id kind renderer_version symbol snapshot_id last_success_id status issue_number body_sha256"
                if isinstance(value, dict) and value.get("schema_version") == 2:
                    keys += " comparison"
                    _fields(value["comparison"], "previous_snapshot_id last_good_snapshot_ids")
                    _id(value["comparison"]["previous_snapshot_id"], nullable=True)
                    _fields(value["comparison"]["last_good_snapshot_ids"], " ".join(COMPONENTS))
                    for reference in value["comparison"]["last_good_snapshot_ids"].values():
                        _id(reference, nullable=True)
                _fields(value, keys)
                if (type(value["schema_version"]) is not int or value["schema_version"] not in (1, 2) or
                        type(value["renderer_version"]) is not int or value["renderer_version"] != value["schema_version"] or
                        value["kind"] != "fixed_report" or value["symbol"] != sym or
                        value["status"] not in ("pending", "acked", "superseded")):
                    raise StateError("Invalid publication schema")
                _id(value["snapshot_id"])
                _id(value["last_success_id"], nullable=True)
                _id(value["body_sha256"])
                _issue(value["issue_number"])
                if (value["id"] != fingerprint(_publication_identity(value)) or
                        path != publication_path(value["id"], sym)):
                    raise StateError("Publication identity mismatch")
            elif m := re.fullmatch(r"notifications/tw/([0-9]{4,6}\.TW)/" + HASH + r"\.json", path):
                sym = m.group(1)
                keys = "schema_version id kind renderer_version symbol publication_id snapshot_id comparison status issue_number comment_id creation_attempted body_sha256"
                _fields(value, keys)
                if (type(value["schema_version"]) is not int or value["schema_version"] != 1 or
                        type(value["renderer_version"]) is not int or value["renderer_version"] != 1 or
                        value["kind"] != "change_notification" or value["symbol"] != sym or
                        value["status"] not in ("pending", "acked", "superseded") or
                        type(value["creation_attempted"]) is not bool):
                    raise StateError("Invalid notification schema")
                _id(value["publication_id"])
                _id(value["snapshot_id"])
                _id(value["body_sha256"])
                _issue(value["issue_number"])
                _issue(value["comment_id"])
                _fields(value["comparison"], "previous_snapshot_id last_good_snapshot_ids")
                _id(value["comparison"]["previous_snapshot_id"], nullable=True)
                _fields(value["comparison"]["last_good_snapshot_ids"], " ".join(COMPONENTS))
                for reference in value["comparison"]["last_good_snapshot_ids"].values():
                    _id(reference, nullable=True)
                if (value["id"] != fingerprint(_notification_identity(value)) or
                        path != notification_path(value["id"], sym)):
                    raise StateError("Notification identity mismatch")
            elif m := re.fullmatch(r"checkpoints/tw/([0-9]{4,6}\.TW)\.json", path):
                sym = m.group(1)
                keys = "schema_version symbol consumed_event_ids consumed_financial_version pending_rerun last_completed_snapshot_id"
                _fields(value, keys)
                if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["symbol"] != sym:
                    raise StateError("Invalid checkpoint schema")
                ev_ids = value["consumed_event_ids"]
                if (not isinstance(ev_ids, list) or len(ev_ids) > 2000 or
                        len(ev_ids) != len(set(x for x in ev_ids if isinstance(x, str))) or
                        any(not isinstance(x, str) or not re.fullmatch(EVENT_ID_RE, x) for x in ev_ids)):
                    raise StateError("Invalid consumed event IDs in checkpoint")
                fin_ver = value["consumed_financial_version"]
                if fin_ver is not None and (not isinstance(fin_ver, str) or not re.fullmatch(EVENT_ID_RE, fin_ver)):
                    raise StateError("Invalid consumed financial version in checkpoint")
                _id(value["last_completed_snapshot_id"], nullable=True)
                pr = value["pending_rerun"]
                if pr is not None:
                    _fields(pr, "request_id reasons trigger_event_ids target_financial_version")
                    _id(pr["request_id"])
                    if (not isinstance(pr["reasons"], list) or not pr["reasons"] or
                            any(r not in ("new_official_events", "financial_version_changed") for r in pr["reasons"])):
                        raise StateError("Invalid pending rerun reasons")
                    if (not isinstance(pr["trigger_event_ids"], list) or
                            any(not isinstance(x, str) or not re.fullmatch(EVENT_ID_RE, x) for x in pr["trigger_event_ids"])):
                        raise StateError("Invalid pending rerun trigger event IDs")
                    tfv = pr["target_financial_version"]
                    if tfv is not None and (not isinstance(tfv, str) or not re.fullmatch(EVENT_ID_RE, tfv)):
                        raise StateError("Invalid pending rerun target financial version")
            elif m := re.fullmatch(r"subjects/tw/([0-9]{4,6}\.TW)\.json", path):
                sym = m.group(1)
                keys = "schema_version symbol latest_observation_id last_success_id pending_publication_id published_publication_id issue_number"
                if isinstance(value, dict) and value.get("schema_version") == 2:
                    keys += " creation_attempted"
                    if type(value.get("creation_attempted")) is not bool:
                        raise StateError("Invalid creation attempt fence")
                    for opt_key in ("pending_notification_id", "published_notification_id"):
                        if opt_key in value:
                            keys += f" {opt_key}"
                            _id(value[opt_key], nullable=True)
                _fields(value, keys)
                if type(value["schema_version"]) is not int or value["schema_version"] not in (1, 2) or value["symbol"] != sym:
                    raise StateError("Invalid subject schema")
                for key in ("latest_observation_id", "last_success_id", "pending_publication_id", "published_publication_id"):
                    _id(value[key], nullable=key != "latest_observation_id")
                _issue(value["issue_number"])
            else:
                raise StateError("Unapproved research path")
        for path, value in records.items():
            if path.startswith("publications/"):
                sym = value["symbol"]
                if (snapshot_path(value["snapshot_id"], sym) not in records or
                        value["last_success_id"] is not None and snapshot_path(value["last_success_id"], sym) not in records):
                    raise StateError("Missing publication snapshot")
                if value["body_sha256"] != body_hash(render_publication(records, value["id"], branch)):
                    raise StateError("Publication body checksum mismatch")
                if value["status"] == "acked" and value["issue_number"] is None:
                    raise StateError("Publication ACK lacks Issue identity")
            elif path.startswith("notifications/"):
                sym = value["symbol"]
                if (snapshot_path(value["snapshot_id"], sym) not in records or
                        publication_path(value["publication_id"], sym) not in records):
                    raise StateError("Missing notification snapshot or publication")
                if value["body_sha256"] != body_hash(render_notification(records, value["id"], branch)):
                    raise StateError("Notification body checksum mismatch")
                if value["status"] == "acked" and (value["issue_number"] is None or value["comment_id"] is None):
                    raise StateError("Notification ACK lacks Issue or comment identity")
        symbols_with_snapshots = {v["symbol"] for p, v in records.items() if p.startswith("snapshots/")}
        for sym in symbols_with_snapshots:
            s_path = subject_path(sym)
            if s_path not in records:
                raise StateError("Missing subject record")
            subject = records[s_path]
            snapshots = [v for p, v in records.items() if p.startswith(f"snapshots/tw/{sym}/")]
            if subject["latest_observation_id"] != max(snapshots, key=_order)["id"]:
                raise StateError("Latest observation reference mismatch")
            good = [v for v in snapshots if v["execution"]["legacy_complete"]]
            if subject["last_success_id"] != (max(good, key=_order)["id"] if good else None):
                raise StateError("Last-success reference mismatch")
            for key, status in (("pending_publication_id", "pending"), ("published_publication_id", "acked")):
                if subject[key] is not None and records[publication_path(subject[key], sym)]["status"] != status:
                    raise StateError("Subject publication status mismatch")
            for key, status in (("pending_notification_id", "pending"), ("published_notification_id", "acked")):
                if subject.get(key) is not None and records[notification_path(subject[key], sym)]["status"] != status:
                    raise StateError("Subject notification status mismatch")
            pending = subject["pending_publication_id"]
            if pending:
                item = records[publication_path(pending, sym)]
                if (item["snapshot_id"] != subject["latest_observation_id"] or
                        item["last_success_id"] != subject["last_success_id"]):
                    raise StateError("Pending publication is stale")
            identities = {v["issue_number"] for p, v in records.items()
                          if p.startswith((f"publications/tw/{sym}/", f"notifications/tw/{sym}/")) and v["issue_number"] is not None}
            if identities and identities != {subject["issue_number"]}:
                raise StateError("Conflicting fixed Issue identities")
    except (SnapshotError, KeyError, TypeError, ValueError, OverflowError) as error:
        raise StateError("Invalid research records") from error
    return records


def _order(snapshot):
    return utc(snapshot["observed_at_utc"]), snapshot["id"]


def _creation_attempted(subject):
    # v1 did not record intent. Absence is uncertainty, never permission to POST.
    return subject.get("creation_attempted", True) if subject else False


def body_hash(body):
    # Hash the exact external body, including newlines.
    import hashlib
    return hashlib.sha256(body.encode()).hexdigest()


def _render_v1(records, identifier, branch):
    pub_path = find_publication_path(records, identifier)
    item = records[pub_path]
    sym = item.get("symbol")
    if not sym:
        m = re.match(r"publications/tw/([^/]+)/", pub_path) if pub_path else None
        sym = m.group(1) if m else "2330.TW"
    latest = records.get(snapshot_path(item["snapshot_id"], sym)) or records.get(snapshot_path(item["snapshot_id"]))
    success = records.get(snapshot_path(item["last_success_id"], sym)) if item.get("last_success_id") else None
    if not success and item.get("last_success_id"):
        success = records.get(snapshot_path(item["last_success_id"]))
    def text(value):
        return escape(str(value)).replace("|", "&#124;").replace("[", "&#91;").replace("]", "&#93;")
    company_name = text(latest['issuer']['company_name'] or '未取得身分資料')
    title = "2330 台積電研究" if sym == "2330.TW" else f"{sym} {company_name}研究"
    lines = [marker(branch, sym), f"# {title}", "",
             f"最近嘗試：{latest['observed_at_utc']} — {latest['execution']['status']}",
             f"最近資料流程完成：{success['observed_at_utc'] if success else '尚無'}",
             "資料流程完成不代表財報、估值或買賣建議已完成。", "",
             f"[最近執行]({latest['run']['run_url']})；evaluation cutoff：{latest['evaluation_cutoff_utc']}"]
    if success:
        lines.append(f"[最近資料流程完成的執行]({success['run']['run_url']})")
    lines += ["", f"公司：{company_name}", "",
              "| 研究部分 | 狀態 |", "| --- | --- |"]
    lines += [f"| {key} | {latest['readiness'][key]} |" for key in READINESS]
    lines += ["", "月營收（TWSE 開放資料；原始期別／TWD_thousands）："]
    lines += [f"- {fact['period']}：{fact['value']:,}；出表日 {fact['reported_at'] or '未知'}；[來源]({fact['source']})"
              for fact in latest["monthly_revenue"]] or ["- 尚無允許保存的月營收證據。"]
    tech, events = latest["technical"], latest["events"]
    lines += ["", f"行情：{tech['status']}；session：{tech['session'] or '未知'}；freshness：{tech['freshness']}",
              f"官方事件：{events['status']}；snapshot：{events['snapshot_date'] or '未知'}；coverage：{events['coverage']}",
              "", "比較限制：" + ", ".join(latest["comparison_limits"]),
              "只保存允許公開的精簡證據；行情與事件僅留 metadata，未驗證歷史首次可知時間。",
              "Artifact 有保存期限且未保留完整輸入，不宣稱可完整 replay；尚未完成前後變化分析。", "",
              "來源："]
    lines += [f"- {link}" for link in latest["source_links"]]
    attribution = latest["attribution"]
    lines += ["", f"開放資料提供：{attribution['provider']}。"]
    lines += [f"- [{dataset['name']}]({dataset['catalog']})；上架年 {dataset['released_year']}；dataset version：{dataset['dataset_version']}"
              for dataset in attribution["datasets"]]
    lines += [f"以上開放資料依[政府資料開放授權條款第 {attribution['license_version']} 版]({attribution['license']}) 提供；使用須遵守該條款。"]
    lines += ["", f"snapshot `{latest['id']}`", f"publication `{identifier}`", ""]
    return "\n".join(lines)


def publication_comparison(records, identifier):
    pub_path = find_publication_path(records, identifier)
    item = records[pub_path]
    sym = item.get("symbol")
    if not sym:
        m = re.match(r"publications/tw/([^/]+)/", pub_path) if pub_path else None
        sym = m.group(1) if m else "2330.TW"
    refs = item["comparison"]
    previous = records.get(snapshot_path(refs["previous_snapshot_id"], sym)) if refs["previous_snapshot_id"] else None
    if not previous and refs["previous_snapshot_id"]:
        previous = records.get(snapshot_path(refs["previous_snapshot_id"]))
    current = records.get(snapshot_path(item["snapshot_id"], sym)) or records.get(snapshot_path(item["snapshot_id"]))
    good = {}
    for key, value in refs["last_good_snapshot_ids"].items():
        if value:
            cand = records.get(snapshot_path(value, sym)) or records.get(snapshot_path(value))
            if cand:
                good[key] = cand
    return compare_snapshots(previous, current, good)


def render_publication(records, identifier, branch):
    pub_path = find_publication_path(records, identifier)
    item = records[pub_path]
    sym = item.get("symbol")
    if not sym:
        m = re.match(r"publications/tw/([^/]+)/", pub_path) if pub_path else None
        sym = m.group(1) if m else "2330.TW"
    body = _render_v1(records, identifier, branch)
    if item["renderer_version"] == 1:
        return body
    delta = publication_comparison(records, identifier)
    snapshots = {value["id"]: value for path, value in records.items() if path.startswith(f"snapshots/tw/{sym}/")}
    latest = records.get(snapshot_path(item["snapshot_id"], sym)) or records.get(snapshot_path(item["snapshot_id"]))
    extra = ""
    if latest and "financial_research" in latest:
        extra = "\n" + "\n".join(render_tw_full_research_sections(latest["financial_research"])) + "\n"
    return body.replace("；尚未完成前後變化分析。", "。") + extra + "\n" + render_comparison(delta, snapshots)


def render_notification(records, identifier, branch):
    """Render a traceable GitHub Issue comment for a meaningful research change (TW14)."""
    notif_path = find_notification_path(records, identifier)
    item = records[notif_path]
    sym = item.get("symbol")
    if not sym:
        m = re.match(r"notifications/tw/([^/]+)/", notif_path) if notif_path else None
        sym = m.group(1) if m else "2330.TW"
    latest = records.get(snapshot_path(item["snapshot_id"], sym)) or records.get(snapshot_path(item["snapshot_id"]))
    refs = item["comparison"]
    previous = records.get(snapshot_path(refs["previous_snapshot_id"], sym)) if refs["previous_snapshot_id"] else None
    if not previous and refs["previous_snapshot_id"]:
        previous = records.get(snapshot_path(refs["previous_snapshot_id"]))
    good = {}
    for key, value in refs["last_good_snapshot_ids"].items():
        if value:
            cand = records.get(snapshot_path(value, sym)) or records.get(snapshot_path(value))
            if cand:
                good[key] = cand
    delta = compare_snapshots(previous, latest, good)
    snapshots = {value["id"]: value for path, value in records.items() if path.startswith(f"snapshots/tw/{sym}/")}
    company_name = latest['issuer']['company_name'] or ''
    title = "2330 台積電" if sym == "2330.TW" else f"{sym} {company_name}".strip()
    lines = [
        notification_marker(branch, identifier, sym),
        f"## {title}研究變更通知（自動對帳摘要）",
        "",
        f"- **觀測時間 (UTC)**：`{latest['observed_at_utc']}`｜**評估截止時間 (UTC)**：`{latest['evaluation_cutoff_utc']}`",
        f"- **執行紀錄**：[{latest['run']['run_id']}]({latest['run']['run_url']})｜**當次狀態**：`{latest['execution']['status']}`",
        f"- **對應 Snapshot**：`{latest['id']}`｜**前次 Snapshot**：`{delta['previous_snapshot_id'] or 'none'}`",
        f"- **對應固定報告 Publication**：`{item['publication_id']}`",
        "",
        render_comparison(delta, snapshots).strip(),
        "",
        "### 資料來源連結",
    ]
    lines += [f"- {link}" for link in latest["source_links"]]
    lines += [
        "",
        "> **研究限制與免責聲明**：本通知僅反映系統已觀測之公開研究輸入或來源涵蓋變化，**不構成任何買進、賣出、目標價、停損價或利多／利空方向性推論**。",
        "",
        f"notification `{identifier}`",
        "",
    ]
    return "\n".join(lines)


def _comparison_refs(records, latest, symbol=None):
    sym = symbol or latest["symbol"]
    older = [value for path, value in records.items()
             if path.startswith(f"snapshots/tw/{sym}/") and _order(value) < _order(latest)]
    previous = max(older, key=_order) if older else None
    good = {}
    for component in COMPONENTS:
        candidates = [value for value in older if available(value, component)]
        good[component] = max(candidates, key=_order)["id"] if candidates else None
    return {"previous_snapshot_id": previous["id"] if previous else None, "last_good_snapshot_ids": good}


def read(store=None):
    store = store or GitStateStore()
    state = store.read("research")
    if state["status"] != "available":
        raise StateError("Research namespace needs explicit initialization")
    validate_records(state["records"], store.branch)
    return state


def _commit(store, merge, **kwargs):
    before = store.main_head()
    checkout = store._git("rev-parse", "HEAD").stdout.strip()
    result = store.commit("research", merge, **kwargs)
    return {**result, "main_before": before, "main_after": store.main_head(),
            "checkout_before": checkout, "checkout_after": store._git("rev-parse", "HEAD").stdout.strip()}


def initialize(store=None):
    store = store or GitStateStore()
    return _commit(store, lambda records: validate_records(records, store.branch),
                   initialize=True, legacy_prefix="research")


def _extract_financial_version(snapshot):
    fr = snapshot.get("financial_research")
    if isinstance(fr, dict) and fr.get("reconciled_period_end"):
        return f"ifrs-{fr['reconciled_period_end']}"
    mr = snapshot.get("monthly_revenue") or []
    if mr and isinstance(mr[0], dict) and mr[0].get("period"):
        return f"mrev-{mr[0]['period']}"
    return None


def reconcile_rerun_triggers(store=None, *, symbol="2330.TW", canonical_event_ids=None, financial_version=None):
    """Compare canonical event/financial versions against the research consumption checkpoint (TW13).

    Never creates a second source baseline; stores only the research consumer offset
    and durable pending rerun work inside the `research` state namespace.
    """
    store = store or GitStateStore()
    c_path = checkpoint_path(symbol)
    s_path = subject_path(symbol)
    if canonical_event_ids is None:
        ev_state = store.read("events")
        if ev_state["status"] == "available":
            tw_rec = ev_state["records"].get(f"event_state/tw/{symbol}.json") or {}
            canonical_event_ids = list(tw_rec.get("seen_ids") or [])
        else:
            canonical_event_ids = []
    else:
        canonical_event_ids = list(canonical_event_ids)
    for eid in canonical_event_ids:
        if not isinstance(eid, str) or not re.fullmatch(EVENT_ID_RE, eid):
            raise StateError("Invalid canonical event identifier")
    if financial_version is not None and (not isinstance(financial_version, str) or not re.fullmatch(EVENT_ID_RE, financial_version)):
        raise StateError("Invalid financial version token")

    outcome = {}

    def merge(records):
        validate_records(records, store.branch)
        cp = records.get(c_path)
        subj = records.get(s_path)
        if cp is None:
            # First-time checkpoint initialization: adopt current canonical event IDs
            # as baseline without backfilling historical alerts.
            init_fin = financial_version
            if init_fin is None and subj and subj.get("last_success_id"):
                init_fin = _extract_financial_version(records[snapshot_path(subj["last_success_id"], symbol)])
            cp = {
                "schema_version": 1,
                "symbol": symbol,
                "consumed_event_ids": list(dict.fromkeys(canonical_event_ids))[-2000:],
                "consumed_financial_version": init_fin,
                "pending_rerun": None,
                "last_completed_snapshot_id": subj["last_success_id"] if subj else None,
            }
            records[c_path] = cp
            outcome.update(
                trigger_status="baseline_initialized",
                pending_rerun=None,
                new_event_ids=[],
            )
            return validate_records(records, store.branch)

        consumed_set = set(cp["consumed_event_ids"])
        prior_pending = cp.get("pending_rerun") or {}
        prior_triggers = list(prior_pending.get("trigger_event_ids") or [])
        unconsumed_events = [
            x for x in list(dict.fromkeys(prior_triggers + canonical_event_ids))
            if x not in consumed_set
        ]
        target_fin = financial_version if financial_version is not None else prior_pending.get("target_financial_version")
        fin_changed = bool(
            target_fin is not None and
            cp.get("consumed_financial_version") is not None and
            target_fin != cp.get("consumed_financial_version")
        )
        if cp.get("consumed_financial_version") is None and target_fin is not None and prior_pending.get("target_financial_version") is None:
            # Adopt initial financial version when previously unrecorded
            cp["consumed_financial_version"] = target_fin

        reasons = []
        if unconsumed_events:
            reasons.append("new_official_events")
        if fin_changed:
            reasons.append("financial_version_changed")

        if reasons:
            req_payload = {
                "symbol": symbol,
                "reasons": reasons,
                "trigger_event_ids": unconsumed_events,
                "target_financial_version": target_fin if fin_changed else None,
            }
            pending_obj = {
                "request_id": fingerprint(req_payload),
                "reasons": reasons,
                "trigger_event_ids": unconsumed_events,
                "target_financial_version": target_fin if fin_changed else None,
            }
            cp["pending_rerun"] = pending_obj
            outcome.update(
                trigger_status="rerun_pending",
                pending_rerun=pending_obj,
                new_event_ids=unconsumed_events,
            )
        else:
            cp["pending_rerun"] = None
            outcome.update(
                trigger_status="up_to_date",
                pending_rerun=None,
                new_event_ids=[],
            )
        records[c_path] = cp
        return validate_records(records, store.branch)

    commit_res = _commit(store, merge)
    return {**commit_res, **outcome}


def archive(snapshot, store=None, *, consumed_event_ids=None, consumed_financial_version=None):
    store = store or GitStateStore()
    validate_snapshot(snapshot)
    sym = snapshot["symbol"]
    s_path = subject_path(sym)
    c_path = checkpoint_path(sym)

    def merge(records):
        validate_records(records, store.branch)
        path = snapshot_path(snapshot["id"], sym)
        if path in records and records[path] != snapshot:
            raise StateError("Immutable snapshot conflict")
        records[path] = snapshot
        prior = records.get(s_path, {})
        snapshots = [v for p, v in records.items() if p.startswith(f"snapshots/tw/{sym}/")]
        latest = max(snapshots, key=_order)
        good = [v for v in snapshots if v["execution"]["legacy_complete"]]
        success = max(good, key=_order)["id"] if good else None
        comp_refs = _comparison_refs(records, latest, sym)
        item = {"schema_version": 2, "kind": "fixed_report", "renderer_version": 2,
                "symbol": sym, "snapshot_id": latest["id"], "last_success_id": success,
                "comparison": comp_refs}
        item["id"] = fingerprint(item)
        pubpath = publication_path(item["id"], sym)
        if pubpath not in records:
            if prior.get("pending_publication_id"):
                records[publication_path(prior["pending_publication_id"], sym)]["status"] = "superseded"
            records[pubpath] = {**item, "status": "pending", "issue_number": None, "body_sha256": ""}
            records[pubpath]["body_sha256"] = body_hash(render_publication(records, item["id"], store.branch))

        # Evaluate whether this snapshot produces a meaningful change notification (TW14)
        pending_notif_id = prior.get("pending_notification_id")
        published_notif_id = prior.get("published_notification_id")
        delta = publication_comparison(records, item["id"])
        if _meaningful_change(delta):
            notif_base = {
                "schema_version": 1,
                "kind": "change_notification",
                "renderer_version": 1,
                "symbol": sym,
                "publication_id": item["id"],
                "snapshot_id": latest["id"],
                "comparison": comp_refs,
            }
            notif_id = fingerprint(notif_base)
            npath = notification_path(notif_id, sym)
            if npath not in records:
                if pending_notif_id and pending_notif_id != notif_id:
                    old_npath = notification_path(pending_notif_id, sym)
                    if old_npath in records and records[old_npath]["status"] == "pending":
                        records[old_npath]["status"] = "superseded"
                records[npath] = {
                    **notif_base,
                    "id": notif_id,
                    "status": "pending",
                    "issue_number": None,
                    "comment_id": None,
                    "creation_attempted": False,
                    "body_sha256": "",
                }
                records[npath]["body_sha256"] = body_hash(render_notification(records, notif_id, store.branch))
            if records[npath]["status"] == "pending":
                pending_notif_id = notif_id
            elif records[npath]["status"] == "acked":
                published_notif_id = notif_id
                if pending_notif_id == notif_id:
                    pending_notif_id = None

        subj_obj = {
            "schema_version": 2,
            "symbol": sym,
            "latest_observation_id": latest["id"],
            "last_success_id": success,
            "pending_publication_id": item["id"] if records[pubpath]["status"] == "pending" else None,
            "published_publication_id": prior.get("published_publication_id"),
            "issue_number": prior.get("issue_number"),
            "creation_attempted": _creation_attempted(prior),
        }
        if pending_notif_id is not None or published_notif_id is not None or "pending_notification_id" in prior or "published_notification_id" in prior:
            subj_obj["pending_notification_id"] = pending_notif_id
            subj_obj["published_notification_id"] = published_notif_id
        records[s_path] = subj_obj

        # Advance research consumption checkpoint atomically ONLY when snapshot is complete (TW13)
        cp = records.get(c_path)
        if cp is not None and snapshot["execution"]["legacy_complete"] and latest["id"] == snapshot["id"]:
            pr = cp.get("pending_rerun") or {}
            add_events = list(consumed_event_ids or pr.get("trigger_event_ids") or [])
            merged_events = list(dict.fromkeys(cp["consumed_event_ids"] + add_events))[-2000:]
            new_fin = consumed_financial_version or pr.get("target_financial_version") or _extract_financial_version(snapshot) or cp.get("consumed_financial_version")
            cp["consumed_event_ids"] = merged_events
            cp["consumed_financial_version"] = new_fin
            cp["pending_rerun"] = None
            cp["last_completed_snapshot_id"] = snapshot["id"]
            records[c_path] = cp

        return validate_records(records, store.branch)
    return _commit(store, merge)


def publish(sink, store=None, symbol="2330.TW"):
    """Deliver the current outbox item, reconcile uncertain writes, then ACK.

    The workflow serializes publishers. Git retries protect ACK against newer
    archive commits; they cannot provide an exactly-once external transaction.
    """
    store = store or GitStateStore()
    state = read(store)
    records = state["records"]
    s_path = subject_path(symbol)
    subject = records.get(s_path)
    identifier = subject["pending_publication_id"] if subject else None
    receipt = {"schema_version": 1, "state_branch": store.branch,
               "read_state_commit": state["head"], "publication_id": identifier,
               "issue_number": subject["issue_number"] if subject else None}
    if not identifier:
        return {**receipt, "status": "already_current"}
    item = records[publication_path(identifier, symbol)]
    snapshot = records[snapshot_path(item["snapshot_id"], symbol)]
    if snapshot["run"]["repository"] != sink.repository:
        return {**receipt, "status": "blocked", "reason": "repository_mismatch"}
    body = render_publication(records, identifier, store.branch)
    owned_hashes = {v["body_sha256"] for p, v in records.items() if p.startswith(f"publications/tw/{symbol}/")}
    stable_marker = marker(store.branch, symbol)
    try:
        matches = sink.find(stable_marker)
        if len(matches) > 1:
            return {**receipt, "status": "blocked", "reason": "multiple_marker_matches"}
        known = subject["issue_number"]
        if known is not None:
            if len(matches) != 1 or matches[0]["number"] != known:
                return {**receipt, "status": "blocked", "reason": "known_issue_missing_or_marker_changed"}
            issue = sink.get(known)
        else:
            issue = matches[0] if matches else None
        if issue is not None:
            _issue(issue["number"])
            if (not issue["body"].startswith(stable_marker + "\n") or
                    body_hash(issue["body"]) not in owned_hashes or
                    issue["state"] != "open" or issue.get("locked", False)):
                return {**receipt, "status": "blocked", "reason": "external_issue_changed"}
            if issue["body"] != body:
                issue = sink.update(issue["number"], body)
        else:
            if _creation_attempted(subject):
                return {**receipt, "status": "outcome_unknown", "reason": "marker_not_visible_after_attempt"}
            # Reserve creation durably before the external side effect. A fresh
            # process must not infer "never created" from an eventually visible
            # Issue list, including after newer snapshots supersede this item.
            def reserve(current):
                validate_records(current, store.branch)
                owner = current[s_path]
                if owner["issue_number"] is not None or _creation_attempted(owner):
                    raise StateError("Creation was already attempted")
                if owner["pending_publication_id"] != identifier:
                    raise StateError("Publication changed before creation reservation")
                owner.update(schema_version=2, creation_attempted=True)
                return validate_records(current, store.branch)
            receipt["creation_intent_receipt"] = _commit(store, reserve)
            prefix = "[驗證] " if store.branch.endswith("-validation") else ""
            company_name = snapshot['issuer']['company_name'] or ""
            issue_title = prefix + (f"2330 台積電固定研究報告" if symbol == "2330.TW" else f"{symbol} {company_name}固定研究報告".strip())
            issue = sink.create(issue_title, body)
        number = issue["number"]
        _issue(number)
        if number is None or issue["body"] != body or known is not None and known != number:
            return {**receipt, "status": "outcome_unknown", "reason": "unexpected_delivery_response"}
    except Exception as error:
        # Never echo raw responses/tokens; a write may already have succeeded.
        return {**receipt, "status": "outcome_unknown", "reason": type(error).__name__}

    def ack(current):
        validate_records(current, store.branch)
        owner = current[s_path]
        if owner["issue_number"] not in (None, number):
            raise StateError("Fixed Issue identity conflict during ACK")
        delivered = current[publication_path(identifier, symbol)]
        if delivered["body_sha256"] != item["body_sha256"]:
            raise StateError("Publication changed during ACK")
        delivered.update(status="acked", issue_number=number)
        owner.update(schema_version=2, creation_attempted=True)
        owner["issue_number"] = number
        owner["published_publication_id"] = identifier
        if owner["pending_publication_id"] == identifier:
            owner["pending_publication_id"] = None
        return validate_records(current, store.branch)
    try:
        saved = _commit(store, ack)
    except StateError:
        return {**receipt, "status": "ack_pending", "issue_number": number,
                "reason": "state_ack_failed"}
    remaining = read(store)["records"][s_path]["pending_publication_id"]
    return {**receipt, "status": "pending_newer" if remaining else "published", "issue_number": number,
            "issue_url": f"https://github.com/{sink.repository}/issues/{number}",
            "ack_receipt": saved, "pending_publication_id": remaining}


def notify(sink, store=None, symbol="2330.TW"):
    """Deliver the current pending change notification comment to the fixed Issue, reconcile, then ACK (TW14)."""
    store = store or GitStateStore()
    state = read(store)
    records = state["records"]
    s_path = subject_path(symbol)
    subject = records.get(s_path)
    identifier = subject.get("pending_notification_id") if subject else None
    receipt = {
        "schema_version": 1,
        "state_branch": store.branch,
        "read_state_commit": state["head"],
        "notification_id": identifier,
        "issue_number": subject["issue_number"] if subject else None,
        "comment_id": None,
    }
    if not identifier:
        return {**receipt, "status": "already_current"}
    if subject.get("pending_publication_id") is not None:
        return {**receipt, "status": "blocked", "reason": "publication_not_yet_acked"}
    number = subject.get("issue_number")
    if number is None:
        return {**receipt, "status": "blocked", "reason": "missing_fixed_issue"}
    item = records[notification_path(identifier, symbol)]
    snapshot = records[snapshot_path(item["snapshot_id"], symbol)]
    if snapshot["run"]["repository"] != sink.repository:
        return {**receipt, "status": "blocked", "reason": "repository_mismatch"}
    body = render_notification(records, identifier, store.branch)
    stable_marker = marker(store.branch, symbol)
    owned_pub_hashes = {v["body_sha256"] for p, v in records.items() if p.startswith(f"publications/tw/{symbol}/")}
    n_marker = notification_marker(store.branch, identifier, symbol)
    try:
        issue = sink.get(number)
        _issue(issue["number"])
        if (not issue["body"].startswith(stable_marker + "\n") or
                body_hash(issue["body"]) not in owned_pub_hashes or
                issue["state"] != "open" or issue.get("locked", False)):
            return {**receipt, "status": "blocked", "reason": "external_issue_changed"}
        matches = sink.find_comments(number, n_marker)
        if len(matches) > 1:
            return {**receipt, "status": "blocked", "reason": "multiple_comment_marker_matches"}
        if matches:
            comment = matches[0]
            _issue(comment.get("id"))
            if body_hash(comment.get("body") or "") != item["body_sha256"]:
                return {**receipt, "status": "blocked", "reason": "external_comment_changed"}
        else:
            if item.get("creation_attempted"):
                return {**receipt, "status": "outcome_unknown", "reason": "comment_marker_not_visible_after_attempt"}
            def reserve_comment(current):
                validate_records(current, store.branch)
                owner = current[s_path]
                if owner.get("pending_notification_id") != identifier:
                    raise StateError("Notification changed before creation reservation")
                target = current[notification_path(identifier, symbol)]
                if target.get("creation_attempted"):
                    raise StateError("Notification creation was already attempted")
                target["creation_attempted"] = True
                return validate_records(current, store.branch)
            receipt["creation_intent_receipt"] = _commit(store, reserve_comment)
            comment = sink.create_comment(number, body)
        cid = comment.get("id")
        _issue(cid)
        if cid is None or comment.get("body") != body:
            return {**receipt, "status": "outcome_unknown", "reason": "unexpected_comment_response"}
    except Exception as error:
        return {**receipt, "status": "outcome_unknown", "reason": type(error).__name__}

    def ack_comment(current):
        validate_records(current, store.branch)
        owner = current[s_path]
        if owner["issue_number"] != number:
            raise StateError("Fixed Issue identity conflict during notification ACK")
        delivered = current[notification_path(identifier, symbol)]
        if delivered["body_sha256"] != item["body_sha256"]:
            raise StateError("Notification changed during ACK")
        delivered.update(status="acked", issue_number=number, comment_id=cid, creation_attempted=True)
        owner["published_notification_id"] = identifier
        if owner.get("pending_notification_id") == identifier:
            owner["pending_notification_id"] = None
        return validate_records(current, store.branch)
    try:
        saved = _commit(store, ack_comment)
    except StateError:
        return {**receipt, "status": "ack_pending", "issue_number": number, "comment_id": cid, "reason": "state_ack_failed"}
    remaining = read(store)["records"][s_path].get("pending_notification_id")
    return {
        **receipt,
        "status": "pending_newer" if remaining else "delivered",
        "issue_number": number,
        "comment_id": cid,
        "comment_url": f"https://github.com/{sink.repository}/issues/{number}#issuecomment-{cid}",
        "ack_receipt": saved,
        "pending_notification_id": remaining,
    }
