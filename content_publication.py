from collections.abc import Mapping
from typing import Any


DEFAULT_PUBLISH_TO = ("dashboard", "newsletter")


def publication_targets(item: Mapping[str, Any]) -> tuple[str, ...]:
    targets = item.get("publish_to", DEFAULT_PUBLISH_TO)
    if isinstance(targets, str):
        targets = (targets,)
    if not isinstance(targets, (list, tuple, set, frozenset)):
        return ()
    return tuple(target for target in targets if isinstance(target, str))


def is_published_to(item: Mapping[str, Any], channel: str) -> bool:
    return channel in publication_targets(item)