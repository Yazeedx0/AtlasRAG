import hashlib
import json
from collections.abc import Mapping


def canonical_configuration_hash(configuration: Mapping[str, object]) -> str:
    serialized = json.dumps(configuration, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


__all__ = ["canonical_configuration_hash"]
