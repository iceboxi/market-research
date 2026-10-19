from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
import json
from scripts.prospective_observe import collect
from scripts.prospective_archive import archive

def health():
    return {"event":"schedule","health":"healthy","market":"tw",
      "errors":0,"requested":10,"scanned":10,
      "session_dates":{"tw":["2026-10-19"]},
      "input_hashes":[],"run_url":"https://github.com/test/actions/runs/123",
      "run_id":"123"}

def test_prospective_gates_before_new_market_fetch(tmp_path):
    h=health()
    h["event"]="push"
    with pytest.raises(ValueError, match="scheduled"):
        collect(h,"tw",tmp_path/"receipt.json",
                now=datetime(2026,10,19,13,tzinfo=timezone.utc))
    h=health()
    h["health"]="critical"
    with pytest.raises(ValueError, match="healthy"):
        collect(h,"tw",tmp_path/"receipt.json",
                now=datetime(2026,10,19,13,tzinfo=timezone.utc))
    h=health()
    h["scanned"]=9
    with pytest.raises(ValueError, match="Incomplete"):
        collect(h,"tw",tmp_path/"receipt.json",
                now=datetime(2026,10,19,13,tzinfo=timezone.utc))

def test_prospective_archive_rejects_conflicting_session_without_git(monkeypatch,tmp_path):
    import scripts.prospective_archive as p
    monkeypatch.chdir(tmp_path)
    calls=[]
    def fake(*args,**kwargs):
        calls.append(args)
        class Proc:
            returncode=0
            stderr=""
        return Proc()
    monkeypatch.setattr(p,"run",fake)
    receipt={"market":"tw","session_date":"2026-10-19","freeze_hash":"1234567890abcdef",
             "run_id":"11"}
    assert archive(receipt).endswith("tw/2026-10-19.json")
    assert archive(receipt).endswith("tw/2026-10-19.json")
    with pytest.raises(ValueError,match="Immutable"):
        archive({**receipt,"run_id":"12"})
    assert len([c for c in calls if c[:2]==("git","push")])==1


def test_prospective_collect_valid_receipt_and_hash_mismatch(monkeypatch,tmp_path):
    from datetime import date
    from pathlib import Path
    import shutil
    import scripts.prospective_observe as obs
    from scripts.prospective_observe import collect
    root=Path(__file__).resolve().parents[1]
    cfg=tmp_path/"config"
    cfg.mkdir()
    shutil.copyfile(root/"config/strategies.yaml",cfg/"strategies.yaml")
    shutil.copyfile(root/"config/markets.yaml",cfg/"markets.yaml")
    monkeypatch.setattr(obs,"expected_complete_session",lambda market,now: date(2026,10,19))
    monkeypatch.setattr(obs,"fingerprint",lambda: "abcd"*16)
    def mock_scan(market,period,out,config_dir,provider,now,strict_freshness):
        assert strict_freshness is True
        assert market=="tw" and period=="6mo"
        assert len(__import__("yaml").safe_load((config_dir/"strategies.yaml").read_text())["strategies"])==9
        out.mkdir(parents=True,exist_ok=True)
        rows=[{"market":"tw","symbol":f"T{i}","input_sha256":f"hash{i}"}
              for i in range(10)]
        (out/"data_quality.json").write_text(json.dumps({"symbols":rows}))
        observations=[{"symbol":f"T{i}","strategy_id":f"S{j}",
            "strategy_version":"0.1.0","trade_date":"2026-10-19",
            "matched":False,"metrics":{}} for i in range(10) for j in range(9)]
        (out/"screening_results.json").write_text(json.dumps(observations))
        return {"error_count":0,"scanned_symbols":10,
            "strategies":[{"id":f"S{j}","version":"0.1.0"} for j in range(9)]}
    monkeypatch.setattr(obs,"run_scan",mock_scan)
    h=health()
    h["input_hashes"]=[{"market":"tw","symbol":f"T{i}","sha256":f"hash{i}"} for i in range(10)]
    monkeypatch.setattr(obs,"select_variant",lambda candidate: {"status":"implemented"})
    out=tmp_path/"receipt.json"
    result=collect(h,"tw",out,cfg,now=datetime(2026,10,19,13,tzinfo=timezone.utc))
    assert result["freeze_hash"]=="abcd"*16
    assert not result["observations"]
    assert len(result["strategy_versions"])==9
    assert all(not row["id"].startswith(("rsi_","ma_")) for row in result["strategy_versions"])
    assert not result["is_strategy_performance_evidence"]
    assert result["market"] == "tw"
    # Explicit opt-in schema v2 does not change legacy scheduled schema v1.
    revision = {
        "code_sha": "a" * 40,
        "config_sha256": "abcd" * 16,
        "provider_sha256": "b" * 64,
        "calendar_sha256": "c" * 64,
        "method_sha256": "d" * 64,
    }
    monkeypatch.setattr(obs, "runtime_revision", lambda: revision)
    h["source_sha"] = "a" * 40
    pinned = collect(h, "tw", tmp_path/"pinned.json", cfg,
                     now=datetime(2026,10,19,13,tzinfo=timezone.utc),
                     revision_pinned=True)
    assert pinned["schema_version"] == 2
    assert pinned["cohort_revision"] == revision
    h["source_sha"] = "f" * 40
    with pytest.raises(ValueError, match="checkout SHA"):
        collect(h, "tw", tmp_path/"wrong-sha.json", cfg,
                now=datetime(2026,10,19,13,tzinfo=timezone.utc),
                revision_pinned=True)
    h["source_sha"] = "a" * 40
    h["input_hashes"][0]["sha256"]="different"
    with pytest.raises(ValueError,match="hashes differ"):
        collect(h,"tw",tmp_path/"rejected.json",cfg,
                now=datetime(2026,10,19,13,tzinfo=timezone.utc))
