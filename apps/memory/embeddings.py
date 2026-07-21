from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Protocol, Sequence, runtime_checkable

from django.conf import settings


DEFAULT_TEST_EMBEDDING_PROFILE = "local_hash_test_v1"


@dataclass(frozen=True)
class EmbeddingModelMetadata:
    profile_id: str
    provider: str
    model: str
    dimensions: int
    normalization: bool
    version: str


@runtime_checkable
class EmbeddingProvider(Protocol):
    @property
    def metadata(self) -> EmbeddingModelMetadata:
        """Return stable metadata for trace and index invalidation."""

    def embed_text(self, text: str) -> list[float]:
        """Embed indexable document text locally."""

    def embed_query(self, query: str) -> list[float]:
        """Embed search query locally."""


class DeterministicLocalEmbeddingProvider:
    """Small local provider for tests and smoke checks.

    It is not a semantic model. It keeps the vector path executable without
    network downloads or cloud embeddings.
    """

    def __init__(self, *, profile_id: str, model: str = "local-hash-test-v1", dimensions: int = 64, normalization: bool = True):
        self._metadata = EmbeddingModelMetadata(
            profile_id=profile_id,
            provider="local",
            model=model,
            dimensions=dimensions,
            normalization=normalization,
            version=f"{model}:{dimensions}:v1",
        )

    @property
    def metadata(self) -> EmbeddingModelMetadata:
        return self._metadata

    def embed_text(self, text: str) -> list[float]:
        return self._embed(text)

    def embed_query(self, query: str) -> list[float]:
        return self._embed(query)

    def _embed(self, value: str) -> list[float]:
        dims = self._metadata.dimensions
        vector = [0.0] * dims
        tokens = _tokens(value)
        if not tokens:
            return vector
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dims
            sign = -1.0 if digest[4] % 2 else 1.0
            vector[index] += sign
        return _normalise(vector) if self._metadata.normalization else vector


class SentenceTransformerEmbeddingProvider:
    def __init__(self, *, profile_id: str, model: str, dimensions: int, normalization: bool = True):
        self._metadata = EmbeddingModelMetadata(
            profile_id=profile_id,
            provider="local",
            model=model,
            dimensions=dimensions,
            normalization=normalization,
            version=f"{model}:sentence-transformers",
        )
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:
            raise RuntimeError("sentence-transformers is required for this local embedding profile.") from exc
        self._model = SentenceTransformer(model)

    @property
    def metadata(self) -> EmbeddingModelMetadata:
        return self._metadata

    def embed_text(self, text: str) -> list[float]:
        return self._encode(text)

    def embed_query(self, query: str) -> list[float]:
        return self._encode(query)

    def _encode(self, value: str) -> list[float]:
        embedding = self._model.encode(
            str(value or ""),
            normalize_embeddings=self._metadata.normalization,
            show_progress_bar=False,
        )
        return [float(item) for item in embedding.tolist()]


def get_embedding_provider(profile_id: str | None = None) -> EmbeddingProvider:
    selected_profile = profile_id or getattr(settings, "LOCAL_BUSINESS_MEMORY_EMBEDDING_PROFILE", DEFAULT_TEST_EMBEDDING_PROFILE)
    profiles = dict((getattr(settings, "LOCAL_BUSINESS_MEMORY_PROFILES", {}) or {}).get("embedding_profiles", {}) or {})
    profile = profiles.get(selected_profile)
    if profile is None and selected_profile == DEFAULT_TEST_EMBEDDING_PROFILE:
        profile = {
            "provider": "local",
            "model": "local-hash-test-v1",
            "dimensions": 64,
            "normalization": True,
        }
    if profile is None:
        raise RuntimeError(f"Unknown memory embedding profile '{selected_profile}'.")
    model = str(profile.get("model") or "").strip()
    dimensions = int(profile.get("dimensions") or 0)
    normalization = bool(profile.get("normalization", True))
    if model.startswith("local-hash"):
        return DeterministicLocalEmbeddingProvider(
            profile_id=selected_profile,
            model=model,
            dimensions=dimensions or 64,
            normalization=normalization,
        )
    return SentenceTransformerEmbeddingProvider(
        profile_id=selected_profile,
        model=model,
        dimensions=dimensions,
        normalization=normalization,
    )


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token.lower() for token in str(value or "").split() if token.strip())


def _normalise(vector: Sequence[float]) -> list[float]:
    norm = math.sqrt(sum(item * item for item in vector))
    if norm == 0:
        return [0.0 for _item in vector]
    return [float(item / norm) for item in vector]


__all__ = [
    "DEFAULT_TEST_EMBEDDING_PROFILE",
    "DeterministicLocalEmbeddingProvider",
    "EmbeddingModelMetadata",
    "EmbeddingProvider",
    "SentenceTransformerEmbeddingProvider",
    "get_embedding_provider",
]
