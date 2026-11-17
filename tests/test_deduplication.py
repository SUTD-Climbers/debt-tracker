import pytest

from services.deduplication import build_row_key, calculate_multiset_diff


def test_build_row_key_deterministic() -> None:
    # ensure row key is deterministic and case insensitive
    key1 = build_row_key("14/10/2026", "DOE, JANE", -1, "Staff, Alex", "")
    key2 = build_row_key("14/10/2026", "Doe,  Jane", -1, "staff, alex", "  ")
    assert key1 == key2
    assert key1 == "14/10/2026|doe, jane|-1|staff, alex|"


def test_deduplication_two_genuinely_identical_rows() -> None:
    # two identical passes in one file must both be added to empty storage
    row_a = {
        "usage_date": "14/10/2026",
        "customer": "Doe, Jane",
        "adj": -1,
        "gym_staff": "Staff, Alex",
        "remarks": "",
    }
    row_b = {
        "usage_date": "14/10/2026",
        "customer": "Doe, Jane",
        "adj": -1,
        "gym_staff": "Staff, Alex",
        "remarks": "",
    }
    incoming = [row_a, row_b]
    stored = []

    to_add, skipped = calculate_multiset_diff(incoming, stored)
    assert len(to_add) == 2
    assert skipped == 0


def test_deduplication_reupload_same_file() -> None:
    # re-uploading an already stored file must add 0 rows and skip all
    row_a = {
        "usage_date": "14/10/2026",
        "customer": "Doe, Jane",
        "adj": -1,
        "gym_staff": "Staff, Alex",
        "remarks": "",
        "row_key": "14/10/2026|doe, jane|-1|staff, alex|",
    }
    row_b = {
        "usage_date": "14/10/2026",
        "customer": "Doe, Jane",
        "adj": -1,
        "gym_staff": "Staff, Alex",
        "remarks": "",
        "row_key": "14/10/2026|doe, jane|-1|staff, alex|",
    }
    stored = [dict(row_a), dict(row_b)]
    incoming = [dict(row_a), dict(row_b)]

    to_add, skipped = calculate_multiset_diff(incoming, stored)
    assert len(to_add) == 0
    assert skipped == 2


def test_deduplication_additional_identical_occurrence() -> None:
    # if incoming file has 3 identical rows and store has 2, add exactly 1
    row = {
        "usage_date": "14/10/2026",
        "customer": "Doe, Jane",
        "adj": -1,
        "gym_staff": "Staff, Alex",
        "remarks": "",
        "row_key": "14/10/2026|doe, jane|-1|staff, alex|",
    }
    stored = [dict(row), dict(row)]
    incoming = [dict(row), dict(row), dict(row)]

    to_add, skipped = calculate_multiset_diff(incoming, stored)
    assert len(to_add) == 1
    assert skipped == 2


def test_deduplication_partial_overlap_and_new_rows() -> None:
    # verify mixed batch with existing rows and brand new rows
    old_row = {
        "usage_date": "10/10/2026",
        "customer": "Smith, John",
        "adj": -1,
        "gym_staff": "Staff, Sam",
        "remarks": "",
        "row_key": "10/10/2026|smith, john|-1|staff, sam|",
    }
    new_row = {
        "usage_date": "15/10/2026",
        "customer": "Doe, Jane",
        "adj": -1,
        "gym_staff": "Staff, Alex",
        "remarks": "",
        "row_key": "15/10/2026|doe, jane|-1|staff, alex|",
    }

    stored = [dict(old_row)]
    incoming = [dict(old_row), dict(new_row)]

    to_add, skipped = calculate_multiset_diff(incoming, stored)
    assert len(to_add) == 1
    assert to_add[0]["usage_date"] == "15/10/2026"
    assert skipped == 1
