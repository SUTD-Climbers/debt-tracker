from collections import Counter
from typing import Any, Dict, List, Optional, Tuple

from services.normalisation import clean_name, resolve_canonical_name


def build_row_key(
    usage_date: str,
    customer: str,
    adj: int,
    gym_staff: str,
    remarks: str,
    members: Optional[List[Dict[str, Any]]] = None,
) -> str:
    # create deterministic canonical row key for deduplication
    norm_customer = resolve_canonical_name(customer, members).strip().lower()
    norm_staff = clean_name(gym_staff).strip().lower()
    norm_remarks = " ".join(remarks.split()).strip().lower()
    norm_date = usage_date.strip()

    return f"{norm_date}|{norm_customer}|{adj}|{norm_staff}|{norm_remarks}"


def calculate_multiset_diff(
    incoming_rows: List[Dict[str, Any]],
    stored_records: List[Dict[str, Any]],
    members: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    # determine new rows to add by multiset frequency difference
    stored_counts: Counter[str] = Counter()
    for rec in stored_records:
        key = rec.get("row_key")
        if not key:
            key = build_row_key(
                usage_date=rec.get("usage_date", ""),
                customer=rec.get("person", "") or rec.get("customer", ""),
                adj=int(rec.get("adj", 0)),
                gym_staff=rec.get("gym_staff", ""),
                remarks=rec.get("remarks", ""),
                members=members,
            )
        stored_counts[key] += 1

    seen_in_upload: Counter[str] = Counter()
    rows_to_add: List[Dict[str, Any]] = []
    rows_skipped = 0

    for row in incoming_rows:
        key = row.get("row_key")
        if not key:
            key = build_row_key(
                usage_date=row.get("usage_date", ""),
                customer=row.get("customer", "") or row.get("person", ""),
                adj=int(row.get("adj", 0)),
                gym_staff=row.get("gym_staff", ""),
                remarks=row.get("remarks", ""),
                members=members,
            )
            row["row_key"] = key

        seen_in_upload[key] += 1
        # add only when occurrences in file exceed stored occurrences
        if seen_in_upload[key] > stored_counts[key]:
            rows_to_add.append(row)
        else:
            rows_skipped += 1

    return rows_to_add, rows_skipped
