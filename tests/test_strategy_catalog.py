"""Documentation-only catalog contract checks; no runtime registration."""
from pathlib import Path

import yaml
from market_research.strategies import STRATEGIES, get_strategy

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "docs/strategies/catalog.yaml"

def test_catalog_has_unique_family_partition():
    value = yaml.safe_load(CATALOG.read_text())
    assert value["schema_version"] == 1
    assert len(value["families"]) == 5
    assert len(value["variants"]) == 10
    ids = [v["id"] for v in value["variants"]]
    assert len(ids) == len(set(ids))
    assert {v["family"] for v in value["variants"]} == set(value["families"])
    for item in value["variants"]:
        assert item["status"] in {"draft", "specified", "implemented", "validated_for_research"}
        assert item["direction"]
        assert item["confirmation"]
        assert item["required_columns"]
        assert item["open_decisions"]
        if item["status"] == "draft":
            assert item["version"] is None
            assert item["id"] not in STRATEGIES
        elif item["status"] == "specified":
            assert item["version"]
            assert item["id"] not in STRATEGIES
            assert (ROOT / item["specification"]).exists()
            assert (ROOT / item["fixtures"]).exists()
        else:
            assert item["version"]
            assert item["id"] in STRATEGIES
            assert get_strategy(item["id"]).version == str(item["version"])

def test_only_existing_three_soldiers_is_implemented_and_enabled():
    catalog = yaml.safe_load(CATALOG.read_text())
    implemented = [v["id"] for v in catalog["variants"] if v["status"] == "implemented"]
    assert implemented == ["sakata_three_soldiers"]
    cfg = yaml.safe_load((ROOT / "config/strategies.yaml").read_text())
    enabled = [v["id"] for v in cfg["strategies"] if v["enabled"]]
    assert enabled == implemented
    assert get_strategy("sakata_three_soldiers").version == "0.1.0"

def test_candidate_specs_never_enable_by_merely_adding_catalog_entry():
    catalog = yaml.safe_load(CATALOG.read_text())
    active = {v["id"] for v in yaml.safe_load(
        (ROOT / "config/strategies.yaml").read_text())["strategies"] if v["enabled"]}
    assert not active.intersection({v["id"] for v in catalog["variants"] if v["status"] == "draft"})


def test_morning_star_spec_and_test_vectors_are_self_consistent():
    from math import isfinite
    spec = yaml.safe_load((ROOT / "docs/strategies/morning_star.yaml").read_text())
    cases = yaml.safe_load((ROOT / "tests/fixtures/morning_star.yaml").read_text())
    assert spec["strategy_id"] == cases["strategy_id"] == "sakata_morning_star"
    assert spec["spec_version"] == cases["spec_version"] == "0.1.0"
    assert spec["status"] == "specified"
    assert spec["minimum_complete_bars"] == 8
    assert spec["gap_policy"] == "no_strict_gap_required_but_star_body_not_above_first_close"
    assert len(cases["cases"]) >= 6
    names = [case["id"] for case in cases["cases"]]
    assert len(names) == len(set(names))
    for case in cases["cases"]:
        assert case["expected"] in {"match", "no_match", "insufficient_history", "invalid_data"}
        if case["expected"] == "insufficient_history":
            assert len(case["rows"]) < 8
        else:
            assert len(case["rows"]) >= 8
        assert all(len(row) == 4 for row in case["rows"])
        assert all(isinstance(value, (int, float)) and isfinite(value)
                   for row in case["rows"] for value in row)
    assert not {"sakata_morning_star"}.intersection(
        {v["id"] for v in yaml.safe_load((ROOT / "config/strategies.yaml").read_text())["strategies"] if v["enabled"]}
    )
