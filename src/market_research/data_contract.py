"""Shared daily screening artifact invariants and schema identifiers."""
SCHEMA_VERSION = 1
CANDLE_COLUMNS = ("open", "high", "low", "close", "volume")


def verify_scan_artifacts(manifest, quality, results, matches):
    if manifest["schema_version"] != SCHEMA_VERSION:
        raise ValueError("Unsupported screening artifact schema")
    if manifest["scanned_symbols"] + manifest["error_count"] != manifest["requested_symbols"]:
        raise ValueError("Scan results do not cover every requested ticker")
    if len(quality["symbols"]) != manifest["scanned_symbols"]:
        raise ValueError("Data-quality rows do not match scanned symbols")
    if len(quality["errors"]) != manifest["error_count"]:
        raise ValueError("Error count inconsistent with quality rows")
    if matches != [result for result in results if result["matched"]]:
        raise ValueError("Signals do not match screening rows")
    if manifest["matching_signals"] != len(matches):
        raise ValueError("Signal count inconsistent with manifest")
    for result in results:
        if not all(result.get(key) for key in (
            "market", "symbol", "strategy_id", "strategy_version", "trade_date"
        )):
            raise ValueError("Incomplete strategy output contract")
