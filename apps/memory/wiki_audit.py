"""Optional, bounded, read-only semantic audit of committed wiki articles.

Reuse the actor-scoped search and decision gateway. No model can publish a
change, and no raw source is re-ingested. Findings refer to a fixed Git SHA.
"""
from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError

from .crow_provider import CrowUnavailable, search_crow_pages
from .knowledge_files import knowledge_repo_root
from .wiki_files import _require_ancestor
from .wiki_gateway import _available, _basic_search, _bundle_for, _page, _visible, compare_wiki
from .wiki_reconcile import wiki_tree


def audit_wiki(actor, *, bundle_id, since=None, revision=None, offset=0, max_pairs=30, neighbors=5):
    """Compare changed Notes with a limited number of relevant visible neighbors.

    Use a complete pass or an explicit base SHA; callers may page a large pass
    using next_offset with the returned revision. No persistent audit queue.
    """
    if (type(offset) is not int or offset < 0 or (offset and not revision)
            or type(max_pairs) is not int or not 1 <= max_pairs <= 100
            or type(neighbors) is not int or not 1 <= neighbors <= 10):
        raise ValidationError("Invalid audit budget or continuation.")
    bundle, _ = _bundle_for(actor, bundle_id)
    snapshot, entries = _available(actor, bundle)
    if revision is not None and snapshot.revision != revision:
        raise ValidationError("Wiki audit revision changed; restart the pass.")
    root = knowledge_repo_root()
    old = None
    if since:
        _require_ancestor(root, since, snapshot.revision)
        old = wiki_tree(root, since, bundle.path)
    changed = sorted(key for key, entry in entries.items()
                     if old is None or old.get(entry[0].path) != entry[0].blob_oid)
    pages = [_page(entries[key], snapshot.revision) for key in sorted(entries)]
    by_id = {page.knowledge_id: page for page in pages}

    def pairs():
        seen = set()
        for key in changed:
            page = by_id[key]
            candidates = [p for p in pages if p.knowledge_id != key]
            if not candidates:
                continue
            query = f"{page.title} {page.description} {page.body[:2000]}".strip()
            if not query:
                continue
            if settings.LOCAL_BUSINESS_WIKI_SEARCH == "crow":
                try:
                    ranked = search_crow_pages(query, candidates, limit=neighbors)
                except CrowUnavailable as exc:
                    raise ValidationError(str(exc)) from exc
            else:
                ranked = _basic_search(query, candidates, neighbors)
            for other in ranked:
                pair = tuple(sorted((key, other)))
                if pair not in seen and other in by_id and other != key:
                    seen.add(pair)
                    yield pair

    from itertools import islice

    selected = list(islice(pairs(), offset, offset + max_pairs + 1))
    more = len(selected) > max_pairs
    checked = selected[:max_pairs]
    findings = []
    uncertain = 0
    for left, right in checked:
        result = compare_wiki(actor, bundle_id=bundle_id, left_id=left, right_id=right)
        if result["revision"] != snapshot.revision:
            raise ValidationError("Wiki audit revision changed; restart the pass.")
        if result["relation"] == "conflicts":
            findings.append({key: result[key] for key in
                             ("left_id", "right_id", "relation", "probability", "model", "revision")})
        elif result["relation"] == "uncertain":
            uncertain += 1
    # Re-evaluate access before reporting, including pages seen early in a pass.
    current = _visible(actor, bundle, snapshot)
    if set(current) != set(entries):
        raise PermissionDenied("Wiki audit access changed; restart the pass.")
    return {"bundle_id": bundle_id, "revision": snapshot.revision, "since": since,
            "changed_articles": len(changed), "checked_pairs": len(checked),
            "uncertain_pairs": uncertain, "findings": findings,
            "next_offset": offset + len(checked) if more else None}
