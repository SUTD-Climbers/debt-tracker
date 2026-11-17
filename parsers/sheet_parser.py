import re
from typing import Any, Dict, List, Optional, Tuple


def normalize_gym_name(name: str) -> str:
    # normalize gym name variations to standard display names
    raw = (name or "").strip()
    clean = re.sub(r"\s+", " ", raw).strip()
    lower = clean.lower()

    if "planet" in lower:
        return "Boulder Planet"
    if "boulder" in lower and ("+" in lower or "plus" in lower):
        return "Boulder +"
    if "fitbloc" in lower:
        return "Fitbloc"
    if "bff" in lower:
        return "BFF"
    return clean


def get_gym_sheet_name(gym: str) -> str:
    # return the exact Google Sheet tab title for the given gym
    clean = (gym or "").strip().lower()
    if "planet" in clean:
        return "Boulder Planet"
    if "fitbloc" in clean:
        return "Fitbloc"
    if "bff" in clean:
        return "BFF"
    if "boulder" in clean:
        return "Boulder Plus"
    return gym


def parse_pricing_tab(rows: List[List[Any]]) -> Dict[str, Dict[str, float]]:
    # parse gym pricing matrix from pricing sheet rows
    pricing: Dict[str, Dict[str, float]] = {}
    if not rows:
        return pricing

    # locate header row with tier 1 and tier 2
    t1_col: Optional[int] = None
    t2_col: Optional[int] = None
    header_idx = -1

    for idx, row in enumerate(rows):
        for col_idx, cell in enumerate(row):
            txt = str(cell).strip().lower()
            if "tier 1" in txt or txt == "t1":
                t1_col = col_idx
            elif "tier 2" in txt or txt == "t2":
                t2_col = col_idx
        if t1_col is not None and t2_col is not None:
            header_idx = idx
            break

    # fallback to default column positions if not found
    if t1_col is None:
        t1_col = 1
    if t2_col is None:
        t2_col = 2

    # parse each gym pricing row
    start_row = header_idx + 1 if header_idx >= 0 else 1
    for row in rows[start_row:]:
        if not row or not str(row[0]).strip():
            continue

        raw_gym = str(row[0]).strip()
        norm_gym = normalize_gym_name(raw_gym)

        try:
            val_t1 = str(row[t1_col]).replace("$", "").strip() if len(row) > t1_col else ""
            t1_price = float(val_t1) if val_t1 else 18.0
        except (ValueError, TypeError):
            t1_price = 18.0

        try:
            val_t2 = str(row[t2_col]).replace("$", "").strip() if len(row) > t2_col else ""
            t2_price = float(val_t2) if val_t2 else 16.0
        except (ValueError, TypeError):
            t2_price = 16.0

        rates = {"tier_1": t1_price, "tier_2": t2_price}
        pricing[norm_gym] = rates
        pricing[raw_gym] = rates

    return pricing


def parse_gym_debt_sheet(
    rows: List[List[Any]],
    gym_name: str = "Boulder +",
) -> Dict[str, Any]:
    # parse member debts and last updated date from gym tab
    last_updated = ""
    members: List[Dict[str, Any]] = []

    if not rows:
        return {
            "gym": gym_name,
            "last_updated": last_updated,
            "members": members,
            "tier_1_members": [],
            "tier_2_members": [],
        }

    # find last updated date across top rows
    for r_idx in range(min(5, len(rows))):
        row = rows[r_idx]
        for c_idx, cell in enumerate(row):
            txt = str(cell).strip().lower()
            if "last updated" in txt:
                # check adjacent cells or same cell for date
                if ":" in str(cell):
                    parts = str(cell).split(":", 1)
                    if len(parts) > 1 and parts[1].strip():
                        last_updated = parts[1].strip()
                        break
                # look at subsequent cells in the same row
                for next_cell in row[c_idx + 1:]:
                    if str(next_cell).strip():
                        last_updated = str(next_cell).strip()
                        break
                if last_updated:
                    break
        if last_updated:
            break

    current_tier = ""
    name_col = 0
    passes_col = 1
    cost_col = 2

    for row in rows:
        if not row:
            continue

        first_cell = str(row[0]).strip() if len(row) > 0 else ""
        first_cell_lower = first_cell.lower()

        # detect tier sections
        if "tier 1" in first_cell_lower:
            current_tier = "tier_1"
            continue
        elif "tier 2" in first_cell_lower:
            current_tier = "tier_2"
            continue

        # detect header row inside tier
        if "name" in first_cell_lower and ("pass" in str(row).lower() or "cost" in str(row).lower()):
            for c_idx, c in enumerate(row):
                c_str = str(c).strip().lower()
                if "name" in c_str:
                    name_col = c_idx
                elif "pass" in c_str or "used" in c_str:
                    passes_col = c_idx
                elif "cost" in c_str or "$" in c_str:
                    cost_col = c_idx
            continue

        # if inside a tier section and first cell has a member name
        if current_tier and first_cell:
            if (
                first_cell.upper() in ("BOULDER PLUS", "BOULDER +", "BOULDER PLANET", "FITBLOC", "BFF")
                or "last updated" in first_cell_lower
                or "name" in first_cell_lower
            ):
                continue

            member_name = str(row[name_col]).strip() if len(row) > name_col else ""
            if not member_name:
                continue

            # parse passes used
            raw_passes = str(row[passes_col]).strip() if len(row) > passes_col else "0"
            try:
                passes_used = int(float(raw_passes))
            except (ValueError, TypeError):
                continue

            # parse total cost
            raw_cost = str(row[cost_col]).replace("$", "").strip() if len(row) > cost_col else ""
            try:
                total_cost = float(raw_cost) if raw_cost else float(passes_used * 16.0)
            except (ValueError, TypeError):
                total_cost = float(passes_used * 16.0)

            if passes_used > 0:
                members.append({
                    "name": member_name,
                    "tier": current_tier,
                    "passes_used": passes_used,
                    "total_cost": total_cost,
                })

    tier_1 = [m for m in members if m["tier"] == "tier_1"]
    tier_2 = [m for m in members if m["tier"] == "tier_2"]

    return {
        "gym": gym_name,
        "last_updated": last_updated,
        "members": members,
        "tier_1_members": tier_1,
        "tier_2_members": tier_2,
    }


def convert_sheet_debt_to_records(
    sheet_data: Dict[str, Any],
    pricing: Optional[Dict[str, Dict[str, float]]] = None,
) -> List[Dict[str, Any]]:
    # convert parsed sheet debts into granular usage records
    gym = sheet_data.get("gym", "Boulder +")
    last_updated = sheet_data.get("last_updated", "15/06/2026")
    members = sheet_data.get("members", [])

    records: List[Dict[str, Any]] = []

    for m in members:
        name = m["name"]
        tier = m.get("tier", "tier_2")
        passes_used = int(m.get("passes_used", 0))

        # create one individual usage record per pass owed
        for p_idx in range(passes_used):
            clean_name = re.sub(r"[^a-zA-Z0-9]", "_", name.lower()).strip("_")
            rec_id = f"rec_gsheet_{clean_name}_{p_idx + 1}"
            row_key = f"{gym}|{name}|{last_updated}|sheet_sync_{p_idx + 1}"

            records.append({
                "record_id": rec_id,
                "gym": gym,
                "row_kind": "usage",
                "person": name,
                "usage_date": last_updated,
                "adj": -1,
                "gym_staff": "Google Sheet Sync",
                "remarks": f"Initial debt from Google Sheet ({tier.replace('_', ' ').title()})",
                "source_upload_id": "google_sheet_baseline",
                "status": "unpaid",
                "made_by": "",
                "made_at": "",
                "row_key": row_key,
            })

    return records


def extract_member_tiers_from_sheet(rows: List[List[Any]]) -> Dict[str, str]:
    # extract known tier assignments per member from sheet rows
    tiers: Dict[str, str] = {}
    if not rows:
        return tiers

    current_tier = ""
    for row in rows:
        if not row:
            continue
        first_cell = str(row[0]).strip().lower()
        if "tier 1" in first_cell:
            current_tier = "tier_1"
            continue
        elif "tier 2" in first_cell:
            current_tier = "tier_2"
            continue
        if (
            "name" in first_cell
            or "last updated" in first_cell
            or first_cell.startswith("boulder")
            or first_cell.startswith("fitbloc")
            or first_cell.startswith("bff")
        ):
            continue
        if current_tier and row[0]:
            name = str(row[0]).strip()
            if name:
                tiers[name] = current_tier

    return tiers


def format_gym_debt_sheet(
    records: List[Dict[str, Any]],
    gym_name: str = "Boulder +",
    last_updated: Optional[str] = None,
    pricing_matrix: Optional[Dict[str, Dict[str, float]]] = None,
    member_tiers: Optional[Dict[str, str]] = None,
) -> List[List[Any]]:
    # format active member debts into the standard 2-tier google sheet grid
    from parsers.climbers_sutd import parse_day_first_date
    from services.pricing import get_pass_price

    tiers_map = member_tiers or {}

    # filter records for target gym
    gym_records = [r for r in records if r.get("gym") == gym_name or gym_name is None]

    # determine last updated date if not provided
    if not last_updated:
        dates = [parse_day_first_date(r.get("usage_date", "")) for r in gym_records if r.get("usage_date")]
        valid_dates = [d for d in dates if d is not None]
        if valid_dates:
            last_updated = max(valid_dates).strftime("%d/%m/%Y")
        else:
            last_updated = "15/06/2026"

    # aggregate debts per member for unpaid usage
    usage_records = [r for r in gym_records if r.get("row_kind") == "usage" and r.get("person")]
    member_groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in usage_records:
        person = r["person"]
        if person not in member_groups:
            member_groups[person] = []
        member_groups[person].append(r)

    tier_1_rows: List[List[Any]] = []
    tier_2_rows: List[List[Any]] = []

    for person, p_records in member_groups.items():
        # count unpaid passes
        unpaid_records = [r for r in p_records if r.get("status") in ("unpaid", "not_made")]
        unpaid_adj = sum(int(r.get("adj", 0)) for r in unpaid_records)
        unpaid_passes = -unpaid_adj

        # only members who owe passes appear on the sheet
        if unpaid_passes > 0:
            tier = tiers_map.get(person, "tier_2")
            rate = get_pass_price(gym_name, tier=tier, pricing_matrix=pricing_matrix)
            total_cost = int(unpaid_passes * rate)

            row_data = [person, unpaid_passes, total_cost]
            if tier == "tier_1":
                tier_1_rows.append(row_data)
            else:
                tier_2_rows.append(row_data)

    # sort members by passes owed descending, then name
    tier_1_rows.sort(key=lambda x: (-x[1], x[0]))
    tier_2_rows.sort(key=lambda x: (-x[1], x[0]))

    if "planet" in gym_name.lower():
        display_title = "BOULDER PLANET"
    elif "fitbloc" in gym_name.lower():
        display_title = "FITBLOC"
    elif "bff" in gym_name.lower():
        display_title = "BFF"
    elif "boulder" in gym_name.lower():
        display_title = "BOULDER PLUS"
    else:
        display_title = gym_name.upper()

    grid: List[List[Any]] = [
        [display_title, "Last Updated:", last_updated],
        ["Tier 1", "", ""],
        ["Name", "Passes Used", "Total Cost ($)"],
    ]
    grid.extend(tier_1_rows)

    grid.append(["", "", ""])
    grid.append(["Tier 2", "", ""])
    grid.append(["Name", "Passes Used", "Total Cost ($)"])
    grid.extend(tier_2_rows)

    # ensure all rows are rectangular with exactly 3 columns
    for row in grid:
        while len(row) < 3:
            row.append("")

    return grid
