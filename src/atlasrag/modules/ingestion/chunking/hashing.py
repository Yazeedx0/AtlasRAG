import hashlib


def normalized_content_hash(content: str) -> str:
    normalized = "\n".join(line.rstrip() for line in content.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


__all__ = ["normalized_content_hash"]
