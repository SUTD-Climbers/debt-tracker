import tempfile
import pytest

from services.records import mark_pass_as_paid, mark_passes_as_paid_bulk, unmark_pass
from storage.local_csv import LocalCsvStorage


def test_mark_and_unmark_pass_paid() -> None:
    # verify status transitions and audit fields on marking and unmarking
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = LocalCsvStorage(data_dir=tmp_dir)

        records = [
            {
                "record_id": "rec_001",
                "gym": "Boulder +",
                "row_kind": "usage",
                "person": "Doe, Jane",
                "usage_date": "14/10/2026",
                "adj": -1,
                "status": "unpaid",
                "made_by": "",
                "made_at": "",
            },
            {
                "record_id": "rec_002",
                "gym": "Boulder +",
                "row_kind": "usage",
                "person": "Doe, Jane",
                "usage_date": "12/10/2026",
                "adj": -1,
                "status": "unpaid",
                "made_by": "",
                "made_at": "",
            },
        ]
        storage.add_records(records)

        # mark single pass as paid
        ok = mark_pass_as_paid(storage, "rec_001", paid_by="exco_user")
        assert ok is True

        stored = storage.get_records()
        rec_1 = next(r for r in stored if r["record_id"] == "rec_001")
        assert rec_1["status"] == "paid"
        assert rec_1["made_by"] == "exco_user"
        assert len(rec_1["made_at"]) > 0

        # unmark pass back to unpaid
        ok_unmark = unmark_pass(storage, "rec_001")
        assert ok_unmark is True

        stored_after = storage.get_records()
        rec_1_after = next(r for r in stored_after if r["record_id"] == "rec_001")
        assert rec_1_after["status"] == "unpaid"
        assert rec_1_after["made_by"] == ""
        assert rec_1_after["made_at"] == ""

        # bulk mark remaining
        count = mark_passes_as_paid_bulk(storage, ["rec_001", "rec_002"], paid_by="exco_admin")
        assert count == 2

        stored_final = storage.get_records()
        assert all(r["status"] == "paid" for r in stored_final)
        assert all(r["made_by"] == "exco_admin" for r in stored_final)
