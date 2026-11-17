from datetime import datetime
from typing import Any, Dict, List, Optional

from parsers.climbers_sutd import parse_day_first_date


def filter_records_by_date(
    records: List[Dict[str, Any]],
    start_date: Optional[datetime] = None,
    end_date: Optional[datetime] = None,
) -> List[Dict[str, Any]]:
    # filter record list by inclusive date range
    if not start_date and not end_date:
        return records

    filtered: List[Dict[str, Any]] = []
    for r in records:
        d = parse_day_first_date(r.get("usage_date", ""))
        if not d:
            continue
        if start_date and d < start_date:
            continue
        if end_date and d > end_date:
            continue
        filtered.append(r)

    return filtered


def calculate_member_debts(
    records: List[Dict[str, Any]],
    price_per_pass: float = 16.0,
    include_paid: bool = False,
    gym_name: str = "Boulder +",
    pricing_matrix: Optional[Dict[str, Dict[str, float]]] = None,
    member_tiers: Optional[Dict[str, str]] = None,
    canonical_members: Optional[List[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    # aggregate pass usage and debts per member handling positive corrections and tier pricing
    # only usage rows count toward member tallies
    usage_records = [r for r in records if r.get("row_kind") == "usage" and r.get("person")]

    member_groups: Dict[str, List[Dict[str, Any]]] = {}
    for r in usage_records:
        person = r["person"]
        if person not in member_groups:
            member_groups[person] = []
        member_groups[person].append(r)

    summary_list: List[Dict[str, Any]] = []

    for person, p_records in member_groups.items():
        # net passes used is minus the sum of adj
        total_adj = sum(int(r.get("adj", 0)) for r in p_records)
        net_passes_used = -total_adj

        # count unpaid passes
        unpaid_records = [r for r in p_records if r.get("status") in ("unpaid", "not_made")]
        unpaid_adj = sum(int(r.get("adj", 0)) for r in unpaid_records)
        unpaid_passes = -unpaid_adj

        # determine member tier
        tier = "tier_2"
        if member_tiers and person in member_tiers:
            tier = member_tiers[person]
        elif canonical_members:
            from services.members import get_member_tier
            tier = get_member_tier(person, canonical_members)

        # resolve applicable pass rate
        if pricing_matrix:
            from services.pricing import get_pass_price
            rate = get_pass_price(gym_name, tier=tier, pricing_matrix=pricing_matrix)
        else:
            rate = price_per_pass

        amount_owed = max(0, unpaid_passes) * rate

        # resolve canonical name for bridging display
        matched_canonical = person
        if canonical_members:
            from services.members import match_person_to_member
            matched, _ = match_person_to_member(person, canonical_members)
            if matched:
                matched_canonical = matched.get("canonical_name", person)

        if include_paid or unpaid_passes > 0:
            summary_list.append({
                "member": person,
                "canonical_name": matched_canonical,
                "tier": tier,
                "rate_per_pass": rate,
                "passes_used": max(0, net_passes_used),
                "passes_owed": max(0, unpaid_passes),
                "amount_owed": amount_owed,
                "status": f"{unpaid_passes} passes owed" if unpaid_passes > 0 else "Paid",
                "records": sorted(
                    p_records,
                    key=lambda r: parse_day_first_date(r.get("usage_date", "")) or datetime.min,
                    reverse=True,
                ),
            })

    # sort by most passes owed descending
    summary_list.sort(key=lambda x: x["passes_owed"], reverse=True)
    return summary_list


def calculate_pool_summary(records: List[Dict[str, Any]]) -> Dict[str, int]:
    # calculate top-ups, member usage, and report-derived net balance
    total_topups = 0
    total_usage = 0

    for r in records:
        adj = int(r.get("adj", 0))
        if r.get("row_kind") == "topup" or adj > 0:
            total_topups += adj
        else:
            total_usage += adj

    net_balance = total_topups + total_usage

    return {
        "total_topups": total_topups,
        "total_usage": total_usage,
        "net_balance": net_balance,
    }
