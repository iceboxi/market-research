"""#183 PL3: a prediction edited after First seen is void; a deleted one is listed."""
import copy
from datetime import datetime

import pytest
import yaml

from scripts.prediction_review import sync
from tests.test_prediction_review import FakeSink

NOW = datetime.fromisoformat("2026-11-18T10:00:00+08:00")  # nothing due yet
SEEN = datetime.fromisoformat("2026-11-18T00:03:59+08:00")
ORIGINAL = {
    "id": "E-20261117-nvda", "trigger": "event", "event": "輝達財報",
    "event_time": "2026-11-17T16:00:00-05:00", "method": "judgment", "reasoning": "理由",
    "claim": {"kind": "return", "symbol": "TAIEX", "op": ">", "threshold_pct": 0},
    "horizon_sessions": 1, "probability": 0.55, "written_at": "2026-11-18T00:30:00+08:00",
}


def run(current, history_entries, sink=None):
    sink = sink or FakeSink()
    history = {e["id"]: {"first_seen": SEEN, "entry": e} for e in history_entries}
    result = sync(sink, current, history, NOW, run_id="1", run_url="https://example.invalid/run/1")
    return sink, result, {r["id"]: r for r in result["records"]}


def changed(**fields):
    entry = copy.deepcopy(ORIGINAL)
    entry.update(fields)
    return entry


@pytest.mark.parametrize("fields, names", [
    ({"claim": {"kind": "return", "symbol": "TAIEX", "op": ">", "threshold_pct": -1}}, "claim"),
    ({"probability": 0.6}, "probability"),
    ({"horizon_sessions": 2}, "horizon_sessions"),
    ({"reasoning": "改寫的理由"}, "reasoning"),
    ({"method": "forced-selling", "method_version": "2026-11-12"}, "method、method_version"),
    ({"event_time": "2026-11-18T16:00:00-05:00"}, "event_time"),
])
def test_an_edited_field_voids_the_prediction(fields, names):
    sink, result, records = run([changed(**fields)], [ORIGINAL])
    record = records["E-20261117-nvda"]
    assert (record["status"], record["void_reason"]) == ("void", "edited")
    assert record["reason"] == f"合併後改過：{names}"
    assert result["changes"] == ["E-20261117-nvda"] and "合併後改過" in sink.comments[901][0]


def test_review_and_withdrawn_may_change():
    current = changed(review={"date": "2026-11-19", "cause": "noise", "note": "n", "action": "keep"})
    _, _, records = run([current], [ORIGINAL])
    assert records["E-20261117-nvda"]["status"] == "pending"
    current = changed(withdrawn={"date": "2026-11-19", "reason": "重複"})
    _, _, records = run([current], [ORIGINAL])
    assert records["E-20261117-nvda"]["status"] == "withdrawn"


def test_layout_and_quoting_are_not_edits():
    # Same values written with other quoting, key order and an unquoted timestamp.
    text = ("predictions:\n  - probability: 0.55\n    horizon_sessions: 1\n    id: 'E-20261117-nvda'\n"
            "    trigger: event\n    event: 輝達財報\n    event_time: 2026-11-17T16:00:00-05:00\n"
            "    method: judgment\n    reasoning: 理由  # 註解\n"
            "    claim: {kind: return, symbol: TAIEX, op: '>', threshold_pct: 0.0}\n"
            "    written_at: \"2026-11-18T00:30:00+08:00\"\n")
    [current] = yaml.safe_load(text)["predictions"]
    _, _, records = run([current], [ORIGINAL])
    assert records["E-20261117-nvda"]["status"] == "pending"


def test_a_deleted_prediction_is_listed():
    other = changed(id="W-20261117-taiex", trigger="weekly", horizon_sessions=5)
    for key in ("event", "event_time"):
        other.pop(key)
    sink, result, _ = run([other], [ORIGINAL, other])
    assert result["deleted"] == ["E-20261117-nvda"]
    body = sink.issues[901]["body"]
    assert "## 已刪除的預測" in body
    assert "| `E-20261117-nvda` | 2026-11-18 00:03 | 加權指數 1 個交易日報酬 > 0% |" in body


def test_an_edited_prediction_is_never_judged():
    calls = []

    def bars_fn(symbol, since):
        calls.append(symbol)
        raise AssertionError("an edited prediction must not fetch prices")
    sink = FakeSink()
    history = {"E-20261117-nvda": {"first_seen": SEEN, "entry": ORIGINAL}}
    result = sync(sink, [changed(probability=0.9)], history,
                  datetime.fromisoformat("2026-11-18T16:00:00+08:00"),  # due
                  run_id="1", run_url="https://example.invalid/run/1", bars_fn=bars_fn)
    assert calls == [] and result["records"][0]["status"] == "void"
