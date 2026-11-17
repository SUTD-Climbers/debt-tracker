from datetime import datetime
from pathlib import Path
import tempfile
import pytest

from parsers.climbers_sutd import parse_day_first_date
from services.records import commit_upload, process_upload
from storage.local_csv import LocalCsvStorage


def test_process_upload_references_latest_date_non_inclusive():
    # test that process_upload ignores rows on or before the reference date
    with tempfile.TemporaryDirectory() as tmp_dir:
        storage = LocalCsvStorage(data_dir=tmp_dir)

        # pre-populate a record on 15/06/2026
        storage.add_records([
            {
                "gym": "Boulder +",
                "row_kind": "usage",
                "person": "TestMember, One",
                "usage_date": "15/06/2026",
                "adj": -1,
                "status": "unpaid",
            }
        ])

        latest_dt = storage.get_latest_updated_date("Boulder +")
        assert latest_dt == datetime(2026, 6, 15)

        # check that real sample file (if available) only imports rows strictly after 15/06/2026
        sample_pdf = Path("samples/punches_history_sample.pdf")
        if sample_pdf.exists():
            with open(sample_pdf, "rb") as f:
                pdf_bytes = f.read()

            parse_res, summary = process_upload(
                file_bytes=pdf_bytes,
                filename="punches_history_sample.pdf",
                uploaded_by="exco_tester",
                storage=storage,
                gym_name="Boulder +",
            )

            assert parse_res.reconciliation_passed is True
            assert summary["rows_parsed"] == 754

            # exactly 27 rows occur after 15/06/2026
            assert summary["rows_added_count"] == 27
            assert summary["rows_prior_skipped"] == 727
            assert summary["reference_date"] == "15/06/2026"

            # all rows to add must have usage_date strictly after 15/06/2026
            ref_dt = datetime(2026, 6, 15)
            for r in summary["rows_to_add"]:
                row_dt = parse_day_first_date(r["usage_date"])
                assert row_dt > ref_dt

            # commit the upload
            upload_id = commit_upload(summary, storage, gym_name="Boulder +")
            assert upload_id.startswith("upl_")

            # verify storage latest updated date has been updated to 25/10/2026
            new_latest = storage.get_latest_updated_date("Boulder +")
            assert new_latest == datetime(2026, 10, 25)

            # re-uploading immediately after should add 0 rows because all rows are now <= 25/10/2026
            parse_res2, summary2 = process_upload(
                file_bytes=pdf_bytes,
                filename="punches_history_sample.pdf",
                uploaded_by="exco_tester",
                storage=storage,
                gym_name="Boulder +",
            )
            assert summary2["rows_added_count"] == 0
            assert summary2["rows_skipped_count"] == 754
