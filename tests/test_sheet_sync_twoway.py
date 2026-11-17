import json
from pathlib import Path
import tempfile
import pytest

from parsers.sheet_parser import (
    extract_member_tiers_from_sheet,
    format_gym_debt_sheet,
    parse_gym_debt_sheet,
    parse_pricing_tab,
)
from storage.local_csv import LocalCsvStorage


def test_format_gym_debt_sheet_removes_paid_members():
    # simulate records where synthetic member 1 has 2 passes and member 2 has 1 pass
    pricing_matrix = {
        "Boulder +": {"tier_1": 18.0, "tier_2": 16.0},
    }

    records = [
        {
            "record_id": "rec_1",
            "gym": "Boulder +",
            "row_kind": "usage",
            "person": "Synthetic, Member1",
            "usage_date": "15/06/2026",
            "adj": -1,
            "status": "unpaid",
        },
        {
            "record_id": "rec_2",
            "gym": "Boulder +",
            "row_kind": "usage",
            "person": "Synthetic, Member1",
            "usage_date": "15/06/2026",
            "adj": -1,
            "status": "unpaid",
        },
        {
            "record_id": "rec_3",
            "gym": "Boulder +",
            "row_kind": "usage",
            "person": "Synthetic, Member2",
            "usage_date": "15/06/2026",
            "adj": -1,
            "status": "unpaid",
        },
    ]

    # before settlement: both members are in tier 2
    grid = format_gym_debt_sheet(records, gym_name="Boulder +", pricing_matrix=pricing_matrix)
    names_in_sheet = [row[0] for row in grid if row and len(row) > 1 and row[0] not in ("BOULDER PLUS", "Tier 1", "Tier 2", "Name")]
    assert "Synthetic, Member1" in names_in_sheet
    assert "Synthetic, Member2" in names_in_sheet

    # mark member 2 pass as paid
    records[2]["status"] = "paid"
    grid_after = format_gym_debt_sheet(records, gym_name="Boulder +", pricing_matrix=pricing_matrix)
    names_after = [row[0] for row in grid_after if row and len(row) > 1 and row[0] not in ("BOULDER PLUS", "Tier 1", "Tier 2", "Name")]

    # member 2 has 0 unpaid passes, so row is completely removed from the sheet!
    assert "Synthetic, Member2" not in names_after
    assert "Synthetic, Member1" in names_after

    # member 1 partially pays 1 pass: passes used becomes 1, cost becomes 16
    records[0]["status"] = "paid"
    grid_partial = format_gym_debt_sheet(records, gym_name="Boulder +", pricing_matrix=pricing_matrix)
    m1_row = next(row for row in grid_partial if row and row[0] == "Synthetic, Member1")
    assert m1_row[1] == 1
    assert m1_row[2] == 16


def test_format_gym_debt_sheet_appends_new_pdf_upload():
    # simulate existing records plus new usage rows from an uploaded pdf
    pricing_matrix = {
        "Boulder +": {"tier_1": 18.0, "tier_2": 16.0},
    }

    records = [
        {
            "record_id": "rec_1",
            "gym": "Boulder +",
            "row_kind": "usage",
            "person": "Synthetic, ExistingMember",
            "usage_date": "15/06/2026",
            "adj": -1,
            "status": "unpaid",
        },
    ]

    grid_initial = format_gym_debt_sheet(records, gym_name="Boulder +", pricing_matrix=pricing_matrix)
    assert grid_initial[0][2] == "15/06/2026"

    # new pdf uploaded with a pass for a new member on 25/10/2026
    new_pdf_record = {
        "record_id": "rec_new_from_pdf",
        "gym": "Boulder +",
        "row_kind": "usage",
        "person": "Synthetic, NewClimber",
        "usage_date": "25/10/2026",
        "adj": -1,
        "status": "unpaid",
    }
    records.append(new_pdf_record)

    grid_updated = format_gym_debt_sheet(records, gym_name="Boulder +", pricing_matrix=pricing_matrix)

    # date is updated to latest date in file
    assert grid_updated[0][2] == "25/10/2026"

    # new member is appended in the sheet
    names = [row[0] for row in grid_updated if row and len(row) > 1 and row[0] not in ("BOULDER PLUS", "Tier 1", "Tier 2", "Name")]
    assert "Synthetic, NewClimber" in names
    assert "Synthetic, ExistingMember" in names


def test_local_storage_two_way_sheet_sync():
    # verify that LocalCsvStorage updates the seed sheet json when marking paid and adding records
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # create initial seed json in tmp_dir
        initial_seed = {
            "Pricing": [
                ["", "Tier 1", "Tier 2"],
                ["Boulder +", "18", "16"],
            ],
            "Boulder Plus": [
                ["BOULDER PLUS", "Last Updated:", "15/06/2026"],
                ["Tier 1"],
                ["Name", "Passes Used", "Total Cost ($)"],
                [],
                ["Tier 2"],
                ["Name", "Passes Used", "Total Cost ($)"],
                ["Synthetic, MemberA", "1", "16"],
                ["Synthetic, MemberB", "2", "32"],
            ],
        }
        with open(tmp_path / "seed_google_sheet.json", "w", encoding="utf-8") as f:
            json.dump(initial_seed, f)

        # initialize storage, which reads and seeds initial data
        storage = LocalCsvStorage(data_dir=tmp_dir)
        records = storage.get_records("Boulder +")
        assert len(records) == 3

        # find MemberA's record and mark as paid
        rec_a = next(r for r in records if r["person"] == "Synthetic, MemberA")
        storage.update_record_status(rec_a["record_id"], "paid", "exco_tester", "17/11/2026 10:00")

        # read updated seed json file from disk
        with open(tmp_path / "seed_google_sheet.json", "r", encoding="utf-8") as f:
            updated_seed = json.load(f)

        boulder_sheet = updated_seed["Boulder Plus"]
        active_names = [r[0] for r in boulder_sheet if r and len(r) > 1 and r[0] not in ("BOULDER PLUS", "Tier 1", "Tier 2", "Name")]

        # MemberA has paid, so MemberA's row is removed from the sheet!
        assert "Synthetic, MemberA" not in active_names
        # MemberB still owes passes, so MemberB remains!
        assert "Synthetic, MemberB" in active_names

        # Now simulate committing new upload rows (PDF upload)
        new_row = {
            "gym": "Boulder +",
            "row_kind": "usage",
            "person": "Synthetic, NewMemberFromPDF",
            "usage_date": "20/10/2026",
            "adj": -1,
            "status": "unpaid",
        }
        storage.add_records([new_row])

        # read updated seed json file again
        with open(tmp_path / "seed_google_sheet.json", "r", encoding="utf-8") as f:
            final_seed = json.load(f)

        final_sheet = final_seed["Boulder Plus"]
        final_names = [r[0] for r in final_sheet if r and len(r) > 1 and r[0] not in ("BOULDER PLUS", "Tier 1", "Tier 2", "Name")]

        # new member is appended in the sheet and latest date is updated
        assert "Synthetic, NewMemberFromPDF" in final_names
        assert final_sheet[0][2] == "20/10/2026"
