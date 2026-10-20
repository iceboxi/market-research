"""Two independent runner processes replay fixed inputs against a bare Git remote."""
import json
from pathlib import Path
import subprocess
import sys

from scripts.research_state import read
from scripts.state_store import GitStateStore
from test_research_state import repo
from test_research_snapshot import report, identity
from market_research.research_snapshot import prepare_snapshot


def test_two_fixed_input_processes_export_the_same_comparison_as_fixed_report(repo, tmp_path):
    checkout, _, store = repo
    for index, value in enumerate((1000, 1100)):
        payload = report(f"2026-10-19T12:0{index}:00+00:00")
        payload["issuer"]["facts"][0]["value"] = value
        snapshot = prepare_snapshot(payload, identity(str(100 + index), f"2026-10-19T12:0{index}:30+00:00"))
        source = tmp_path / f"input-{index}.json"
        source.write_text(json.dumps(snapshot))
        out = tmp_path / f"output-{index}"
        subprocess.run([sys.executable, "-m", "scripts.research_diff_replay", "--snapshot", str(source),
                        "--repo", str(checkout), "--out", str(out)], check=True, capture_output=True, text=True)
        delta = json.loads((out / "comparison.json").read_text())
        assert delta["categories"] == [["baseline"], ["revision"]][index]
        assert (out / "comparison.md").read_text() in (out / "fixed_report.md").read_text()
    assert "1,000 → 1,100 TWD_thousands" in (out / "comparison.md").read_text()
    assert read(store)["records"]
