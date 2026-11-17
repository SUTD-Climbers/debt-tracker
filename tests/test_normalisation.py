import pytest

from services.normalisation import clean_name, resolve_canonical_name


def test_clean_name_whitespace_and_casing() -> None:
    # verify trimming and title casing for names
    assert clean_name("  DOE,   JANE  ") == "Doe, Jane"
    assert clean_name("smith, john") == "Smith, John"
    assert clean_name("ALEX TAN") == "Alex Tan"
    assert clean_name("") == ""
    assert clean_name(None) == ""


def test_resolve_canonical_name_with_aliases() -> None:
    # verify alias resolution against canonical member list
    members = [
        {
            "canonical_name": "Lim, Zachary",
            "aliases": "Lim, Zach;Zachary Lim;Zach Lim",
        },
        {
            "canonical_name": "Tan, Marcus",
            "aliases": "Tan Marcus;Marcus Tan",
        },
    ]

    # exact match
    assert resolve_canonical_name("Lim, Zachary", members) == "Lim, Zachary"

    # alias match
    assert resolve_canonical_name("Lim, Zach", members) == "Lim, Zachary"
    assert resolve_canonical_name("lim, zach", members) == "Lim, Zachary"
    assert resolve_canonical_name("Marcus Tan", members) == "Tan, Marcus"

    # unknown member returns cleaned title case
    assert resolve_canonical_name("Lee, Sarah", members) == "Lee, Sarah"
