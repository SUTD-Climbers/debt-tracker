import tempfile
import pytest

from storage.local_csv import LocalCsvStorage


def test_local_storage_crud() -> None:
    # verify local csv storage operations in temporary directory
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = LocalCsvStorage(data_dir=tmp_dir)

        # initially empty
        assert len(storage.get_records()) == 0
        assert len(storage.get_uploads()) == 0

        # add records
        records = [
            {
                "gym": "Boulder +",
                "row_kind": "usage",
                "person": "Doe, Jane",
                "usage_date": "14/10/2026",
                "adj": -1,
                "gym_staff": "Staff, Alex",
                "remarks": "",
                "source_upload_id": "upl_test_1",
                "status": "unpaid",
                "made_by": "",
                "made_at": "",
                "row_key": "14/10/2026|doe, jane|-1|staff, alex|",
            },
            {
                "gym": "Boulder +",
                "row_kind": "usage",
                "person": "Smith, John",
                "usage_date": "15/10/2026",
                "adj": -1,
                "gym_staff": "Staff, Sam",
                "remarks": "",
                "source_upload_id": "upl_test_1",
                "status": "unpaid",
                "made_by": "",
                "made_at": "",
                "row_key": "15/10/2026|smith, john|-1|staff, sam|",
            },
        ]
        added = storage.add_records(records)
        assert added == 2

        stored = storage.get_records()
        assert len(stored) == 2
        rec_id_1 = stored[0]["record_id"]

        # update single record status
        ok = storage.update_record_status(rec_id_1, "paid", "exco_user", "16/10/2026 10:00")
        assert ok is True

        updated = storage.get_records()
        row_1 = next(r for r in updated if r["record_id"] == rec_id_1)
        assert row_1["status"] == "paid"
        assert row_1["made_by"] == "exco_user"
        assert row_1["made_at"] == "16/10/2026 10:00"

        # record upload entry
        upload_entry = {
            "gym": "Boulder +",
            "filename": "audit.pdf",
            "uploaded_by": "exco_user",
            "uploaded_at": "16/10/2026 10:00",
            "report_prepared_at": "16/10/2026 09:00",
            "rows_parsed": 2,
            "usage_rows": 2,
            "topup_rows": 0,
            "rows_added": 2,
            "rows_skipped": 0,
            "earliest_date": "14/10/2026",
            "latest_date": "15/10/2026",
        }
        upl_id = storage.add_upload(upload_entry)
        assert upl_id.startswith("upl_")

        uploads = storage.get_uploads()
        assert len(uploads) == 1
        assert uploads[0]["filename"] == "audit.pdf"


def test_local_storage_balances() -> None:
    # verify available passes balance persistence
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = LocalCsvStorage(data_dir=tmp_dir)

        # verify defaults
        assert storage.get_available_passes("Boulder +") == 9
        assert storage.get_available_passes("Fitbloc") == 0
        assert storage.get_available_passes("Boulder Planet") == 18

        # update balances
        storage.set_available_passes("Boulder +", 50, updated_by="treasurer", note="New pass package")
        storage.set_available_passes("Fitbloc", 20, updated_by="treasurer", note="Fitbloc topup")

        assert storage.get_available_passes("Boulder +") == 50
        assert storage.get_available_passes("Boulder Plus") == 50
        assert storage.get_available_passes("Fitbloc") == 20
        assert storage.get_available_passes("Boulder Planet") == 18

        # verify re-loading from disk in new instance
        reloaded = LocalCsvStorage(data_dir=tmp_dir)
        assert reloaded.get_available_passes("Boulder +") == 50
        assert reloaded.get_available_passes("Fitbloc") == 20
        assert reloaded.get_available_passes("Boulder Planet") == 18
