from datetime import datetime, timezone
import json
from pathlib import Path
import pytest
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
