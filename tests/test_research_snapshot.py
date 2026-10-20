"""Source-policy projection at the compact research snapshot seam."""
import json
from copy import deepcopy

import pytest

from market_research.fundamentals import TW_PROFILE, TW_REVENUE
from market_research.research_snapshot import SnapshotError, fingerprint, prepare_snapshot, validate_snapshot


def report(stamp="2026-10-19T12:00:00+00:00", complete=True):
    return {
        "schema_version": 4, "symbol": "2330.TW", "market": "tw", "generated_utc": stamp,
        "complete": complete,
        "issuer": {"company_name": "Fixture Semiconductor" if complete else None,
                   "profile": {"source": TW_PROFILE, "reported_at": "1151019"},
                   "facts": [{"metric": "monthly_reported_revenue", "value": 1000,
                              "unit": "TWD_thousands", "period": "11509",
                              "reported_at": "1151010", "source": TW_REVENUE}]},
        "technical": {"status": "available" if complete else "unavailable", "source": "fixture_daily",
                      "last_session": "2026-10-19" if complete else None,
                      "input_sha256": "b" * 64, "price_basis": "unadjusted",
                      "analytical_close": 123.45, "ohlcv": ["DO_NOT_STORE_PRICE_SERIES"]},
        "official_events": {"status": "available", "source": "https://openapi.twse.com.tw/v1/opendata/t187ap04_L",
                            "snapshot_date": "2026-10-19", "coverage": "recent_daily_snapshot_only_not_a_full_history",
                            "events": [{"title": "DO_NOT_STORE_DISCLOSURE_BODY"}]},
        "research_readiness": {"components": {"financial": {"status": "unavailable"},
                                  "valuation": {"status": "not_evaluated"},
                                  "trade_plan": {"status": "not_evaluated"}}},
    }


def identity(run_id="100", stamp="2026-10-19T12:01:00+00:00"):
    return {"repository": "owner/repo", "run_id": run_id, "run_attempt": 1,
            "code_sha": "a" * 40, "observed_at_utc": stamp}


def test_retains_permitted_monthly_values_and_only_price_event_metadata():
    snapshot = prepare_snapshot(report(), identity())
    validate_snapshot(snapshot)
    assert snapshot["monthly_revenue"][0]["value"] == 1000
    assert snapshot["monthly_revenue"][0]["unit"] == "TWD_thousands"
    assert snapshot["monthly_revenue"][0]["policy"] == "twse_monthly_ogdl_v1"
    assert snapshot["issuer"]["company_name"] == "Fixture Semiconductor"
    assert snapshot["technical"]["session"] == "2026-10-19"
    assert snapshot["technical"]["input_sha256"] == "b" * 64
    assert snapshot["readiness"]["valuation"] == "not_evaluated"
    assert snapshot["run"]["run_url"] == "https://github.com/owner/repo/actions/runs/100"
    assert snapshot["evaluation_cutoff_utc"] != snapshot["observed_at_utc"]
    assert "prices_metadata_only" in snapshot["comparison_limits"]
    assert "DO_NOT_STORE" not in json.dumps(snapshot)
    assert "123.45" not in json.dumps(snapshot)


def test_unknown_sources_and_future_periods_do_not_become_public_numeric_evidence():
    payload = report()
    payload["issuer"]["profile"]["source"] = "https://example.invalid/profile?token=SECRET"
    payload["issuer"]["facts"] += [
        {"metric": "net_income", "value": 99, "source": "https://example.invalid/financials"},
        {**payload["issuer"]["facts"][0], "period": "11511"},
    ]
    result = prepare_snapshot(payload, identity())
    assert result["issuer"]["company_name"] is None
    assert len(result["monthly_revenue"]) == 1
    assert "future_period_evidence_omitted" in result["comparison_limits"]
    assert "unapproved_numeric_evidence_omitted" in result["comparison_limits"]
    assert "SECRET" not in json.dumps(result)


@pytest.mark.parametrize("field", ["ohlcv", "response", "disclosure_body"])
def test_unknown_fields_rejected_even_with_valid_checksum(field):
    snapshot = prepare_snapshot(report(), identity())
    snapshot[field] = "raw"
    snapshot["id"] = fingerprint({k: v for k, v in snapshot.items() if k != "id"})
    with pytest.raises(SnapshotError):
        validate_snapshot(snapshot)


def test_forged_source_budget_and_future_session_fail_closed():
    original = prepare_snapshot(report(), identity())
    for kind in ("source", "budget", "session", "checksum"):
        snapshot = deepcopy(original)
        if kind == "source":
            snapshot["monthly_revenue"][0]["source"] = "https://example.invalid/financials"
        elif kind == "budget":
            snapshot["issuer"]["company_name"] = "x" * 20_001
        elif kind == "session":
            snapshot["technical"]["session"] = "2026-10-20"
        else:
            snapshot["monthly_revenue"][0]["value"] += 1
        with pytest.raises(SnapshotError):
            validate_snapshot(snapshot)


def test_future_announced_revenue_is_omitted_and_missing_values_stay_missing():
    payload = report(complete=False)
    payload["issuer"]["facts"][0]["reported_at"] = "1151020"
    snapshot = prepare_snapshot(payload, identity())
    assert snapshot["monthly_revenue"] == []
    assert snapshot["issuer"]["company_name"] is None
    assert snapshot["technical"]["session"] is None
    assert snapshot["execution"]["status"] == "partial"
    assert "future_period_evidence_omitted" in snapshot["comparison_limits"]


def test_execution_start_is_separate_and_old_snapshots_remain_readable():
    old = prepare_snapshot(report(), identity())
    assert old["schema_version"] == 1
    payload = report()
    payload["started_utc"] = "2026-10-19T11:59:50+00:00"
    current = prepare_snapshot(payload, identity())
    assert current["schema_version"] == 2
    assert current["started_at_utc"] == payload["started_utc"]
    assert current["started_at_utc"] != current["evaluation_cutoff_utc"]
    validate_snapshot(old)
    validate_snapshot(current)


@pytest.mark.parametrize("stamp", ["1151020", "1150230", "not_a_date"])
def test_invalid_or_future_profile_cannot_be_verified_evidence(stamp):
    payload = report()
    payload["issuer"]["profile"]["reported_at"] = stamp
    snapshot = prepare_snapshot(payload, identity())
    assert snapshot["issuer"]["company_name"] is None
    assert snapshot["issuer"]["reported_at"] is None
    assert snapshot["readiness"]["instrument"] == "unknown"
    assert "invalid_or_future_profile_omitted" in snapshot["comparison_limits"]


def test_same_roc_period_with_leading_zero_cannot_hide_duplicate_values():
    payload = report()
    payload["issuer"]["facts"].append({**payload["issuer"]["facts"][0], "period": "011509", "value": 1100})
    with pytest.raises(SnapshotError):
        prepare_snapshot(payload, identity())
