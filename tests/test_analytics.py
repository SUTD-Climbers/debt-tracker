from datetime import datetime
import pytest

from services.analytics import calculate_member_debts, calculate_pool_summary, filter_records_by_date


def test_member_debt_aggregation_with_positive_corrections() -> None:
    # verify pass tallying handles negative usage and positive correction rows
    # Jane has two usage rows (-1, -1) and one positive correction (+1) -> net 1 pass used
    records = [
        {"row_kind": "usage", "person": "Doe, Jane", "adj": -1, "status": "unpaid", "usage_date": "14/10/2026"},
        {"row_kind": "usage", "person": "Doe, Jane", "adj": -1, "status": "unpaid", "usage_date": "12/10/2026"},
        {"row_kind": "usage", "person": "Doe, Jane", "adj": 1, "status": "unpaid", "usage_date": "10/10/2026"},
        {"row_kind": "usage", "person": "Smith, John", "adj": -1, "status": "unpaid", "usage_date": "15/10/2026"},
        {"row_kind": "topup", "person": "", "adj": 50, "status": "paid", "usage_date": "01/10/2026"},
    ]

    debts = calculate_member_debts(records, price_per_pass=16.0)

    # topup row should not create a member
    assert len(debts) == 2

    jane = next(d for d in debts if d["member"] == "Doe, Jane")
    assert jane["passes_used"] == 1
    assert jane["passes_owed"] == 1
    assert jane["amount_owed"] == 16.0

    john = next(d for d in debts if d["member"] == "Smith, John")
    assert john["passes_used"] == 1
    assert john["passes_owed"] == 1
    assert john["amount_owed"] == 16.0


def test_calculate_pool_summary() -> None:
    # verify pool summary calculates top-ups, usage, and derived net balance
    records = [
        {"row_kind": "topup", "adj": 100},
        {"row_kind": "topup", "adj": 50},
        {"row_kind": "usage", "adj": -1},
        {"row_kind": "usage", "adj": -1},
        {"row_kind": "usage", "adj": -1},
    ]

    summary = calculate_pool_summary(records)
    assert summary["total_topups"] == 150
    assert summary["total_usage"] == -3
    assert summary["net_balance"] == 147


def test_filter_records_by_date() -> None:
    # verify date range filtering
    records = [
        {"usage_date": "01/10/2026", "adj": -1},
        {"usage_date": "15/10/2026", "adj": -1},
        {"usage_date": "05/11/2026", "adj": -1},
    ]

    filtered = filter_records_by_date(
        records,
        start_date=datetime(2026, 10, 10),
        end_date=datetime(2026, 10, 31),
    )
    assert len(filtered) == 1
    assert filtered[0]["usage_date"] == "15/10/2026"
