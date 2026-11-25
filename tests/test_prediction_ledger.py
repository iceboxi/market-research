"""#183: the knowledge-base prediction ledger must parse and follow the format before it merges."""
import copy
from pathlib import Path

import pytest

from market_research.prediction_ledger import LedgerError, check_entry, load_ledger, supported_symbols

ROOT = Path(__file__).resolve().parents[1]
LEDGER = ROOT / "knowledge" / "predictions.yaml"
SYMBOLS = supported_symbols(ROOT / "config")

VALID = {
    "id": "W-20261117-taiex", "trigger": "weekly", "method": "judgment", "reasoning": "理由",
    "claim": {"kind": "return", "symbol": "TAIEX", "op": ">", "threshold_pct": 0},
    "horizon_sessions": 5, "probability": 0.55,
}


def test_real_ledger_follows_the_format():
    entries = load_ledger(LEDGER, SYMBOLS)
    assert entries, "the ledger holds at least one prediction"
    assert len({e["id"] for e in entries}) == len(entries)


def test_supported_symbols_are_what_the_pipeline_prices():
    assert {"TAIEX", "0050.TW", "2330.TW", "2408.TW", "8299.TWO"} <= SYMBOLS
    assert "NVDA" not in SYMBOLS  # US universe is not scheduled


def test_valid_entry_passes():
    check_entry(copy.deepcopy(VALID), SYMBOLS)


def _with(**changes):
    entry = copy.deepcopy(VALID)
    for key, value in changes.items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    return entry


@pytest.mark.parametrize("entry, message", [
    (_with(probability=0.4), "把條件改寫成你認為會發生的方向"),
    (_with(probability=1), "probability 要在 0.5 以上、1 以下"),
    (_with(horizon_sessions=0), "horizon_sessions 要是 1–252 的整數"),
    (_with(horizon_sessions=4), "週預測的標的是 TAIEX，期間 5 個交易日"),
    (_with(claim={"kind": "return", "symbol": "NVDA", "op": ">", "threshold_pct": 0}), "改用 kind: manual"),
    (_with(claim={"kind": "held", "symbol": "TAIEX", "op": ">", "level": 37837.05}), "held 的 claim 欄位要剛好是"),
    (_with(claim={"kind": "held", "symbol": "TAIEX", "op": ">", "level": 1, "basis": "open"}), "basis 要是 close"),
    (_with(trigger="event"), "event 類要寫 event"),
    (_with(trigger="event", event="財報", event_time="2026-11-17T16:00:00"), "event_time 要帶時區"),
    (_with(event_time="2026-11-17T16:00:00-05:00"), "只有 trigger: event 才寫"),
    (_with(method="forced-selling"), "要寫 method_version"),
    (_with(id="weekly-1"), "id 格式是"),
    (_with(reasoning=None), "缺少欄位 ['reasoning']"),
    (_with(outcome="hit"), "不認得的欄位 ['outcome']"),
    (_with(review={"date": "2026-11-24", "cause": "noise", "note": "n", "action": "keep", "outcome": "hit"}),
     "自動評分的結果不寫在 outcome"),
    (_with(withdrawn={"date": "2026-11-20"}), "withdrawn 要寫 date 和 reason"),
    (_with(claim={"kind": "range", "symbol": "TAIEX", "low": 37600, "high": 35750}), "range 的 low 要大於 0，而且小於 high"),
    (_with(claim={"kind": "range", "symbol": "TAIEX", "op": ">", "low": 35750, "high": 37600}), "range 的 claim 欄位要剛好是"),
    (_with(decision={"rule": "0050 停止加碼", "if_hit": "維持"}), "decision 要寫 rule"),
    (_with(decision={"rule": "0050 停止加碼", "if_hit": "維持", "if_miss": " "}), "decision 要寫 rule"),
    (_with(id="W-20261340-taiex"), "id 裡的日期不是有效日期"),
])
def test_bad_entries_fail_with_the_fix(entry, message):
    with pytest.raises(LedgerError, match=message.replace("[", r"\[").replace("]", r"\]")):
        check_entry(entry, SYMBOLS)


def test_manual_claim_may_record_its_outcome_in_review():
    entry = _with(id="E-20261117-nvda-guide", trigger="event", event="輝達財報",
                  event_time="2026-11-17T16:00:00-05:00", horizon_sessions=1,
                  claim={"kind": "manual", "text": "輝達第四季營收指引中值高於 1,150 億美元"},
                  review={"date": "2026-11-18", "cause": "correct", "note": "n", "action": "keep",
                          "outcome": "hit"})
    check_entry(entry, SYMBOLS)


def test_duplicate_ids_fail(tmp_path):
    path = tmp_path / "predictions.yaml"
    path.write_text("predictions:\n"
                    "  - {id: W-20261117-taiex, trigger: weekly, method: judgment, reasoning: r,\n"
                    "     claim: {kind: return, symbol: TAIEX, op: '>', threshold_pct: 0},\n"
                    "     horizon_sessions: 5, probability: 0.55}\n" * 1
                    + "  - {id: W-20261117-taiex, trigger: weekly, method: judgment, reasoning: r,\n"
                    "     claim: {kind: return, symbol: TAIEX, op: '>', threshold_pct: 0},\n"
                    "     horizon_sessions: 5, probability: 0.55}\n", encoding="utf-8")
    with pytest.raises(LedgerError, match="id 重複"):
        load_ledger(path, SYMBOLS)


DECISION = {"rule": "0050 停止加碼：收盤跌破 39,385", "if_hit": "停止加碼維持", "if_miss": "重算參考價位再談分批"}
TOUCH = {"kind": "held", "symbol": "TAIEX", "op": ">", "level": 34232, "basis": "intraday"}


def test_range_claim_passes():
    check_entry(_with(claim={"kind": "range", "symbol": "TAIEX", "low": 35750, "high": 37600}), SYMBOLS)


def test_predictions_written_from_11_22_name_their_decision_rule():
    with pytest.raises(LedgerError, match="要寫 decision"):
        check_entry(_with(id="W-20261122-taiex", claim=TOUCH), SYMBOLS)
    check_entry(_with(id="W-20261122-taiex", claim=TOUCH, decision=DECISION), SYMBOLS)
    check_entry(_with(decision=DECISION), SYMBOLS)  # older ids may carry one too


def test_a_bare_up_down_call_is_rejected_from_11_22():
    # The draft W-20261120-taiex (TAIEX 5-day return > 0) that the user found impossible to act on.
    draft = _with(id="W-20261122-taiex", decision=DECISION,
                  claim={"kind": "return", "symbol": "TAIEX", "op": ">", "threshold_pct": 0})
    with pytest.raises(LedgerError, match="只預測漲跌對應不到動作"):
        check_entry(draft, SYMBOLS)
    check_entry({**draft, "claim": {**draft["claim"], "threshold_pct": 3}}, SYMBOLS)  # a magnitude is fine
    check_entry(copy.deepcopy(VALID), SYMBOLS)  # entries written before 11/22 keep their format
