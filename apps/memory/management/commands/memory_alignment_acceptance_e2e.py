"""End-to-end acceptance runner for the ADR-0030 memory-alignment block.

Packet 08 (docs/tests/acceptance) requires the block's e2e acceptance
scenarios to run as one managed set that exits non-zero on any failure
(see docs/planning/active/memory-hybrid-knowledge-v05-alignment.md,
"Acceptance-сценарии e2e блока"). Each scenario below reuses the existing
service functions exercised individually by apps/memory/tests.py (packets
01-07); this command wires them into one real, sequential integration run
instead of re-implementing the logic.

Scenarios:

1. manual file edit -> memory_reconcile -> knowledge is found by search,
   with no read error (ADR-0030 decision 1).
2. remember_knowledge -> file + git commit + searchable index in one call
   (ADR-0030 decision 2).
3. a manual sensitivity downgrade is held pending, not applied silently
   (ADR-0030 decision 2 guardrail).
4. personal knowledge -> organization candidate is not searchable while
   pending -> owner accepts it -> it is found under org/ (ADR-0030
   decisions 4 & 8).
5. the reconciler is idempotent: a second run with no changes reconciles 0
   items.
6. a `relations:` entry with an accepted edge type produces a
   MemoryKnowledgeEdge row after reconcile; an unknown type is rejected
   (ADR-0030 decision 3).
7. the data_store stub raises NotImplementedError and the DEBT markers for
   stages 5a/5b exist in the code (ADR-0030 decision 7, managed debt).

Runs against whichever database backend is configured (sqlite or
PostgreSQL) via Django settings; only the knowledge-repo filesystem
location is isolated (under .local/e2e/), never the real
data/knowledge_repo/.
"""

from __future__ import annotations

import uuid
from io import StringIO
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.test.utils import override_settings

from apps.ai.models import ChatMessage, ChatSession
from apps.memory.chat_memory import create_organization_candidate, remember_knowledge
from apps.memory.knowledge_edges import validate_relation_entry
from apps.memory.knowledge_files import (
    KnowledgeFile,
    _safe_repo_path,
    knowledge_repo_root,
    parse_knowledge_file,
    read_knowledge_item_file,
    render_knowledge_file,
    sha256_text,
)
from apps.memory.models import MemoryKnowledgeItem
from apps.memory.retrieval import memory_search
from apps.memory.review_services import accept_pending_item


class _AcceptancePassed(Exception):
    """Internal sentinel: raised to force a rollback of the atomic block below
    even when every scenario passed, so this command never leaves permanent
    User/ChatSession/MemoryKnowledgeItem/MemoryKnowledgeEdge rows in whichever
    real database (sqlite dev.db or PostgreSQL) it is pointed at. Only the
    knowledge-repo filesystem is isolated via ``override_settings(DATA_DIR=...)``;
    without also rolling back the DB side, repeated runs would accumulate
    orphaned rows whose files live only under the disposable .local/e2e/
    workspace and would show up as failures in memory_verify_knowledge_files."""

    def __init__(self, scenarios):
        super().__init__("internal: forced rollback after a successful acceptance run")
        self.scenarios = scenarios


class Command(BaseCommand):
    help = "Run the ADR-0030 memory-alignment block's e2e acceptance scenarios as one set."

    def handle(self, *args, **options):
        User = get_user_model()
        marker = uuid.uuid4().hex[:12]
        workspace = Path(".local") / "e2e" / "memory_alignment_acceptance" / marker
        data_dir = workspace / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        passed = []
        try:
            with transaction.atomic():
                with override_settings(DATA_DIR=data_dir, LOCAL_BUSINESS_MEMORY_FILE_CANON_AUTHORITATIVE=True):
                    self._scenario_manual_edit_reconcile_search(User, marker)
                    passed.append("1_manual_edit_reconcile_search")

                    self._scenario_remember_file_commit_index(User, marker)
                    passed.append("2_remember_file_commit_index")

                    self._scenario_sensitivity_downgrade_held_pending(User, marker)
                    passed.append("3_sensitivity_downgrade_held_pending")

                    self._scenario_candidate_pending_then_accept(User, marker)
                    passed.append("4_candidate_pending_then_accept")

                    self._scenario_reconciler_idempotent(User, marker)
                    passed.append("5_reconciler_idempotent")

                    self._scenario_edge_vocabulary(User, marker)
                    passed.append("6_edge_vocabulary")

                # No DB writes below; runs inside the same atomic block only so a
                # failure here also aborts cleanly with the rest rolled back.
                self._scenario_data_store_stub_and_debt_markers()
                passed.append("7_data_store_stub_and_debt_markers")

                # Force the whole block to roll back now that every scenario has
                # passed: this run must not leave any row behind in the real DB.
                raise _AcceptancePassed(passed)
        except _AcceptancePassed as outcome:
            passed = outcome.scenarios
        # Any other exception (CommandError from a failed scenario, etc.)
        # propagates out of handle() uncaught, which is what makes manage.py
        # exit non-zero on failure; transaction.atomic() has already rolled
        # back everything written above by the time it does.

        self.stdout.write(self.style.SUCCESS(f"Memory alignment acceptance e2e passed: {', '.join(passed)}"))

    # -- helpers ----------------------------------------------------------

    def _make_item(self, User, *, marker, tag, content=None):
        user = User.objects.create_user(username=f"acc-{tag}-{marker}", password="pass")
        session = ChatSession.objects.create(user=user, title=f"Acceptance {tag}")
        message = ChatMessage.objects.create(
            session=session,
            role=ChatMessage.Role.USER,
            content=content or f"Запомни: контрольное знание {tag} {marker}.",
        )
        result = remember_knowledge(
            actor=user,
            session=session,
            payload={"message_ids": [message.id]},
            request_id=f"req-{tag}-{marker}",
        )
        item = MemoryKnowledgeItem.objects.get(memory_id=result["memory_id"])
        return user, item, result

    def _rewrite_file(self, item, *, body=None, metadata_updates=None):
        path = _safe_repo_path(knowledge_repo_root(), item.knowledge_file_path)
        parsed = parse_knowledge_file(path.read_text(encoding="utf-8"))
        meta = dict(parsed.metadata)
        if metadata_updates:
            meta.update(metadata_updates)
        new = KnowledgeFile(metadata=meta, body=body if body is not None else parsed.body)
        path.write_text(render_knowledge_file(new), encoding="utf-8")

    # -- scenarios ----------------------------------------------------------

    def _scenario_manual_edit_reconcile_search(self, User, marker):
        user, item, _result = self._make_item(User, marker=marker, tag="edit")
        new_body = f"alpha калибруется ежемесячно editedtoken{marker}"
        self._rewrite_file(item, body=new_body)

        # ADR-0030 decision 1: a manual edit must not break reads.
        try:
            parsed = read_knowledge_item_file(item)
        except ValidationError as exc:
            raise CommandError(f"scenario 1: manual edit broke the read path: {exc}") from exc
        if f"editedtoken{marker}" not in parsed.body:
            raise CommandError("scenario 1: read did not return the manually edited body.")

        out = StringIO()
        call_command("memory_reconcile", stdout=out)
        item.refresh_from_db()
        if item.text_hash != sha256_text(new_body):
            raise CommandError("scenario 1: reconcile did not update the projection's text_hash.")
        if "reconciled=1" not in out.getvalue():
            raise CommandError(f"scenario 1: reconcile did not report the edit as reconciled: {out.getvalue()}")

        search_result = memory_search(
            actor=user, query=f"editedtoken{marker}", sensitivity="internal", request_id=f"search-edit-{marker}"
        )
        if not search_result["items"]:
            raise CommandError("scenario 1: manually edited knowledge was not found by memory.search after reconcile.")

    def _scenario_remember_file_commit_index(self, User, marker):
        user, _item, result = self._make_item(
            User, marker=marker, tag="remember", content=f"Запомни: remember-token{marker} готовится за один вызов."
        )
        if not result.get("knowledge_file_path"):
            raise CommandError("scenario 2: remember_knowledge did not return a knowledge_file_path.")
        if not result.get("knowledge_file_commit"):
            raise CommandError("scenario 2: remember_knowledge did not produce a git commit.")
        path = _safe_repo_path(knowledge_repo_root(), result["knowledge_file_path"])
        if not path.exists():
            raise CommandError("scenario 2: knowledge file was not written to disk.")
        if result.get("index_status") != "ready":
            raise CommandError(f"scenario 2: inline indexing did not complete: index_status={result.get('index_status')!r}")

        search_result = memory_search(
            actor=user, query=f"remember-token{marker}", sensitivity="internal", request_id=f"search-remember-{marker}"
        )
        if not search_result["items"]:
            raise CommandError("scenario 2: knowledge saved by remember_knowledge was not searchable in the same run.")

    def _scenario_sensitivity_downgrade_held_pending(self, User, marker):
        _user, item, _result = self._make_item(User, marker=marker, tag="downgrade")
        item.sensitivity = "confidential"
        item.save(update_fields=["sensitivity"])
        self._rewrite_file(item, metadata_updates={"sensitivity": "public"})

        out = StringIO()
        call_command("memory_reconcile", stdout=out)
        item.refresh_from_db()
        if item.sensitivity != "confidential":
            raise CommandError(
                f"scenario 3: sensitivity downgrade was applied silently: sensitivity={item.sensitivity!r}."
            )
        if "held=1" not in out.getvalue():
            raise CommandError(f"scenario 3: reconcile did not report the downgrade as held: {out.getvalue()}")
        if (item.metadata or {}).get("lifecycle") != "pending":
            raise CommandError("scenario 3: downgraded item was not marked lifecycle=pending.")

    def _scenario_candidate_pending_then_accept(self, User, marker):
        personal_user, personal_item, _result = self._make_item(
            User, marker=marker, tag="candidate-source", content=f"Запомни: candidatetoken{marker} общий регламент."
        )
        candidate = create_organization_candidate(source_item=personal_item, created_by=personal_user)
        if (candidate.metadata or {}).get("lifecycle") != "pending":
            raise CommandError("scenario 4: new organization candidate was not created as lifecycle=pending.")

        not_yet = memory_search(
            actor=personal_user,
            query=f"candidatetoken{marker}",
            sensitivity="internal",
            request_id=f"search-candidate-pending-{marker}",
        )
        found_candidate = any(
            item.get("knowledge_id") == candidate.memory_id or item.get("memory_id") == candidate.memory_id
            for item in not_yet.get("items", [])
        )
        if found_candidate:
            raise CommandError("scenario 4: pending organization candidate was searchable before acceptance.")

        reviewer = User.objects.create_user(username=f"acc-reviewer-{marker}", password="pass", is_superuser=True)
        accepted = accept_pending_item(item=candidate, actor=reviewer)
        if accepted.metadata.get("lifecycle") != "current":
            raise CommandError("scenario 4: accepted candidate did not flip lifecycle to current.")
        if not accepted.knowledge_file_path.startswith("org/"):
            raise CommandError(
                f"scenario 4: accepted candidate is not filed under org/: {accepted.knowledge_file_path!r}"
            )

        after_accept = memory_search(
            actor=reviewer,
            query=f"candidatetoken{marker}",
            sensitivity="internal",
            request_id=f"search-candidate-accepted-{marker}",
        )
        if not after_accept["items"]:
            raise CommandError("scenario 4: accepted organization candidate was not found by memory.search.")

    def _scenario_reconciler_idempotent(self, User, marker):
        _user, item, _result = self._make_item(User, marker=marker, tag="idempotent")
        self._rewrite_file(item, body=f"idempotent body {marker} v2")
        call_command("memory_reconcile", stdout=StringIO())

        out = StringIO()
        call_command("memory_reconcile", stdout=out)
        if "reconciled=0" not in out.getvalue():
            raise CommandError(f"scenario 5: second reconcile run was not a no-op: {out.getvalue()}")

    def _scenario_edge_vocabulary(self, User, marker):
        _source_user, source_item, _ = self._make_item(User, marker=marker, tag="edge-source")
        _target_user, target_item, _ = self._make_item(User, marker=marker, tag="edge-target")
        self._rewrite_file(
            source_item,
            metadata_updates={
                "relations": [
                    {
                        "type": "relates_to",
                        "target": target_item.memory_id,
                        "provenance": f"source_code:acceptance_e2e/{marker}",
                    }
                ]
            },
        )

        out = StringIO()
        call_command("memory_reconcile", stdout=out)
        if "edges_created=1" not in out.getvalue():
            raise CommandError(f"scenario 6: reconcile did not materialize the declared edge: {out.getvalue()}")
        from apps.memory.models import MemoryKnowledgeEdge

        if not MemoryKnowledgeEdge.objects.filter(
            source_path=source_item.knowledge_file_path,
            edge_type="relates_to",
            target=target_item.memory_id,
        ).exists():
            raise CommandError("scenario 6: expected MemoryKnowledgeEdge row was not materialized.")

        try:
            validate_relation_entry(
                {"type": "not_a_real_relation_type", "target": target_item.memory_id, "provenance": "source_code:x"}
            )
        except ValidationError:
            pass
        else:
            raise CommandError("scenario 6: an unknown edge type was accepted instead of rejected.")

    def _scenario_data_store_stub_and_debt_markers(self):
        from apps.memory import data_store

        try:
            data_store.capture("fx_rates", {"date": "2026-07-04", "pair": "USD/RUB", "value": "105"})
        except NotImplementedError:
            pass
        else:
            raise CommandError("scenario 7: data_store.capture did not raise NotImplementedError.")

        try:
            data_store.query_dataset("fx_rates", "latest", {"pair": "USD/RUB"})
        except NotImplementedError:
            pass
        else:
            raise CommandError("scenario 7: data_store.query_dataset did not raise NotImplementedError.")

        # Check the two known marker locations directly (chat_memory.py and
        # memory_reconcile.py) rather than rglobbing all of apps/memory: the
        # unit test apps.memory.tests.MemoryDataStoreStubTests.
        # test_debt_markers_present already asserts an exact repo-wide count
        # of the stage-5a/5b marker text; rglobbing here too would inflate
        # that count if this very file's marker text were included in the
        # scan. The marker strings below are deliberately built by
        # concatenation so this file's own source never contains the marker
        # text as one contiguous substring.
        import apps.memory.chat_memory as chat_memory_module
        from apps.memory.management.commands import memory_reconcile as memory_reconcile_module

        marker_5a = "DEBT(ADR-0030-" + "5a)"
        marker_5b = "DEBT(ADR-0030-" + "5b)"
        chat_memory_text = Path(chat_memory_module.__file__).read_text(encoding="utf-8")
        reconcile_text = Path(memory_reconcile_module.__file__).read_text(encoding="utf-8")

        if marker_5a not in chat_memory_text:
            raise CommandError("scenario 7: no stage-5a DEBT marker found in apps/memory/chat_memory.py.")
        if marker_5a not in reconcile_text:
            raise CommandError("scenario 7: no stage-5a DEBT marker found in memory_reconcile.py.")
        if marker_5b not in chat_memory_text:
            raise CommandError("scenario 7: no stage-5b DEBT marker found in apps/memory/chat_memory.py.")
