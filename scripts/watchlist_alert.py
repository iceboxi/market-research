"""Watchlist alert Issue (#116): one Issue, a comment only when a satellite's state changes.

The Issue body is the current dashboard and stores the last evaluated state in a
hidden marker. Each daily TW run compares every satellite's valuation zone and
thesis status with it and comments only on a change. `not_evaluated` (missing
data, source failure) is never a change: the last evaluated value is kept and
the body shows the gap. Only the main TW schedule or dispatch may write.
"""
import argparse
from datetime import datetime
import json
import os
from pathlib import Path
import re
from zoneinfo import ZoneInfo

from market_research.thesis_check import STATUS_LABELS as THESIS_LABELS
from market_research.valuation_zone import ZONE_LABELS, load_watchlist
from scripts.research_github import GitHubResearchSink

ROOT = Path(__file__).resolve().parents[1]
MARKER = "<!-- market-research:watchlist-alert -->"
STATE_RE = re.compile(r"<!-- watchlist-alert-state:(.*?) -->", re.S)
TITLE = "觀察名單提醒（請檢視，非買賣建議）"
DISCLAIMER = "請檢視，非買賣建議"
STATE_SCHEMA = 1
VALUES = {"zone": set(ZONE_LABELS), "thesis": {"ok", "review"}}
ITEMS = (("zone", "估值區間"), ("thesis", "論點"))
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


def parse_state(body):
    """Last evaluated state from the Issue body; None when the body never had one."""
    found = STATE_RE.findall(body or "")
    if not found:
        return None
    if len(found) > 1:
        raise ValueError("多個狀態標記")
    try:
        state = json.loads(found[0])
    except json.JSONDecodeError as error:
        raise ValueError(f"狀態 JSON 無法解析：{error.msg}")
    if not isinstance(state, dict) or state.get("schema") != STATE_SCHEMA:
        raise ValueError("狀態版本不符")
    symbols = state.get("symbols")
    if not isinstance(symbols, dict):
        raise ValueError("狀態缺少 symbols")
    for symbol, items in symbols.items():
        if not isinstance(items, dict) or set(items) != set(VALUES) or any(
                items[k] is not None and items[k] not in VALUES[k] for k in VALUES):
            raise ValueError(f"{symbol} 的狀態值無效")
    return symbols


def diff_states(previous, current):
    """Changes between evaluated values, and the state to store next."""
    changes, stored = [], {}
    for symbol, now in current.items():
        before = previous.get(symbol) or {}
        kept = {}
        for item, _ in ITEMS:
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
    return (ZONE_LABELS if item == "zone" else THESIS_LABELS).get(value, value)


def _prices(zone):
    prices = zone.get("prices") or {}
    band = "／".join(_money(prices.get(k)) for k in ("low", "mid", "high"))
    return f"收盤 {_money(zone.get('close'))}；偏低／合理／偏高 {band}"


def _basis(item, state):
    if item == "zone":
        return _prices(state["zone"])
    thesis = state["thesis"]
    titles = "；".join(t for t in thesis["announcements"] if t)
    if thesis.get("reason"):
        return thesis["reason"] + (f"：{titles}" if titles else "")
    return "月營收年增率 " + " / ".join(thesis["yoy"]) if thesis["yoy"] else "—"


def _data_date(item, state):
    return (state["zone"].get("session") if item == "zone" else state["thesis"].get("cutoff")) or "—"


def render_body(current, stored, as_of, run_url):
    lines = [MARKER, "# 觀察名單提醒", "",
             f"**{DISCLAIMER}。** 每日 TW 排程比較衛星個股的估值區間（歷史本益比檢視區）與論點狀態，"
             "只在改變時於本 Issue 留言。未評估（資料不足或來源失敗）不算改變，保留上次已評估的狀態。", "",
             f"最後更新：{as_of}（[執行紀錄]({run_url})）", "",
             "| 標的 | 估值區間 | 收盤（日期） | 偏低／合理／偏高 | 論點 | 論點依據 |",
             "| :--- | :--- | ---: | ---: | :--- | :--- |"]
    for symbol, state in current.items():
        zone, thesis = state["zone"], state["thesis"]
        zone_cell = (_value_label("zone", zone["value"]) if zone["value"] != "not_evaluated"
                     else f"未評估：{zone['reason']}")
        thesis_cell = THESIS_LABELS.get(thesis["value"], thesis["value"])
        prices = zone.get("prices") or {}
        lines.append(
            f"| {_label(symbol, state)} | {zone_cell} | {_money(zone.get('close'))}（{zone.get('session') or '—'}） | "
            + "／".join(_money(prices.get(k)) for k in ("low", "mid", "high"))
            + f" | {thesis_cell} | {_basis('thesis', state)} |")
    state = {"schema": STATE_SCHEMA, "as_of": as_of, "symbols": stored}
    lines += ["", "<!-- watchlist-alert-state:" + json.dumps(state, sort_keys=True, separators=(",", ":"))
              + " -->"]
    return "\n".join(lines) + "\n"


def render_comment(changes, current, kind, as_of, run_id, run_url, note=None):
    heading = {"change": "狀態改變", "baseline": "初始狀態（基線）", "rebuilt": "重建基線"}[kind]
    lines = [f"<!-- watchlist-alert-run:{run_id} -->", f"## {heading}：{as_of}（{DISCLAIMER}）", ""]
    if note:
        lines += [f"前次狀態無法使用（{note}），已用本次結果重建基線；以下為目前狀態。", ""]
    lines += ["| 標的 | 項目 | 改變 | 價位／依據 | 資料日期 |", "| :--- | :--- | :--- | :--- | :--- |"]
    names = dict(ITEMS)
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
    issues = [issue for issue in sink.find(MARKER) if issue.get("state") == "open"]
    if len(issues) > 1:
        raise ValueError("More than one open watchlist alert Issue")
    number, kind, note, previous = None, "baseline", None, {}
    if issues:
        number = issues[0]["number"]
        try:
            parsed = parse_state(issues[0].get("body"))
        except ValueError as error:
            kind, note = "rebuilt", str(error)
        else:
            if parsed is not None:
                kind, previous = "change", parsed
    changes, stored = diff_states(previous, current)
    if number is None:
        # The state lands only after the baseline comment, so a failed comment is retried.
        number = sink.create(TITLE, MARKER + "\n初始化中。\n")["number"]
    comment = "not_needed"
    if changes or kind != "change":
        run_marker = f"<!-- watchlist-alert-run:{run_id} -->"
        if sink.find_comments(number, run_marker):
            comment = "already_posted"
        else:
            sink.create_comment(number, render_comment(changes, current, kind, as_of, run_id, run_url, note))
            comment = "posted"
    sink.update(number, render_body(current, stored, as_of, run_url))
    return {"status": "synced", "issue_number": number, "kind": kind, "note": note,
            "changes": changes, "comment": comment, "as_of": as_of}


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
