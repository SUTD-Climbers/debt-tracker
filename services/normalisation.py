import re
from typing import Any, Dict, List, Optional


def clean_name(name: Optional[str]) -> str:
    # trim collapse whitespace and format name in title case
    if not name:
        return ""

    # collapse multiple spaces and tabs
    collapsed = re.sub(r"\s+", " ", name).strip()
    if not collapsed:
        return ""

    # preserve last first comma formatting
    parts = collapsed.split(",")
    if len(parts) == 2:
        last = parts[0].strip().title()
        first = parts[1].strip().title()
        return f"{last}, {first}"

    return collapsed.title()


def resolve_canonical_name(
    name: Optional[str],
    members: Optional[List[Dict[str, Any]]] = None,
) -> str:
    # map name variant to canonical member name if registered
    cleaned = clean_name(name)
    if not cleaned or not members:
        return cleaned

    target_lower = cleaned.lower()

    for m in members:
        canonical = m.get("canonical_name", "").strip()
        if not canonical:
            continue
        if canonical.lower() == target_lower:
            return canonical

        raw_aliases = m.get("aliases", "")
        if isinstance(raw_aliases, str):
            alias_list = [a.strip().lower() for a in raw_aliases.split(";") if a.strip()]
        elif isinstance(raw_aliases, list):
            alias_list = [str(a).strip().lower() for a in raw_aliases if str(a).strip()]
        else:
            alias_list = []

        if target_lower in alias_list:
            return canonical

    # smart token & permutation match
    from services.members import match_person_to_member
    matched, score = match_person_to_member(cleaned, members)
    if matched and score >= 80.0:
        return matched.get("canonical_name", cleaned)

    return cleaned
