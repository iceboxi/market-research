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
