import pytest

from parsers.sheet_parser import (
    convert_sheet_debt_to_records,
    parse_gym_debt_sheet,
    parse_pricing_tab,
)
from services.analytics import calculate_member_debts
from services.pricing import get_gym_pricing, get_pass_price


def test_pricing_matrix_lookup():
    # test pricing lookups across gyms and tiers
    pricing_matrix = {
        "Boulder +": {"tier_1": 18.0, "tier_2": 16.0},
        "Boulder Planet": {"tier_1": 18.0, "tier_2": 16.0},
        "Fitbloc": {"tier_1": 18.0, "tier_2": 16.0},
        "BFF": {"tier_1": 18.0, "tier_2": 16.0},
    }

    # test rates for boulder +
    assert get_pass_price("Boulder +", tier="tier_1", pricing_matrix=pricing_matrix) == 18.0
    assert get_pass_price("Boulder +", tier="tier_2", pricing_matrix=pricing_matrix) == 16.0

    # test normalize gym name in lookup
    assert get_pass_price("Boulder Plus", tier="tier_2", pricing_matrix=pricing_matrix) == 16.0
    assert get_pass_price("Fitbloc", tier="tier_1", pricing_matrix=pricing_matrix) == 18.0
    assert get_pass_price("BFF", tier="tier_2", pricing_matrix=pricing_matrix) == 16.0


def test_sheet_debt_and_analytics_integration():
    # verify that parsed sheet debts feed directly into analytics with accurate tallies
    raw_pricing = [
        ["", "Tier 1", "Tier 2"],
        ["Boulder Planet", "18", "16"],
        ["Fitbloc", "18", "16"],
        ["BFF", "18", "16"],
        ["Boulder +", "18", "16"],
    ]
    pricing = parse_pricing_tab(raw_pricing)

    # use fake names for privacy constraint
    raw_sheet = [
        ["BOULDER PLUS", "Last Updated:", "15/06/2026"],
        ["Tier 1"],
        ["Name", "Passes Used", "Total Cost ($)"],
        [],
        ["Tier 2"],
        ["Name", "Passes Used", "Total Cost ($)"],
        ["Synthetic, Member1", "2", "32"],
        ["Synthetic, Member2", "2", "32"],
        ["Synthetic, Member3", "2", "32"],
        ["Synthetic, Member4", "2", "32"],
        ["Synthetic, Member5", "1", "16"],
        ["Synthetic, Member6", "1", "16"],
    ]

    sheet_data = parse_gym_debt_sheet(raw_sheet, gym_name="Boulder +")
    records = convert_sheet_debt_to_records(sheet_data, pricing)

    # calculate debts with tier 2 rate ($16)
    rate = get_pass_price("Boulder +", tier="tier_2", pricing_matrix=pricing)
    debts = calculate_member_debts(records, price_per_pass=rate, include_paid=False)

    # verify 6 members owe passes
    assert len(debts) == 6

    # total passes owed: 2 + 2 + 2 + 2 + 1 + 1 = 10
    total_passes = sum(m["passes_owed"] for m in debts)
    assert total_passes == 10

    # total dollar debt: 10 * $16 = $160
    total_dollar = sum(m["amount_owed"] for m in debts)
    assert total_dollar == 160.0

    # verify individual member totals
    m1 = next(m for m in debts if m["member"] == "Synthetic, Member1")
    assert m1["passes_owed"] == 2
    assert m1["amount_owed"] == 32.0

    m5 = next(m for m in debts if m["member"] == "Synthetic, Member5")
    assert m5["passes_owed"] == 1
    assert m5["amount_owed"] == 16.0
