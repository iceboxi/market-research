"""Offline tests for scan -> company report orchestration and safety gates."""
import json
from datetime import datetime, timezone

from scripts.scan_company_research import candidates, execute

NOW = datetime(2026, 10, 18, tzinfo=timezone.utc)
DIGEST = "a" * 64


def artifacts(tmp_path, signals=None, quality=None, health=None, manifest=None):
    manifest = manifest or {"strict_freshness": True, "error_count": 0,
                            "official_mismatch_count": 0, "scanned_symbols": 1,
                            "matching_signals": len(signals or []),
                            "strategies": [{"id": "sakata_three_soldiers",
                                            "version": "0.1.0"}]}
    quality = quality or {"symbols": [{"market": "tw", "symbol": "2330.TW",
                                      "last_date": "2026-10-16",
                                      "input_sha256": DIGEST}], "errors": []}
    health = health or {"health": "healthy", "scan_outcome": "success", "run_id": "123"}
    for path, payload in (("manifest.json", manifest), ("data_quality.json", quality),
                          ("signals.json", signals or []), ("health_report.json", health)):
        (tmp_path / path).write_text(json.dumps(payload))
    return tmp_path


def signal(symbol="2330.TW", market="tw", day="2026-10-16"):
    return {"symbol": symbol, "market": market, "trade_date": day,
            "strategy_id": "sakata_three_soldiers", "strategy_version": "0.1.0",
            "matched": True}


def test_no_matches_does_not_fetch_issuer(tmp_path):
    folder = artifacts(tmp_path)
    def never(*args, **kwargs):
        raise AssertionError("No network on no-match")
    result = execute(folder, tmp_path / "reports", research_fn=never, now=NOW)
    assert result["status"] == "no_candidates"
    assert result["attempted_count"] == 0


def test_tw_matched_stock_generates_source_linked_report(tmp_path):
    s = [signal()]
    artifacts(tmp_path, signals=s)
    calls = []
    def research(symbol, out, now, sec_user_agent):
        calls.append((symbol, now))
        return {"complete": True, "technical": {"status": "available",
                "last_session": "2026-10-16", "input_sha256": DIGEST},
                "valuation": {"status": "not_evaluated"},
                "research_readiness": {"stage": "preliminary_only"}}
    result = execute(tmp_path, tmp_path / "reports", research_fn=research, now=NOW)
    assert calls == [("2330.TW", NOW)]
    assert result["status"] == "complete"
    assert result["candidate_reports"][0]["readiness"] == "preliminary_only"
    assert result["candidate_reports"][0]["report_path"] == "2330.TW/report.json"


def test_scan_hash_drift_blocks_association(tmp_path):
    artifacts(tmp_path, signals=[signal()])
    def research(symbol, out, now, sec_user_agent):
        return {"complete": True, "technical": {"status": "available",
                "last_session": "2026-10-16", "input_sha256": "b" * 64}}
    result = execute(tmp_path, tmp_path / "reports", research_fn=research, now=NOW)
    assert result["status"] == "partial"
    assert result["candidate_reports"][0]["status"] == "blocked_data_drift"


def test_unhealthy_scan_refuses_research(tmp_path):
    artifacts(tmp_path, signals=[signal()],
              health={"health": "degraded", "scan_outcome": "success", "run_id": "x"})
    result = execute(tmp_path, tmp_path / "reports", now=NOW)
    assert result["status"] == "blocked"
    assert result["candidate_reports"] == []


def test_mismatched_trade_date_and_unrecognized_strategy_block(tmp_path):
    manifest = {"strict_freshness": True, "error_count": 0,
                "official_mismatch_count": 0, "scanned_symbols": 1,
                "matching_signals": 1,
                "strategies": [{"id": "sakata_three_soldiers", "version": "0.1.0"}]}
    quality = {"symbols": [{"market": "tw", "symbol": "2330.TW",
                            "last_date": "2026-10-16", "input_sha256": DIGEST}], "errors": []}
    health = {"health": "healthy", "scan_outcome": "success"}
    try:
        candidates(manifest, quality, [signal(day="2026-10-15")], health)
        assert False
    except ValueError:
        pass
    bad = signal()
    bad["strategy_version"] = "99.0.0"
    try:
        candidates(manifest, quality, [bad], health)
        assert False
    except ValueError:
        pass


def test_no_secret_blocks_us_with_visible_reason(tmp_path):
    us = [signal(symbol="AAPL", market="us")]
    quality = {"symbols": [{"market": "us", "symbol": "AAPL",
                            "last_date": "2026-10-16", "input_sha256": DIGEST}], "errors": []}
    artifacts(tmp_path, signals=us, quality=quality)
    result = execute(tmp_path, tmp_path / "reports", now=NOW, sec_user_agent="")
    assert result["status"] == "partial"
    assert result["candidate_reports"][0]["status"] == "blocked_configuration"


def test_invalid_symbol_is_rejected_before_network(tmp_path):
    artifacts(tmp_path, signals=[signal(symbol="../../bad", market="tw")])
    result = execute(tmp_path, tmp_path / "reports", now=NOW)
    assert result["status"] == "blocked"
    assert result["attempted_count"] == 0
