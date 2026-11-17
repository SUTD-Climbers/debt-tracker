from services.analytics import calculate_member_debts
from services.members import (
    clean_tokens,
    generate_name_variants,
    get_member_tier,
    get_member_tier_map,
    match_person_to_member,
)
from parsers.sheet_parser import format_gym_debt_sheet


def test_tier_difference_computation():
    # synthetic members test
    all_members = [
        {"canonical_name": "Member Alpha", "email": "alpha@example.com"},
        {"canonical_name": "Member Beta", "email": "beta@example.com"},
        {"canonical_name": "Member Gamma", "email": "gamma@example.com"},
    ]
    t2_emails = {"alpha@example.com", "gamma@example.com"}

    classified = []
    for m in all_members:
        tier = "tier_2" if m["email"] in t2_emails else "tier_1"
        classified.append({**m, "tier": tier})

    t1 = [m["canonical_name"] for m in classified if m["tier"] == "tier_1"]
    t2 = [m["canonical_name"] for m in classified if m["tier"] == "tier_2"]

    assert t1 == ["Member Beta"]
    assert sorted(t2) == ["Member Alpha", "Member Gamma"]


def test_smart_name_matching_variations():
    # test various synthetic and realistic naming discrepancies
    members = [
        {"canonical_name": "Charlotte Lim Hui Wen", "aliases": "", "tier": "tier_2"},
        {"canonical_name": "Li Guan Yi", "aliases": "", "tier": "tier_2"},
        {"canonical_name": "Anton Rahul Obordo Karve", "aliases": "", "tier": "tier_2"},
        {"canonical_name": "Ho Shang Luen Owen", "aliases": "", "tier": "tier_2"},
        {"canonical_name": "Aishah Suratman", "aliases": "", "tier": "tier_1"},
        {"canonical_name": "Emmanuel Luis Delacruz Fontanilla", "aliases": "", "tier": "tier_1"},
        {"canonical_name": "Senthilkumar Kunalkumar", "aliases": "", "tier": "tier_2"},
    ]

    # Inverted comma
    m1, sc1 = match_person_to_member("Lim, Charlotte", members)
    assert m1 is not None and m1["canonical_name"] == "Charlotte Lim Hui Wen"
    assert sc1 >= 90.0

    # Compounded Chinese name
    m2, sc2 = match_person_to_member("Li, Guanyi", members)
    assert m2 is not None and m2["canonical_name"] == "Li Guan Yi"

    # Middle token initial
    m3, sc3 = match_person_to_member("Ho, Shang Luen O", members)
    assert m3 is not None and m3["canonical_name"] == "Ho Shang Luen Owen"

    # First and last only
    m4, sc4 = match_person_to_member("Karve, Anton", members)
    assert m4 is not None and m4["canonical_name"] == "Anton Rahul Obordo Karve"

    # Subtoken containment
    m5, sc5 = match_person_to_member("Kumar, Kunal", members)
    assert m5 is not None and m5["canonical_name"] == "Senthilkumar Kunalkumar"

    # Unregistered person returns None
    m_unreg, sc_unreg = match_person_to_member("Unknown Climber", members)
    assert m_unreg is None
    assert sc_unreg < 80.0


def test_member_tier_pricing_calculation():
    # test calculation of member debts with tier 1 ($18) and tier 2 ($16) pricing
    records = [
        {"person": "Suratman, Aishah", "row_kind": "usage", "adj": -2, "status": "unpaid", "gym": "Boulder +"},
        {"person": "Lim, Charlotte", "row_kind": "usage", "adj": -3, "status": "unpaid", "gym": "Boulder +"},
        {"person": "Unknown Person", "row_kind": "usage", "adj": -1, "status": "unpaid", "gym": "Boulder +"},
    ]

    canonical_members = [
        {"canonical_name": "Aishah Suratman", "tier": "tier_1", "aliases": "Suratman, Aishah"},
        {"canonical_name": "Charlotte Lim Hui Wen", "tier": "tier_2", "aliases": "Lim, Charlotte"},
    ]

    pricing_matrix = {
        "Boulder +": {"tier_1": 18.0, "tier_2": 16.0}
    }

    tier_map = get_member_tier_map(canonical_members, records=records)

    debts = calculate_member_debts(
        records,
        gym_name="Boulder +",
        pricing_matrix=pricing_matrix,
        member_tiers=tier_map,
        canonical_members=canonical_members,
        include_paid=False,
    )

    debts_by_name = {d["member"]: d for d in debts}

    # Aishah: Tier 1, 2 passes * $18 = $36
    aishah = debts_by_name["Suratman, Aishah"]
    assert aishah["tier"] == "tier_1"
    assert aishah["passes_owed"] == 2
    assert aishah["rate_per_pass"] == 18.0
    assert aishah["amount_owed"] == 36.0

    # Charlotte: Tier 2, 3 passes * $16 = $48
    charlotte = debts_by_name["Lim, Charlotte"]
    assert charlotte["tier"] == "tier_2"
    assert charlotte["passes_owed"] == 3
    assert charlotte["rate_per_pass"] == 16.0
    assert charlotte["amount_owed"] == 48.0

    # Unknown Person: defaults to Tier 2, 1 pass * $16 = $16
    unknown = debts_by_name["Unknown Person"]
    assert unknown["tier"] == "tier_2"
    assert unknown["passes_owed"] == 1
    assert unknown["rate_per_pass"] == 16.0
    assert unknown["amount_owed"] == 16.0


def test_format_gym_debt_sheet_segregates_tiers():
    # test format_gym_debt_sheet formats 2-tier rectangular layout
    records = [
        {"person": "Member T1", "row_kind": "usage", "adj": -2, "status": "unpaid", "gym": "Boulder +"},
        {"person": "Member T2", "row_kind": "usage", "adj": -1, "status": "unpaid", "gym": "Boulder +"},
    ]

    pricing = {"Boulder +": {"tier_1": 18.0, "tier_2": 16.0}}
    tiers = {"Member T1": "tier_1", "Member T2": "tier_2"}

    grid = format_gym_debt_sheet(
        records=records,
        gym_name="Boulder +",
        pricing_matrix=pricing,
        member_tiers=tiers,
        last_updated="25/10/2026",
    )

    # verify rectangularity (every row has 3 columns)
    for row in grid:
        assert len(row) == 3

    # verify header
    assert grid[0] == ["BOULDER PLUS", "Last Updated:", "25/10/2026"]
    assert grid[1] == ["Tier 1", "", ""]
    assert grid[2] == ["Name", "Passes Used", "Total Cost ($)"]
    assert grid[3] == ["Member T1", 2, 36]

    # verify tier 2 section
    assert grid[4] == ["", "", ""]
    assert grid[5] == ["Tier 2", "", ""]
    assert grid[6] == ["Name", "Passes Used", "Total Cost ($)"]
    assert grid[7] == ["Member T2", 1, 16]


def test_members_not_stored_in_main_spreadsheet():
    # verify GoogleSheetsStorage holds members in memory and does not write them to the main spreadsheet
    from unittest.mock import MagicMock
    from storage.google_sheets import GoogleSheetsStorage

    storage = GoogleSheetsStorage()
    mock_ss = MagicMock()
    mock_ws_records = MagicMock()
    mock_ws_uploads = MagicMock()
    mock_legacy_members = MagicMock()
    mock_legacy_members.row_values.return_value = ["canonical_name", "tier", "email"]

    def fake_worksheet(name):
        if name == "Records":
            return mock_ws_records
        elif name == "Uploads":
            return mock_ws_uploads
        elif name == "Members":
            return mock_legacy_members
        raise Exception(f"Worksheet {name} not found")

    mock_ss.worksheet.side_effect = fake_worksheet
    mock_client = MagicMock()
    mock_client.open_by_key.return_value = mock_ss

    storage._client = mock_client
    storage._spreadsheet = mock_ss

    # Test save_members only stores in memory
    synthetic_members = [
        {"canonical_name": "Test Climber", "tier": "tier_1", "email": "test@example.com"}
    ]
    storage.save_members(synthetic_members)

    # verify mock_ss.worksheet was NEVER called to write or update a "Members" tab
    assert storage.get_members() == synthetic_members
    mock_ss.add_worksheet.assert_not_called()
    mock_legacy_members.update.assert_not_called()
    mock_legacy_members.clear.assert_not_called()


def test_member_drilldown_rate_resolution():
    # verify member drilldown rows resolve m_rate without NameError
    from services.analytics import calculate_member_debts
    records = [
        {"person": "Climber A", "row_kind": "usage", "adj": -1, "status": "unpaid", "gym": "Boulder +", "usage_date": "15/06/2026", "type": "Usage", "gym_staff": "Alex"}
    ]
    debts = calculate_member_debts(records, gym_name="Boulder +")
    member_data = debts[0]
    m_rate = member_data.get("rate_per_pass", 16.0)
    drill_rows = [
        [
            r.get("usage_date", ""),
            r.get("type", "Adj"),
            f"{r.get('adj', -1)} pass",
            f"${int(m_rate)}",
            r.get("gym_staff", ""),
            "Unpaid" if r.get("status") in ("unpaid", "not_made") else "Paid",
        ]
        for r in member_data.get("records", [])
    ]
    assert len(drill_rows) == 1
    assert drill_rows[0][3] == "$16"
