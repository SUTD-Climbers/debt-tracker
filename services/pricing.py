from typing import Any, Dict, Optional
import streamlit as st

from parsers.sheet_parser import normalize_gym_name

# default pricing matrix matching the google sheet pricing tab
DEFAULT_PRICING: Dict[str, Dict[str, float]] = {
    "Boulder +": {"tier_1": 18.0, "tier_2": 16.0},
    "Boulder Plus": {"tier_1": 18.0, "tier_2": 16.0},
    "Boulder Planet": {"tier_1": 18.0, "tier_2": 16.0},
    "Fitbloc": {"tier_1": 18.0, "tier_2": 16.0},
    "BFF": {"tier_1": 18.0, "tier_2": 16.0},
}


def get_gym_pricing(
    gym_name: str,
    pricing_matrix: Optional[Dict[str, Dict[str, float]]] = None,
) -> Dict[str, float]:
    # return tier pricing dictionary for a given gym
    matrix = pricing_matrix or DEFAULT_PRICING
    norm_gym = normalize_gym_name(gym_name)

    if norm_gym in matrix:
        return matrix[norm_gym]
    if gym_name in matrix:
        return matrix[gym_name]

    # case-insensitive and normalized fallback search
    for k, v in matrix.items():
        if normalize_gym_name(k) == norm_gym or k.strip().lower() == gym_name.strip().lower():
            return v

    # fallback default
    return {"tier_1": 18.0, "tier_2": 16.0}


def get_pass_price(
    gym_name: str,
    tier: str = "tier_2",
    pricing_matrix: Optional[Dict[str, Dict[str, float]]] = None,
) -> float:
    # return the price for a pass at the specified gym and tier
    gym_rates = get_gym_pricing(gym_name, pricing_matrix)
    normalized_tier = "tier_1" if "1" in str(tier).lower() else "tier_2"
    return gym_rates.get(normalized_tier, 16.0)
