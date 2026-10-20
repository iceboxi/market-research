"""Semantic report comparisons against independent, bounded evidence fixtures."""
from market_research.research_comparison import compare_snapshots, render_comparison
from market_research.research_snapshot import prepare_snapshot
from test_research_snapshot import report, identity


def snapshot(run="100", minute="00", **overrides):
    payload = report(f"2026-10-19T12:{minute}:00+00:00")
    payload.update(overrides)
    return prepare_snapshot(payload, identity(run, f"2026-10-19T12:{minute}:30+00:00"))


def test_first_snapshot_is_baseline_and_time_run_export_refreshes_are_unchanged():
    before = snapshot()
    assert compare_snapshots(None, before)["categories"] == ["baseline"]
    payload = report("2026-10-19T12:10:00+00:00")
    payload["issuer"]["facts"][0]["reported_at"] = "1151011"
    after = prepare_snapshot(payload, identity("101", "2026-10-19T12:10:30+00:00"))
    result = compare_snapshots(before, after)
    assert result["categories"] == ["unchanged"]
    assert result["changes"] == []
    assert "prices_metadata_only" in result["limitations"]


def test_new_period_and_same_period_revision_have_distinct_evidence():
    before = snapshot()
    payload = report("2026-10-19T12:10:00+00:00")
    payload["issuer"]["facts"][0]["value"] = 1100
    revised = prepare_snapshot(payload, identity("101", "2026-10-19T12:10:30+00:00"))
    delta = compare_snapshots(before, revised)
    assert delta["categories"] == ["revision"]
    assert delta["changes"] == [{"kind": "revision", "component": "monthly_revenue",
                                  "period": "11509", "reason": "reported_value_changed"}]
    payload["issuer"]["facts"][0]["period"] = "11510"
    newer = prepare_snapshot(payload, identity("102", "2026-10-19T12:11:30+00:00"))
    delta = compare_snapshots(before, newer)
    assert delta["categories"] == ["new_period"]
    assert delta["changes"][0]["period"] == "11510"


def test_source_loss_restore_and_stale_use_real_last_known_good_without_zero():
    before = snapshot()
    payload = report("2026-10-19T12:10:00+00:00", complete=False)
    payload["issuer"]["facts"] = []
    payload["official_events"]["status"] = "unavailable"
    failed = prepare_snapshot(payload, identity("101", "2026-10-19T12:10:30+00:00"))
    result = compare_snapshots(before, failed, {"monthly_revenue": before, "technical": before})
    assert set(result["categories"]) == {"coverage_change", "incomparable"}
    assert result["last_known_good"]["monthly_revenue"] == before["id"]
    assert {c["component"] for c in result["changes"]} >= {"issuer", "monthly_revenue", "technical", "events"}
    restored = snapshot("102", "20")
    result = compare_snapshots(failed, restored, {"monthly_revenue": before})
    assert "coverage_change" in result["categories"]
    assert "new_period" not in result["categories"]
    assert "revision" not in result["categories"]
    payload = report("2026-10-19T12:30:00+00:00")
    payload["technical"]["warnings"] = [{"reason": "stale_history_allowed_for_research"}]
    stale = prepare_snapshot(payload, identity("103", "2026-10-19T12:30:30+00:00"))
    assert "coverage_change" in compare_snapshots(restored, stale)["categories"]


def test_schema_source_and_omitted_price_inputs_are_explicitly_incomparable():
    before = snapshot()
    payload = report("2026-10-19T12:10:00+00:00")
    payload["started_utc"] = "2026-10-19T12:09:00+00:00"
    payload["technical"]["source"] = "other_daily_provider"
    payload["technical"]["input_sha256"] = "c" * 64
    after = prepare_snapshot(payload, identity("101", "2026-10-19T12:10:30+00:00"))
    result = compare_snapshots(before, after)
    assert result["categories"] == ["incomparable"]
    assert {c["reason"] for c in result["changes"]} >= {"schema_changed", "price_inputs_not_retained", "source_or_basis_changed"}


def test_model_identity_changes_are_distinct_from_source_data_changes():
    payload = report()
    payload.update(started_utc="2026-10-19T11:59:00+00:00", model_identity="a" * 64)
    before = prepare_snapshot(payload, identity())
    payload["model_identity"] = "b" * 64
    after = prepare_snapshot(payload, identity("101", "2026-10-19T12:01:30+00:00"))
    assert compare_snapshots(before, after)["categories"] == ["model_change"]


def test_renderer_one_characterization_remains_byte_identical():
    from scripts.research_state import render_publication, body_hash, snapshot_path, publication_path
    # Captured from existing renderer 1 before introducing version 2.
    value = prepare_snapshot(report(), identity())
    identifier = "d" * 64
    records = {snapshot_path(value["id"]): value, publication_path(identifier): {
        "snapshot_id": value["id"], "last_success_id": value["id"], "renderer_version": 1}}
    assert body_hash(render_publication(records, identifier, "research-state")) == "f5b305d6f544f81d1a5092028c789c8d7ff10048ff161f2b903c6de9c9987c85"


def test_newly_retrieved_values_do_not_revise_an_earlier_historical_cutoff():
    before = snapshot()
    payload = report("2026-10-19T11:00:00+00:00")
    payload["issuer"]["facts"][0]["value"] = 1100
    historical = prepare_snapshot(payload, identity("101", "2026-10-19T12:10:00+00:00"))
    result = compare_snapshots(before, historical)
    assert "incomparable" in result["categories"]
    assert "revision" not in result["categories"]


def test_equivalent_roc_period_representation_does_not_invent_new_period():
    before = snapshot()
    payload = report()
    payload["issuer"]["facts"][0]["period"] = "011509"
    after = prepare_snapshot(payload, identity("101", "2026-10-19T12:02:30+00:00"))
    assert compare_snapshots(before, after)["categories"] == ["unchanged"]


def test_selected_last_good_cutoff_cannot_look_ahead_of_current_historical_cutoff():
    good = snapshot()
    failed_report = report("2026-10-19T11:00:00+00:00", False)
    failed_report["issuer"]["facts"] = []
    failed = prepare_snapshot(failed_report, identity("101", "2026-10-19T12:01:30+00:00"))
    restored_report = report("2026-10-19T11:30:00+00:00")
    restored_report["issuer"]["facts"][0]["value"] = 1100
    restored_report["issuer"]["company_name"] = "Corrected fixture name"
    restored = prepare_snapshot(restored_report, identity("102", "2026-10-19T12:02:30+00:00"))
    result = compare_snapshots(failed, restored, {"monthly_revenue": good, "issuer": good})
    assert "coverage_change" in result["categories"]
    assert "incomparable" in result["categories"]
    assert "revision" not in result["categories"]


def test_restored_identity_uses_retained_last_good_to_detect_name_revision():
    before = snapshot()
    failed = prepare_snapshot(report("2026-10-19T12:10:00+00:00", complete=False),
                              identity("101", "2026-10-19T12:10:30+00:00"))
    assert failed["issuer"]["company_name"] is None
    payload = report("2026-10-19T12:20:00+00:00")
    payload["issuer"]["company_name"] = "Corrected fixture name"
    restored = prepare_snapshot(payload, identity("102", "2026-10-19T12:20:30+00:00"))
    result = compare_snapshots(failed, restored, {"issuer": before})
    assert "revision" in result["categories"]
    assert any(item["component"] == "issuer" and item["kind"] == "revision" for item in result["changes"])
    assert result["last_known_good"]["issuer"] == before["id"]
    rendered = render_comparison(result, {s["id"]: s for s in (before, failed, restored)})
    assert "Fixture Semiconductor → Corrected fixture name" in rendered
    assert f"比較 baseline snapshot `{before['id']}`" in rendered
