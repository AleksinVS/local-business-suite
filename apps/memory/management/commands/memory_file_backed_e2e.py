import uuid

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from apps.ai.models import ChatMessage, ChatSession
from apps.memory.chat_memory import remember_knowledge
from apps.memory.knowledge_files import verify_knowledge_item_file
from apps.memory.models import MemoryKnowledgeItem
from apps.memory.retrieval import memory_search


class Command(BaseCommand):
    help = "Run an end-to-end check of the synchronous remember -> knowledge file -> index -> search path."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="memory-e2e-user", help="User for the e2e check.")

    def handle(self, *args, **options):
        User = get_user_model()
        user, _created = User.objects.get_or_create(username=options["username"], defaults={"is_active": True})
        marker = f"memory-e2e-{uuid.uuid4().hex[:12]}"
        session = ChatSession.objects.create(user=user, title="Memory file-backed e2e")
        message = ChatMessage.objects.create(
            session=session,
            role=ChatMessage.Role.USER,
            content=f"Запомни: контрольное знание {marker} хранится в файловом репозитории.",
        )
        result = remember_knowledge(
            actor=user,
            session=session,
            payload={"message_ids": [message.id], "user_note": "e2e"},
            request_id=f"req-{marker}",
        )
        item = MemoryKnowledgeItem.objects.get(memory_id=result["memory_id"])
        verification = verify_knowledge_item_file(item)
        if not verification["ok"]:
            raise CommandError(f"Knowledge file verification failed: {verification}")
        search_result = memory_search(actor=user, query=marker, sensitivity="internal", request_id=f"search-{marker}")
        if not search_result["items"]:
            raise CommandError("Saved knowledge was not found through memory.search.")
        self.stdout.write(
            self.style.SUCCESS(
                "Memory file-backed e2e succeeded: "
                f"memory_id={item.memory_id}, file={item.knowledge_file_path}, commit={result['knowledge_file_commit'][:12]}"
            )
        )
