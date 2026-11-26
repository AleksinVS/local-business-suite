"""Run an advisory semantic audit from an explicitly authorized account."""
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management.base import BaseCommand, CommandError

from apps.memory.wiki_audit import audit_wiki


class Command(BaseCommand):
    help = "Read-only wiki contradiction audit; can be scheduled separately from reconciliation."

    def add_arguments(self, parser):
        parser.add_argument("--wiki-bundle", required=True)
        parser.add_argument("--actor-id", required=True, type=int)
        parser.add_argument("--since", help="Only inspect Notes changed since this Git commit.")
        parser.add_argument("--revision", help="Require this current Git SHA (for continuation).")
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--max-pairs", type=int, default=30)
        parser.add_argument("--neighbors", type=int, default=5)

    def handle(self, *args, **options):
        actor = get_user_model().objects.filter(pk=options["actor_id"], is_active=True).first()
        if actor is None:
            raise CommandError("An active audit account is required.")
        try:
            report = audit_wiki(
                actor, bundle_id=options["wiki_bundle"], since=options["since"],
                revision=options["revision"], offset=options["offset"],
                max_pairs=options["max_pairs"], neighbors=options["neighbors"],
            )
        except (PermissionDenied, ValidationError) as exc:
            # Do not print paths, source text, Git stderr or a classifier response.
            raise CommandError("Wiki audit incomplete; check permissions, revision and local classifier.") from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False))
