from typing import Any, Dict, List
import pytest

from parsers.climbers_sutd import elements_to_raw_rows, raw_rows_to_dataframe


def create_synthetic_line(
    top: float,
    usage_date: str,
    row_type: str,
    customer: str,
    gym_staff: str,
    remarks: str,
    expires: str,
    adj: str,
) -> List[Dict[str, Any]]:
    # helper generating synthetic character dictionaries with exact anchor positions
    chars: List[Dict[str, Any]] = []

    def add_fragment(text: str, start_x: float) -> None:
        if not text:
            return
        curr_x = start_x
        for char in text:
            chars.append({
                "text": char,
                "x0": curr_x,
                "x1": curr_x + 5.0,
                "top": top,
                "bottom": top + 10.0,
            })
            curr_x += 5.0

    add_fragment(usage_date, 52.5)
    add_fragment(row_type, 123.2)
    add_fragment(customer, 193.9)
    add_fragment(gym_staff, 264.6)
    add_fragment(remarks, 335.3)
    add_fragment(expires, 406.0)
    add_fragment(adj, 476.7)

    return chars


def test_parser_layer_b_and_c_basic() -> None:
    # verify end-to-end synthetic parsing of standard usage row
    line_chars = create_synthetic_line(
        top=180.0,
        usage_date="14/10/2026",
        row_type="Adj",
        customer="Doe, Jane",
        gym_staff="Staff, Alex",
        remarks="",
        expires="",
        adj="-1",
    )

    page_data = [{"page_idx": 0, "chars": line_chars, "text": "14/10/2026 Adj Doe, Jane Staff, Alex -1"}]
    raw_rows, failed_rows, prepared_at, total_dates = elements_to_raw_rows(page_data)

    assert len(raw_rows) == 1
    assert len(failed_rows) == 0
    assert total_dates == 1
    assert raw_rows[0]["adj"] == -1

    df = raw_rows_to_dataframe(raw_rows)
    assert len(df) == 1
    assert df.iloc[0]["customer"] == "Doe, Jane"
    assert df.iloc[0]["gym_staff"] == "Staff, Alex"
    assert df.iloc[0]["row_kind"] == "usage"
    assert df.iloc[0]["adj"] == -1


def test_parser_boundary_overlapping_customer_and_staff() -> None:
    # verify that a long customer name crossing into employee anchor is cleanly separated
    # customer text is 16 characters long (16 * 5 = 80 units wide, starting at 193.9 -> reaches 273.9 past 264.6)
    chars: List[Dict[str, Any]] = []

    # date at 52.5
    for i, ch in enumerate("14/10/2026"):
        chars.append({"text": ch, "x0": 52.5 + i * 5, "top": 180.0})
    # type at 123.2
    for i, ch in enumerate("Adj"):
        chars.append({"text": ch, "x0": 123.2 + i * 5, "top": 180.0})
    # long customer name at 193.9 extending past 264.6
    for i, ch in enumerate("Longmember, John"):
        chars.append({"text": ch, "x0": 193.9 + i * 5, "top": 180.0})
    # staff starting at 264.6
    for i, ch in enumerate("Staff, Alex"):
        chars.append({"text": ch, "x0": 264.6 + i * 5, "top": 180.0})
    # adj at 476.7
    for i, ch in enumerate("-1"):
        chars.append({"text": ch, "x0": 476.7 + i * 5, "top": 180.0})

    page_data = [{"page_idx": 0, "chars": chars, "text": ""}]
    raw_rows, failed_rows, _, total_dates = elements_to_raw_rows(page_data)

    assert len(raw_rows) == 1
    assert raw_rows[0]["customer"] == "Longmember, John"
    assert raw_rows[0]["gym_staff"] == "Staff, Alex"


def test_parser_topup_row_positive_adj() -> None:
    # verify top-up row with positive adj and no customer
    line_chars = create_synthetic_line(
        top=180.0,
        usage_date="10/4/2026",
        row_type="Adj",
        customer="",
        gym_staff="Staff, Sam",
        remarks="passes top up",
        expires="",
        adj="50",
    )

    page_data = [{"page_idx": 1, "chars": line_chars, "text": ""}]
    raw_rows, _, _, _ = elements_to_raw_rows(page_data)
    df = raw_rows_to_dataframe(raw_rows)

    assert len(df) == 1
    assert df.iloc[0]["row_kind"] == "topup"
    assert df.iloc[0]["adj"] == 50
    assert df.iloc[0]["customer"] == ""
    assert df.iloc[0]["gym_staff"] == "Staff, Sam"


def test_parser_missing_customer_heuristic() -> None:
    # usage row with single name present means that name is customer
    line_chars = create_synthetic_line(
        top=180.0,
        usage_date="12/05/2026",
        row_type="Adj",
        customer="",
        gym_staff="Doe, Jane",
        remarks="",
        expires="",
        adj="-1",
    )

    page_data = [{"page_idx": 1, "chars": line_chars, "text": ""}]
    raw_rows, _, _, _ = elements_to_raw_rows(page_data)
    df = raw_rows_to_dataframe(raw_rows)

    assert len(df) == 1
    assert df.iloc[0]["customer"] == "Doe, Jane"
    assert df.iloc[0]["gym_staff"] == ""
    assert df.iloc[0]["row_kind"] == "usage"


def test_parser_failed_row_detected() -> None:
    # verify row starting with date but corrupted adj is routed to failed rows
    chars: List[Dict[str, Any]] = []
    for i, ch in enumerate("14/10/2026"):
        chars.append({"text": ch, "x0": 52.5 + i * 5, "top": 180.0})
    for i, ch in enumerate("Adj"):
        chars.append({"text": ch, "x0": 123.2 + i * 5, "top": 180.0})
    # missing valid integer adj at 476.7

    page_data = [{"page_idx": 1, "chars": chars, "text": "14/10/2026 Adj"}]
    raw_rows, failed_rows, _, total_dates = elements_to_raw_rows(page_data)

    assert len(raw_rows) == 0
    assert len(failed_rows) == 1
    assert total_dates == 1
