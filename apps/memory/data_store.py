"""Data store interface stubs — ADR-0030 decision 7 (stages 5a/5b), concept §3.1.

The data plane (append-only observations, typed dataset queries) is a MANAGED
DEBT: it is NOT implemented in the memory-alignment block. This module exists so
the interface and its contract are pinned in code and cannot be lost, and so the
two future stages have a named home:

- Stage 5a — dataset registry + typed capture/query (first consumer: the
  analytics contour, ADR-0008). A dataset descriptor is a `type: Dataset`
  concept page in the wiki; the registry is a derived projection materialized by
  the reconciler from those pages (like the edge table from ``relations:``).
  ``capture`` is allowed only into a registered dataset and is idempotent (an
  observation carries a dedup key = dataset + natural key/timestamp). Schema
  evolution is additive and review-gated; an incompatible change is a new
  dataset (version). Rows do not enter the FTS/vector index by default; each
  dataset gets a `type: Dataset` concept page that IS indexed so users/agents
  find it, and row access is only via this typed query interface.
- Stage 5b — reflection proposes a dataset when it notices a recurring series of
  like observations; on acceptance the observations migrate into the data store
  and the old pages are marked ``superseded``.

Routing is fail-safe (concept §3.1): an utterance is written to the data store
ONLY when it matches the schema of a registered dataset; otherwise it becomes an
ordinary knowledge file. Until stage 5a ships, everything is a knowledge file
(the wiki is the staging area) and these functions raise ``NotImplementedError``.

Start criteria: 5a after packets 1–4 of the alignment block are accepted; 5b
after 5a is working. See the ``Later`` debt entry in docs/planning/backlog.md
and the dataset descriptor template in
docs/planning/active/memory-hybrid-knowledge-v05-alignment.md.
"""

from __future__ import annotations

from typing import Any, Mapping

_NOT_IMPLEMENTED = (
    "Memory data store is deferred debt (ADR-0030 decision 7, stages 5a/5b; "
    "concept §3.1). Not implemented in the memory-alignment block."
)


def capture(dataset: str, observation: Mapping[str, Any]) -> None:
    """Append an observation to a registered dataset (deferred — stage 5a).

    Will be idempotent via a per-observation dedup key and allowed only into a
    dataset declared by a `type: Dataset` concept page. Raises until stage 5a.
    """
    raise NotImplementedError(_NOT_IMPLEMENTED)


def query_dataset(dataset: str, query_name: str, params: Mapping[str, Any] | None = None) -> Any:
    """Run a named, versioned typed query over a dataset (deferred — stage 5a).

    Row access is only through this interface (never ``memory.search``). Raises
    until stage 5a.
    """
    raise NotImplementedError(_NOT_IMPLEMENTED)
