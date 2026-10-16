"""Private, explicit local snapshots, verified before deterministic replay."""
from hashlib import sha256
from io import BytesIO
from pathlib import Path
import json
import re

import pandas as pd

SNAPSHOT_SCHEMA = 1


def _name(symbol):
    if not re.fullmatch(r"[A-Za-z0-9_.-]+", symbol):
        raise ValueError(f"Invalid ticker for snapshot: {symbol}")
    return symbol + ".csv"


def write_snapshot(directory: Path, symbol: str, frame: pd.DataFrame,
                   source: str) -> dict:
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    encoded = frame.to_csv(index=True).encode("utf-8")
    (directory / _name(symbol)).write_bytes(encoded)
    return {
        "symbol": symbol, "file": _name(symbol), "source": source,
        "sha256": sha256(encoded).hexdigest(), "rows": len(frame),
        "first_date": str(frame.index[0]), "last_date": str(frame.index[-1]),
    }


def write_index(directory: Path, records: list[dict]):
    directory = Path(directory)
    index = {"schema_version": SNAPSHOT_SCHEMA,
             "symbols": sorted(records, key=lambda row: row["symbol"])}
    (directory / "index.json").write_text(
        json.dumps(index, sort_keys=True, indent=2) + "\n", encoding="utf-8"
    )


class ReplayProvider:
    source = "checksummed_local_replay"

    def __init__(self, directory):
        self.directory = Path(directory)
        index = json.loads((self.directory / "index.json").read_text(encoding="utf-8"))
        if index.get("schema_version") != SNAPSHOT_SCHEMA:
            raise ValueError("Unknown snapshot schema")
        records = index["symbols"]
        self.records = {item["symbol"]: item for item in records}
        if len(records) != len(self.records):
            raise ValueError("Duplicate symbols in snapshot index")

    def provider_for(self, symbol):
        return self

    def load(self, symbol, period="1y") -> pd.DataFrame:
        record = self.records[symbol]
        if record["file"] != _name(symbol):
            raise ValueError("Snapshot index file name mismatch")
        payload = (self.directory / record["file"]).read_bytes()
        if sha256(payload).hexdigest() != record["sha256"]:
            raise ValueError(f"{symbol}: snapshot checksum mismatch")
        frame = pd.read_csv(BytesIO(payload), index_col=0)
        frame.index = pd.Index(pd.to_datetime(frame.index).date, name="date")
        if len(frame) != record["rows"]:
            raise ValueError(f"{symbol}: snapshot row count mismatch")
        if str(frame.index[0]) != record["first_date"] or str(frame.index[-1]) != record["last_date"]:
            raise ValueError(f"{symbol}: snapshot date mismatch")
        return frame
