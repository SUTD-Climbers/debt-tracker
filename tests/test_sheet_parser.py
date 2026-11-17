import pytest
from parsers.sheet_parser import (
    convert_sheet_debt_to_records,
    normalize_gym_name,
    parse_gym_debt_sheet,
    parse_pricing_tab,
)


def test_normalize_gym_name():
    assert normalize_gym_name("Boulder Plus") == "Boulder +"
    assert normalize_gym_name("BOULDER PLUS") == "Boulder +"
    assert normalize_gym_name("Boulder +") == "Boulder +"
    assert normalize_gym_name("Boulder Planet") == "Boulder Planet"
    assert normalize_gym_name("Fitbloc") == "Fitbloc"
    assert normalize_gym_name("BFF") == "BFF"


def test_parse_pricing_tab():
    # simulate the pricing tab from screenshot with Boulder Plus and swapped row order
    raw_pricing = [
        ["", "Tier 1", "Tier 2"],
        ["Boulder Planet", 18, 16],
        ["Fitbloc", "18", "16"],
        ["Boulder Plus", "18", "16"],
        ["BFF", "$18", "$16"],
    ]

    pricing = parse_pricing_tab(raw_pricing)
    assert "Boulder +" in pricing
    assert "Boulder Plus" in pricing
    assert pricing["Boulder +"]["tier_1"] == 18.0
    assert pricing["Boulder +"]["tier_2"] == 16.0
    assert pricing["Boulder Plus"]["tier_1"] == 18.0
    assert pricing["Boulder Plus"]["tier_2"] == 16.0
    assert pricing["Boulder Planet"]["tier_1"] == 18.0
    assert pricing["Boulder Planet"]["tier_2"] == 16.0
    assert pricing["Fitbloc"]["tier_1"] == 18.0
    assert pricing["Fitbloc"]["tier_2"] == 16.0
    assert pricing["BFF"]["tier_1"] == 18.0
    assert pricing["BFF"]["tier_2"] == 16.0


def test_parse_gym_debt_sheet_and_convert_records():
    # simulate the gym sheet from screenshot 1 using synthetic test names
    raw_sheet = [
        ["BOULDER PLUS", "Last Updated:", "15/06/2026", ""],
        ["Tier 1", "", "", ""],
        ["Name", "Passes Used", "Total Cost ($)", ""],
        ["", "", "", ""],
        ["Tier 2", "", "", ""],
        ["Name", "Passes Used", "Total Cost ($)", ""],
        ["TestMember, Alpha", "2", "32", ""],
        ["TestMember, Beta", "2", "32", ""],
        ["TestMember, Gamma", "2", "32", ""],
        ["TestMember, Delta", "2", "32", ""],
        ["TestMember, Epsilon", "1", "16", ""],
        ["TestMember, Zeta", "1", "16", ""],
    ]

    res = parse_gym_debt_sheet(raw_sheet, gym_name="Boulder +")
    assert res["last_updated"] == "15/06/2026"
    assert len(res["tier_1_members"]) == 0
    assert len(res["tier_2_members"]) == 6

    # check member parsing
    members = res["tier_2_members"]
    assert members[0]["name"] == "TestMember, Alpha"
    assert members[0]["passes_used"] == 2
    assert members[0]["total_cost"] == 32.0
    assert members[4]["name"] == "TestMember, Epsilon"
    assert members[4]["passes_used"] == 1
    assert members[4]["total_cost"] == 16.0

    # convert to records
    records = convert_sheet_debt_to_records(res)
    # 2 + 2 + 2 + 2 + 1 + 1 = 10 records
    assert len(records) == 10
    assert all(r["gym"] == "Boulder +" for r in records)
    assert all(r["usage_date"] == "15/06/2026" for r in records)
    assert all(r["status"] == "unpaid" for r in records)
    assert all(r["adj"] == -1 for r in records)
    assert all(r["row_kind"] == "usage" for r in records)

    # verify 2 individual records created for 2 passes
    alpha_recs = [r for r in records if r["person"] == "TestMember, Alpha"]
    assert len(alpha_recs) == 2
