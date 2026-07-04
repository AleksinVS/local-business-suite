import base64
import json
import uuid
import zipfile
import zlib
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from apps.memory.document_ingestion import discover_source_objects, ingest_source_objects
from apps.memory.models import MemoryAccessAudit, MemorySearchDocument, MemorySource
from apps.memory.retrieval import memory_search


LEGACY_XLS_BASE64 = (
    "0M8R4KGxGuEAAAAAAAAAAAAAAAAAAAAAPgADAP7/CQAGAAAAAAAAAAAAAAABAAAACQAAAAAAAAAAEAAA/v///wAAAAD+////AAAAAAgAAAD"
    "////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////"
    "///////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////8J"
    "CBAAAAYFALsNzAcAAAAABgAAAOEAAgCwBMEAAgAAAOIAAABcAHAATm9uZSAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgIEIAAgCwBGEBAgAA"
    "AD0BAgABAJwAAgAOABkAAgAAABIAAgAAAGMAAgAAABMAAgAAAK8BAgAAALwBAgAAAEAAAgAAAI0AAgAAAD0AEgDgAVoAzz9OKjgAAAAAAAEA"
    "WAIiAAIAAAAOAAIAAQC3AQIAAADaAAIAAAAxABUAyAAAAP9/kAEAAAAAAQAFAEFyaWFsMQAVAMgAAAD/f5ABAAAAAAEABQBBcmlhbDEAFQDI"
    "AAAA/3+QAQAAAAABAAUAQXJpYWwxABUAyAAAAP9/kAEAAAAAAQAFAEFyaWFsMQAVAMgAAAD/f5ABAAAAAAEABQBBcmlhbDEAFQDIAAAA/3+Q"
    "AQAAAAABAAUAQXJpYWwxABUAyAAAAP9/kAEAAAAAAQAFAEFyaWFsHgQMAKQABwAAR2VuZXJhbOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAA"
    "FAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8g"
    "AAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAA"
    "AADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAG"
    "AKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0AAAAAAAAAADAIOAAFAAGAKQA9f8gAAD0"
    "AAAAAAAAAADAIOAAFAAHAKQAAQAgAAD4AAAAAAAAAADAIJMCBAAAgAD/YAECAAEAhQAOANMDAAAAAAYATGVnYWN5/AAuAAIAAAACAAAADwAA"
    "bGVnYWN5eGxzbmVlZGxlEQAAY2FsaWJyYXRpb24gdmFsdWUKAAAACQgQAAAGEAC7DcwHAAAAAAYAAAANAAIAAQAMAAIAZAAPAAIAAQARAAIA"
    "AAAQAAgA/Knx0k1iUD9fAAIAAACAAAgAAAAAAAEAAAAlAgQAAAD/AIEAAgABDAACDgAAAAAAAQAAAAAAAgAAACoAAgAAACsAAgAAAIIAAgAB"
    "ABsAAgAAABoAAgAAABQABQACAAAmUBUABQACAAAmRoMAAgABAIQAAgAAACYACAAzMzMzMzPTPycACAAzMzMzMzPTPygACACF61G4HoXjPykA"
    "CACuR+F6FK7XP6EAIgAJAGQAAQABAAEAgwAsASwBmpmZmZmZuT+amZmZmZm5PwEAEgACAAAA3QACAAAAGQACAAAAYwACAAAAEwACAAAACAIQ"
    "AAAAAAACAP8AAAAAAAABDwD9AAoAAAAAABEAAAAAAP0ACgAAAAEAEQABAAAAPgISALYCAAAAAEAAAAAAAAAAAAAAAAoAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAIA"
    "AAADAAAABAAAAAUAAAAGAAAABwAAAP7////9/////v//////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////"
    "////////////////////////////////////////////////////////////////////////////////////////////////////////////////////////9SAG8AbwB0"
    "ACAARQBuAHQAcgB5AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFgAFAf//////////AQAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAP7///8AAAAAAAAAAFcAbwByAGsAYgBvAG8AawAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAASAAIB////////////////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAQAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAH///////////////8AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
    "AAAAAAD+////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAf//////"
    "/////////wAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAP7///8AAAAAAAAAAA=="
)

LEGACY_XLS_ZLIB_BASE64 = (
    "eNq7cF7wwcKNUg8Z0IAdAzPDv/+cDGxIYoxAzAnjCDAA5f//BzFhNAcQ/x8FQwpwcgAjko2VYTfvGXZQHILi+yEDE8MGloNA"
    "koHhERDHMBQw+OXnpSrQETiB3ZDICHKDLZBkZJgDFOFjkAS7SghMJoNJYTC5HqxyD5h0AIv0gklboNoHjFEM5+39tCygqTiC"
    "SQksx8cAMnc7WM8tsIghgyjDCVAqrp/ACFHLyuBYlJmYMzgl5Fh4GJYwAOPNPTUvtSgx5wGDCDAClzB8/a/AwPAFllMPKIyK"
    "01eckQEo/gNVnB2L+GQmFgaGBob/CeAE3gpMkJeZIZnQJzU9MbnyD4MeOFmCMD8DQw5YsCKnOC81NSUnVRCYAxJzMpOKEksy"
    "8/MUyhJzSlO5QEU0OEsLoGRpXnBS5wGSKUCTQGxBsKkCwEL7z8qPl3yTAuzjwSIN4GIcUtirgtzH8J+hEaQDqJkPLgNxkxaY"
    "1AaTTWBTpcFsKTApAkymQFotQBTKcGsGq2kBy6oB7TEGg8v26khsDSC79XXgDrnWx/aaQPY694dVIuuu2y9kUAJWPilA/SDY"
    "zKDDqMM4ayYI7LSH0YzQguEumJTEKCQ4mASgbv8PrdH4Gf4ycIGZgmASwgOFDsiXdkxCDNtAGoFFCgJwMYyCUTAKRsEoGAWj"
    "YBSMglEwRAEjtCkP6neAGvus0A4DO3Rc5y8Q/xsdJhm2IIghHwhLgB1TV4Y8IF3EUElS+hFjYGWEmcVIpB7YeCEIhANtL2LI"
    "ZkgCuyOb5PQL7PAxIvuHaI0C1MtCpNr/jxR30th+ALSjxgs="
)


class Command(BaseCommand):
    help = "Run an end-to-end check of file content extraction, FTS search and source_data warnings."

    def add_arguments(self, parser):
        parser.add_argument("--username", default="memory-file-content-e2e-user", help="User for the e2e check.")

    def handle(self, *args, **options):
        marker = uuid.uuid4().hex[:10]
        root = settings.BASE_DIR / ".local" / "memory-file-content-search-e2e" / marker
        root.mkdir(parents=True, exist_ok=True)

        tokens = {
            "txt": f"txtneedle{marker}",
            "md": f"mdneedle{marker}",
            "csv": f"csvneedle{marker}",
            "tsv": f"tsvneedle{marker}",
            "xlsx": f"xlsxneedle{marker}",
            "semantic": f"semanticfileneedle{marker}",
            "prefix": f"prefixneedle{marker}",
            "prefix_query": f"prefixneedle{marker[:5]}",
            "xls": "legacyxlsneedle",
        }
        (root / "plain.txt").write_text(f"Plain content {tokens['txt']} {tokens['prefix']}tail", encoding="utf-8")
        (root / "guide.md").write_text(f"# Guide\n\nMarkdown body {tokens['md']} {tokens['semantic']}", encoding="utf-8")
        (root / "table.csv").write_text(f"name,value\nalpha,{tokens['csv']}\n", encoding="utf-8")
        (root / "table.tsv").write_text(f"name\tvalue\nalpha\t{tokens['tsv']}\n", encoding="utf-8")
        _write_minimal_xlsx(root / "modern.xlsx", tokens["xlsx"])
        (root / "legacy.xls").write_bytes(zlib.decompress(base64.b64decode(LEGACY_XLS_ZLIB_BASE64)))

        User = get_user_model()
        user, _created = User.objects.get_or_create(username=options["username"], defaults={"is_active": True})
        group, _created = Group.objects.get_or_create(name="memory-e2e-readers")
        user.groups.add(group)
        source_code = f"file_content_e2e_{marker}"
        source = MemorySource.objects.create(
            code=source_code,
            title="Memory file content e2e",
            source_kind="local_path",
            domain="docs",
            owner="memory",
            sensitivity="internal",
            pii_policy="deidentify_before_index",
            trust_status=MemorySource.TrustStatus.TRUSTED,
            authority_class=MemorySource.AuthorityClass.APPROVED_CORPUS,
            trusted_for_context=True,
            requires_source_review=False,
            trusted_context_kinds=["retrieved_chunk", "citation"],
            index_profiles=["fulltext_default", "vector_default"],
            scope_rule="authenticated_user",
            config={
                "source_ref": str(root),
                "ignore_patterns": [],
                "ingestion_profile": "corporate_docs_windows_v1",
                "default_acl": {"allow": [{"kind": "group", "name": group.name}]},
            },
        )

        discover_source_objects(source=source, dry_run=False)
        metrics = ingest_source_objects(source=source, dry_run=False)
        if metrics["issues"]:
            raise CommandError(f"Ingestion produced issues: {metrics}")

        for key in ("txt", "md", "csv", "tsv", "xlsx", "xls"):
            self._assert_source_search(user=user, token=tokens[key], request_id=f"file-content-e2e-{key}-{marker}")

        prefix_result = self._assert_source_search(user=user, token=tokens["prefix_query"], request_id=f"file-content-e2e-prefix-{marker}")
        prefix_audit = MemoryAccessAudit.objects.get(request_id=f"file-content-e2e-prefix-{marker}")
        if not prefix_audit.retrieval_trace["search_channels"]["fulltext"].get("prefix_search_used"):
            raise CommandError("Prefix fallback was not reflected in retrieval trace.")

        # ADR-0030 decision 6: there is no longer a selectable "source_semantic"
        # named profile — the single default RRF profile always blends the
        # fulltext and vector channels, so a semantic-only match is still
        # found through the vector channel without picking a profile.
        semantic_result = self._assert_source_search(
            user=user,
            token=tokens["semantic"],
            request_id=f"file-content-e2e-source-semantic-{marker}",
        )
        semantic_audit = MemoryAccessAudit.objects.get(request_id=f"file-content-e2e-source-semantic-{marker}")
        if not semantic_audit.retrieval_trace["search_channels"]["vector"].get("requested"):
            raise CommandError("Source semantic search did not request the vector channel.")
        if semantic_result["meta"].get("ranking_profile") != "default":
            raise CommandError("The single default ranking profile is missing from response metadata.")

        for document in MemorySearchDocument.objects.filter(source_object__source=source):
            metadata_json = json.dumps(document.metadata or {}, ensure_ascii=False)
            for key, token in tokens.items():
                if key == "prefix_query":
                    continue
                if token and token in metadata_json:
                    raise CommandError(f"Extracted content token leaked into MemorySearchDocument.metadata: {token}")

        first_item = prefix_result["items"][0]
        if first_item.get("kind") != "source_data" or "warning" not in first_item:
            raise CommandError("source_data result warning is missing.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Memory file content search e2e succeeded: source={source.code}, documents={MemorySearchDocument.objects.filter(source_object__source=source).count()}"
            )
        )

    def _assert_source_search(self, *, user, token, request_id):
        result = memory_search(
            actor=user,
            query=token,
            sensitivity="internal",
            request_id=request_id,
            search_mode="source_explicit",
        )
        if not result["items"]:
            raise CommandError(f"Token was not found through source_data search: {token}")
        if result["items"][0].get("kind") != "source_data":
            raise CommandError(f"Expected source_data result for token: {token}")
        if "warning" not in result["items"][0]:
            raise CommandError(f"Expected source_data warning for token: {token}")
        audit = MemoryAccessAudit.objects.get(request_id=request_id)
        if "fulltext" not in audit.retrieval_trace["search_channels"]:
            raise CommandError("Fulltext trace is missing.")
        return result


def _write_minimal_xlsx(path: Path, token: str) -> None:
    shared = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">'
        f"<si><t>{token}</t></si></sst>"
    )
    sheet = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetData><row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>'
    )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", _xlsx_content_types())
        archive.writestr("_rels/.rels", _xlsx_root_rels())
        archive.writestr("xl/workbook.xml", _xlsx_workbook())
        archive.writestr("xl/_rels/workbook.xml.rels", _xlsx_workbook_rels())
        archive.writestr("xl/worksheets/sheet1.xml", sheet)
        archive.writestr("xl/sharedStrings.xml", shared)


def _xlsx_content_types() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
        '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>'
        "</Types>"
    )


def _xlsx_root_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
        "</Relationships>"
    )


def _xlsx_workbook() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
    )


def _xlsx_workbook_rels() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>'
        '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/sharedStrings" Target="sharedStrings.xml"/>'
        "</Relationships>"
    )
