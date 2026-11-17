from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import pandas as pd

from parsers.base import ParseResult
from parsers.registry import get_parser
from parsers.climbers_sutd import parse_day_first_date
from services.deduplication import calculate_multiset_diff
from storage.base import StorageBackend


def process_upload(
    file_bytes: bytes,
    filename: str,
    uploaded_by: str,
    storage: StorageBackend,
    gym_name: str = "Boulder +",
    cutoff_date: Optional[datetime] = None,
) -> Tuple[Optional[ParseResult], Optional[Dict[str, Any]]]:
    # parse upload file and take rows appearing strictly after the latest updated date
    parser = get_parser(gym_name)
    if not parser:
        raise ValueError(f"No registered parser found for gym: {gym_name}")

    members = storage.get_members()
    parse_result = parser.parse(file_bytes, members=members)

    if parse_result.error_message:
        return parse_result, None

    # determine reference date from storage if not explicitly provided
    reference_date = cutoff_date if cutoff_date is not None else storage.get_latest_updated_date(gym=gym_name)

    # retrieve stored records for target gym
    stored_records = storage.get_records(gym=gym_name)

    # convert parsed dataframe to record dicts
    incoming_rows: List[Dict[str, Any]] = parse_result.data.to_dict(orient="records")

    candidate_rows: List[Dict[str, Any]] = []
    rows_prior_skipped = 0

    for r in incoming_rows:
        row_dt = parse_day_first_date(r.get("usage_date", ""))
        # if reference date exists, take only rows occurring after that date (non-inclusive)
        if reference_date and row_dt and row_dt <= reference_date:
            rows_prior_skipped += 1
        else:
            candidate_rows.append(r)

    # perform multiset deduplication on candidate rows
    rows_to_add, duplicate_skipped = calculate_multiset_diff(
        candidate_rows,
        stored_records,
        members=members,
    )

    total_skipped = rows_prior_skipped + duplicate_skipped

    for r in rows_to_add:
        r["gym"] = gym_name
        r["source_upload_id"] = ""
        r["person"] = r.get("customer", "")
        r["status"] = "unpaid"
        r["made_by"] = ""
        r["made_at"] = ""

    # find earliest and latest date among rows to add
    add_dates = [parse_day_first_date(r.get("usage_date", "")) for r in rows_to_add if r.get("usage_date")]
    valid_add_dates = [d for d in add_dates if d is not None]
    newest_add_date = max(valid_add_dates).strftime("%d/%m/%Y") if valid_add_dates else parse_result.latest_date
    earliest_add_date = min(valid_add_dates).strftime("%d/%m/%Y") if valid_add_dates else parse_result.earliest_date

    summary = {
        "gym_name": gym_name,
        "filename": filename,
        "uploaded_by": uploaded_by,
        "report_prepared_at": parse_result.report_prepared_at,
        "rows_parsed": len(incoming_rows),
        "rows_to_add": rows_to_add,
        "rows_added_count": len(rows_to_add),
        "rows_skipped_count": total_skipped,
        "rows_prior_skipped": rows_prior_skipped,
        "duplicate_skipped": duplicate_skipped,
        "reference_date": reference_date.strftime("%d/%m/%Y") if reference_date else None,
        "earliest_date": earliest_add_date,
        "latest_date": newest_add_date,
    }

    return parse_result, summary


def commit_upload(
    summary: Dict[str, Any],
    storage: StorageBackend,
    gym_name: str = "Boulder +",
) -> str:
    # save confirmed rows and upload audit entry to storage
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    rows_to_add = summary["rows_to_add"]

    # record upload audit entry first
    upload_entry = {
        "gym": gym_name,
        "filename": summary["filename"],
        "uploaded_by": summary["uploaded_by"],
        "uploaded_at": now_str,
        "report_prepared_at": summary.get("report_prepared_at", ""),
        "rows_parsed": summary["rows_parsed"],
        "usage_rows": sum(1 for r in rows_to_add if r.get("row_kind") == "usage"),
        "topup_rows": sum(1 for r in rows_to_add if r.get("row_kind") == "topup"),
        "rows_added": len(rows_to_add),
        "rows_skipped": summary["rows_skipped_count"],
        "earliest_date": summary.get("earliest_date", ""),
        "latest_date": summary.get("latest_date", ""),
    }
    upload_id = storage.add_upload(upload_entry)

    # attach upload id to records
    for r in rows_to_add:
        r["source_upload_id"] = upload_id

    storage.add_records(rows_to_add)
    return upload_id


def mark_pass_as_paid(
    storage: StorageBackend,
    record_id: str,
    paid_by: str,
) -> bool:
    # mark a single pass record as paid
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    return storage.update_record_status(record_id, "paid", paid_by, now_str)


def mark_passes_as_paid_bulk(
    storage: StorageBackend,
    record_ids: List[str],
    paid_by: str,
) -> int:
    # mark multiple pass records as paid
    now_str = datetime.now().strftime("%d/%m/%Y %H:%M")
    return storage.update_records_bulk(record_ids, "paid", paid_by, now_str)


def unmark_pass(
    storage: StorageBackend,
    record_id: str,
) -> bool:
    # revert pass record back to unpaid
    return storage.update_record_status(record_id, "unpaid", "", "")
