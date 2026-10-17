import json
from datetime import datetime, timezone
from scripts import monitor

def fixture():
    m={"requested_symbols":2,"scanned_symbols":2,"error_count":0,
       "matching_signals":0,"official_mismatch_count":0,"strict_freshness":True,
       "strategies":[{"id":"sakata_three_soldiers","version":"0.1.0"}]}
    q={"symbols":[{"market":"tw","symbol":"2330.TW","last_date":"2026-10-16",
                    "input_sha256":"a"*64},{"market":"tw","symbol":"2303.TW",
                    "last_date":"2026-10-16","input_sha256":"b"*64}],
       "errors":[],"warnings":[{"reason":"unfinalized_session_bars_excluded"}]}
    return m,q

def test_expected_warning():
    assert monitor.classify(*fixture(),"success")==("healthy",[])

def test_missing_data_and_mismatch():
    m,q=fixture()
    assert monitor.classify(None,None,"failure")[0]=="critical"
    m["official_mismatch_count"]=1
    assert monitor.classify(m,q,"success")[0]=="critical"

def test_unexpected_warning():
    m,q=fixture()
    q["warnings"].append({"reason":"unreconciled_source"})
    assert monitor.classify(m,q,"success")==("degraded",["unreconciled_source"])

def test_sanitized_report(tmp_path):
    m,q=fixture()
    (tmp_path/"manifest.json").write_text(json.dumps(m))
    (tmp_path/"data_quality.json").write_text(json.dumps(q))
    (tmp_path/"signals.json").write_text("[]")
    r=monitor.summarize(tmp_path,"iceboxi/market-research","123","schedule","tw",
                        "success",datetime(2026,10,17,tzinfo=timezone.utc))
    assert r["health"]=="healthy"
    assert len(r["input_hashes"])==2
    assert r["expected_warnings"]==1
    assert "open" not in r and "close" not in r

def test_issue_update_and_recovery(monkeypatch):
    calls=[]
    def fake(*cmd,**kwargs):
        calls.append(cmd)
        class Result:
            stdout='[{"number":44,"title":"[market-health] EOD scan tw"}]'
        return Result()
    monkeypatch.setattr(monitor,"command",fake)
    r={"market":"tw","health":"critical","run_url":"x","scanned":1,
       "requested":2,"errors":1,"signals":0,"expected_warnings":0,
       "unexpected_warnings":0,"mismatches":0,"session_dates":{},"reasons":["failed"]}
    assert monitor.alert(r,"owner/repo")=="updated"
    assert any(x[:3]==("gh","issue","comment") for x in calls)
    calls.clear()
    r["health"]="healthy"
    assert monitor.alert(r,"owner/repo")=="recovered"
    assert any(x[:3]==("gh","issue","close") for x in calls)
