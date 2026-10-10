"""Roster identity: format check, exact read, whole-section match, and holds."""

import json
import random
from dataclasses import replace
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from k1lens.domain.blank import blank_schedule
from k1lens.domain.fields import REVIEW_THRESHOLD
from k1lens.domain.models import ScheduleK1
from k1lens.eval.harness import evaluate
from k1lens.export.writers import ExportRecord, records_to_csv
from k1lens.extract.deterministic import DeterministicExtractor
from k1lens.generate.build import Variant, build_document
from k1lens.review.app import create_app
from k1lens.review.view import build_rows
from k1lens.roster import (
    Roster,
    bind_roster,
    classify_id,
    dump_roster,
    load_roster,
    roster_from_documents,
    roster_from_fixture_dir,
    synthetic_id_allowed,
)
from k1lens.validate.engine import validate_document

_PARTNERSHIP = {
    "part_i.ein": "00-0000108",
    "part_i.name": "Northwind Partners LP",
    "part_i.street": "10 Oak Avenue",
    "part_i.city": "Portland",
    "part_i.state": "OR",
    "part_i.zip_code": "97201",
}
_INVESTOR = {
    "part_ii.tin": "000-00-0108",
    "part_ii.name": "SAMPLE Finley Cho",
    "part_ii.street": "4 Pine Street",
    "part_ii.city": "Salem",
    "part_ii.state": "OR",
    "part_ii.zip_code": "97301",
}


def _document(
    values: dict[str, str | None],
    *,
    extractor: str = "deterministic",
    id_digit_confidence: float | None = None,
    id_confidence: float = 0.95,
    evidence_confidence: float = 0.92,
) -> ScheduleK1:
    document = blank_schedule("K1-ROSTER", extractor="deterministic", tax_year=2024)
    data = document.model_dump(mode="json")
    data["tax_year_confidence"] = 1.0
    data["layout_recognized"] = True
    for path, value in values.items():
        node: object = data
        for part in path.split("."):
            assert isinstance(node, dict)
            node = node[part]
        assert isinstance(node, dict)
        node["value"] = value
        node["confidence"] = id_confidence if path in {"part_i.ein", "part_ii.tin"} else 0.49
        source = node["provenance"]
        assert isinstance(source, dict)
        source["extractor"] = extractor
        source["evidence_confidence"] = evidence_confidence
        source["own_region"] = True
        if path in {"part_i.ein", "part_ii.tin"}:
            source["id_digit_confidence"] = id_digit_confidence
    return ScheduleK1.model_validate(data)


def _roster_for(values: dict[str, str | None]) -> Roster:
    return roster_from_documents([_document(values)])


def _ids(document: ScheduleK1, roster: Roster | None) -> set[tuple[str, str]]:
    return {
        (item.rule_id, item.field_path)
        for item in validate_document(document, roster=roster)
        if item.rule_id
        in {
            "no_roster",
            "no_tin",
            "no_roster_match",
            "new_partner",
            "identity_mismatch",
            "duplicate_roster_key",
        }
    }


def test_synthetic_ranges_pass_the_format_check_and_masks_do_not() -> None:
    assert synthetic_id_allowed("00-0000108")
    assert synthetic_id_allowed("000-00-0108")
    assert classify_id("00-0000108") == "valid"
    assert classify_id("000-00-0108") == "valid"
    assert classify_id("12-3456789") == "valid"
    assert synthetic_id_allowed("12-3456789") is False
    for masked in ("***-**-0108", "XXX-XX-0108", "xxxx-xx-0108", "0108", "**-0108"):
        assert classify_id(masked) == "masked", masked


def test_a_masked_id_is_no_tin_even_when_the_last_four_match_a_roster_row() -> None:
    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    page = {**_PARTNERSHIP, **_INVESTOR, "part_ii.tin": "0108"}
    document = _document(page)
    holds = _ids(document, roster)
    assert ("no_tin", "part_ii.name") in holds
    assert ("no_tin", "part_ii.street") in holds
    bound = bind_roster(document, roster)
    assert bound.part_ii.name.confidence < REVIEW_THRESHOLD
    assert bound.part_ii.name.value == "SAMPLE Finley Cho"


def test_an_id_is_not_repaired_to_force_a_match() -> None:
    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    letters = _document({**_PARTNERSHIP, **_INVESTOR, "part_i.ein": "OO-0000108"})
    assert classify_id(letters.part_i.ein.value) == "invalid"
    assert ("no_tin", "part_i.name") in _ids(letters, roster)
    assert letters.part_i.ein.value == "OO-0000108"
    neighbor = _document({**_PARTNERSHIP, **_INVESTOR, "part_i.ein": "00-0000109"})
    assert neighbor.part_i.ein.value == "00-0000109"
    assert ("new_partner", "part_i.city") in _ids(neighbor, roster)
    bound = bind_roster(neighbor, roster)
    assert bound.part_i.name.value == "Northwind Partners LP"
    assert bound.part_i.name.confidence < REVIEW_THRESHOLD


def test_a_low_ocr_digit_confidence_is_not_a_roster_key() -> None:
    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    document = _document(
        {**_PARTNERSHIP, **_INVESTOR},
        extractor="ocr",
        id_digit_confidence=0.4,
    )
    assert ("no_roster_match", "part_i.name") in _ids(document, roster)
    assert ("no_roster_match", "part_ii.zip_code") in _ids(document, roster)
    bound = bind_roster(document, roster)
    assert bound.part_i.city.confidence < REVIEW_THRESHOLD


def test_a_whole_section_match_lifts_to_the_threshold_and_keeps_the_page() -> None:
    values = {**_PARTNERSHIP, **_INVESTOR}
    roster = _roster_for(values)
    document = _document(values)
    bound = bind_roster(document, roster)
    assert bound.part_i.name.value == "Northwind Partners LP"
    assert bound.part_ii.name.value == "SAMPLE Finley Cho"
    assert bound.part_i.name.confidence == REVIEW_THRESHOLD
    assert bound.part_ii.zip_code.confidence == REVIEW_THRESHOLD
    assert bound.part_i.name.provenance.evidence_confidence == 0.92
    assert _ids(bound, roster) == set()


def test_blank_zip_mismatch_middle_initial_and_a_blank_roster_field_hold() -> None:
    complete = {**_PARTNERSHIP, **_INVESTOR}
    roster = _roster_for(complete)
    blank_zip = _document({**complete, "part_i.zip_code": ""})
    assert ("identity_mismatch", "part_i.zip_code") in _ids(blank_zip, roster)
    assert bind_roster(blank_zip, roster).part_i.city.confidence < REVIEW_THRESHOLD

    plus4 = _document({**complete, "part_i.zip_code": "97201-1234"})
    assert ("identity_mismatch", "part_i.state") in _ids(plus4, roster)
    spaced = _document({**complete, "part_ii.zip_code": "97301"})
    roster_spaced = roster_from_documents([_document({**complete, "part_ii.zip_code": "97301"})])
    # ZIP+4 with interior spaces matches the same digits and hyphen.
    spaced_plus = _document({**complete, "part_i.zip_code": "97201 - 1234"})
    plus_roster = roster_from_documents([_document({**complete, "part_i.zip_code": "97201-1234"})])
    assert _ids(spaced_plus, plus_roster) == set()
    assert _ids(spaced, roster_spaced) == set()

    initial = _document({**complete, "part_ii.name": "SAMPLE F Cho"})
    assert ("identity_mismatch", "part_ii.name") in _ids(initial, roster)
    dropped = _document({**complete, "part_ii.name": "SAMPLE Cho"})
    roster_initial = roster_from_documents(
        [_document({**complete, "part_ii.name": "SAMPLE F. Cho"})]
    )
    assert ("identity_mismatch", "part_ii.name") in _ids(dropped, roster_initial)

    page = _document(complete)
    data = roster_from_documents([page])
    blank_record = Roster(
        partnerships=data.partnerships,
        investors=(replace(data.investors[0], street=""),),
    )
    assert ("identity_mismatch", "part_ii.street") in _ids(page, blank_record)
    assert bind_roster(page, blank_record).part_ii.name.confidence < REVIEW_THRESHOLD


def test_cross_record_traps_hold_the_section() -> None:
    left = {**_PARTNERSHIP, **_INVESTOR}
    right = {
        **_PARTNERSHIP,
        "part_i.ein": "00-0000208",
        "part_i.name": "Other Partnership LP",
        "part_i.street": "99 Other Road",
        "part_ii.tin": "000-00-0208",
        "part_ii.name": "SAMPLE Other Person",
        "part_ii.street": "8 Other Street",
        "part_ii.city": "Eugene",
    }
    roster = roster_from_documents([_document(left), _document(right)])
    wrong_name = _document({**left, "part_ii.name": right["part_ii.name"]})
    assert ("identity_mismatch", "part_ii.name") in _ids(wrong_name, roster)
    assert bind_roster(wrong_name, roster).part_ii.city.confidence < REVIEW_THRESHOLD
    wrong_address = _document({**left, "part_i.street": right["part_i.street"]})
    assert ("identity_mismatch", "part_i.street") in _ids(wrong_address, roster)
    borrowed = _document({**left, "part_i.name": right["part_i.name"]})
    assert borrowed.part_i.ein.value == left["part_i.ein"]
    assert ("identity_mismatch", "part_i.name") in _ids(borrowed, roster)
    assert bind_roster(borrowed, roster).part_i.name.value == "Other Partnership LP"


def test_no_roster_and_a_new_partner_are_separate_holds() -> None:
    document = _document({**_PARTNERSHIP, **_INVESTOR})
    bare = _ids(document, None)
    assert ("no_roster", "part_i.name") in bare
    assert ("no_tin", "part_i.name") not in bare
    empty = roster_from_documents([])
    assert ("new_partner", "part_ii.name") in _ids(document, empty)


def test_a_model_identity_value_stays_under_review_when_the_roster_matches() -> None:
    from k1lens.extract.assemble import assemble
    from k1lens.extract.labels import LayoutStats
    from k1lens.extract.text import Observed

    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    labels = {
        "E Partner TIN": "000-00-0108",
        "F Partner name": "SAMPLE Finley Cho",
        "F Partner street": "4 Pine Street",
        "F Partner city": "Salem",
        "F Partner state": "OR",
        "F Partner ZIP": "97301",
    }
    assembled = assemble(
        "K1-MODEL",
        {
            label: [
                Observed(
                    value,
                    1,
                    None,
                    "llm",
                    label_score=1.0,
                    proximity=1.0,
                    reported_confidence=0.99,
                )
            ]
            for label, value in labels.items()
        },
        extractor="llm",
        layout_stats=LayoutStats(seen_lines=8, strong_anchors=8),
    )
    matched = bind_roster(assembled, roster)
    assert matched.part_ii.name.value == "SAMPLE Finley Cho"
    assert matched.part_ii.name.provenance.extractor == "llm"
    assert matched.part_ii.name.confidence < REVIEW_THRESHOLD
    assert matched.part_ii.street.confidence < REVIEW_THRESHOLD
    assert matched.part_ii.city.confidence < REVIEW_THRESHOLD


def test_roster_findings_show_in_the_review_queue_and_the_csv() -> None:
    document = _document({**_PARTNERSHIP, **_INVESTOR, "part_ii.tin": "****"})
    findings = validate_document(document, roster=roster_from_documents([]))
    rows = build_rows(document, findings)
    queued = [row for row in rows if row.path == "part_ii.name"]
    assert queued
    assert any("no_tin" in message or "masked" in message.lower() for message in queued[0].messages)
    csv_text = records_to_csv(
        [
            ExportRecord(
                document=document,
                approved_by="Ada Reviewer",
                approved_at="2026-01-01",
                findings=tuple(findings),
            )
        ]
    )
    assert "review_findings" in csv_text.splitlines()[0]
    assert "no_tin part_ii.name" in csv_text


def test_the_api_accepts_a_roster_and_eval_does_not_invent_one(tmp_path: Path) -> None:
    document = build_document(random.Random(3), 1, Variant.CLEAN)
    application = create_app(db_path=tmp_path / "queue.db", auto_ingest=False)
    from k1lens.review.store import ReviewStore

    ReviewStore(tmp_path / "queue.db").upsert(document, b"%PDF-1.4", [])
    payload = dump_roster(roster_from_documents([document]))
    with TestClient(application) as client:
        before = client.get(f"/api/documents/{document.document_id}/findings").json()
        assert any(item["rule_id"] == "no_roster" for item in before)
        posted = client.post("/api/roster", json=payload)
        assert posted.status_code == 200
        after = client.get(f"/api/documents/{document.document_id}/findings").json()
        assert not any(
            item["rule_id"] in {"no_roster", "identity_mismatch", "new_partner", "no_tin"}
            for item in after
        )
    example = load_roster(Path("fixtures/example-roster.json"))
    assert example.partnerships[0].ein.startswith("00-")
    assert example.investors[0].tin.startswith("000-")
    dest = tmp_path / "corpus"
    from k1lens.generate.corpus import generate_corpus

    generate_corpus(dest, seed=21, count=1, plan=(Variant.CLEAN,))
    bare = evaluate(dest, extractor=DeterministicExtractor())
    assert bare.straight_through == 0
    assert bare.confident_id_sections == 2
    assert bare.id_sections == 2
    assert "No roster was passed" in " ".join(bare.notes)
    built = roster_from_fixture_dir(dest)
    path = tmp_path / "from-ground-truth.json"
    path.write_text(json.dumps(dump_roster(built)), encoding="utf-8")
    scored = evaluate(
        dest,
        extractor=DeterministicExtractor(),
        roster=load_roster(path),
        roster_path=str(path),
    )
    assert "known before scoring" in " ".join(scored.notes)
    assert scored.confident_id_sections == 2
    unseen = evaluate(
        dest,
        extractor=DeterministicExtractor(),
        roster=example,
        roster_path="fixtures/example-roster.json",
    )
    assert unseen.straight_through == 0


def _section_stays_under(document: ScheduleK1, part: str) -> None:
    section = document.part_i if part == "part_i" else document.part_ii
    for name in ("name", "street", "city", "state", "zip_code"):
        assert getattr(section, name).confidence < REVIEW_THRESHOLD, name


def test_a_partial_match_does_not_lift() -> None:
    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    page = _document({**_PARTNERSHIP, **_INVESTOR, "part_i.city": "Salem"})
    bound = bind_roster(page, roster)
    _section_stays_under(bound, "part_i")
    assert bound.part_ii.name.confidence == REVIEW_THRESHOLD
    assert ("identity_mismatch", "part_i.name") in _ids(page, roster)


def test_a_low_confidence_id_does_not_lift() -> None:
    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    document = _document({**_PARTNERSHIP, **_INVESTOR}, id_confidence=0.79)
    assert document.part_i.ein.value == "00-0000108"
    bound = bind_roster(document, roster)
    _section_stays_under(bound, "part_i")
    _section_stays_under(bound, "part_ii")
    assert ("no_roster_match", "part_i.name") in _ids(document, roster)
    assert ("new_partner", "part_i.name") not in _ids(document, roster)


def test_an_invalid_id_does_not_lift_even_when_the_roster_stores_it() -> None:
    values = {**_PARTNERSHIP, **_INVESTOR, "part_i.ein": "OO-0000108"}
    document = _document(values)
    roster = roster_from_documents([document])
    assert classify_id(document.part_i.ein.value) == "invalid"
    bound = bind_roster(document, roster)
    _section_stays_under(bound, "part_i")
    assert bound.part_i.name.value == "Northwind Partners LP"
    assert ("no_tin", "part_i.name") in _ids(document, roster)
    assert ("new_partner", "part_i.name") not in _ids(document, roster)


def test_a_text_layer_id_below_the_threshold_is_not_a_key() -> None:
    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    document = _document(
        {**_PARTNERSHIP, **_INVESTOR},
        extractor="deterministic",
        id_digit_confidence=None,
        id_confidence=0.79,
    )
    assert classify_id(document.part_i.ein.value) == "valid"
    assert document.part_i.ein.provenance.extractor == "deterministic"
    assert document.part_i.ein.provenance.id_digit_confidence is None
    assert document.part_i.ein.confidence < REVIEW_THRESHOLD
    bound = bind_roster(document, roster)
    _section_stays_under(bound, "part_i")
    _section_stays_under(bound, "part_ii")
    holds = _ids(document, roster)
    assert ("no_roster_match", "part_i.name") in holds
    assert ("new_partner", "part_i.name") not in holds
    assert ("identity_mismatch", "part_i.name") not in holds


def test_a_lift_keeps_the_page_string_when_the_roster_case_or_spacing_differs() -> None:
    page_name = "Northwind  Partners LP"
    page_street = "4 Pine Street"
    document = _document(
        {
            **_PARTNERSHIP,
            **_INVESTOR,
            "part_i.name": page_name,
            "part_ii.street": page_street,
        }
    )
    built = roster_from_documents([document])
    roster = Roster(
        partnerships=(replace(built.partnerships[0], name="northwind partners lp"),),
        investors=(replace(built.investors[0], street="4  pine   street"),),
    )
    bound = bind_roster(document, roster)
    assert bound.part_i.name.value == page_name
    assert bound.part_i.name.value != "northwind partners lp"
    assert bound.part_i.name.confidence == REVIEW_THRESHOLD
    assert bound.part_ii.street.value == page_street
    assert bound.part_ii.street.confidence == REVIEW_THRESHOLD


def test_a_lift_stops_at_exactly_the_review_threshold() -> None:
    document = _document({**_PARTNERSHIP, **_INVESTOR}, evidence_confidence=0.99)
    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    assert document.part_i.name.confidence < REVIEW_THRESHOLD
    assert document.part_i.name.provenance.evidence_confidence == 0.99
    bound = bind_roster(document, roster)
    assert bound.part_i.name.confidence == REVIEW_THRESHOLD
    assert bound.part_ii.zip_code.confidence == REVIEW_THRESHOLD
    assert bound.part_i.name.confidence != 0.99
    assert bound.part_i.name.provenance.evidence_confidence == 0.99
    assert bound.part_i.name.value == "Northwind Partners LP"


def test_a_lifted_field_records_roster_exact_match(tmp_path: Path) -> None:
    from k1lens.review.store import ReviewStore

    page_name = "Northwind  Partners LP"
    document = _document({**_PARTNERSHIP, **_INVESTOR, "part_i.name": page_name})
    built = roster_from_documents([_document({**_PARTNERSHIP, **_INVESTOR})])
    roster = Roster(
        partnerships=(replace(built.partnerships[0], name="northwind partners lp"),),
        investors=built.investors,
    )
    store = ReviewStore(tmp_path / "lift.db", roster=roster)
    store.upsert(document, b"%PDF-1.4", [])
    stored = store.get("K1-ROSTER")
    assert stored is not None
    assert stored.document.part_i.name.value == page_name
    assert stored.document.part_i.name.confidence == REVIEW_THRESHOLD
    lifts = [entry for entry in store.audit("K1-ROSTER") if entry.action == "roster_exact_match"]
    by_path = {entry.field_path: entry for entry in lifts}
    assert "part_i.name" in by_path
    assert "part_ii.name" in by_path
    assert by_path["part_i.name"].new_value == page_name
    assert by_path["part_i.name"].new_value != "northwind partners lp"

    later = ReviewStore(tmp_path / "later.db")
    later.upsert(document, b"%PDF-1.4", [])
    assert not any(entry.action == "roster_exact_match" for entry in later.audit("K1-ROSTER"))
    later.set_roster(roster)
    attached = [entry for entry in later.audit("K1-ROSTER") if entry.action == "roster_exact_match"]
    attached_name = next(entry for entry in attached if entry.field_path == "part_i.name")
    assert attached_name.new_value == page_name

    mismatched = _document({**_PARTNERSHIP, **_INVESTOR, "part_i.city": "Salem"})
    fixing = ReviewStore(tmp_path / "fix.db", roster=_roster_for({**_PARTNERSHIP, **_INVESTOR}))
    fixing.upsert(mismatched, b"%PDF-1.4", [])
    assert not any(
        entry.field_path == "part_i.street" and entry.action == "roster_exact_match"
        for entry in fixing.audit("K1-ROSTER")
    )
    fixing.correct("K1-ROSTER", "part_i.city", "Portland", "Ada Reviewer")
    after = [entry for entry in fixing.audit("K1-ROSTER") if entry.action == "roster_exact_match"]
    corrected = {entry.field_path: entry for entry in after}
    assert "part_i.city" not in corrected
    assert corrected["part_i.street"].new_value == "10 Oak Avenue"
    assert corrected["part_i.name"].new_value == "Northwind Partners LP"


def test_a_duplicate_roster_key_is_not_a_match() -> None:
    page = _document({**_PARTNERSHIP, **_INVESTOR})
    built = roster_from_documents([page])
    first = built.partnerships[0]
    other = replace(first, name="Other Partnership LP", street="99 Other Road")
    duplicated = Roster(partnerships=(first, other), investors=built.investors)
    bound = bind_roster(page, duplicated)
    _section_stays_under(bound, "part_i")
    assert bound.part_i.name.value == "Northwind Partners LP"
    holds = _ids(page, duplicated)
    assert ("duplicate_roster_key", "part_i.name") in holds
    assert ("duplicate_roster_key", "part_i.zip_code") in holds
    assert ("new_partner", "part_i.name") not in holds
    assert bound.part_ii.name.confidence == REVIEW_THRESHOLD

    investor = built.investors[0]
    twin = replace(investor, name="SAMPLE Other Person", city="Eugene")
    both = Roster(partnerships=built.partnerships, investors=(investor, twin))
    partner = bind_roster(page, both)
    _section_stays_under(partner, "part_ii")
    partner_holds = _ids(page, both)
    assert ("duplicate_roster_key", "part_ii.name") in partner_holds
    assert ("new_partner", "part_ii.name") not in partner_holds


def test_an_unrecognized_layout_does_not_lift() -> None:
    document = _document({**_PARTNERSHIP, **_INVESTOR})
    data = document.model_dump(mode="json")
    data["layout_recognized"] = False
    unrecognized = ScheduleK1.model_validate(data)
    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    bound = bind_roster(unrecognized, roster)
    _section_stays_under(bound, "part_i")
    _section_stays_under(bound, "part_ii")


def test_a_model_field_blocks_the_whole_section_lift() -> None:
    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    data = _document({**_PARTNERSHIP, **_INVESTOR}).model_dump(mode="json")
    name = data["part_i"]["name"]
    assert isinstance(name, dict)
    provenance = name["provenance"]
    assert isinstance(provenance, dict)
    provenance["extractor"] = "llm"
    mixed = ScheduleK1.model_validate(data)
    bound = bind_roster(mixed, roster)
    _section_stays_under(bound, "part_i")
    assert bound.part_i.street.provenance.extractor != "llm"
    assert bound.part_ii.name.confidence == REVIEW_THRESHOLD


def test_a_value_outside_its_own_region_blocks_the_whole_section_lift() -> None:
    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    data = _document({**_PARTNERSHIP, **_INVESTOR}).model_dump(mode="json")
    street = data["part_ii"]["street"]
    assert isinstance(street, dict)
    provenance = street["provenance"]
    assert isinstance(provenance, dict)
    provenance["own_region"] = False
    off_region = ScheduleK1.model_validate(data)
    bound = bind_roster(off_region, roster)
    _section_stays_under(bound, "part_ii")
    assert bound.part_ii.name.provenance.own_region is True
    assert bound.part_i.name.confidence == REVIEW_THRESHOLD


def test_assemble_marks_another_column_as_not_this_fields_region() -> None:
    from k1lens.extract.assemble import assemble
    from k1lens.extract.labels import LayoutStats
    from k1lens.extract.text import Observed

    roster = _roster_for({**_PARTNERSHIP, **_INVESTOR})
    labels = {
        "E Partner TIN": ("000-00-0108", False),
        "F Partner name": ("SAMPLE Finley Cho", True),
        "F Partner street": ("4 Pine Street", False),
        "F Partner city": ("Salem", False),
        "F Partner state": ("OR", False),
        "F Partner ZIP": ("97301", False),
    }
    assembled = assemble(
        "K1-REGION",
        {
            label: [
                Observed(
                    value,
                    1,
                    None,
                    "deterministic",
                    label_score=1.0,
                    proximity=1.0,
                    neighbor_column=other_column,
                )
            ]
            for label, (value, other_column) in labels.items()
        },
        extractor="deterministic",
        layout_stats=LayoutStats(seen_lines=8, strong_anchors=8),
    )
    assert assembled.part_ii.name.provenance.own_region is False
    assert assembled.part_ii.street.provenance.own_region is True
    bound = bind_roster(assembled, roster)
    assert bound.part_ii.name.confidence < REVIEW_THRESHOLD
    assert bound.part_ii.street.confidence < REVIEW_THRESHOLD
    assert bound.part_ii.city.confidence < REVIEW_THRESHOLD


def test_validate_refuses_an_object_that_is_not_a_parsed_roster() -> None:
    document = _document({**_PARTNERSHIP, **_INVESTOR})
    with pytest.raises(TypeError, match="not a parsed roster"):
        validate_document(document, roster={"partnerships": []})
