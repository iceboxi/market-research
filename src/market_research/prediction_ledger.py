"""Prediction ledger format (#183): one entry per prediction that can be judged when it is due.

The ledger lives in the knowledge base and is written by the Agent in conversation. This module
only checks the format so a malformed entry fails its PR, not the daily schedule. When an entry
starts (First seen on main), whether it was edited after merge, and its outcome are not stored
here: the daily scorer derives them from git history and prices (later #183 work).
"""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re

import yaml

TRIGGERS = {"weekly", "event", "inference"}
METHODS = {"forced-selling", "business-cycle", "timing-revenue", "fixed-standard", "judgment"}
CLAIM_KINDS = {"return", "close_at_check", "held", "range", "manual"}
OPS = {">", "<"}
BASES = {"close", "intraday"}
CAUSES = {"method", "data", "event", "noise", "correct"}
ACTIONS = {"keep", "watch", "revise"}
OUTCOMES = {"hit", "miss"}
WEEKLY_SYMBOL, WEEKLY_HORIZON = "TAIEX", 5
MAX_HORIZON = 252
ID_RE = re.compile(r"^[A-Z]-\d{8}-[a-z0-9-]+$")
ENTRY_KEYS = {"id", "trigger", "event", "event_time", "method", "method_version", "reasoning",
              "claim", "horizon_sessions", "probability", "decision", "written_at", "withdrawn", "review"}
REQUIRED = {"id", "trigger", "method", "reasoning", "claim", "horizon_sessions", "probability"}
CLAIM_KEYS = {"return": {"kind", "symbol", "op", "threshold_pct"},
              "close_at_check": {"kind", "symbol", "op", "level"},
              "held": {"kind", "symbol", "op", "level", "basis"},
              "range": {"kind", "symbol", "low", "high"},
              "manual": {"kind", "text"}}
DECISION_KEYS = {"rule", "if_hit", "if_miss"}
# From this id date on, a prediction names the knowledge-base decision rule it tests and is more
# than a bare up/down call (user feedback 2026-11-20: direction alone cannot be acted on).
ACTIONABLE_FROM = date(2026, 11, 22)


class LedgerError(ValueError):
    pass


def supported_symbols(config_dir: Path) -> set[str]:
    """Symbols the pipeline already prices: TW scan list, its benchmarks and industry-watch stocks."""
    markets = yaml.safe_load((config_dir / "markets.yaml").read_text(encoding="utf-8"))
    tw = markets["markets"]["tw"]
    watch = yaml.safe_load((config_dir / "watchlist.yaml").read_text(encoding="utf-8"))
    industry = {sym for group in (watch.get("industry_watch") or {}).values()
                for sym in (group.get("symbols") or {})}
    return set(tw.get("symbols") or []) | set(tw.get("benchmarks") or []) | industry


def _aware(value, where):
    try:
        moment = datetime.fromisoformat(str(value))
    except ValueError:
        raise LedgerError(f"{where} 要是 ISO 8601 時間，例如 2026-11-17T16:00:00-05:00") from None
    if moment.tzinfo is None:
        raise LedgerError(f"{where} 要帶時區，例如 +08:00 或 -05:00")
    return moment


def _date(value, where):
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        raise LedgerError(f"{where} 要是日期，例如 2026-11-24") from None


def _number(value, where):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise LedgerError(f"{where} 要是數字")
    return value


def _check_claim(pid, claim, symbols):
    if not isinstance(claim, dict) or claim.get("kind") not in CLAIM_KINDS:
        raise LedgerError(f"{pid}: claim.kind 要是 {sorted(CLAIM_KINDS)} 之一")
    kind = claim["kind"]
    if set(claim) != CLAIM_KEYS[kind]:
        raise LedgerError(f"{pid}: {kind} 的 claim 欄位要剛好是 {sorted(CLAIM_KEYS[kind])}")
    if kind == "manual":
        if not str(claim["text"]).strip():
            raise LedgerError(f"{pid}: manual 的 text 要寫出到期時怎麼判定")
        return
    if claim["symbol"] not in symbols:
        raise LedgerError(f"{pid}: {claim['symbol']} 不在 pipeline 抓價的標的內，改用 kind: manual")
    if kind == "range":
        low, high = _number(claim["low"], f"{pid}: claim.low"), _number(claim["high"], f"{pid}: claim.high")
        if not 0 < low < high:
            raise LedgerError(f"{pid}: range 的 low 要大於 0，而且小於 high")
        return
    if claim["op"] not in OPS:
        raise LedgerError(f"{pid}: claim.op 要是 '>' 或 '<'")
    if kind == "return":
        _number(claim["threshold_pct"], f"{pid}: claim.threshold_pct")
    else:
        if _number(claim["level"], f"{pid}: claim.level") <= 0:
            raise LedgerError(f"{pid}: claim.level 要大於 0")
    if kind == "held" and claim["basis"] not in BASES:
        raise LedgerError(f"{pid}: held 的 basis 要是 close（收盤）或 intraday（最低／最高價）")


def _written_on(pid):
    try:
        return datetime.strptime(str(pid)[2:10], "%Y%m%d").date()
    except ValueError:
        raise LedgerError(f"{pid}: id 裡的日期不是有效日期") from None


def _check_decision(pid, decision):
    if (not isinstance(decision, dict) or set(decision) != DECISION_KEYS
            or not all(str(decision[key] or "").strip() for key in DECISION_KEYS)):
        raise LedgerError(f"{pid}: decision 要寫 rule（對應知識庫哪一條決策規則）、if_hit 和 if_miss"
                          "（命中、未命中時這條規則怎麼走）")


def _check_review(pid, review, manual):
    allowed = {"date", "cause", "note", "action"} | ({"outcome"} if manual else set())
    if not isinstance(review, dict) or not {"date", "cause", "note", "action"} <= set(review) <= allowed:
        extra = "；自動評分的結果不寫在 outcome，手算時寫在 note" if not manual else ""
        raise LedgerError(f"{pid}: review 欄位要是 {sorted(allowed)}{extra}")
    _date(review["date"], f"{pid}: review.date")
    if review["cause"] not in CAUSES:
        raise LedgerError(f"{pid}: review.cause 要是 {sorted(CAUSES)} 之一")
    if review["action"] not in ACTIONS:
        raise LedgerError(f"{pid}: review.action 要是 {sorted(ACTIONS)} 之一")
    if manual and "outcome" in review and review["outcome"] not in OUTCOMES:
        raise LedgerError(f"{pid}: review.outcome 要是 hit 或 miss")


def check_entry(entry, symbols):
    if not isinstance(entry, dict):
        raise LedgerError("每筆預測要是一個 mapping")
    pid = entry.get("id", "<沒有 id>")
    missing, unknown = REQUIRED - set(entry), set(entry) - ENTRY_KEYS
    if missing:
        raise LedgerError(f"{pid}: 缺少欄位 {sorted(missing)}")
    if unknown:
        raise LedgerError(f"{pid}: 不認得的欄位 {sorted(unknown)}")
    if not ID_RE.match(str(pid)):
        raise LedgerError(f"{pid}: id 格式是 <W|E|P>-<YYYYMMDD>-<小寫英數與連字號>，例如 W-20261117-taiex")
    trigger = entry["trigger"]
    if trigger not in TRIGGERS:
        raise LedgerError(f"{pid}: trigger 要是 {sorted(TRIGGERS)} 之一")
    if trigger == "event":
        if not str(entry.get("event") or "").strip() or "event_time" not in entry:
            raise LedgerError(f"{pid}: event 類要寫 event（事件名稱）和 event_time（含時區）")
        _aware(entry["event_time"], f"{pid}: event_time")
    elif "event" in entry or "event_time" in entry:
        raise LedgerError(f"{pid}: 只有 trigger: event 才寫 event 和 event_time")
    if entry["method"] not in METHODS:
        raise LedgerError(f"{pid}: method 要是 {sorted(METHODS)} 之一")
    if entry["method"] != "judgment" and not str(entry.get("method_version") or "").strip():
        raise LedgerError(f"{pid}: 要寫 method_version：固定標準寫 v2，方法檔寫最新一筆更新紀錄的日期")
    if not str(entry["reasoning"]).strip():
        raise LedgerError(f"{pid}: reasoning 要寫理由和依據")
    horizon = entry["horizon_sessions"]
    if isinstance(horizon, bool) or not isinstance(horizon, int) or not 1 <= horizon <= MAX_HORIZON:
        raise LedgerError(f"{pid}: horizon_sessions 要是 1–{MAX_HORIZON} 的整數（交易日數）")
    probability = _number(entry["probability"], f"{pid}: probability")
    if not 0.5 <= probability < 1:
        raise LedgerError(f"{pid}: probability 要在 0.5 以上、1 以下；把條件改寫成你認為會發生的方向")
    claim = entry["claim"]
    _check_claim(pid, claim, symbols)
    if trigger == "weekly" and (claim.get("symbol") != WEEKLY_SYMBOL or horizon != WEEKLY_HORIZON):
        raise LedgerError(f"{pid}: 週預測的標的是 {WEEKLY_SYMBOL}，期間 {WEEKLY_HORIZON} 個交易日")
    if _written_on(pid) >= ACTIONABLE_FROM:
        if "decision" not in entry:
            raise LedgerError(f"{pid}: 要寫 decision：對應知識庫哪一條決策規則，命中和未命中時這條規則怎麼走")
        if claim["kind"] == "return" and claim["threshold_pct"] == 0:
            raise LedgerError(f"{pid}: 只預測漲跌對應不到動作；改寫成觸價（held）、幅度（close_at_check，"
                              "或門檻不是 0 的 return）或區間（range）")
    if "decision" in entry:
        _check_decision(pid, entry["decision"])
    if "written_at" in entry:
        _aware(entry["written_at"], f"{pid}: written_at")
    if "withdrawn" in entry:
        withdrawn = entry["withdrawn"]
        if not isinstance(withdrawn, dict) or set(withdrawn) != {"date", "reason"} or not str(withdrawn["reason"]).strip():
            raise LedgerError(f"{pid}: withdrawn 要寫 date 和 reason")
        _date(withdrawn["date"], f"{pid}: withdrawn.date")
    if "review" in entry:
        _check_review(pid, entry["review"], claim["kind"] == "manual")


def load_ledger(path: Path, symbols: set[str]) -> list[dict]:
    """Parse and check the ledger; raise LedgerError naming the entry and the fix."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("predictions"), list):
        raise LedgerError("預測紀錄要有頂層的 predictions 清單")
    seen = set()
    for entry in data["predictions"]:
        check_entry(entry, symbols)
        if entry["id"] in seen:
            raise LedgerError(f"{entry['id']}: id 重複；id 不能重複使用")
        seen.add(entry["id"])
    return data["predictions"]
