"""Offline F05 XBRL structural checker; not a source or valuation adapter.

This intentionally does not resolve external schemas, discover taxonomy concept
meanings, validate consolidated scope, persist numeric facts or fetch from MOPS.
The caller must supply *exact* expanded XML QNames from a reviewed taxonomy.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
from zipfile import BadZipFile, ZipFile

XBRLI = "http://www.xbrl.org/2003/instance"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
ISO4217 = "http://www.xbrl.org/2003/iso4217"


def _tag(local):
    return f"{{{XBRLI}}}{local}"


MAX_INPUT_BYTES = 4_000_000
MAX_XML_ELEMENTS = 60_000
REPORT_SCHEMA_VERSION = 1
STATEMENTS = ("balance_sheet", "income", "cash_flow")


class UnsafeInstance(ValueError):
    """The input cannot safely be treated as a bounded XBRL instance."""


def _read_instance(path):
    """Read a bounded XML instance or a ZIP with exactly one XML member."""
    if path.stat().st_size > MAX_INPUT_BYTES:
        raise UnsafeInstance("Input exceeds the offline probe's 4 MB limit")
    if path.suffix.lower() != ".zip":
        if path.suffix.lower() not in (".xml", ".xbrl"):
            raise UnsafeInstance("Expected an .xml, .xbrl, or single-member .zip")
        raw = path.read_bytes()
    else:
        try:
            with ZipFile(path) as archive:
                members = archive.infolist()
                if len(members) != 1 or members[0].is_dir():
                    raise UnsafeInstance("ZIP must contain exactly one XBRL XML file")
                member = members[0]
                name = member.filename
                if (name.startswith(("/", "\\")) or ".." in name.replace("\\", "/").split("/")
                        or not name.lower().endswith((".xml", ".xbrl"))):
                    raise UnsafeInstance("ZIP has an unsupported member path or type")
                if member.file_size > MAX_INPUT_BYTES:
                    raise UnsafeInstance("Expanded XBRL exceeds the 4 MB limit")
                with archive.open(member) as handle:
                    raw = handle.read(MAX_INPUT_BYTES + 1)
        except (BadZipFile, OSError, RuntimeError) as error:
            raise UnsafeInstance("Cannot read bounded ZIP input") from error
    if len(raw) > MAX_INPUT_BYTES:
        raise UnsafeInstance("XBRL XML exceeds the 4 MB limit")
    if b"\x00" in raw or raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise UnsafeInstance("Only UTF-8 encoded XML is supported")
    if re.search(br"<!\s*(DOCTYPE|ENTITY)\b", raw, re.IGNORECASE):
        raise UnsafeInstance("DTD and entity declarations are not allowed")
    return raw


def _exact_qname(qname):
    # No fuzzy/local-name matches: taxonomy-specific namespaces must be supplied.
    match = re.fullmatch(r"\{([^{}\s]+)\}([^{}\s]+)", qname)
    if match is None or not match.group(1).startswith(("https://", "http://")):
        raise ValueError("Concepts require expanded {http(s)://namespace}LocalName QNames")
    return qname


def _context_identity(context):
    identifier = context.find(f"./{_tag('entity')}/{_tag('identifier')}")
    if identifier is None:
        return None
    return ((identifier.text or "").strip(), identifier.get("scheme"))


def _nondimensional_context(context):
    """Avoid treating segment- or scenario-specific numbers as issuer-wide facts."""
    return (context.find(f"./{_tag('entity')}/{_tag('segment')}") is None
            and context.find(_tag("scenario")) is None)


def _valid_twd_unit(unit, namespace_bindings):
    """Only accept a single ISO-4217 TWD measure with an unambiguous prefix."""
    if len(unit) != 1 or unit[0].tag != _tag("measure"):
        return False
    measure = (unit[0].text or "").strip()
    prefix, separator, currency = measure.partition(":")
    return (bool(prefix) and separator == ":" and currency == "TWD"
            and namespace_bindings.get(prefix) == {ISO4217})


def _period_matches(context, statement, year):
    period = context.find(_tag("period"))
    if period is None:
        return False
    if statement == "balance_sheet":
        instant = period.find(_tag("instant"))
        return instant is not None and (instant.text or "").strip() == f"{year}-12-31"
    start = period.find(_tag("startDate"))
    end = period.find(_tag("endDate"))
    return (start is not None and end is not None
            and (start.text or "").strip() == f"{year}-01-01"
            and (end.text or "").strip() == f"{year}-12-31")


def inspect_instance(raw, *, identifier, identifier_scheme, year, concepts):
    """Inspect one provided instance, returning only hashes/structural evidence.

    Structural matching is NOT a proof of semantic statement coverage or source
    authority; dimensional contexts / consolidation scope need independent review.
    """
    if not re.fullmatch(r"[0-9]{4,6}", identifier):
        raise ValueError("Expected a numeric Taiwanese stock identifier")
    if not identifier_scheme or not identifier_scheme.startswith(("https://", "http://")):
        raise ValueError("Expected an explicit source-observed identifier scheme URL")
    if year < 1990 or year > 2100:
        raise ValueError("Year outside this limited FY structural probe")
    if set(concepts) != set(STATEMENTS):
        raise ValueError("Exactly one concept per required statement must be supplied")
    qnames = {statement: _exact_qname(concepts[statement]) for statement in STATEMENTS}
    if len(set(qnames.values())) != len(qnames):
        raise ValueError("Concept QNames must be distinct")
    if b"\x00" in raw or raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        raise UnsafeInstance("Only UTF-8 encoded XML is supported")
    if len(raw) > MAX_INPUT_BYTES or re.search(br"<!\s*(DOCTYPE|ENTITY)\b", raw, re.IGNORECASE):
        raise UnsafeInstance("XML exceeds safety limits or contains a DTD/entity declaration")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as error:
        raise UnsafeInstance("Invalid XBRL XML") from error
    if root.tag != _tag("xbrl"):
        raise UnsafeInstance("Root must be XBRL 2.1 xbrli:xbrl, not HTML/iXBRL")
    if sum(1 for _ in root.iter()) > MAX_XML_ELEMENTS:
        raise UnsafeInstance("XML exceeds bounded element count")
    # ElementTree resolves element QNames but preserves measure QName text as-is.
    # Reject prefix redeclarations with conflicting namespace URIs.
    namespace_bindings = {}
    for _, (prefix, uri) in ET.iterparse(io.BytesIO(raw), events=("start-ns",)):
        namespace_bindings.setdefault(prefix, set()).add(uri)

    context_elements = [child for child in root if child.tag == _tag("context")]
    unit_elements = [child for child in root if child.tag == _tag("unit")]
    contexts = {}
    duplicate_contexts = set()
    for context in context_elements:
        key = context.get("id")
        if not key or key in contexts:
            duplicate_contexts.add(key)
        else:
            contexts[key] = context
    units = {}
    duplicate_units = set()
    for unit in unit_elements:
        key = unit.get("id")
        if not key or key in units:
            duplicate_units.add(key)
        else:
            units[key] = unit
    valid_twd_units = {key for key, unit in units.items()
                       if key not in duplicate_units and _valid_twd_unit(unit, namespace_bindings)}

    checks = {}
    for statement, qname in qnames.items():
        matched = []
        for child in root:
            if child.tag != qname:
                continue
            context_id, unit_id = child.get("contextRef"), child.get("unitRef")
            context = contexts.get(context_id) if context_id is not None else None
            if context is None or context_id in duplicate_contexts:
                continue
            if _context_identity(context) != (identifier, identifier_scheme):
                continue
            if not _nondimensional_context(context):
                continue
            if not _period_matches(context, statement, year):
                continue
            if not unit_id or unit_id not in valid_twd_units:
                continue
            # Check lexical shape without returning or persisting the value.
            # XML schema/taxonomy validation is intentionally NOT performed.
            value = (child.text or "").strip()
            if child.get(f"{{{XSI}}}nil", "false").lower() in ("true", "1"):
                continue
            if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
                continue
            matched.append(context_id)
        # Two same-QName facts in the same eligible context are ambiguous,
        # even when their lexical values happen to agree.
        checks[statement] = {"matching_fact_count": len(matched), "matched": len(matched) == 1}

    structural = all(checks[k]["matched"] for k in STATEMENTS) and not duplicate_contexts and not duplicate_units
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "input_sha256": hashlib.sha256(raw).hexdigest(),
        "requested_issuer": identifier,
        "expected_identifier_scheme": identifier_scheme,
        "requested_year": year,
        "concept_qnames": qnames,
        "structure_checks": checks,
        "context_count": len(context_elements),
        "unit_count": len(unit_elements),
        "duplicate_context_ids": bool(duplicate_contexts),
        "duplicate_unit_ids": bool(duplicate_units),
        "valid_twd_unit_count": len(valid_twd_units),
        "structural_verdict": "matched_supplied_qnames" if structural else "not_verified",
        "source_acceptance": "not_evaluated",
        "consolidation_scope_verified": False,
        "taxonomy_semantics_verified": False,
        "historical_publication_verified": False,
        "authorized_machine_access_verified": False,
        "redistribution_verified": False,
        "limitations": [
            "Synthetic QName evidence cannot establish complete statements or taxonomy semantics",
            "Financial fact values are never returned; only structural fact counts",
            "Monetary fact candidates require a uniquely bound ISO4217:TWD unit",
            "Dimensioned contexts and repeated matching fact candidates fail closed",
            "A valid period/context does not prove consolidated rather than separate-company scope",
            "No source, amendment history, publication time or reuse rights have been established",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True, type=Path)
    parser.add_argument("--identifier", required=True)
    parser.add_argument("--identifier-scheme", required=True)
    parser.add_argument("--year", type=int, required=True)
    for name in STATEMENTS:
        parser.add_argument("--" + name.replace("_", "-") + "-concept", required=True)
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        raw = _read_instance(args.file)
        concepts = {name: getattr(args, name + "_concept") for name in STATEMENTS}
        report = inspect_instance(raw, identifier=args.identifier,
                                  identifier_scheme=args.identifier_scheme,
                                  year=args.year, concepts=concepts)
    except (OSError, ValueError, UnsafeInstance) as error:
        print(f"Offline XBRL check refused input: {type(error).__name__}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"structural_verdict={report['structural_verdict']}; source_acceptance=not_evaluated")
    return 0 if report["structural_verdict"] == "matched_supplied_qnames" else 2


if __name__ == "__main__":
    sys.exit(main())
