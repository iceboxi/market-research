"""Compact public research evidence, with an explicit per-source retention policy."""
from datetime import date, datetime, timezone
import hashlib
import json
import math
import re
from urllib.parse import urlsplit, urlunsplit
from zoneinfo import ZoneInfo

from .fundamentals import TW_PROFILE, TW_REVENUE, tw_report_date

MAX_SNAPSHOT_BYTES = 20_000
READINESS = ("instrument", "source_evidence", "valuation_provenance", "financial",
             "technical", "valuation", "events", "trade_plan", "recommendation")
LIMITS = {"prices_metadata_only", "events_metadata_only", "artifact_inputs_not_retained",
          "unapproved_numeric_evidence_omitted", "future_period_evidence_omitted",
          "invalid_or_future_profile_omitted"}
ATTRIBUTION = {
    "provider": "金融監督管理委員會證券期貨局（證交所資料）",
    "datasets": [
        {"name": "上市公司基本資料", "catalog": "https://data.gov.tw/dataset/18419",
         "released_year": 2015, "dataset_version": "not_specified"},
        {"name": "上市公司每月營業收入彙總表", "catalog": "https://data.gov.tw/dataset/18420",
         "released_year": 2015, "dataset_version": "not_specified"},
    ],
    "license": "https://data.gov.tw/license", "license_version": "1.0",
}


class SnapshotError(ValueError):
    pass


def encoded(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                      separators=(",", ":")).encode()


def fingerprint(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def utc(value):
    try:
        result = datetime.fromisoformat(value)
        if result.tzinfo is None:
            raise ValueError("missing timezone")
        return result.astimezone(timezone.utc)
    except (TypeError, ValueError) as error:
        raise SnapshotError("Research timestamps need a timezone") from error


def _keys(value, expected):
    if not isinstance(value, dict) or set(value) != set(expected.split()):
        raise SnapshotError("Unexpected research fields")


def _text(value, maximum=160, nullable=False):
    if nullable and value is None:
        return
    if (not isinstance(value, str) or not 0 < len(value) <= maximum or
            any(ord(c) < 32 for c in value)):
        raise SnapshotError("Invalid bounded research text")


def _code(value):
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_:-]{1,100}", value):
        raise SnapshotError("Invalid research status/identifier")


def public_url(value):
    if not isinstance(value, str) or len(value) > 600 or any(ord(c) < 33 for c in value):
        return None
    try:
        parts = urlsplit(value)
        if (parts.scheme != "https" or not parts.hostname or parts.username or parts.password or
                parts.port not in (None, 443)):
            return None
        return urlunsplit(("https", parts.netloc, parts.path or "/", "", ""))
    except ValueError:
        return None


def _month(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{3,4}(0[1-9]|1[0-2])", value):
        raise SnapshotError("Invalid original ROC month")
    return int(value[:-2]) + 1911, int(value[-2:])


def _reported_date(value):
    try:
        return tw_report_date(value)
    except ValueError as error:
        raise SnapshotError("Invalid original report date") from error


def validate_snapshot(value):
    fields = "schema_version id symbol market evaluation_cutoff_utc observed_at_utc run execution issuer monthly_revenue technical events readiness source_links comparison_limits availability attribution"
    if isinstance(value, dict) and value.get("schema_version") == 2:
        fields += " started_at_utc"
        if "model_identity" in value:
            fields += " model_identity"
        if "financial_research" in value:
            fields += " financial_research"
    _keys(value, fields)
    if type(value["schema_version"]) is not int or value["schema_version"] not in (1, 2):
        raise SnapshotError("Unsupported research snapshot schema")
    if value["market"] != "tw" or not re.fullmatch(r"[0-9]{4,6}\.TW", str(value["symbol"])):
        raise SnapshotError("Only TWSE-listed research snapshots are supported")
    cutoff, observed = utc(value["evaluation_cutoff_utc"]), utc(value["observed_at_utc"])
    if observed < cutoff:
        raise SnapshotError("Observation precedes evaluation cutoff")
    if value["schema_version"] == 2 and utc(value["started_at_utc"]) > observed:
        raise SnapshotError("Execution start is after observation")
    if "model_identity" in value and (not isinstance(value["model_identity"], str) or
                                      not re.fullmatch(r"[a-f0-9]{64}", value["model_identity"])):
        raise SnapshotError("Invalid model/config identity")
    if "financial_research" in value:
        fr = value["financial_research"]
        if (not isinstance(fr, dict) or fr.get("schema_version") != 1 or
                fr.get("status") != "available" or fr.get("currency") != "TWD" or
                type(fr.get("reconciled_twse_openapi")) is not bool or
                not isinstance(fr.get("annual_summary"), list) or len(fr["annual_summary"]) > 6 or
                not isinstance(fr.get("quarterly_summary"), list) or len(fr["quarterly_summary"]) > 8):
            raise SnapshotError("Invalid financial_research snapshot section")
    run = value["run"]
    _keys(run, "repository run_id run_attempt code_sha run_url")
    if (not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(run["repository"])) or
            not re.fullmatch(r"[0-9]{1,20}", str(run["run_id"])) or
            type(run["run_attempt"]) is not int or not 1 <= run["run_attempt"] <= 1000 or
            not re.fullmatch(r"[a-f0-9]{40,64}", str(run["code_sha"])) or
            run["run_url"] != f"https://github.com/{run['repository']}/actions/runs/{run['run_id']}"):
        raise SnapshotError("Invalid research run identity")
    _keys(value["execution"], "status legacy_complete")
    if (type(value["execution"]["legacy_complete"]) is not bool or
            value["execution"]["status"] != ("completed" if value["execution"]["legacy_complete"] else "partial")):
        raise SnapshotError("Invalid pipeline outcome")
    issuer = value["issuer"]
    _keys(issuer, "company_name source reported_at policy")
    _text(issuer["company_name"], nullable=True)
    if (issuer["policy"] not in ("twse_profile_ogdl_v1", "metadata_only") or
            issuer["policy"] == "twse_profile_ogdl_v1" and issuer["source"] != TW_PROFILE or
            issuer["policy"] == "metadata_only" and issuer["company_name"] is not None):
        raise SnapshotError("Issuer retention policy mismatch")
    profile_date = _reported_date(issuer["reported_at"])
    if profile_date and profile_date > cutoff.astimezone(ZoneInfo("Asia/Taipei")).date():
        raise SnapshotError("Future profile report date")
    facts = value["monthly_revenue"]
    if not isinstance(facts, list) or len(facts) > 12:
        raise SnapshotError("Monthly evidence exceeds budget")
    seen = set()
    for fact in facts:
        _keys(fact, "metric value unit period reported_at source policy")
        if (fact["metric"] != "monthly_reported_revenue" or fact["unit"] != "TWD_thousands" or
                fact["source"] != TW_REVENUE or fact["policy"] != "twse_monthly_ogdl_v1" or
                type(fact["value"]) not in (int, float) or not math.isfinite(fact["value"]) or
                abs(fact["value"]) > 1e18):
            raise SnapshotError("Unapproved numeric research evidence")
        normalized_period = _month(fact["period"])
        if normalized_period > (cutoff.year, cutoff.month) or normalized_period in seen:
            raise SnapshotError("Future or duplicate revenue period")
        seen.add(normalized_period)
        announced = _reported_date(fact["reported_at"])
        if announced and announced > cutoff.astimezone(ZoneInfo("Asia/Taipei")).date():
            raise SnapshotError("Future revenue announcement")
    technical = value["technical"]
    _keys(technical, "status source session freshness price_basis input_sha256")
    for key in ("status", "freshness"):
        _code(technical[key])
    for key in ("source", "price_basis"):
        if technical[key] is not None:
            _code(technical[key])
    if technical["session"] is not None:
        try:
            if date.fromisoformat(technical["session"]) > cutoff.date():
                raise ValueError("future session")
        except (ValueError, TypeError) as error:
            raise SnapshotError("Invalid technical session") from error
    if technical["input_sha256"] is not None and not re.fullmatch(r"[a-f0-9]{64}", str(technical["input_sha256"])):
        raise SnapshotError("Invalid input checksum")
    _keys(value["events"], "status source snapshot_date coverage")
    _code(value["events"]["status"])
    _code(value["events"]["coverage"])
    if value["events"]["snapshot_date"] is not None:
        try:
            date.fromisoformat(value["events"]["snapshot_date"])
        except (TypeError, ValueError) as error:
            raise SnapshotError("Invalid event source date") from error
    _keys(value["readiness"], " ".join(READINESS))
    for state in value["readiness"].values():
        _code(state)
    if not isinstance(value["source_links"], list) or len(value["source_links"]) > 20:
        raise SnapshotError("Source reference budget exceeded")
    for link in value["source_links"] + [issuer["source"], value["events"]["source"]]:
        if link is not None and public_url(link) != link:
            raise SnapshotError("Unsafe source reference")
    limits = value["comparison_limits"]
    if not isinstance(limits, list) or any(item not in LIMITS for item in limits) or len(limits) > len(LIMITS):
        raise SnapshotError("Unrecognized comparison limits")
    if value["availability"] != "first_seen_only_historical_not_verified":
        raise SnapshotError("Unsupported availability claim")
    if value["attribution"] != ATTRIBUTION:
        raise SnapshotError("Missing or changed source attribution")
    try:
        if len(encoded(value)) > MAX_SNAPSHOT_BYTES:
            raise SnapshotError("Research snapshot exceeds size budget")
        expected = fingerprint({k: v for k, v in value.items() if k != "id"})
    except (ValueError, TypeError, OverflowError) as error:
        raise SnapshotError("Invalid research JSON") from error
    if value["id"] != expected:
        raise SnapshotError("Research snapshot checksum mismatch")
    return value


def prepare_snapshot(report, run):
    if report.get("schema_version") != 4:
        raise SnapshotError("Expected a v4 company report")
    observed = run["observed_at_utc"]
    identity = {key: run[key] for key in ("repository", "run_id", "run_attempt", "code_sha")}
    identity["run_url"] = f"https://github.com/{run['repository']}/actions/runs/{run['run_id']}"
    issuer, tech, feed = report["issuer"], report["technical"], report["official_events"]
    profile = issuer["profile"]
    permitted = profile.get("source") == TW_PROFILE
    links = {public_url(profile.get("source")), public_url(feed.get("source"))}
    limits = {"prices_metadata_only", "events_metadata_only", "artifact_inputs_not_retained"}
    facts = []
    cutoff = utc(report["generated_utc"])
    try:
        profile_date = _reported_date(profile.get("reported_at"))
        if profile_date and profile_date > cutoff.astimezone(ZoneInfo("Asia/Taipei")).date():
            raise SnapshotError("Future profile report date")
    except SnapshotError:
        permitted = False
        limits.add("invalid_or_future_profile_omitted")
    for fact in issuer.get("facts", []):
        links.add(public_url(fact.get("source")))
        if fact.get("source") == TW_REVENUE and fact.get("metric") == "monthly_reported_revenue":
            announced = _reported_date(fact.get("reported_at"))
            if (_month(fact["period"]) > (cutoff.year, cutoff.month) or
                    announced and announced > cutoff.astimezone(ZoneInfo("Asia/Taipei")).date()):
                limits.add("future_period_evidence_omitted")
                continue
            facts.append({key: fact.get(key) for key in ("metric", "value", "unit", "period", "reported_at", "source")}
                         | {"policy": "twse_monthly_ogdl_v1"})
        else:
            limits.add("unapproved_numeric_evidence_omitted")
    stale = any(w.get("reason") == "stale_history_allowed_for_research" for w in tech.get("warnings", []))
    snapshot = {"schema_version": 1, "symbol": report["symbol"], "market": report["market"],
                "evaluation_cutoff_utc": report["generated_utc"], "observed_at_utc": observed,
                "run": identity, "execution": {"status": "completed" if report["complete"] else "partial",
                                                 "legacy_complete": report["complete"]},
                "issuer": {"company_name": issuer.get("company_name") if permitted else None,
                           "source": public_url(profile.get("source")), "reported_at": profile.get("reported_at") if permitted else None,
                           "policy": "twse_profile_ogdl_v1" if permitted else "metadata_only"},
                "monthly_revenue": facts,
                "technical": {"status": tech["status"], "source": tech.get("source"), "session": tech.get("last_session"),
                              "freshness": "stale" if stale else "current" if tech["status"] == "available" else "unknown",
                              "price_basis": tech.get("price_basis"), "input_sha256": tech.get("input_sha256")},
                "events": {"status": feed["status"], "source": public_url(feed.get("source")),
                           "snapshot_date": feed.get("snapshot_date"), "coverage": feed.get("coverage", "unknown")},
                "readiness": {key: report["research_readiness"]["components"].get(key, {}).get("status", "not_evaluated")
                              for key in READINESS},
                "source_links": sorted(link for link in links if link), "comparison_limits": sorted(limits),
                "availability": "first_seen_only_historical_not_verified",
                "attribution": json.loads(encoded(ATTRIBUTION))}
    if "invalid_or_future_profile_omitted" in limits:
        snapshot["readiness"]["instrument"] = "unknown"
        snapshot["readiness"]["source_evidence"] = "not_evaluated"
    if "started_utc" in report:
        snapshot.update(schema_version=2, started_at_utc=report["started_utc"])
        if "model_identity" in report:
            snapshot["model_identity"] = report["model_identity"]
        if (permitted and isinstance(report.get("financial_research"), dict) and
                report["financial_research"].get("status") == "available"):
            snapshot["financial_research"] = json.loads(encoded(report["financial_research"]))
    snapshot["id"] = fingerprint(snapshot)
    return validate_snapshot(snapshot)
