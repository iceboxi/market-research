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
TW_SHAREHOLDER_ANNOUNCE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap38_L"
TW_SHAREHOLDER_MEETING_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap41_L"
TW_DIVIDEND_SCHEDULE_URL = "https://openapi.twse.com.tw/v1/opendata/t187ap45_L"
FINMIND_NEWS_DATASET = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockNews"
CALENDAR_EVENT_TYPES = (
    "investor_conference",
    "earnings_release",
    "board_meeting",
    "shareholder_meeting",
    "statutory_filing_deadline",
)
CONFIRMATION_STATUSES = ("confirmed", "tentative", "revised", "cancelled", "unknown")
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


def normalize_headline_key(title):
    """Strip trailing media outlet attribution to deduplicate syndicated/reposted news."""
    if not isinstance(title, str):
        return ""
    cleaned = re.sub(r"\s+", " ", title.strip())
    cleaned = re.sub(r"(\s*[-－—｜|]\s*[^-－—｜|]{1,28})+$", "", cleaned).strip()
    cleaned = re.sub(r"[【】「」『』()（）\[\]\s:：,，.。!！?？]", "", cleaned).lower()
    return cleaned


def _parse_roc_or_iso_date(value):
    if value is None:
        return None
    raw = str(value).strip()
    if not raw or raw in ("-", "--", "N/A", "不適用"):
        return None
    if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw):
        return date.fromisoformat(raw)
    digits = raw.replace("/", "").replace("-", "")
    if re.fullmatch(r"[0-9]{7}", digits):
        return _roc(digits)
    if re.fullmatch(r"[0-9]{8}", digits):
        return date(int(digits[:4]), int(digits[4:6]), int(digits[6:8]))
    return None


def _parse_roc_datetime(day_raw, clock_raw=None):
    d = _parse_roc_or_iso_date(day_raw)
    if d is None:
        return None
    if not clock_raw:
        return None
    clock = str(clock_raw).strip().replace(":", "").zfill(6)
    if not re.fullmatch(r"[0-9]{6}", clock):
        return None
    try:
        return datetime(d.year, d.month, d.day, int(clock[:2]), int(clock[2:4]), int(clock[4:6]), tzinfo=TW)
    except ValueError:
        return None


def normalize_event_timezone(timestamp_str, target_tz="Asia/Taipei"):
    """Normalize an ISO timestamp with timezone into target_tz and return local date + ISO string."""
    dt = datetime.fromisoformat(str(timestamp_str).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Event timestamp requires explicit timezone")
    tz = ZoneInfo(target_tz)
    localized = dt.astimezone(tz)
    return {
        "scheduled_at": localized.isoformat(),
        "scheduled_date": localized.date().isoformat(),
        "timezone": target_tz,
    }


def build_tw_disclosures_and_news(
    symbol,
    now,
    *,
    material_feed=None,
    shareholder_announce=None,
    dividend_rows=None,
    finmind_news=None,
    source_errors=None,
):
    """Build TW08 official disclosures and deduplicated third-party news references."""
    if now.tzinfo is None:
        raise ValueError("Evaluation time must be timezone aware")
    local_now = now.astimezone(TW)
    cutoff_date = local_now.date()
    first_seen = now.astimezone(timezone.utc).isoformat()
    ticker = symbol.removesuffix(".TW")
    errors = dict(source_errors or {})

    official_disclosures = []
    source_statuses = {}

    # 1. TWSE Daily Material Information (t187ap04_L)
    if isinstance(material_feed, dict) and material_feed.get("status") in ("available", "partial"):
        mat_events = material_feed.get("events") or []
        source_statuses["twse_material_t187ap04_L"] = (
            "available_with_events" if mat_events else "available_no_matching_events"
        )
        for ev in mat_events:
            pub = ev.get("published_at")
            if pub:
                try:
                    if datetime.fromisoformat(pub).astimezone(TW) > local_now:
                        continue
                except ValueError:
                    continue
            ev_dt = _parse_roc_or_iso_date(ev.get("event_date"))
            official_disclosures.append({
                "disclosure_id": ev["event_id"],
                "category": "material_information",
                "title": ev["title"],
                "event_date": ev_dt.isoformat() if ev_dt else ev.get("event_date"),
                "published_at": pub,
                "reported_at": material_feed.get("snapshot_date"),
                "first_seen_at": first_seen,
                "source": TW_MATERIAL_URL,
                "source_class": "official_exchange_disclosure",
                "verification_status": "verified_official_snapshot",
            })
    else:
        reason = (material_feed or {}).get("reason") or errors.get("material", "")
        if "No verifiable publication timestamps" in str(reason):
            source_statuses["twse_material_t187ap04_L"] = "empty_source_window"
        else:
            source_statuses["twse_material_t187ap04_L"] = "source_unavailable"

    # 2. TWSE Shareholder Meeting Convocation Announcement (t187ap38_L)
    if "shareholder_announce" in errors:
        source_statuses["twse_shareholder_t187ap38_L"] = "source_unavailable"
    elif isinstance(shareholder_announce, list):
        matched_rows = [
            r for r in shareholder_announce
            if isinstance(r, dict) and str(r.get("公司代號") or "").strip() == ticker
        ]
        kept = 0
        for r in matched_rows:
            rep_d = _parse_roc_or_iso_date(r.get("出表日期"))
            if rep_d and rep_d > cutoff_date:
                continue
            pub_dt = _parse_roc_datetime(r.get("公告日期"), r.get("公告時間"))
            pub_d = _parse_roc_or_iso_date(r.get("公告日期"))
            if pub_dt and pub_dt > local_now:
                continue
            if pub_d and pub_d > cutoff_date:
                continue
            meet_d = _parse_roc_or_iso_date(r.get("股東常(臨時)會日期-日期"))
            kind_label = str(r.get("股東常(臨時)會日期-常或臨時") or "常會").strip()
            title = f"公告召開股東{kind_label}（開會日期：{meet_d.isoformat() if meet_d else '未定'}）"
            pub_iso = pub_dt.isoformat() if pub_dt else (pub_d.isoformat() if pub_d else None)
            key = f"{ticker}|t187ap38_L|{pub_iso}|{meet_d.isoformat() if meet_d else ''}"
            official_disclosures.append({
                "disclosure_id": "tw-agm-" + hashlib.sha256(key.encode()).hexdigest()[:16],
                "category": "shareholder_meeting_announcement",
                "title": title,
                "event_date": meet_d.isoformat() if meet_d else None,
                "published_at": pub_iso,
                "reported_at": rep_d.isoformat() if rep_d else str(r.get("出表日期") or ""),
                "first_seen_at": first_seen,
                "source": TW_SHAREHOLDER_ANNOUNCE_URL,
                "source_class": "official_exchange_disclosure",
                "verification_status": "verified_official_snapshot",
            })
            kept += 1
        source_statuses["twse_shareholder_t187ap38_L"] = (
            "available_with_events" if kept else (
                "empty_source_window" if not shareholder_announce else "available_no_matching_events"
            )
        )
    else:
        source_statuses["twse_shareholder_t187ap38_L"] = "source_unavailable"

    # 3. TWSE Board Dividend & Quarterly Earnings Resolution Announcements (t187ap45_L)
    if "dividends" in errors:
        source_statuses["twse_dividend_t187ap45_L"] = "source_unavailable"
    elif isinstance(dividend_rows, list):
        matched_divs = [
            r for r in dividend_rows
            if isinstance(r, dict) and str(r.get("公司代號") or "").strip() in ("", ticker)
        ]
        kept = 0
        for r in matched_divs:
            rep_d = _parse_roc_or_iso_date(r.get("出表日期"))
            if rep_d and rep_d > cutoff_date:
                continue
            board_raw = r.get("董事會（擬議）股利分派日") or r.get("board_Or_approval_date_roc")
            board_d = _parse_roc_or_iso_date(board_raw)
            if board_d and board_d > cutoff_date:
                continue
            yr_raw = str(r.get("股利年度") if r.get("股利年度") is not None else (r.get("年度") or "")).strip()
            q_raw = str(r.get("股利所屬年(季)度") or r.get("季別") or r.get("period") or "").strip()
            period_label = q_raw if "Q" in q_raw else (
                f"{int(yr_raw) + 1911}{q_raw}" if yr_raw.isdigit() else q_raw
            )
            cash_raw = (
                r.get("股東配發-盈餘分配之現金股利(元/股)")
                if r.get("股東配發-盈餘分配之現金股利(元/股)") is not None
                else (r.get("現金股利(元/股)") if "現金股利(元/股)" in r else r.get("cash_dividend_per_share_twd"))
            )
            try:
                cash_div = f"{float(str(cash_raw).replace(',', '')):,.2f}" if cash_raw is not None else "—"
            except ValueError:
                cash_div = str(cash_raw)
            progress = str(r.get("決議（擬議）進度") or "董事會決議").strip()
            if not board_d:
                continue
            title = f"{progress}通過 {period_label} 盈餘分派（每股現金股利 {cash_div} 元）"
            key = f"{ticker}|t187ap45_L|{period_label}|{board_d.isoformat()}"
            official_disclosures.append({
                "disclosure_id": "tw-board-" + hashlib.sha256(key.encode()).hexdigest()[:16],
                "category": "board_dividend_and_earnings_resolution",
                "title": title,
                "event_date": board_d.isoformat(),
                "published_at": None,  # t187ap45_L provides board resolution date & export date, not exact published_at timestamp
                "reported_at": rep_d.isoformat() if rep_d else str(r.get("出表日期") or ""),
                "first_seen_at": first_seen,
                "source": TW_DIVIDEND_SCHEDULE_URL,
                "source_class": "official_exchange_disclosure",
                "verification_status": "verified_official_snapshot",
            })
            kept += 1
        source_statuses["twse_dividend_t187ap45_L"] = (
            "available_with_events" if kept else "available_no_matching_events"
        )
    else:
        source_statuses["twse_dividend_t187ap45_L"] = "source_unavailable"

    official_disclosures.sort(
        key=lambda x: (x.get("published_at") or x.get("event_date") or "", x["disclosure_id"]),
        reverse=True,
    )

    # 4. FinMind TaiwanStockNews (third-party news index, strictly separated from official disclosures)
    news_items = []
    duplicates_removed = 0
    if "finmind_news" in errors:
        source_statuses["finmind_news"] = "source_unavailable"
    elif isinstance(finmind_news, list):
        by_key = {}
        for row in finmind_news:
            if not isinstance(row, dict):
                continue
            if str(row.get("stock_id") or ticker).strip() != ticker:
                continue
            raw_date = str(row.get("date") or "").strip()
            title = str(row.get("title") or "").strip()
            link = str(row.get("link") or "").strip()
            outlet = str(row.get("source") or "unknown").strip()
            if not raw_date or not title:
                continue
            pub_dt = None
            try:
                if re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", raw_date):
                    d_only = date.fromisoformat(raw_date)
                    if d_only > cutoff_date:
                        continue
                    pub_iso = d_only.isoformat()
                else:
                    parsed = datetime.fromisoformat(raw_date.replace(" ", "T"))
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=TW)
                    if parsed.astimezone(TW) > local_now:
                        continue
                    pub_dt = parsed.astimezone(TW)
                    pub_iso = pub_dt.isoformat()
            except ValueError:
                continue
            dedup_key = normalize_headline_key(title)
            if not dedup_key:
                continue
            if dedup_key in by_key:
                duplicates_removed += 1
                existing = by_key[dedup_key]
                if outlet and outlet not in existing["sources"]:
                    existing["sources"].append(outlet)
                existing["syndicated_count"] += 1
                continue
            safe_link = link if link.startswith("https://") else None
            entry = {
                "news_id": "tw-news-" + hashlib.sha256(f"{ticker}|{dedup_key}".encode()).hexdigest()[:16],
                "headline": title[:200],
                "published_at": pub_iso,
                "event_date": None,  # News publication time does not equal underlying corporate event date
                "first_seen_at": first_seen,
                "sources": [outlet] if outlet else [],
                "syndicated_count": 1,
                "link": safe_link,
                "index_source": FINMIND_NEWS_DATASET,
                "source_class": "third_party_news_index_not_official_filing",
                "summary_status": "headline_and_link_only_full_text_not_fetched",
                "sentiment_score": "not_evaluated",
            }
            by_key[dedup_key] = entry
            news_items.append(entry)
        news_items.sort(key=lambda x: x["published_at"], reverse=True)
        news_items = news_items[:8]
        source_statuses["finmind_news"] = (
            "available_with_events" if news_items else (
                "empty_source_window" if not finmind_news else "available_no_matching_events"
            )
        )
    else:
        source_statuses["finmind_news"] = "source_unavailable"

    avail_values = list(source_statuses.values())
    if any(v.startswith("available_") for v in avail_values):
        overall = "partial" if "source_unavailable" in avail_values else "available"
    else:
        overall = "unavailable"

    return {
        "schema_version": 1,
        "status": overall,
        "evaluated_at_utc": first_seen,
        "source_statuses": source_statuses,
        "official_disclosures": official_disclosures[:10],
        "news_references": news_items,
        "deduplicated_repost_count": duplicates_removed,
        "manual_verification_links": [
            {"label": "MOPS 公開資訊觀測站（2330 重大訊息與公告）", "url": "https://mops.twse.com.tw/mops/web/t05st01"},
            {"label": "台積公司投資人關係（新聞中心與財務報告）", "url": "https://investor.tsmc.com/chinese"},
            {"label": "Yahoo 奇摩股市（2330 新聞／公告人工查核頁）", "url": "https://tw.stock.yahoo.com/quote/2330.TW/news"},
        ],
        "policy_notes": [
            "官方交易所公告（TWSE/MOPS）與第三方新聞索引（FinMind TaiwanStockNews）嚴格分列，新聞轉載不視為官方申報。",
            "同主題多媒體轉載已依標題正規化去重，僅保留標題、時間與來源連結，不擷取未授權全文、不生成假摘要、不做情緒評分。",
            "嚴格區分事實發生日（event_date）、來源發布時間（published_at）、系統首次觀測時間（first_seen_at）與彙總出表日（reported_at）。",
        ],
    }


def build_tw_calendar_schedule(
    symbol,
    now,
    *,
    shareholder_announce=None,
    shareholder_meeting=None,
    dividend_rows=None,
    material_feed=None,
    previous_schedule=None,
    source_errors=None,
):
    """Build TW09 corporate calendar schedule with timezone, confirmation status, and fallback retention."""
    if now.tzinfo is None:
        raise ValueError("Evaluation time must be timezone aware")
    local_now = now.astimezone(TW)
    cutoff_date = local_now.date()
    first_seen = now.astimezone(timezone.utc).isoformat()
    ticker = symbol.removesuffix(".TW")
    errors = dict(source_errors or {})

    events = []
    source_statuses = {}

    # 1. Shareholder meeting (t187ap38_L + t187ap41_L)
    agm_date = None
    agm_pub = None
    agm_rep = None
    agm_location = None
    agm_evote = None
    agm_kind = "股東常會"
    if isinstance(shareholder_announce, list) and "shareholder_announce" not in errors:
        for r in shareholder_announce:
            if not isinstance(r, dict) or str(r.get("公司代號") or "").strip() != ticker:
                continue
            rep_d = _parse_roc_or_iso_date(r.get("出表日期"))
            if rep_d and rep_d > cutoff_date:
                continue
            pub_dt = _parse_roc_datetime(r.get("公告日期"), r.get("公告時間"))
            if pub_dt and pub_dt > local_now:
                continue
            meet_d = _parse_roc_or_iso_date(r.get("股東常(臨時)會日期-日期"))
            if meet_d:
                agm_date = meet_d
                agm_pub = pub_dt.isoformat() if pub_dt else None
                agm_rep = rep_d.isoformat() if rep_d else None
                k_raw = str(r.get("股東常(臨時)會日期-常或臨時") or "常會").strip()
                agm_kind = f"股東{k_raw}"
        source_statuses["twse_shareholder_t187ap38_L"] = "available"
    else:
        source_statuses["twse_shareholder_t187ap38_L"] = "source_unavailable"

    if isinstance(shareholder_meeting, list) and "shareholder_meeting" not in errors:
        for r in shareholder_meeting:
            if not isinstance(r, dict) or str(r.get("公司代號") or "").strip() != ticker:
                continue
            rep_d = _parse_roc_or_iso_date(r.get("出表日期"))
            if rep_d and rep_d > cutoff_date:
                continue
            meet_d = _parse_roc_or_iso_date(r.get("開會日期"))
            if meet_d and agm_date is None:
                agm_date = meet_d
                agm_rep = rep_d.isoformat() if rep_d else None
            agm_location = str(r.get("開會地點") or "").strip() or None
            agm_evote = str(r.get("是否採電子投票") or "").strip() or None
        source_statuses["twse_shareholder_t187ap41_L"] = "available"
    else:
        source_statuses["twse_shareholder_t187ap41_L"] = "source_unavailable"

    if agm_date is not None:
        events.append({
            "schedule_id": f"{ticker}-shareholder_meeting-{agm_date.year}",
            "event_type": "shareholder_meeting",
            "period_label": f"FY{agm_date.year}",
            "title": f"{agm_date.year} 年{agm_kind}" + (f"（地點：{agm_location}）" if agm_location else ""),
            "scheduled_date": agm_date.isoformat(),
            "scheduled_at": None,
            "timezone": "Asia/Taipei",
            "confirmation_status": "confirmed",
            "published_at": agm_pub,
            "reported_at": agm_rep,
            "first_seen_at": first_seen,
            "source": TW_SHAREHOLDER_ANNOUNCE_URL,
            "electronic_voting": agm_evote,
        })

    # 2. Board meetings from t187ap45_L
    if isinstance(dividend_rows, list) and "dividends" not in errors:
        source_statuses["twse_dividend_t187ap45_L"] = "available"
        for r in dividend_rows:
            if not isinstance(r, dict) or str(r.get("公司代號") or "").strip() not in ("", ticker):
                continue
            rep_d = _parse_roc_or_iso_date(r.get("出表日期"))
            if rep_d and rep_d > cutoff_date:
                continue
            board_raw = r.get("董事會（擬議）股利分派日") or r.get("board_Or_approval_date_roc")
            board_d = _parse_roc_or_iso_date(board_raw)
            if not board_d or board_d > cutoff_date:
                continue
            yr_raw = str(r.get("股利年度") if r.get("股利年度") is not None else (r.get("年度") or "")).strip()
            q_raw = str(r.get("股利所屬年(季)度") or r.get("季別") or r.get("period") or "").strip()
            if "Q" in q_raw:
                p_lbl = q_raw
            elif yr_raw.isdigit() and "1" in q_raw:
                p_lbl = f"{int(yr_raw) + 1911}Q1"
            elif yr_raw.isdigit() and "2" in q_raw:
                p_lbl = f"{int(yr_raw) + 1911}Q2"
            elif yr_raw.isdigit() and "3" in q_raw:
                p_lbl = f"{int(yr_raw) + 1911}Q3"
            elif yr_raw.isdigit() and "4" in q_raw:
                p_lbl = f"{int(yr_raw) + 1911}Q4"
            else:
                p_lbl = f"{yr_raw}-{q_raw}"
            events.append({
                "schedule_id": f"{ticker}-board_meeting-{p_lbl}",
                "event_type": "board_meeting",
                "period_label": p_lbl,
                "title": f"{p_lbl} 董事會決議季度盈餘分派與財務報告核准",
                "scheduled_date": board_d.isoformat(),
                "scheduled_at": None,
                "timezone": "Asia/Taipei",
                "confirmation_status": "confirmed",
                "published_at": None,
                "reported_at": rep_d.isoformat() if rep_d else None,
                "first_seen_at": first_seen,
                "source": TW_DIVIDEND_SCHEDULE_URL,
            })
    else:
        source_statuses["twse_dividend_t187ap45_L"] = "source_unavailable"

    # 3. Check material disclosures for any observed investor_conference or earnings_release notices
    observed_conf = False
    observed_earn = False
    if isinstance(material_feed, dict) and material_feed.get("status") in ("available", "partial"):
        for ev in material_feed.get("events") or []:
            title = str(ev.get("title") or "")
            ev_d = _parse_roc_or_iso_date(ev.get("event_date"))
            if not ev_d:
                continue
            is_cancelled = any(k in title for k in ("取消", "暫停召開"))
            is_revised = any(k in title for k in ("更正", "變更", "改期", "延期"))
            conf_status = "cancelled" if is_cancelled else ("revised" if is_revised else "confirmed")
            if any(k in title for k in ("法人說明會", "法說會")):
                observed_conf = True
                events.append({
                    "schedule_id": f"{ticker}-investor_conference-{ev_d.isoformat()[:7]}",
                    "event_type": "investor_conference",
                    "period_label": f"{ev_d.year}",
                    "title": title[:160],
                    "scheduled_date": ev_d.isoformat(),
                    "scheduled_at": None,
                    "timezone": "Asia/Taipei",
                    "confirmation_status": conf_status,
                    "published_at": ev.get("published_at"),
                    "reported_at": material_feed.get("snapshot_date"),
                    "first_seen_at": first_seen,
                    "source": TW_MATERIAL_URL,
                })
            elif any(k in title for k in ("提報董事會", "預計提報董事會", "財務報告公告")):
                observed_earn = True
                events.append({
                    "schedule_id": f"{ticker}-earnings_release-{ev_d.isoformat()[:7]}",
                    "event_type": "earnings_release",
                    "period_label": f"{ev_d.year}",
                    "title": title[:160],
                    "scheduled_date": ev_d.isoformat(),
                    "scheduled_at": None,
                    "timezone": "Asia/Taipei",
                    "confirmation_status": conf_status,
                    "published_at": ev.get("published_at"),
                    "reported_at": material_feed.get("snapshot_date"),
                    "first_seen_at": first_seen,
                    "source": TW_MATERIAL_URL,
                })

    if not observed_conf:
        events.append({
            "schedule_id": f"{ticker}-investor_conference-upcoming",
            "event_type": "investor_conference",
            "period_label": "upcoming",
            "title": "下次法人說明會（Investor Conference）日期",
            "scheduled_date": None,
            "scheduled_at": None,
            "timezone": "Asia/Taipei",
            "confirmation_status": "unknown",
            "published_at": None,
            "reported_at": None,
            "first_seen_at": first_seen,
            "source": TW_MATERIAL_URL,
            "note": "當日重訊快照未觀測到新法說會公告；依研究規範嚴格標記為 unknown，絕不沿用往年日期推算。",
        })

    if not observed_earn:
        events.append({
            "schedule_id": f"{ticker}-earnings_release-upcoming",
            "event_type": "earnings_release",
            "period_label": "upcoming",
            "title": "下次季度財報公布／提報董事會確定日期",
            "scheduled_date": None,
            "scheduled_at": None,
            "timezone": "Asia/Taipei",
            "confirmation_status": "unknown",
            "published_at": None,
            "reported_at": None,
            "first_seen_at": first_seen,
            "source": TW_MATERIAL_URL,
            "note": "當日重訊快照未觀測到下次財報公告日；不以歷史季度推算預計公布日。",
        })

    # 4. Statutory IFRS filing deadline reference (distinct from actual company earnings_release date)
    events.append({
        "schedule_id": f"{ticker}-statutory_filing_deadline-tw_ifrs",
        "event_type": "statutory_filing_deadline",
        "period_label": "TW_IFRS_Rule",
        "title": "證交法／一般上市公司財報法定申報期限（Q1: 5/15、Q2: 8/14、Q3: 11/14、年度: 次年 3/31；僅供法規參照，非公司實際公布日）",
        "scheduled_date": None,
        "scheduled_at": None,
        "timezone": "Asia/Taipei",
        "confirmation_status": "confirmed",
        "published_at": None,
        "reported_at": None,
        "first_seen_at": first_seen,
        "source": "https://www.twse.com.tw/",
    })

    # Preserve prior confirmed schedule items if a source is currently unavailable
    retained_from_previous = []
    if isinstance(previous_schedule, dict):
        current_ids = {e["schedule_id"] for e in events if e.get("confirmation_status") != "unknown"}
        for prev_ev in previous_schedule.get("events") or []:
            if not isinstance(prev_ev, dict):
                continue
            sid = prev_ev.get("schedule_id")
            if sid and sid not in current_ids and prev_ev.get("confirmation_status") in ("confirmed", "revised", "tentative"):
                retained_copy = {**prev_ev, "retained_from_previous": True}
                events.append(retained_copy)
                retained_from_previous.append(sid)

    events.sort(
        key=lambda x: (
            0 if x.get("scheduled_date") else 1,
            -(int(x["scheduled_date"].replace("-", "")) if x.get("scheduled_date") else 0),
            x["schedule_id"],
        )
    )

    avail = list(source_statuses.values())
    status = "available" if all(v == "available" for v in avail) else (
        "partial" if any(v == "available" for v in avail) or retained_from_previous else "unavailable"
    )
    schedule = {
        "schema_version": 1,
        "status": status,
        "timezone": "Asia/Taipei",
        "evaluated_at_utc": first_seen,
        "source_statuses": source_statuses,
        "events": events,
        "retained_from_previous_ids": retained_from_previous,
        "manual_verification_links": [
            {"label": "台積公司行事曆與法說會專區（TSMC IR Financial Calendar）", "url": "https://investor.tsmc.com/chinese/quarterly-results"},
            {"label": "MOPS 召開法人說明會一覽表", "url": "https://mops.twse.com.tw/mops/web/t100sb02_1"},
            {"label": "Yahoo 奇摩股市（2330 行事曆與股東會頁）", "url": "https://tw.stock.yahoo.com/quote/2330.TW"},
        ],
    }
    if isinstance(previous_schedule, dict):
        schedule["schedule_changes"] = compare_calendar_schedules(previous_schedule, schedule)
    else:
        schedule["schedule_changes"] = []
    return schedule


def compare_calendar_schedules(previous_schedule, current_schedule):
    """Compare two TW09 calendar schedules and detect new, revised, or cancelled events."""
    if not isinstance(previous_schedule, dict) or not isinstance(current_schedule, dict):
        return []
    old_map = {
        e["schedule_id"]: e
        for e in (previous_schedule.get("events") or [])
        if isinstance(e, dict) and "schedule_id" in e
    }
    changes = []
    for cur in current_schedule.get("events") or []:
        if not isinstance(cur, dict) or "schedule_id" not in cur:
            continue
        if cur.get("retained_from_previous"):
            continue
        sid = cur["schedule_id"]
        old = old_map.get(sid)
        if old is None:
            if cur.get("confirmation_status") != "unknown":
                changes.append({
                    "schedule_id": sid,
                    "event_type": cur.get("event_type"),
                    "change_kind": "new_schedule",
                    "old_date": None,
                    "new_date": cur.get("scheduled_date"),
                    "old_status": None,
                    "new_status": cur.get("confirmation_status"),
                    "reason": "new_confirmed_schedule_observed",
                })
            continue
        old_d = old.get("scheduled_date")
        new_d = cur.get("scheduled_date")
        old_s = old.get("confirmation_status")
        new_s = cur.get("confirmation_status")
        if new_s == "cancelled" and old_s != "cancelled":
            changes.append({
                "schedule_id": sid,
                "event_type": cur.get("event_type"),
                "change_kind": "schedule_cancelled",
                "old_date": old_d,
                "new_date": new_d,
                "old_status": old_s,
                "new_status": new_s,
                "reason": "scheduled_event_cancelled",
            })
        elif old_d != new_d and (old_d is not None or new_d is not None):
            if old_s == "unknown" and new_d is not None:
                changes.append({
                    "schedule_id": sid,
                    "event_type": cur.get("event_type"),
                    "change_kind": "new_schedule",
                    "old_date": None,
                    "new_date": new_d,
                    "old_status": old_s,
                    "new_status": new_s,
                    "reason": "previously_unknown_schedule_confirmed",
                })
            elif new_d is not None:
                changes.append({
                    "schedule_id": sid,
                    "event_type": cur.get("event_type"),
                    "change_kind": "schedule_revised",
                    "old_date": old_d,
                    "new_date": new_d,
                    "old_status": old_s,
                    "new_status": "revised" if new_s == "confirmed" else new_s,
                    "reason": "scheduled_date_changed",
                })
        elif old_s != new_s and new_s not in ("unknown", None):
            changes.append({
                "schedule_id": sid,
                "event_type": cur.get("event_type"),
                "change_kind": "status_changed",
                "old_date": old_d,
                "new_date": new_d,
                "old_status": old_s,
                "new_status": new_s,
                "reason": "confirmation_status_changed",
            })
    return changes

