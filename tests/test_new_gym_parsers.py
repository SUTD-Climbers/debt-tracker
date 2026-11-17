from pathlib import Path
import pytest
from parsers.boulder_planet import BoulderPlanetParser
from parsers.fitbloc import FitblocParser
from parsers.registry import get_parser
from parsers.sheet_parser import format_gym_debt_sheet, get_gym_sheet_name, normalize_gym_name
from services.records import process_upload
from storage.local_csv import LocalCsvStorage


def test_parser_registry_new_gyms():
    p_fitbloc = get_parser("Fitbloc")
    assert p_fitbloc is not None
    assert p_fitbloc.gym_name == "Fitbloc"

    p_bp = get_parser("Boulder Planet")
    assert p_bp is not None
    assert p_bp.gym_name == "Boulder Planet"


def test_get_gym_sheet_name():
    assert get_gym_sheet_name("Boulder +") == "Boulder Plus"
    assert get_gym_sheet_name("Boulder Plus") == "Boulder Plus"
    assert get_gym_sheet_name("Fitbloc") == "Fitbloc"
    assert get_gym_sheet_name("Boulder Planet") == "Boulder Planet"


def test_fitbloc_sample_parsing():
    sample_path = Path("samples/fitbloc_sample.PDF")
    assert sample_path.exists()

    parser = FitblocParser()
    res = parser.parse(sample_path)

    assert res.gym == "Fitbloc"
    assert res.reconciliation_passed is True
    assert len(res.data) == 30
    assert res.earliest_date == "17/04/2026"
    assert res.latest_date == "24/08/2026"


def test_boulder_planet_sample_parsing():
    sample_path = Path("samples/boulder_planet_sample.PDF")
    assert sample_path.exists()

    parser = BoulderPlanetParser()
    res = parser.parse(sample_path)

    assert res.gym == "Boulder Planet"
    assert res.reconciliation_passed is True
    assert len(res.data) == 82
    assert res.earliest_date == "10/01/2026"
    assert res.latest_date == "19/09/2026"


def test_format_gym_debt_sheet_titles():
    # test header title generation for the new gyms
    dummy_records = [
        {
            "record_id": "r1",
            "gym": "Fitbloc",
            "row_kind": "usage",
            "person": "Climber A",
            "usage_date": "01/08/2026",
            "adj": -1,
            "status": "unpaid",
        },
        {
            "record_id": "r2",
            "gym": "Boulder Planet",
            "row_kind": "usage",
            "person": "Climber B",
            "usage_date": "02/08/2026",
            "adj": -2,
            "status": "unpaid",
        },
    ]

    fitbloc_sheet = format_gym_debt_sheet(dummy_records, gym_name="Fitbloc")
    assert fitbloc_sheet[0][0] == "FITBLOC"

    bp_sheet = format_gym_debt_sheet(dummy_records, gym_name="Boulder Planet")
    assert bp_sheet[0][0] == "BOULDER PLANET"


def test_process_upload_fitbloc(tmp_path):
    from services.records import commit_upload

    storage = LocalCsvStorage(data_dir=str(tmp_path))
    sample_path = Path("samples/fitbloc_sample.PDF")
    file_bytes = sample_path.read_bytes()

    parse_res, summary = process_upload(
        file_bytes=file_bytes,
        filename="fitbloc_sample.PDF",
        uploaded_by="test_user",
        storage=storage,
        gym_name="Fitbloc",
    )

    assert parse_res is not None
    assert parse_res.reconciliation_passed is True
    assert summary["gym_name"] == "Fitbloc"
    assert summary["rows_parsed"] == 30

    upload_id = commit_upload(summary, storage, gym_name="Fitbloc")
    assert upload_id is not None
    records = storage.get_records(gym="Fitbloc")
    assert len(records) == 30
    assert all(r["gym"] == "Fitbloc" for r in records)


def test_process_upload_boulder_planet(tmp_path):
    from services.records import commit_upload

    storage = LocalCsvStorage(data_dir=str(tmp_path))
    sample_path = Path("samples/boulder_planet_sample.PDF")
    file_bytes = sample_path.read_bytes()

    parse_res, summary = process_upload(
        file_bytes=file_bytes,
        filename="boulder_planet_sample.PDF",
        uploaded_by="test_user",
        storage=storage,
        gym_name="Boulder Planet",
    )

    assert parse_res is not None
    assert parse_res.reconciliation_passed is True
    assert summary["gym_name"] == "Boulder Planet"
    assert summary["rows_parsed"] == 82

    upload_id = commit_upload(summary, storage, gym_name="Boulder Planet")
    assert upload_id is not None
    records = storage.get_records(gym="Boulder Planet")
    assert len(records) == 82
    assert all(r["gym"] == "Boulder Planet" for r in records)

