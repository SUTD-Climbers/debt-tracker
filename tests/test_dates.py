from datetime import datetime
import pytest

from parsers.climbers_sutd import parse_day_first_date


def test_parse_day_first_non_padded_dates() -> None:
    # verify day-first parsing with and without zero padding
    dt1 = parse_day_first_date("7/1/2026")
    assert dt1 == datetime(2026, 1, 7)

    dt2 = parse_day_first_date("25/10/2026")
    assert dt2 == datetime(2026, 10, 25)

    dt3 = parse_day_first_date("01/05/2025")
    assert dt3 == datetime(2025, 5, 1)

    dt4 = parse_day_first_date("11/3/2026")
    assert dt4 == datetime(2026, 3, 11)


def test_parse_invalid_dates() -> None:
    # verify invalid or malformed dates return None
    assert parse_day_first_date("") is None
    assert parse_day_first_date("not-a-date") is None
    assert parse_day_first_date("2026-10-25") is None
    assert parse_day_first_date("32/1/2026") is None
