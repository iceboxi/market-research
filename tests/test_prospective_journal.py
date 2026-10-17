from datetime import date
import pytest
from scripts.prospective_journal import journal_entry, fingerprint, FREEZE_DATE

def health():
    return {"health":"healthy","event":"schedule","errors":0,"market":"tw",
        "requested":10,"scanned":10,"run_url":"https://github.com/o/r/actions/runs/1",
        "session_dates":{"tw":["2026-10-19"]},"signals":0}

def test_only_new_completed_scheduled_scans_can_be_journaled():
    entry=journal_entry(health(),"sha",None,date(2026,10,20))
    assert entry["signals_observed"]==0
    with pytest.raises(ValueError,match="AFTER"):
        journal_entry(health(),"sha",None,FREEZE_DATE)
    with pytest.raises(ValueError,match="backfill"):
        journal_entry(health(),"sha",entry,date(2026,10,20))
    with pytest.raises(ValueError,match="changed"):
        journal_entry(health(),"different",entry,date(2026,10,21))

def test_push_and_unhealthy_runs_not_eligible():
    item=health()
    item["event"]="push"
    with pytest.raises(ValueError,match="push"):
        journal_entry(item,"sha",None,date(2026,10,20))
    item=health()
    item["health"]="critical"
    with pytest.raises(ValueError,match="healthy"):
        journal_entry(item,"sha",None,date(2026,10,20))
