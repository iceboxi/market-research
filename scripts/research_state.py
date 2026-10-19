"""Single research owner: compact snapshots, publication outbox and ACK.

All Git I/O stays in GitStateStore. External delivery is injected at publish().
"""
from html import escape
import re

from market_research.research_snapshot import (
    READINESS, SnapshotError, encoded, fingerprint, utc, validate_snapshot,
)
from scripts.state_store import GitStateStore, StateError

MAX_RECORDS = 2000
MAX_NAMESPACE_BYTES = 5_000_000
SUBJECT = "subjects/tw/2330.TW.json"
HASH = r"[a-f0-9]{64}"


def marker(branch):
    if branch not in ("research-state", "research-state-validation"):
        raise StateError("Invalid publication branch")
    return f"<!-- market-research:fixed-report:{branch}:tw:2330.TW -->"


def snapshot_path(identifier):
    return f"snapshots/tw/2330.TW/{identifier}.json"


def publication_path(identifier):
    return f"publications/tw/2330.TW/{identifier}.json"


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
    return {k: value[k] for k in ("schema_version", "kind", "renderer_version", "symbol",
                                  "snapshot_id", "last_success_id")}


def validate_records(records, branch):
    if not isinstance(records, dict) or len(records) > MAX_RECORDS:
        raise StateError("Research record budget exceeded")
    try:
        if len(encoded(records)) > MAX_NAMESPACE_BYTES:
            raise StateError("Research namespace byte budget exceeded")
        for path, value in records.items():
            if re.fullmatch(r"snapshots/tw/2330\.TW/" + HASH + r"\.json", path):
                validate_snapshot(value)
                if path != snapshot_path(value["id"]) or value["symbol"] != "2330.TW":
                    raise StateError("Snapshot identity/path mismatch")
            elif re.fullmatch(r"publications/tw/2330\.TW/" + HASH + r"\.json", path):
                _fields(value, "schema_version id kind renderer_version symbol snapshot_id last_success_id "
                        "status issue_number body_sha256")
                if (type(value["schema_version"]) is not int or value["schema_version"] != 1 or
                        type(value["renderer_version"]) is not int or value["renderer_version"] != 1 or
                        value["kind"] != "fixed_report" or value["symbol"] != "2330.TW" or
                        value["status"] not in ("pending", "acked", "superseded")):
                    raise StateError("Invalid publication schema")
                _id(value["snapshot_id"])
                _id(value["last_success_id"], nullable=True)
                _id(value["body_sha256"])
                _issue(value["issue_number"])
                if (value["id"] != fingerprint(_publication_identity(value)) or
                        path != publication_path(value["id"])):
                    raise StateError("Publication identity mismatch")
            elif path == SUBJECT:
                keys = "schema_version symbol latest_observation_id last_success_id pending_publication_id published_publication_id issue_number"
                if isinstance(value, dict) and value.get("schema_version") == 2:
                    keys += " creation_attempted"
                    if type(value.get("creation_attempted")) is not bool:
                        raise StateError("Invalid creation attempt fence")
                _fields(value, keys)
                if type(value["schema_version"]) is not int or value["schema_version"] not in (1, 2) or value["symbol"] != "2330.TW":
                    raise StateError("Invalid subject schema")
                for key in ("latest_observation_id", "last_success_id", "pending_publication_id", "published_publication_id"):
                    _id(value[key], nullable=key != "latest_observation_id")
                _issue(value["issue_number"])
            else:
                raise StateError("Unapproved research path")
        for path, value in records.items():
            if path.startswith("publications/"):
                if (snapshot_path(value["snapshot_id"]) not in records or
                        value["last_success_id"] is not None and snapshot_path(value["last_success_id"]) not in records):
                    raise StateError("Missing publication snapshot")
                if value["body_sha256"] != body_hash(render_publication(records, value["id"], branch)):
                    raise StateError("Publication body checksum mismatch")
                if value["status"] == "acked" and value["issue_number"] is None:
                    raise StateError("Publication ACK lacks Issue identity")
        if records:
            subject = records[SUBJECT]
            snapshots = [v for p, v in records.items() if p.startswith("snapshots/")]
            if subject["latest_observation_id"] != max(snapshots, key=_order)["id"]:
                raise StateError("Latest observation reference mismatch")
            good = [v for v in snapshots if v["execution"]["legacy_complete"]]
            if subject["last_success_id"] != (max(good, key=_order)["id"] if good else None):
                raise StateError("Last-success reference mismatch")
            for key, status in (("pending_publication_id", "pending"), ("published_publication_id", "acked")):
                if subject[key] is not None and records[publication_path(subject[key])]["status"] != status:
                    raise StateError("Subject publication status mismatch")
            pending = subject["pending_publication_id"]
            if pending:
                item = records[publication_path(pending)]
                if (item["snapshot_id"] != subject["latest_observation_id"] or
                        item["last_success_id"] != subject["last_success_id"]):
                    raise StateError("Pending publication is stale")
            identities = {v["issue_number"] for p, v in records.items()
                          if p.startswith("publications/") and v["issue_number"] is not None}
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


def render_publication(records, identifier, branch):
    item = records[publication_path(identifier)]
    latest = records[snapshot_path(item["snapshot_id"])]
    success = records[snapshot_path(item["last_success_id"])] if item["last_success_id"] else None
    def text(value):
        return escape(str(value)).replace("|", "&#124;").replace("[", "&#91;").replace("]", "&#93;")
    lines = [marker(branch), "# 2330 台積電研究", "",
             f"最近嘗試：{latest['observed_at_utc']} — {latest['execution']['status']}",
             f"最近資料流程完成：{success['observed_at_utc'] if success else '尚無'}",
             "資料流程完成不代表財報、估值或買賣建議已完成。", "",
             f"[最近執行]({latest['run']['run_url']})；evaluation cutoff：{latest['evaluation_cutoff_utc']}"]
    if success:
        lines.append(f"[最近資料流程完成的執行]({success['run']['run_url']})")
    lines += ["", f"公司：{text(latest['issuer']['company_name'] or '未取得身分資料')}", "",
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


def archive(snapshot, store=None):
    store = store or GitStateStore()
    validate_snapshot(snapshot)
    if snapshot["symbol"] != "2330.TW":
        raise StateError("Only the first 2330 milestone is enabled")
    def merge(records):
        validate_records(records, store.branch)
        path = snapshot_path(snapshot["id"])
        if path in records and records[path] != snapshot:
            raise StateError("Immutable snapshot conflict")
        records[path] = snapshot
        prior = records.get(SUBJECT, {})
        snapshots = [v for p, v in records.items() if p.startswith("snapshots/")]
        latest = max(snapshots, key=_order)
        good = [v for v in snapshots if v["execution"]["legacy_complete"]]
        success = max(good, key=_order)["id"] if good else None
        item = {"schema_version": 1, "kind": "fixed_report", "renderer_version": 1,
                "symbol": "2330.TW", "snapshot_id": latest["id"], "last_success_id": success}
        item["id"] = fingerprint(item)
        pubpath = publication_path(item["id"])
        if pubpath not in records:
            if prior.get("pending_publication_id"):
                records[publication_path(prior["pending_publication_id"])]["status"] = "superseded"
            records[pubpath] = {**item, "status": "pending", "issue_number": None, "body_sha256": ""}
            records[pubpath]["body_sha256"] = body_hash(render_publication(records, item["id"], store.branch))
        records[SUBJECT] = {"schema_version": 2, "symbol": "2330.TW",
                            "latest_observation_id": latest["id"], "last_success_id": success,
                            "pending_publication_id": item["id"] if records[pubpath]["status"] == "pending" else None,
                            "published_publication_id": prior.get("published_publication_id"),
                            "issue_number": prior.get("issue_number"),
                            "creation_attempted": _creation_attempted(prior)}
        return validate_records(records, store.branch)
    return _commit(store, merge)


def publish(sink, store=None):
    """Deliver the current outbox item, reconcile uncertain writes, then ACK.

    The workflow serializes publishers. Git retries protect ACK against newer
    archive commits; they cannot provide an exactly-once external transaction.
    """
    store = store or GitStateStore()
    state = read(store)
    records = state["records"]
    subject = records.get(SUBJECT)
    identifier = subject["pending_publication_id"] if subject else None
    receipt = {"schema_version": 1, "state_branch": store.branch,
               "read_state_commit": state["head"], "publication_id": identifier,
               "issue_number": subject["issue_number"] if subject else None}
    if not identifier:
        return {**receipt, "status": "already_current"}
    item = records[publication_path(identifier)]
    snapshot = records[snapshot_path(item["snapshot_id"])]
    if snapshot["run"]["repository"] != sink.repository:
        return {**receipt, "status": "blocked", "reason": "repository_mismatch"}
    body = render_publication(records, identifier, store.branch)
    owned_hashes = {v["body_sha256"] for p, v in records.items() if p.startswith("publications/")}
    stable_marker = marker(store.branch)
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
                owner = current[SUBJECT]
                if owner["issue_number"] is not None or _creation_attempted(owner):
                    raise StateError("Creation was already attempted")
                if owner["pending_publication_id"] != identifier:
                    raise StateError("Publication changed before creation reservation")
                owner.update(schema_version=2, creation_attempted=True)
                return validate_records(current, store.branch)
            receipt["creation_intent_receipt"] = _commit(store, reserve)
            prefix = "[驗證] " if store.branch.endswith("-validation") else ""
            issue = sink.create(prefix + "2330 台積電固定研究報告", body)
        number = issue["number"]
        _issue(number)
        if number is None or issue["body"] != body or known is not None and known != number:
            return {**receipt, "status": "outcome_unknown", "reason": "unexpected_delivery_response"}
    except Exception as error:
        # Never echo raw responses/tokens; a write may already have succeeded.
        return {**receipt, "status": "outcome_unknown", "reason": type(error).__name__}

    def ack(current):
        validate_records(current, store.branch)
        owner = current[SUBJECT]
        if owner["issue_number"] not in (None, number):
            raise StateError("Fixed Issue identity conflict during ACK")
        delivered = current[publication_path(identifier)]
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
    remaining = read(store)["records"][SUBJECT]["pending_publication_id"]
    return {**receipt, "status": "pending_newer" if remaining else "published", "issue_number": number,
            "issue_url": f"https://github.com/{sink.repository}/issues/{number}",
            "ack_receipt": saved, "pending_publication_id": remaining}
