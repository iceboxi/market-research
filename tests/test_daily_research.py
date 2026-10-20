"""Daily output contract; source/delivery boundaries are injectable."""
import json
from datetime import datetime, timezone

import httpx

from scripts.daily_research import execute
from scripts.company_report import run
from test_company_report_feedback import Prices, NOW, facts_get, source_clock
from test_scan_company_research import artifacts, signal

FIXTURE_DIGEST = "f8e0d9151d2d3b77a747fdfb3874e2ab9066bd29880e7160cccf9924eab5bb05"


class Sources:
    def __init__(self, get=facts_get, unavailable_prices=()):
        self.prices = []
        self.facts = []
        self.get = get
        self.unavailable_prices = unavailable_prices

    def research(self, symbol, out, now, sec_user_agent):
        owner = self
        class Provider(Prices):
            def load(self, symbol, period):
                owner.prices.append(symbol)
                if symbol in owner.unavailable_prices:
                    raise httpx.ReadTimeout("fixture")
                return super().load(symbol, period)
        def get(url):
            self.facts.append(url)
            return self.get(url)
        return run(symbol, out=out, now=now, provider=Provider(), facts_get=get,
                   clock=lambda: NOW)


def delivered(mode, bootstrap, out, *, report, daily):
    # Deployment boundary stand-in; real Git/Issue ownership is verified below.
    assert daily and not bootstrap
    out.mkdir(parents=True, exist_ok=True)
    return {"acceptance": "passed", "publication": {"status": "published",
            "issue_url": "https://github.com/owner/repo/issues/900"},
            "snapshot_id": "a" * 64}


def test_no_candidates_still_delivers_fixed_research_and_compact_daily_summary(tmp_path):
    folder = artifacts(tmp_path)
    sources = Sources()
    out = tmp_path / "reports"
    result = execute(folder, out, research_fn=sources.research, publication_fn=delivered, now=NOW)
    assert result["candidates"]["status"] == "no_candidates"
    assert result["fixed_research"]["status"] == "complete"
    assert result["fixed_research"]["session"] == "2026-10-19"
    assert result["fixed_research"]["publication"]["status"] == "published"
    assert sources.prices == ["2330.TW"]
    assert len(sources.facts) == 3
    assert "0" in (out / "daily_summary.md").read_text()
    assert "2330" in (out / "daily_summary.md").read_text()
    assert json.loads((out / "daily_receipt.json").read_text()) == result
    assert not (out / "2330.TW" / "report.json").exists()


def test_fixed_match_reuses_one_input_batch_and_preserves_candidate_contract(tmp_path):
    artifacts(tmp_path, signals=[signal(day="2026-10-19")], quality={"symbols": [
        {"market": "tw", "symbol": "2330.TW", "last_date": "2026-10-19",
         "input_sha256": FIXTURE_DIGEST}], "errors": []})
    sources = Sources()
    out = tmp_path / "reports"
    result = execute(tmp_path, out, research_fn=sources.research, publication_fn=delivered, now=NOW)
    assert result["status"] == "complete"
    assert result["candidates"]["candidate_reports"][0]["status"] == "research_ready"
    assert sources.prices == ["2330.TW"]
    assert len(sources.facts) == 3
    candidate = json.loads((out / "2330.TW/report.json").read_text())
    manual = run("2330.TW", tmp_path / "manual", now=NOW, provider=Prices(),
                 facts_get=facts_get, clock=lambda: NOW)
    assert candidate == manual


def test_scan_drift_blocks_candidate_but_keeps_independent_fixed_publication(tmp_path):
    artifacts(tmp_path, signals=[signal()])
    sources = Sources()
    result = execute(tmp_path, tmp_path / "reports", research_fn=sources.research,
                     publication_fn=delivered, now=NOW)
    assert result["status"] == "partial"
    assert result["candidates"]["candidate_reports"][0]["status"] == "blocked_data_drift"
    assert result["fixed_research"]["publication"]["status"] == "published"
    assert "not_a_scan_candidate" in result["fixed_research"]["scope"]
    assert sources.prices == ["2330.TW"]


def test_unhealthy_scan_never_acquires_candidate_association_but_fixed_is_delivered(tmp_path):
    artifacts(tmp_path, signals=[signal()], health={"health": "degraded", "scan_outcome": "success"})
    sources = Sources()
    result = execute(tmp_path, tmp_path / "reports", research_fn=sources.research,
                     publication_fn=delivered, now=NOW)
    assert result["candidates"]["status"] == "blocked"
    assert result["candidates"]["candidate_reports"] == []
    assert result["fixed_research"]["publication"]["status"] == "published"


def test_fixed_source_failure_keeps_other_healthy_candidate_and_partial_report(tmp_path):
    def get(url):
        rows = facts_get(url)
        return rows + [{**row, "公司代號": "2303"} for row in rows]
    quality = {"symbols": [{"market": "tw", "symbol": "2303.TW", "last_date": "2026-10-19",
                             "input_sha256": FIXTURE_DIGEST}], "errors": []}
    artifacts(tmp_path, signals=[signal("2303.TW", day="2026-10-19")], quality=quality)
    sources = Sources(get=get, unavailable_prices=("2330.TW",))
    out = tmp_path / "reports"
    result = execute(tmp_path, out, research_fn=sources.research, publication_fn=delivered, now=NOW)
    assert result["status"] == "partial"
    assert result["candidates"]["candidate_reports"][0]["status"] == "research_ready"
    assert (out / "2303.TW/report.json").exists()
    fixed = result["fixed_research"]
    assert fixed["status"] == "partial"
    assert fixed["publication"]["status"] == "published"
    assert fixed["source_coverage"]["issuer_profile"]["status"] == "available"
    assert fixed["source_coverage"]["technical"]["status"] == "unavailable"


def test_failed_publication_still_exports_candidate_and_daily_receipts(tmp_path):
    artifacts(tmp_path)
    def failed_delivery(*args, **kwargs):
        raise OSError("delivery unavailable")
    out = tmp_path / "reports"
    result = execute(tmp_path, out, research_fn=Sources().research, publication_fn=failed_delivery, now=NOW)
    assert result["status"] == "partial"
    assert result["fixed_research"]["publication"] == {"status": "failed", "error_type": "OSError"}
    assert result["candidates"]["status"] == "no_candidates"
    assert (out / "daily_summary.md").exists()
    assert json.loads((out / "daily_receipt.json").read_text()) == result


def test_explicit_historical_cutoff_never_advances_to_newly_fetched_session(tmp_path):
    artifacts(tmp_path)
    historical = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
    result = execute(tmp_path, tmp_path / "reports", research_fn=Sources().research,
                     publication_fn=delivered, now=historical)
    fixed = result["fixed_research"]
    assert fixed["evaluation_cutoff_utc"] == historical.isoformat()
    assert fixed["session"] == "2026-10-16"
    assert fixed["source_coverage"]["issuer_profile"]["status"] == "unavailable"
