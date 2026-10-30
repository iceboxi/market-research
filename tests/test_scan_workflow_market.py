"""#135: only a manual dispatch picks the scan market; schedule and push scan TW."""
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def scan_market(event, chosen=None):
    """The scan.yml SCAN_MARKET expression, evaluated for one trigger."""
    return chosen if event == "workflow_dispatch" and chosen else "tw"


def test_workflow_keeps_the_market_choice_for_dispatch_only():
    env = yaml.safe_load((ROOT / ".github/workflows/scan.yml").read_text())["jobs"]["scan"]["env"]
    assert env["SCAN_MARKET"] == "${{ github.event_name == 'workflow_dispatch' && inputs.market || 'tw' }}"
    assert scan_market("schedule") == "tw"
    assert scan_market("push") == "tw"
    assert scan_market("workflow_dispatch", "us") == "us"
    assert scan_market("workflow_dispatch", "both") == "both"
