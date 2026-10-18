"""Official disclosure events for investment research; no headline sentiment.

SEC submission filings are *observed*, not upcoming earnings dates.
TWSE OpenAPI provides a current daily snapshot, NOT a historical archive.
Unknown coverage must never imply that no risk exists.
"""
from datetime import date, datetime, timezone, timedelta
from zoneinfo import ZoneInfo
import hashlib
import re

import httpx

TW_MATERIAL_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"
SEC_FORMS = {"10-K": "annual_report", "10-K/A": "amended_annual_report",
             "10-Q": "quarterly_report", "10-Q/A": "amended_quarterly_report",
             "8-K": "current_report", "8-K/A": "amended_current_report",
             "20-F": "annual_report", "6-K": "foreign_issuer_report"}
REVIEW_WINDOW_DAYS = 7
TW = ZoneInfo("Asia/Taipei")


def unknown(source, reason):
    return {"source": source, "status": "unavailable", "reason": reason, "events": [],
            "coverage": "not_verified", "upcoming_earnings": "not_verified"}


def _roc(value):
    raw = str(value).strip().replace("/", "").replace("-", "")
    if not re.fullmatch(r"[0-9]{7}", raw):
        raise ValueError("Invalid ROC date")
    return date(int(raw[:3]) + 1911, int(raw[3:5]), int(raw[5:7]))


def parse_tw_disclosures(payload, symbol, now):
    """Only the latest snapshot known by evaluation time. No historical replay."""
    if now.tzinfo is None:
        raise ValueError("Evaluation time must be timezone aware")
    if not isinstance(payload, list):
        return unknown(TW_MATERIAL_URL, "TWSE material-information payload is not a list")
    local = now.astimezone(TW)
    ticker = symbol.removesuffix(".TW")
    events, valid_snapshot_dates, malformed = [], [], 0
    for row in payload:
        if not isinstance(row, dict):
            malformed += 1
            continue
        try:
            snapshot = _roc(row["出表日期"])
            spoken = _roc(row["發言日期"])
            clock = str(row["發言時間"]).strip().zfill(6)
            if not re.fullmatch(r"[0-9]{6}", clock):
                raise ValueError("Invalid speech time")
            published = datetime(spoken.year, spoken.month, spoken.day,
                                 int(clock[:2]), int(clock[2:4]), int(clock[4:6]),
                                 tzinfo=TW)
            if snapshot > local.date() or published > local:
                continue  # Information not yet known at requested evaluation time
            valid_snapshot_dates.append(snapshot)
        except (ValueError, KeyError, TypeError, OverflowError):
            malformed += 1
            continue
        if str(row.get("公司代號") or "").strip() != ticker:
            continue
        subject = str(row.get("主旨 ") or row.get("主旨") or "").strip()
        if not subject:
            malformed += 1
            continue
        key = "|".join((ticker, published.isoformat(), subject))
        events.append({
            "event_id": "tw-material-" + hashlib.sha256(key.encode()).hexdigest()[:20],
            "kind": "material_disclosure", "form": None,
            "title": subject[:240], "published_at": published.isoformat(),
            "event_date": str(row.get("事實發生日") or "")[:14],
            "source": TW_MATERIAL_URL, "status": "observed",
            "interpretation": "Unclassified official disclosure; contents not scored as positive/negative",
        })
    if not valid_snapshot_dates:
        return unknown(TW_MATERIAL_URL, "No verifiable publication timestamps in current TWSE snapshot")
    latest = max(valid_snapshot_dates)
    if (local.date() - latest).days > 2:
        return unknown(TW_MATERIAL_URL, "TWSE daily snapshot too old for current event assessment")
    # If any rows fail to parse, coverage cannot be considered complete.
    result = {
        "source": TW_MATERIAL_URL, "status": "partial" if malformed else "available",
        "reason": "Some published rows could not be parsed" if malformed else None,
        "coverage": "recent_daily_snapshot_only_not_a_full_history",
        "snapshot_date": latest.isoformat(), "upcoming_earnings": "not_verified",
        "events": sorted({e["event_id"]: e for e in events}.values(),
                         key=lambda x: x["published_at"], reverse=True)[:20],
    }
    return result


def tw_material_events(symbol, now, get):
    if not re.fullmatch(r"[0-9]{4,6}\.TW", symbol):
        raise ValueError("TWSE listed company symbol required")
    if now.tzinfo is None:
        raise ValueError("Evaluation time must be timezone aware")
    # A current daily endpoint cannot reconstruct what was known historically.
    if abs((datetime.now(timezone.utc) - now.astimezone(timezone.utc)).total_seconds()) > 86400:
        return unknown(TW_MATERIAL_URL, "Historical TWSE material-event snapshots cannot be reconstructed")
    try:
        return parse_tw_disclosures(get(TW_MATERIAL_URL), symbol, now)
    except (httpx.HTTPError, ValueError, TypeError, KeyError, OSError) as exc:
        return unknown(TW_MATERIAL_URL, "TWSE events unavailable: " + type(exc).__name__)


def sec_filing_events(submissions, now, source, max_events=20):
    """Recent SEC submissions; same-day rows need a parseable acceptance timestamp."""
    if now.tzinfo is None:
        raise ValueError("Evaluation time must be timezone aware")
    try:
        recent = submissions["filings"]["recent"]
        forms, filed, accessions = (recent[k] for k in
                                     ("form", "filingDate", "accessionNumber"))
        accepted = recent.get("acceptanceDateTime", [])
        if not all(isinstance(v, list) for v in (forms, filed, accessions, accepted)):
            raise TypeError("Unexpected SEC filing columns")
        if len({len(forms), len(filed), len(accessions)}) != 1:
            raise ValueError("Inconsistent SEC filing metadata lengths")
    except (KeyError, TypeError, ValueError):
        return unknown(source, "SEC filing metadata columns are unavailable or inconsistent")
    events, invalid = [], 0
    floor = now.astimezone(timezone.utc) - timedelta(days=120)
    for i, form in enumerate(forms):
        if form not in SEC_FORMS:
            continue
        try:
            day = date.fromisoformat(filed[i])
            if day >= now.astimezone(timezone.utc).date() or day < floor.date():
                # SEC submissions acceptanceDateTime is not reliably UTC for
                # intraday ordering. Block same-UTC-day filings until verified.
                continue
                continue
            timestamp = accepted[i] if i < len(accepted) else None
            published = None
            if isinstance(timestamp, str):
                try:
                    published = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
                except ValueError:
                    pass
            if published is not None and published.tzinfo is not None:
                if published.astimezone(timezone.utc) > now.astimezone(timezone.utc):
                    continue
            # Older filing dates are safe to treat as past-day metadata.
            # Do not use acceptanceDateTime to determine intraday ordering.
            accession = accessions[i]
            if not re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", accession):
                raise ValueError("Invalid SEC accession")
            events.append({
                "event_id": "sec-" + accession, "kind": SEC_FORMS[form],
                "form": form, "title": "SEC Form " + form + " filed",
                "published_at": (published.astimezone(timezone.utc).isoformat()
                                 if published and published.tzinfo else None),
                "filed_date": day.isoformat(), "accession": accession,
                "source": source, "status": "observed",
                "interpretation": "Filing metadata only; no earnings surprise or directional inference",
            })
        except (ValueError, TypeError, IndexError):
            invalid += 1
    return {
        "source": source, "status": "partial" if invalid else "available",
        "reason": "Some SEC filing rows could not be parsed" if invalid else None,
        "coverage": "recent_SEC_submissions_metadata_only",
        "upcoming_earnings": "not_verified", "events": events[:max_events],
    }


def evaluate_events(feed, now):
    """Recent disclosures request review, never a directional recommendation."""
    if now.tzinfo is None:
        raise ValueError("Evaluation time must be timezone aware")
    recent = []
    for e in feed.get("events", []):
        try:
            when = (datetime.fromisoformat(e["published_at"]) if e.get("published_at")
                    else datetime.fromisoformat(e["filed_date"] + "T00:00:00+00:00"))
            if when.tzinfo is None:
                continue
            days = (now.astimezone(timezone.utc) - when.astimezone(timezone.utc)).total_seconds() / 86400
            if 0 <= days <= REVIEW_WINDOW_DAYS:
                recent.append(e)
        except (ValueError, KeyError, TypeError):
            continue
    coverage = feed.get("status") or "unavailable"
    return {
        "status": ("manual_review_required" if recent else
                   "coverage_incomplete" if coverage != "available" else
                   "no_recent_observed_events"),
        "source_status": coverage,
        "review_required": bool(recent),
        "recent_event_ids": [e["event_id"] for e in recent],
        "event_count": len(feed.get("events", [])),
        "upcoming_earnings": "not_verified",
        "trade_recommendation_allowed": False,
        "reason": ("Recent official disclosures need content and financial-impact review"
                   if recent else "Event coverage is incomplete, not evidence of no risk"
                   if coverage != "available" else
                   "No qualifying recent observed disclosures in the limited source window"),
    }


def render_events(feed, risk):
    lines = ["", "## Official filings and event risks", "",
             f"Event coverage: **{feed['status']}** ({feed['coverage']})",
             f"Research risk: **{risk['status']}**",
             risk["reason"],
             "**Upcoming earnings date: not verified** (never inferred from prior filing dates).",
             ""]
    if feed.get("reason"):
        lines.append("Source limitation: " + feed["reason"])
    if feed.get("events"):
        lines += ["| Published / filed | Disclosure | Original source |",
                  "| --- | --- | --- |"]
        for event in feed["events"][:10]:
            when = event.get("published_at") or event.get("filed_date")
            title = str(event.get("title") or "").replace("|", "/").replace("\n", " ")[:160]
            lines.append(f"| {when} | {title} | {event['source']} |")
    else:
        lines.append("No official events verifiably observed in this available snapshot; absence is not evidence of safety.")
    lines += ["", "No automatic bullish/bearish classification or price target is inferred from a filing headline."]
    return lines
