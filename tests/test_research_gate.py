import copy
import pytest
from scripts.research_gate import gate

POLICY={"policy_version":1,"minimums":{"per_market_events":20,"per_market_symbols":3,"each_test_half_events":8}}

def report(market, signals=0):
    rows=[]
    for strategy in ("sakata_morning_star","sakata_evening_star"):
        for idx in range(3):
            events=[{"signal_date":"2026-08-01","label_end_date":"2026-08-08"} for _ in range(signals)]
            rows.append({"strategy_id":strategy,"symbol":f"T{idx}","market":market,
              "nonoverlapping_labeled_events":len(events),"raw_holdout_signals":len(events),
              "events":events,"first_test_date":"2026-07-01","test_end_date":"2026-10-01",
              "corporate_action_abstentions":0})
    return {"study":"retrospective_fixed_chronological_holdout","market":market,
            "complete":True,"error_count":0,"strategy_ids":["sakata_morning_star","sakata_evening_star"],
            "requested_symbols":3,"rows":rows,"training_fraction":0.7,
            "forward_horizon_sessions":5,"embargo_sessions":5}

def test_sparse_samples_block_and_do_not_enable():
    result=gate(report("tw",1),report("us",0),POLICY)
    assert result["production_activation_allowed"] is False
    assert all(row["readiness"]=="blocked" for row in result["strategies"])

def test_no_auto_approval_even_when_event_thresholds_pass():
    result=gate(report("tw",12),report("us",12),POLICY)
    assert not result["production_activation_allowed"]
    assert all("independent_execution_cost_and_dividend_model" in row["why"] for row in result["strategies"])

def test_incomplete_or_tampered_market_fails_closed():
    x=report("us")
    x["rows"].pop()
    with pytest.raises(ValueError,match="coverage"):
        gate(report("tw"),x,POLICY)
    x=report("us")
    x["complete"]=False
    with pytest.raises(ValueError,match="incomplete"):
        gate(report("tw"),x,POLICY)

def test_cross_market_strategy_mismatch_fails():
    x=report("us")
    x["strategy_ids"].reverse()
    with pytest.raises(ValueError,match="different strategy"):
        gate(report("tw"),x,POLICY)
