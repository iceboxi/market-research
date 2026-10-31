"""Watchlist alert Issue (#116, #145): one Issue, a comment only when a watched state changes.

The Issue body is the current dashboard and stores the last evaluated state in a
hidden marker. Each daily TW run compares every satellite's valuation zone and
thesis status, and every industry-watch stock's P/B zone and revenue momentum,
with it and comments only on a change. `not_evaluated` (missing data, source
failure) is never a change: the last evaluated value is kept and the body shows
the gap. Items the stored state has never held get one baseline comment. Only
the main TW schedule or dispatch may write.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from market_research.industry_watch import MOMENTUM_LABELS
from market_research.thesis_check import STATUS_LABELS as THESIS_LABELS
from market_research.valuation_zone import ZONE_LABELS, load_watchlist
from scripts.research_github import GitHubResearchSink

ROOT = Path(__file__).resolve().parents[1]
MARKER = "<!-- market-research:watchlist-alert -->"
STATE_RE = re.compile(r"<!-- watchlist-alert-state:(.*?) -->", re.S)
TITLE = "觀察名單提醒（請檢視，非買賣建議）"
DISCLAIMER = "請檢視，非買賣建議"
STATE_SCHEMA = 2  # 2 adds industry watch (#145); schema 1 (satellites only) still reads
VALUES = {"zone": set(ZONE_LABELS), "thesis": {"ok", "review"}}
ITEMS = (("zone", "估值區間"), ("thesis", "論點"))
INDUSTRY_VALUES = {"pb_zone": set(ZONE_LABELS), "momentum": {"ok", "slowing", "contracting"}}
INDUSTRY_ITEMS = (("pb_zone", "股價淨值比區間"), ("momentum", "營收動能"))
ITEM_NAMES = dict(ITEMS + INDUSTRY_ITEMS)
TAIPEI = ZoneInfo("Asia/Taipei")


class AlertContextError(ValueError):
    pass


def require_alert_context(env):
    """Branch, pull-request and validation runs must never write the alert Issue."""
    if (env.get("GITHUB_REF") != "refs/heads/main" or
            env.get("GITHUB_EVENT_NAME") not in ("schedule", "workflow_dispatch") or
            env.get("SCAN_MARKET") not in ("tw", "both")):
        raise AlertContextError("Watchlist alerts write only from the main TW schedule or dispatch")


def satellite_states(receipt, satellites):
    """Current zone and thesis per satellite from daily_receipt.json."""
    records = (receipt.get("pilot_coverage") or {}).get("symbols") or {}
    states = {}
    for symbol in satellites:
        rec = records.get(symbol) or {}
        failed = (f"研究失敗：{rec.get('error_type')}" if rec.get("status") == "failed"
                  else None if rec else "本次未研究")
        zone = rec.get("valuation_zone") or {}
        thesis = rec.get("thesis_check") or {}
        price = zone.get("price") or {}
        announcements = (thesis.get("announcements") or {}).get("items") or []
        months = (thesis.get("revenue") or {}).get("months") or []
        states[symbol] = {
            "name": rec.get("company_name"),
            "zone": {"value": zone["zone"] if zone.get("status") == "available" else "not_evaluated",
                     "reason": failed or zone.get("reason"), "close": price.get("close"),
                     "session": price.get("session"), "prices": zone.get("review_prices_twd")},
            "thesis": {"value": thesis["status"] if thesis.get("status") in VALUES["thesis"]
                       else "not_evaluated",
                       "reason": failed or thesis.get("reason"), "cutoff": thesis.get("cutoff"),
                       "announcements": [item.get("title") for item in announcements],
                       "yoy": [f"{m['period']} {m['yoy_pct']:+.2f}%" for m in months]},
        }
    return states


def industry_states(receipt):
    """Industry-watch groups and each stock's P/B zone and revenue momentum (#145).

    None when the section never ran (not configured); {"failed": reason} when it failed.
    """
    section = receipt.get("industry_watch")
    if not section:
        return None
    if section.get("status") == "failed":
        return {"failed": f"{section.get('error_type')}：{section.get('reason')}"}
    states = {}
    for row in section.get("rows") or []:
        zone, momentum = row.get("pb_zone") or {}, row.get("revenue_momentum") or {}
        price, history = zone.get("price") or {}, zone.get("pbr_history") or {}
        months = momentum.get("months") or []
        states[row["symbol"]] = {
            "name": row.get("name"), "group": row.get("group"),
            "pb_zone": {"value": zone["zone"] if zone.get("status") == "available" else "not_evaluated",
                        "reason": zone.get("reason"), "close": price.get("close"),
                        "session": price.get("session"), "prices": zone.get("review_prices_twd"),
                        "pbr": history.get("latest_pbr"), "rank": history.get("latest_percentile_rank")},
            "momentum": {"value": (momentum["status"] if momentum.get("status") in INDUSTRY_VALUES["momentum"]
                                   else "not_evaluated"),
                         "reason": momentum.get("reason"),
                         "period": momentum.get("latest_period") if months else None,
                         "published": momentum.get("latest_published"),
                         "rolling": [f"{m['period']} {m['rolling_3m_yoy_pct']:+.1f}%" for m in months]},
        }
    groups = [{"id": g.get("id"), "name": g.get("name")} for g in section.get("groups") or []]
    return {"groups": groups, "states": states}


def _valid(entries, values, where):
    if not isinstance(entries, dict):
        raise ValueError(f"狀態缺少 {where}")
    for symbol, items in entries.items():
        if not isinstance(items, dict) or set(items) != set(values) or any(
                items[k] is not None and items[k] not in values[k] for k in values):
            raise ValueError(f"{symbol} 的狀態值無效")
    return entries


def parse_state(body):
    """Last evaluated state from the Issue body; None when the body never had one.

    Returns {"symbols": satellites, "industry": industry-watch stocks}; schema 1 has no industry.
    """
    found = STATE_RE.findall(body or "")
    if not found:
        return None
    if len(found) > 1:
        raise ValueError("多個狀態標記")
    try:
        state = json.loads(found[0])
    except json.JSONDecodeError as error:
        raise ValueError(f"狀態 JSON 無法解析：{error.msg}")
    if not isinstance(state, dict) or state.get("schema") not in (1, STATE_SCHEMA):
        raise ValueError("狀態版本不符")
    symbols = _valid(state.get("symbols"), VALUES, "symbols")
    industry = (_valid(state.get("industry"), INDUSTRY_VALUES, "industry")
                if state["schema"] == STATE_SCHEMA else {})
    return {"symbols": symbols, "industry": industry}


def diff_states(previous, current, items=ITEMS):
    """Changes between evaluated values, and the state to store next."""
    changes, stored = [], {}
    for symbol, now in current.items():
        before = previous.get(symbol) or {}
        kept = {}
        for item, _ in items:
            value = now[item]["value"]
            if value == "not_evaluated":
                kept[item] = before.get(item)
                continue
            kept[item] = value
            if value != before.get(item):
                changes.append({"symbol": symbol, "item": item, "old": before.get(item), "new": value})
        stored[symbol] = kept
    return changes, stored


# ---------------------------------------------------------------- rendering

def _money(value):
    return f"{value:,.2f}" if isinstance(value, (int, float)) else "—"


def _label(symbol, state):
    return f"{symbol} {state['name']}" if state.get("name") else symbol


def _value_label(item, value):
    if value is None:
        return "—"
    labels = {"zone": ZONE_LABELS, "pb_zone": ZONE_LABELS, "thesis": THESIS_LABELS,
              "momentum": MOMENTUM_LABELS}[item]
    return labels.get(value, value)


def _prices(zone):
    prices = zone.get("prices") or {}
    band = "／".join(_money(prices.get(k)) for k in ("low", "mid", "high"))
    return f"收盤 {_money(zone.get('close'))}；偏低／合理／偏高 {band}"


def _pbr(zone):
    if zone.get("pbr") is None:
        return "—"
    rank = zone.get("rank")
    return f"{zone['pbr']:.2f}" + (f"（P{rank:.0f}）" if rank is not None else "")


def _momentum_basis(momentum):
    trend = " → ".join(momentum["rolling"])
    reason = momentum.get("reason") or ""
    return f"3 個月滾動年增率 {trend}；{reason}" if trend else (reason or "—")


def _basis(item, state):
    if item == "zone":
        return _prices(state["zone"])
    if item == "pb_zone":
        return f"{_prices(state['pb_zone'])}；PBR {_pbr(state['pb_zone'])}"
    if item == "momentum":
        return _momentum_basis(state["momentum"])
    thesis = state["thesis"]
    titles = "；".join(t for t in thesis["announcements"] if t)
    if thesis.get("reason"):
        return thesis["reason"] + (f"：{titles}" if titles else "")
    return "月營收年增率 " + " / ".join(thesis["yoy"]) if thesis["yoy"] else "—"


def _data_date(item, state):
    if item == "momentum":
        momentum = state["momentum"]
        if not momentum.get("period"):
            return "—"
        return f"{momentum['period']}（{momentum.get('published') or '依法定期限'}）"
    return (state[item].get("session") if item in ("zone", "pb_zone")
            else state["thesis"].get("cutoff")) or "—"


def _cell(item, part):
    return (_value_label(item, part["value"]) if part["value"] != "not_evaluated"
            else f"未評估：{part['reason']}")


def _industry_lines(industry, stored_industry):
    """Body section for industry-watch stocks (#145); the stored state is kept when it did not run."""
    if industry is None:
        if not stored_industry:
            return []
        return ["", "## 產業觀察", "", "本次未執行產業觀察，保留上次已評估的狀態。"]
    lines = ["", "## 產業觀察", "",
             "股價淨值比區間 = 近 5 年每日 PBR 百分位 × 每股淨值（檢視區）；"
             "營收動能看 3 個月滾動年增率（低於 0 為衰退，連續下降達門檻為放緩）。價格位置只顯示在 Pages，不列入提醒。"]
    if "failed" in industry:
        return lines + ["", f"本次取得失敗：{industry['failed']}；保留上次已評估的狀態。"]
    states = industry["states"]
    for group in industry["groups"]:
        members = [s for s, state in states.items() if state.get("group") == group["id"]]
        if not members:
            continue
        lines += ["", f"### {group['name']}", "",
                  "| 標的 | 股價淨值比區間 | 收盤（日期） | PBR（5 年百分位） | 偏低／合理／偏高 | 營收動能 | 動能依據 |",
                  "| :--- | :--- | ---: | ---: | ---: | :--- | :--- |"]
        for symbol in members:
            state = states[symbol]
            zone, momentum = state["pb_zone"], state["momentum"]
            prices = zone.get("prices") or {}
            lines.append(
                f"| {_label(symbol, state)} | {_cell('pb_zone', zone)} | "
                f"{_money(zone.get('close'))}（{zone.get('session') or '—'}） | {_pbr(zone)} | "
                + "／".join(_money(prices.get(k)) for k in ("low", "mid", "high"))
                + f" | {_cell('momentum', momentum)} | {_momentum_basis(momentum)} |")
    return lines


def render_body(current, stored, as_of, run_url, industry=None, stored_industry=None):
    lines = [MARKER, "# 觀察名單提醒", "",
             f"**{DISCLAIMER}。** 每日 TW 排程比較衛星個股的估值區間（歷史本益比檢視區）與論點狀態，"
             "以及產業觀察股的股價淨值比區間與營收動能，"
             "只在改變時於本 Issue 留言。未評估（資料不足或來源失敗）不算改變，保留上次已評估的狀態。", "",
             f"最後更新：{as_of}（[執行紀錄]({run_url})）", "",
             "| 標的 | 估值區間 | 收盤（日期） | 偏低／合理／偏高 | 論點 | 論點依據 |",
             "| :--- | :--- | ---: | ---: | :--- | :--- |"]
    for symbol, state in current.items():
        zone, thesis = state["zone"], state["thesis"]
        zone_cell = _cell("zone", zone)
        thesis_cell = THESIS_LABELS.get(thesis["value"], thesis["value"])
        prices = zone.get("prices") or {}
        lines.append(
            f"| {_label(symbol, state)} | {zone_cell} | {_money(zone.get('close'))}（{zone.get('session') or '—'}） | "
            + "／".join(_money(prices.get(k)) for k in ("low", "mid", "high"))
            + f" | {thesis_cell} | {_basis('thesis', state)} |")
    lines += _industry_lines(industry, stored_industry)
    state = {"schema": STATE_SCHEMA, "as_of": as_of, "symbols": stored, "industry": stored_industry or {}}
    lines += ["", "<!-- watchlist-alert-state:" + json.dumps(state, sort_keys=True, separators=(",", ":"))
              + " -->"]
    return "\n".join(lines) + "\n"


def render_comment(changes, current, kind, as_of, run_id, run_url, note=None):
    """One comment per run; `current` holds satellite and industry-watch states by symbol."""
    heading = {"change": "狀態改變", "baseline": "初始狀態（基線）", "rebuilt": "重建基線"}[kind]
    lines = [f"<!-- watchlist-alert-run:{run_id} -->", f"## {heading}：{as_of}（{DISCLAIMER}）", ""]
    if note:
        lines += [f"前次狀態無法使用（{note}），已用本次結果重建基線；以下為目前狀態。", ""]
    lines += ["| 標的 | 項目 | 改變 | 價位／依據 | 資料日期 |", "| :--- | :--- | :--- | :--- | :--- |"]
    names = ITEM_NAMES
    for change in changes:
        state = current[change["symbol"]]
        lines.append(f"| {_label(change['symbol'], state)} | {names[change['item']]} | "
                     f"{_value_label(change['item'], change['old'])} → {_value_label(change['item'], change['new'])} | "
                     f"{_basis(change['item'], state)} | {_data_date(change['item'], state)} |")
    if not changes:
        lines.append("| — | — | 本次沒有已評估的項目 | 未評估原因見 Issue 內文 | — |")
    lines += ["", f"執行紀錄：{run_url}"]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------- delivery

def sync(sink, receipt, satellites, *, run_id, run_url):
    """Create or update the alert Issue; comment once per run, only on a change."""
    as_of = datetime.fromisoformat(receipt["generated_utc"]).astimezone(TAIPEI).date().isoformat()
    current = satellite_states(receipt, satellites)
    industry = industry_states(receipt)
    issues = [issue for issue in sink.find(MARKER) if issue.get("state") == "open"]
    if len(issues) > 1:
        raise ValueError("More than one open watchlist alert Issue")
    number, kind, note, previous, previous_industry = None, "baseline", None, {}, {}
    if issues:
        number = issues[0]["number"]
        try:
            parsed = parse_state(issues[0].get("body"))
        except ValueError as error:
            kind, note = "rebuilt", str(error)
        else:
            if parsed is not None:
                kind, previous, previous_industry = "change", parsed["symbols"], parsed["industry"]
    changes, stored = diff_states(previous, current)
    industry_current = (industry or {}).get("states")
    if industry_current is None:
        # Not run or failed: nothing is a change and the last evaluated values stay.
        stored_industry = previous_industry
    else:
        industry_changes, stored_industry = diff_states(previous_industry, industry_current, INDUSTRY_ITEMS)
        changes += industry_changes
    # Items the stored state never held (first industry run, a newly added stock) are a baseline.
    if kind == "change" and changes and all(change["old"] is None for change in changes):
        kind = "baseline"
    if number is None:
        # The state lands only after the baseline comment, so a failed comment is retried.
        number = sink.create(TITLE, MARKER + "\n初始化中。\n")["number"]
    comment = "not_needed"
    if changes or kind != "change":
        run_marker = f"<!-- watchlist-alert-run:{run_id} -->"
        if sink.find_comments(number, run_marker):
            comment = "already_posted"
        else:
            sink.create_comment(number, render_comment(changes, {**current, **(industry_current or {})},
                                                       kind, as_of, run_id, run_url, note))
            comment = "posted"
    sink.update(number, render_body(current, stored, as_of, run_url, industry, stored_industry))
    industry_status = ("not_run" if industry is None else "failed" if "failed" in industry else "evaluated")
    return {"status": "synced", "issue_number": number, "kind": kind, "note": note,
            "changes": changes, "comment": comment, "as_of": as_of, "industry": industry_status}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--repo", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--run-url", required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config-dir", type=Path, default=ROOT / "config")
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    try:
        require_alert_context(os.environ)
        if not args.receipt.exists():
            raise FileNotFoundError(f"{args.receipt} missing; daily research did not finish")
    except (AlertContextError, FileNotFoundError) as error:
        result = {"status": "skipped", "reason": str(error)}
    else:
        receipt = json.loads(args.receipt.read_text(encoding="utf-8"))
        result = sync(GitHubResearchSink(args.repo), receipt, list(load_watchlist(args.config_dir)),
                      run_id=args.run_id, run_url=args.run_url)
    (args.out / "watchlist_alert_receipt.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
