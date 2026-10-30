"""#137: the public snapshot leaves out values the site rebuilds."""
import copy

from market_research.company_analysis import TW_OGDL_DATASETS
from market_research.event_risk import TW_MATERIAL_URL
from market_research.research_comparison import compare_snapshots
from market_research.research_site import render_research_site_html
from market_research.research_snapshot import _compact_financial_research, encoded
from test_research_site import _make_full_financial_research, _sample_report


def full_fr():
    fr = _make_full_financial_research()
    fr["ogdl_datasets"] = list(TW_OGDL_DATASETS)
    fr["disclosure_and_news"] = {"official_disclosures": [
        {"disclosure_id": "d1", "category": "material_information", "title": "董事會決議", "event_date": "2026-10-28",
         "published_at": "2026-10-28T17:00:00+08:00", "reported_at": "2026-10-28", "source": TW_MATERIAL_URL},
        {"disclosure_id": "d2", "category": "material_information", "title": "其他來源", "event_date": "2026-10-27",
         "published_at": "2026-10-27T17:00:00+08:00", "reported_at": "2026-10-27", "source": "https://mops.example/x"}]}
    cal = fr["calendar_schedule"]
    cal["timezone"] = "Asia/Taipei"
    for ev in cal["events"]:
        ev["timezone"] = "Asia/Taipei"
    cal["events"].append({**cal["events"][0], "schedule_id": "other-tz", "timezone": "UTC"})
    return fr


def test_rebuildable_values_are_left_out_and_others_kept():
    compact = _compact_financial_research(full_fr())
    assert "ogdl_datasets" not in compact
    disclosures = compact["disclosure_and_news"]["official_disclosures"]
    assert "source" not in disclosures[0]
    assert disclosures[1]["source"] == "https://mops.example/x"  # not the category default
    events = compact["calendar_schedule"]["events"]
    assert all("timezone" not in e for e in events if e["schedule_id"] != "other-tz")
    assert next(e for e in events if e["schedule_id"] == "other-tz")["timezone"] == "UTC"
    assert len(encoded(compact)) < len(encoded(_compact_financial_research_unslimmed(full_fr())))


def _compact_financial_research_unslimmed(fr):
    """What the snapshot kept before #137 for the same input, for the size comparison."""
    before = copy.deepcopy(fr)
    compact = _compact_financial_research(fr)
    compact["ogdl_datasets"] = before["ogdl_datasets"]
    for ev in compact["calendar_schedule"]["events"]:
        ev.setdefault("timezone", before["calendar_schedule"]["timezone"])
    for item in compact["disclosure_and_news"]["official_disclosures"]:
        item.setdefault("source", TW_MATERIAL_URL)
    return compact


def page_for(fr):
    report = _sample_report()
    report["financial_research"] = fr
    report["research_readiness"]["components"]["financial"]["status"] = "available"
    return render_research_site_html(latest_report=report)


def test_site_restores_the_dataset_list_and_disclosure_links():
    old = page_for(_compact_financial_research_unslimmed(full_fr()))
    new = page_for(full_fr())  # prepare_snapshot compacts it on the way into the page
    for dataset in TW_OGDL_DATASETS:
        assert dataset["endpoint"] in new and dataset["endpoint"] in old
    assert new.count(TW_MATERIAL_URL) == old.count(TW_MATERIAL_URL)
    assert "https://mops.example/x" in new


def test_leaving_values_out_is_never_a_research_change():
    from market_research.research_snapshot import prepare_snapshot
    report = _sample_report()
    report["financial_research"] = full_fr()
    report["research_readiness"]["components"]["financial"]["status"] = "available"
    new = prepare_snapshot(report, {"repository": "iceboxi/market-research", "run_id": "2", "run_attempt": 1,
                                    "code_sha": "a" * 40, "observed_at_utc": "2026-10-19T12:01:00+00:00"})
    from market_research.research_snapshot import fingerprint
    old = copy.deepcopy(new)  # the same research stored the pre-#137 way
    old["financial_research"] = _compact_financial_research_unslimmed(full_fr())
    old["id"] = fingerprint({k: v for k, v in old.items() if k != "id"})
    comparison = compare_snapshots(old, new, {})
    assert comparison["categories"] == ["unchanged"]
