"""CROW operations on already authorized Markdown at a specific Git revision.

The caller resolves authorization, page IDs, revisions and destinations. This
module cannot open a wiki, resolve a source, publish a page or expand a scope.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from ipaddress import ip_address
from math import isclose, isfinite
from pathlib import Path
from urllib.parse import urlsplit


class CrowUnavailable(RuntimeError):
    """Optional engine or configured decision endpoint is unavailable."""


@dataclass(frozen=True)
class CrowPage:
    knowledge_id: str
    revision: str
    title: str
    description: str
    body: str

    def __post_init__(self) -> None:
        if not self.knowledge_id or not re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", self.revision):
            raise ValueError("CROW requires a knowledge ID and a full Git commit SHA.")


def _load_crow():
    try:
        import llmw2
    except ImportError as exc:
        raise CrowUnavailable("Install the optional requirements-crow.txt dependency.") from exc
    if getattr(llmw2, "__version__", None) != "1.0.5":
        raise CrowUnavailable("This adapter supports llmwiki2==1.0.5.")
    return llmw2


def search_crow_pages(query: str, pages: Sequence[CrowPage], *, limit: int = 8) -> list[str]:
    """Rank exactly these pages with CROW BM25, without I/O, embeddings or a writer."""
    if not query.strip() or limit < 1:
        raise ValueError("Provide a non-empty query and a positive search limit.")
    crow = _load_crow()
    # 1.0.5's public Wiki.search loads a whole bundle. NoteSearch is the pinned
    # internal implementation that Wiki.search uses after loading its candidates.
    from llmw2.search import NoteSearch

    notes = []
    ids = set()
    for index, page in enumerate(pages):
        if page.knowledge_id in ids:
            raise ValueError("Duplicate knowledge ID in the authorized CROW candidates.")
        ids.add(page.knowledge_id)
        opaque_path = f"{index}.md"
        notes.append(crow.Note(
            path=Path(opaque_path),
            rel=opaque_path,
            frontmatter={"id": page.knowledge_id, "title": page.title, "description": page.description},
            body=page.body,
        ))
    # Never reuse frequency statistics across recipients. Both upstream input
    # lists include only the approved notes, including when the caller found none.
    ranked = NoteSearch(vectors=None).search(notes, notes, query, limit)
    return [note.id for note in ranked]


@dataclass(frozen=True)
class CrowDecisionConfig:
    """Server configuration. A key, model or URL must never come from a tool call."""

    provider: str
    model: str = ""
    base_url: str = ""
    api_key: str = field(default="", repr=False)


_RELATIONS = {
    "supports": "The texts agree on the same claim under the same conditions.",
    "complements": "One text adds scope or detail without contradicting the other.",
    "conflicts": "Claims about the same subject, period and conditions cannot both hold.",
    "unrelated": "The texts concern different subjects.",
    "uncertain": "The evidence or applicable conditions are insufficient.",
}
_CHANGE_RELATIONS = {
    "already_covered": "The current article already covers the entire proposal under the same conditions.",
    "extends": "The proposal adds compatible information or clarifies the current topic.",
    "conflicts": "A claim conflicts with the article under comparable conditions and dates.",
    "unrelated": "The proposal belongs to a different topic.",
    "uncertain": "There is insufficient evidence to decide the relation.",
}
_REMOTE_ENDPOINTS = {
    "typesafe": "https://api.typesafe.ai/v1",
    "openrouter": "https://openrouter.ai/api/v1",
}


def _decision_endpoint(config: CrowDecisionConfig, allow_external: bool) -> str:
    if config.provider in _REMOTE_ENDPOINTS:
        expected = _REMOTE_ENDPOINTS[config.provider]
        if not allow_external:
            raise ValueError("External CROW classification is not permitted for these pages.")
        if config.base_url and config.base_url.rstrip("/") != expected:
            raise ValueError("The configured CROW endpoint does not match the named provider.")
        if not config.api_key:
            raise CrowUnavailable("No API key configured for the CROW classifier.")
        return expected
    if config.provider != "custom":
        raise CrowUnavailable("No supported CROW decision provider configured.")

    # A local decision must remain local even with external HTTP proxy settings.
    url = urlsplit(config.base_url)
    host = url.hostname or ""
    if (url.scheme not in ("http", "https") or url.username is not None or
            url.password is not None or url.query or url.fragment):
        raise ValueError("Local CROW requires a loopback HTTP(S) base URL.")
    if host == "localhost" and url.scheme == "http":
        host = "127.0.0.1"
    try:
        local = ip_address(host)
    except ValueError:
        raise ValueError("Use a numeric loopback address for the local CROW classifier.") from None
    if not local.is_loopback:
        raise ValueError("A custom CROW classifier must run on a loopback address.")
    hostname = f"[{local}]" if local.version == 6 else str(local)
    port = f":{url.port}" if url.port is not None else ""
    return f"{url.scheme}://{hostname}{port}{url.path.rstrip('/')}"


def classify_crow_relation(
    left: CrowPage,
    right: CrowPage,
    *,
    config: CrowDecisionConfig,
    allow_external: bool = False,
) -> dict:
    """Compare two approved page versions. The result is advisory and changes nothing.

    allow_external is set by server policy after checking BOTH pages and the
    audience/destination. The System One call receives only their titles/bodies.
    """
    if left.knowledge_id == right.knowledge_id and left.revision == right.revision:
        raise ValueError("Select two different pages or revisions.")
    state = [{"title": p.title, "body": p.body} for p in (left, right)]
    return _typed_choice(
        state, "Compare the claims in these two documents, including their scope and dates.", _RELATIONS,
        config=config, allow_external=allow_external, operation="lbs/wiki-relation",
    )


def classify_proposed_change(page: CrowPage, proposed_text: str, *, config: CrowDecisionConfig) -> dict:
    """Compare approved evidence with a page using only a configured loopback classifier."""
    if not isinstance(proposed_text, str) or not proposed_text.strip():
        raise ValueError("Provide a non-empty proposed change.")
    state = {"article": {"title": page.title, "body": page.body}, "proposal": proposed_text}
    return _typed_choice(
        state, "Determine how the proposed change relates to the existing article, including scope and dates.",
        _CHANGE_RELATIONS, config=config, allow_external=False, operation="lbs/wiki-change",
    )


def _typed_choice(state, instructions, options, *, config, allow_external, operation):
    endpoint = _decision_endpoint(config, allow_external)
    crow = _load_crow()
    import httpx
    from llmw2.config import ClassifierConfig

    cfg = ClassifierConfig(
        provider=config.provider, model=config.model, base_url=endpoint, api_key=config.api_key,
    )
    state = json.dumps(state, ensure_ascii=False)
    question = {"q": {"type": "choice", "instructions": instructions, "criteria": options}}
    if len(state) + len(json.dumps(question)) > cfg.request_chars:
        raise ValueError("The documents exceed the classifier request budget.")
    try:
        with httpx.Client(timeout=cfg.timeout, trust_env=False, follow_redirects=False) as client:
            classifier = crow.Classifier(cfg, crow.UsageTracker(), client=client)
            answer = classifier.choice(state, instructions, options, op=operation)
    except (crow.WikiError, TypeError, ValueError, AttributeError, KeyError):
        # The upstream exception may contain the response body; it is not a
        # diagnostic that can be returned to an actor or an application log.
        raise CrowUnavailable("The CROW decision provider did not return a usable decision.") from None

    probabilities = answer.probabilities
    if (answer.choice not in options or set(probabilities) != set(options)
            or not isclose(sum(probabilities.values()), 1.0, abs_tol=1e-3) or
            any(not isfinite(value) or not 0 <= value <= 1 for value in probabilities.values())):
        raise CrowUnavailable("Invalid decision probabilities from the CROW provider.")
    return {"relation": answer.choice, "probability": probabilities[answer.choice], "model": cfg.model}
