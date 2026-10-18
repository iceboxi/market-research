"""Event-watch baseline, repeatability, data loss and optional US coverage."""
from datetime import datetime, timezone
import json

from market_research.event_monitor import build_snapshot, compare_snapshots
from scripts.event_watch import watch

NOW = datetime(2026, 10, 19, 12, tzinfo=timezone.utc)
SOURCE = "https://openapi.twse.com.tw/v1/opendata/t187ap04_L"


def feed(ids, status="available"):
    return {"source": SOURCE, "status": status,
            "coverage": "recent_daily_snapshot_only_not_a_full_history",
            "events": [{"event_id": item} for item in ids]}


def test_initial_baseline_no_alert():
    current = build_snapshot("2330.TW", "tw", feed(["tw-material-a"]), NOW)
    receipt, merged = compare_snapshots(None, current)
    assert receipt["status"] == "baseline_initialized"
    assert receipt["notify"] is False
    assert merged["seen_ids"] == ["tw-material-a"]


def test_new_id_triggers_review_once_and_does_not_forget_disappeared_id():
    first = build_snapshot("2330.TW", "tw", feed(["tw-material-a"]), NOW)
    later = build_snapshot("2330.TW", "tw", feed(["tw-material-b"]), NOW)
    change, merged = compare_snapshots(first, later)
    assert change["status"] == "changed"
    assert change["new_event_ids"] == ["tw-material-b"]
    assert merged["seen_ids"] == ["tw-material-a", "tw-material-b"]
    repeat, _ = compare_snapshots(merged, later)
    assert repeat["status"] == "unchanged"


def test_source_failure_never_erases_baseline_or_sends_alert():
    first = build_snapshot("2330.TW", "tw", feed(["tw-material-a"]), NOW)
    current = build_snapshot("2330.TW", "tw", feed([], "unavailable"), NOW)
    change, merged = compare_snapshots(first, current)
    assert change["status"] == "coverage_unknown"
    assert change["notify"] is False
    assert merged is None


def test_out_of_order_cannot_override_prior():
    first = build_snapshot("2330.TW", "tw", feed(["tw-material-a"]), NOW)
    before = build_snapshot("2330.TW", "tw", feed(["tw-material-b"]),
                            datetime(2026, 10, 18, tzinfo=timezone.utc))
    change, merged = compare_snapshots(first, before)
    assert change["status"] == "state_incompatible"
    assert merged is None


def test_watchlist_writes_receipt_and_proposal(tmp_path, monkeypatch):
    cfg = tmp_path / "watch.yaml"
    cfg.write_text("symbols:\n  - market: tw\n    symbol: 2330.TW\n")
    def stub(symbol, now, get):
        return feed(["tw-material-a"])
    monkeypatch.setattr("scripts.event_watch.tw_material_events", stub)
    res = watch(cfg, tmp_path / "state", tmp_path / "output", now=NOW)
    assert res["status"] == "complete"
    assert res["reports"][0]["change_status"] == "baseline_initialized"
    file = tmp_path / "output/proposed_state/tw/2330.TW.json"
    assert json.loads(file.read_text())["seen_ids"] == ["tw-material-a"]
    assert "not an alert" in (tmp_path / "output/watch_summary.md").read_text()


def test_watchlist_second_scan_detects_new_ids(tmp_path, monkeypatch):
    cfg = tmp_path / "watch.yaml"
    cfg.write_text("symbols:\n  - market: tw\n    symbol: 2330.TW\n")
    state = tmp_path / "state/tw"
    state.mkdir(parents=True)
    state.joinpath("2330.TW.json").write_text(json.dumps(
        build_snapshot("2330.TW", "tw", feed(["tw-material-a"]), NOW)
    ))
    monkeypatch.setattr("scripts.event_watch.tw_material_events",
                        lambda symbol, now, get: feed(["tw-material-b"]))
    res = watch(cfg, tmp_path / "state", tmp_path / "output", now=NOW)
    assert res["reports"][0]["new_event_ids"] == ["tw-material-b"]
    assert res["reports"][0]["requires_research_review"] is True


def test_no_secret_us_watch_requires_explicit_configuration(tmp_path):
    cfg = tmp_path / "watch.yaml"
    cfg.write_text("symbols:\n  - market: us\n    symbol: AAPL\n")
    res = watch(cfg, tmp_path / "state", tmp_path / "output", now=NOW, user_agent="")
    assert res["status"] == "partial"
    assert res["reports"][0]["source_status"] == "unavailable"
    assert not res["reports"][0]["updated_state"]
