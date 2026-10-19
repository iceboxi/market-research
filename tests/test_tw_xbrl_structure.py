"""Synthetic XBRL fixtures only; no real 2330 filing or taxonomy is asserted."""
import json
from zipfile import ZipFile

import pytest

from scripts.tw_xbrl_structure import UnsafeInstance, _read_instance, inspect_instance, main

NS = "https://test.invalid/fake-taxonomy"
SCHEME = "https://test.invalid/issuer-id"
CONCEPTS = {
    "balance_sheet": f"{{{NS}}}AssetSample",
    "income": f"{{{NS}}}IncomeSample",
    "cash_flow": f"{{{NS}}}CashSample",
}


def xml(*, identifier="2330", balance_date="2024-12-31", start="2024-01-01",
        end="2024-12-31", extra="", duplicate="", scheme=SCHEME,
        hide_cash=False, cash_unit="TWD"):
    return f'''<?xml version="1.0" encoding="UTF-8"?>
    <xbrli:xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:t="{NS}">
      <xbrli:context id="BS"><xbrli:entity><xbrli:identifier scheme="{scheme}">{identifier}</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:instant>{balance_date}</xbrli:instant></xbrli:period></xbrli:context>
      <xbrli:context id="FY"><xbrli:entity><xbrli:identifier scheme="{scheme}">{identifier}</xbrli:identifier></xbrli:entity>
        <xbrli:period><xbrli:startDate>{start}</xbrli:startDate><xbrli:endDate>{end}</xbrli:endDate></xbrli:period></xbrli:context>
      <xbrli:unit id="TWD"><xbrli:measure>iso4217:TWD</xbrli:measure></xbrli:unit>
      <t:AssetSample contextRef="BS" unitRef="TWD">12345</t:AssetSample>
      <t:IncomeSample contextRef="FY" unitRef="TWD">54321</t:IncomeSample>
      {'' if hide_cash else f'<t:CashSample contextRef="FY" unitRef="{cash_unit}">11111</t:CashSample>'}
      {extra}{duplicate}
    </xbrli:xbrl>'''.encode("utf-8")


def check(payload, **overrides):
    return inspect_instance(payload, identifier=overrides.get("identifier", "2330"),
                            identifier_scheme=SCHEME, year=overrides.get("year", 2024),
                            concepts=overrides.get("concepts", CONCEPTS))


def test_three_matching_synthetic_facts_are_only_structurally_matched():
    report = check(xml())
    assert report["structural_verdict"] == "matched_supplied_qnames"
    assert all(x["matched"] for x in report["structure_checks"].values())
    assert report["source_acceptance"] == "not_evaluated"
    assert report["consolidation_scope_verified"] is False
    assert report["taxonomy_semantics_verified"] is False
    assert report["authorized_machine_access_verified"] is False
    assert "12345" not in json.dumps(report)


@pytest.mark.parametrize("kwargs", [
    {"identifier": "2317"}, {"scheme": "https://test.invalid/other-id"},
    {"balance_date": "2024-09-30"}, {"start": "2024-10-01"},
    {"end": "2025-01-01"}, {"hide_cash": True}, {"cash_unit": "missing"},
])
def test_wrong_entity_date_missing_statement_or_undeclared_unit_fails_closed(kwargs):
    assert check(xml(**kwargs))["structural_verdict"] == "not_verified"


def test_invalid_qname_and_duplicate_qnames_rejected():
    for variant in [dict(CONCEPTS, income="IncomeSample"),
                    dict(CONCEPTS, income=CONCEPTS["balance_sheet"])]:
        with pytest.raises(ValueError):
            check(xml(), concepts=variant)


def test_duplicate_context_id_fails_closed():
    duplicate = '<xbrli:context id="BS"><xbrli:entity/></xbrli:context>'
    report = check(xml(duplicate=duplicate))
    assert report["duplicate_context_ids"] is True
    assert report["structural_verdict"] == "not_verified"


def test_nested_fake_facts_are_not_top_level_facts():
    hidden = '<xbrli:footnote><t:CashSample contextRef="FY" unitRef="TWD">33</t:CashSample></xbrli:footnote>'
    assert check(xml(hide_cash=True, extra=hidden))["structural_verdict"] == "not_verified"


def test_non_xbrl_html_and_doctype_refused():
    for data in [b'<html/>', b'<!DOCTYPE x [<!ENTITY secret SYSTEM "file:///etc/passwd">]><x/>']:
        with pytest.raises(UnsafeInstance):
            check(data)


def test_zip_single_member_and_bounded_members(tmp_path):
    path = tmp_path / "sample.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("sub/report.xml", xml())
    assert check(_read_instance(path))["structural_verdict"] == "matched_supplied_qnames"
    with ZipFile(path, "w") as archive:
        archive.writestr("one.xml", xml())
        archive.writestr("two.xml", xml())
    with pytest.raises(UnsafeInstance):
        _read_instance(path)
    with ZipFile(path, "w") as archive:
        archive.writestr("../escape.xml", xml())
    with pytest.raises(UnsafeInstance):
        _read_instance(path)


def test_cli_writes_metadata_only_and_returns_nonzero_on_unverified(tmp_path):
    source, output = tmp_path / "x.xml", tmp_path / "evidence.json"
    source.write_bytes(xml())
    params = ["--file", str(source), "--identifier", "2330",
              "--identifier-scheme", SCHEME, "--year", "2024",
              "--balance-sheet-concept", CONCEPTS["balance_sheet"],
              "--income-concept", CONCEPTS["income"],
              "--cash-flow-concept", CONCEPTS["cash_flow"], "--out", str(output)]
    assert main(params) == 0
    assert "12345" not in output.read_text()
    source.write_bytes(xml(hide_cash=True))
    assert main(params) == 2
    assert json.loads(output.read_text())["source_acceptance"] == "not_evaluated"


def test_nonnumeric_nil_and_empty_facts_do_not_count():
    valid = xml().decode("utf-8")
    for alternative in [
        '<t:CashSample contextRef="FY" unitRef="TWD">not_a_number</t:CashSample>',
        '<t:CashSample contextRef="FY" unitRef="TWD"></t:CashSample>',
        '<t:CashSample xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
        'contextRef="FY" unitRef="TWD" xsi:nil="true"/>',
    ]:
        candidate = valid.replace(
            '<t:CashSample contextRef="FY" unitRef="TWD">11111</t:CashSample>',
            alternative,
        )
        assert check(candidate.encode("utf-8"))["structural_verdict"] == "not_verified"


def test_utf16_encoded_xml_rejected():
    with pytest.raises(UnsafeInstance):
        check(xml().decode("utf-8").encode("utf-16"))
