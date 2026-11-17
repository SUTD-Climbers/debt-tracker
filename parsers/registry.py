from typing import Dict, List, Optional
from parsers.base import BaseGymParser
from parsers.sheet_parser import normalize_gym_name

_PARSER_REGISTRY: Dict[str, BaseGymParser] = {}


def register_parser(parser: BaseGymParser) -> None:
    # register a parser for a gym
    _PARSER_REGISTRY[parser.gym_name] = parser
    norm = normalize_gym_name(parser.gym_name)
    _PARSER_REGISTRY[norm] = parser


def get_parser(gym_name: str) -> Optional[BaseGymParser]:
    # ensure standard parsers are registered
    import parsers  # noqa: F401

    if gym_name in _PARSER_REGISTRY:
        return _PARSER_REGISTRY[gym_name]
    norm = normalize_gym_name(gym_name)
    if norm in _PARSER_REGISTRY:
        return _PARSER_REGISTRY[norm]
    for k, v in _PARSER_REGISTRY.items():
        if normalize_gym_name(k) == norm or k.strip().lower() == gym_name.strip().lower():
            return v
    return None


def list_registered_gyms() -> List[str]:
    import parsers  # noqa: F401
    return list(_PARSER_REGISTRY.keys())
