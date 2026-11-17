import re
from typing import Any, Dict, List, Optional, Tuple


def clean_tokens(s: str) -> List[str]:
    # split string into lower-case alphanumeric tokens
    if not s:
        return []
    return [t for t in re.split(r"[^a-zA-Z0-9]+", s.lower()) if t]


def generate_name_variants(full_name: str) -> List[str]:
    # generate common permutations and abbreviations for a registered full name
    tokens = [t for t in re.split(r"[^a-zA-Z0-9]+", full_name.strip()) if t]
    if not tokens:
        return []

    variants = set()
    cleaned_original = " ".join(tokens)
    variants.add(cleaned_original)

    if len(tokens) >= 2:
        # Standard Asian surname first: tokens[0] is surname, tokens[1:] given
        rest_1 = " ".join(tokens[1:])
        variants.add(f"{tokens[0]}, {rest_1}")
        variants.add(f"{tokens[0]}, {tokens[1]}")
        # Western surname last: tokens[-1] is surname, tokens[:-1] given
        rest_last = " ".join(tokens[:-1])
        variants.add(f"{tokens[-1]}, {rest_last}")
        variants.add(f"{tokens[-1]}, {tokens[0]}")
        # First and last token combinations
        variants.add(f"{tokens[0]} {tokens[-1]}")
        variants.add(f"{tokens[-1]} {tokens[0]}")

    if len(tokens) >= 3:
        # Cross product of pairs for Chinese/composite names (e.g. Lim Hui Wen -> Lim, Charlotte)
        for idx in range(len(tokens)):
            surname_cand = tokens[idx]
            for other_idx in range(len(tokens)):
                if idx != other_idx:
                    variants.add(f"{surname_cand}, {tokens[other_idx]}")
                    variants.add(f"{tokens[other_idx]} {surname_cand}")

        # Compound last two tokens (e.g. Guan Yi -> Guanyi)
        comp_tail = tokens[-2] + tokens[-1]
        variants.add(f"{tokens[0]}, {comp_tail}")
        variants.add(f"{tokens[0]} {comp_tail}")

    # Sub-token single-letter initial for middle/western name (e.g. Owen -> O)
    if len(tokens) >= 3:
        initial_variant = " ".join(tokens[:-1]) + " " + tokens[-1][0].upper()
        variants.add(f"{tokens[0]}, {' '.join(tokens[1:-1])} {tokens[-1][0].upper()}")
        variants.add(initial_variant)

    return sorted(list(variants))


def match_person_to_member(
    person_name: str,
    members: List[Dict[str, Any]],
) -> Tuple[Optional[Dict[str, Any]], float]:
    # smart matching between a person name from PDF/gym sheet and canonical members
    if not person_name or not members:
        return None, 0.0

    p_tokens = clean_tokens(person_name)
    if not p_tokens:
        return None, 0.0

    p_lower = person_name.strip().lower()
    p_concat = "".join(p_tokens)

    best_match = None
    best_score = 0.0

    for m in members:
        c_name = m.get("canonical_name", "").strip()
        if not c_name:
            continue

        c_lower = c_name.lower()
        m_tokens = clean_tokens(c_name)
        m_concat = "".join(m_tokens)

        # 1. Exact string match against canonical name
        if p_lower == c_lower or p_concat == m_concat:
            return m, 100.0

        # 2. Check registered aliases
        raw_aliases = m.get("aliases", "")
        alias_list: List[str] = []
        if isinstance(raw_aliases, str):
            alias_list = [a.strip().lower() for a in raw_aliases.split(";") if a.strip()]
        elif isinstance(raw_aliases, list):
            alias_list = [str(a).strip().lower() for a in raw_aliases if str(a).strip()]

        if p_lower in alias_list or any("".join(clean_tokens(a)) == p_concat for a in alias_list):
            return m, 98.0

        score = 0.0

        # 3. All tokens in person name appear in member name (subset matching)
        # e.g. {'lim', 'charlotte'} in {'charlotte', 'lim', 'hui', 'wen'}
        p_set = set(p_tokens)
        m_set = set(m_tokens)
        if p_set.issubset(m_set):
            score = 90.0 + (len(p_tokens) / len(m_tokens)) * 5.0
        elif m_set.issubset(p_set):
            score = 88.0 + (len(m_tokens) / len(p_tokens)) * 5.0
        else:
            # 4. Partial token overlap, initial match, and sub-token containment
            matches = 0.0
            for pt in p_tokens:
                if pt in m_tokens:
                    matches += 1.0
                elif len(pt) == 1 and any(mt.startswith(pt) for mt in m_tokens):
                    matches += 0.8
                elif any(pt in mt or (len(mt) >= 4 and mt in pt) for mt in m_tokens if len(pt) >= 4):
                    matches += 0.95
                elif pt in m_concat or any(mt in pt for mt in m_tokens if len(mt) >= 3):
                    matches += 0.9

            # Require significant match relative to person token count
            if matches >= 1.6 and matches >= len(p_tokens) * 0.7:
                score = 80.0 + matches

        if score > best_score:
            best_score = score
            best_match = m

    if best_score >= 80.0:
        return best_match, best_score

    return None, best_score


def get_member_tier(
    person_name: str,
    members: List[Dict[str, Any]],
    default_tier: str = "tier_2",
) -> str:
    # return tier ('tier_1' or 'tier_2') for given person, defaulting to tier_2
    matched_member, _ = match_person_to_member(person_name, members)
    if matched_member:
        return matched_member.get("tier", default_tier)
    return default_tier


def get_member_tier_map(
    members: List[Dict[str, Any]],
    records: Optional[List[Dict[str, Any]]] = None,
    default_tier: str = "tier_2",
) -> Dict[str, str]:
    # return a dictionary mapping both canonical names and seen person names to their tier
    tier_map: Dict[str, str] = {}

    # map registered members
    for m in members:
        name = m.get("canonical_name", "").strip()
        tier = m.get("tier", default_tier)
        if name:
            tier_map[name] = tier

        # also map all aliases
        raw_aliases = m.get("aliases", "")
        if isinstance(raw_aliases, str):
            aliases = [a.strip() for a in raw_aliases.split(";") if a.strip()]
        elif isinstance(raw_aliases, list):
            aliases = [str(a).strip() for a in raw_aliases if str(a).strip()]
        else:
            aliases = []

        for alias in aliases:
            tier_map[alias] = tier

    # if records are provided, resolve any record person names
    if records:
        for r in records:
            p = r.get("person", "")
            if p and p not in tier_map:
                tier_map[p] = get_member_tier(p, members, default_tier=default_tier)

    return tier_map
