import hashlib
import re


DEFAULT_CHUNK_SIZE = 1200
DEFAULT_CHUNK_OVERLAP = 120


def sha256_text(value: str):
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def normalize_index_text(text: str):
    return re.sub(r"\s+", " ", (text or "").strip())


def split_text(text: str, *, chunk_size=DEFAULT_CHUNK_SIZE, chunk_overlap=DEFAULT_CHUNK_OVERLAP):
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive.")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be non-negative and smaller than chunk_size.")
    normalized = normalize_index_text(text)
    if not normalized:
        return
    step = chunk_size - chunk_overlap
    for start in range(0, len(normalized), step):
        yield normalized[start : start + chunk_size]
        if start + chunk_size >= len(normalized):
            break
