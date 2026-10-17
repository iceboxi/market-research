"""Immutable forward-only observation journal; no retroactive prospective labels."""
import argparse
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path

import yaml

FREEZE_DATE = date(2026, 10, 18)

def fingerprint(repo=Path(".")):
    repo=Path(repo)
    paths=["config/strategies.yaml","config/markets.yaml","docs/strategies/catalog.yaml"]
    raw=b""
    for path in paths:
        raw+=path.encode()+b"\0"+(repo/path).read_bytes()+b"\0"
    return sha256(raw).hexdigest()

def journal_entry(health, freeze_hash, existing, today):
    """Accept only future observations after freeze, without mutable history."""
    if today<=FREEZE_DATE:
        raise ValueError("Prospective samples must be observed AFTER freeze day")
    if health.get("health")!="healthy" or health.get("errors")!=0:
        raise ValueError("Only successful complete daily health evidence is eligible")
    if health.get("event") not in ("schedule","workflow_dispatch"):
        raise ValueError("A push CI scan is not prospective operational evidence")
    if health.get("market") not in ("tw","us"):
        raise ValueError("Prospective journal needs a single market")
    if health.get("requested")!=health.get("scanned"):
        raise ValueError("Partial market scan")
    if existing and existing.get("freeze_hash")!=freeze_hash:
        raise ValueError("Frozen research configuration changed; new cohort required")
    if existing and today.isoformat() <= existing["observed_utc_date"]:
        raise ValueError("Cannot backfill or replace a prospective observation")
    return {"schema_version":1,"freeze_date":FREEZE_DATE.isoformat(),
      "freeze_hash":freeze_hash,"observed_utc_date":today.isoformat(),
      "source_scan_run":health["run_url"],"market":health["market"],
      "last_completed_sessions":health["session_dates"],
      "market_coverage":health["scanned"],"signals_observed":health["signals"],
      "note":"Daily observation metadata only; never a post-signal realized-return label."}

def main():
    p=argparse.ArgumentParser()
    p.add_argument("--health",type=Path,required=True)
    p.add_argument("--out",type=Path,required=True)
    p.add_argument("--previous",type=Path)
    p.add_argument("--repo-root",type=Path,default=Path("."))
    a=p.parse_args()
    record=json.loads(a.health.read_text())
    prev=json.loads(a.previous.read_text()) if a.previous and a.previous.exists() else None
    entry=journal_entry(record,fingerprint(a.repo_root),prev,datetime.now(timezone.utc).date())
    a.out.parent.mkdir(parents=True,exist_ok=True)
    if a.out.exists():
        raise ValueError("Prospective record already exists, refusing overwrite")
    a.out.write_text(json.dumps(entry,indent=2,ensure_ascii=False)+"\n")

if __name__=="__main__":
    main()
