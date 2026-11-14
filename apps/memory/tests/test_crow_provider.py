import json
from dataclasses import replace
from importlib.util import find_spec
from unittest import TestCase, skipUnless
from unittest.mock import patch

import httpx
import pytest

from apps.memory.crow_provider import (
    CrowDecisionConfig,
    CrowPage,
    CrowUnavailable,
    classify_crow_relation,
    classify_proposed_change,
    search_crow_pages,
)


pytestmark = pytest.mark.unit


def page(key, body, commit="a"):
    return CrowPage(key, commit * 40, f"Статья {key}", "", body)


@skipUnless(find_spec("llmw2") is not None, "optional llmwiki2 wheel is not installed")
class CrowProviderTests(TestCase):
    def test_bm25_only_ranks_the_current_authorized_versions(self):
        first = page("k1", "Ключ взаимодействия: ABC-1200.")
        linked = page("k2", "Содержание.\n\n# See also\n\n* [ABC-1200](one.md) - Соседняя статья\n")
        updated = replace(first, revision="b" * 40, body="Теперь используется ZZZ-56.")
        with patch("httpx.Client", side_effect=AssertionError("local BM25 attempted network")):
            self.assertEqual(search_crow_pages("ABC-1200", [first, linked]), ["k1"])
            self.assertEqual(search_crow_pages("ABC-1200", [linked]), [])
            self.assertEqual(search_crow_pages("ABC-1200", [updated]), [])
            self.assertEqual(search_crow_pages("ZZZ-56", [updated]), ["k1"])
            self.assertEqual(search_crow_pages("ZZZ-56", []), [])

    def test_candidate_metadata_is_searchable_but_ids_do_not_enter_the_index(self):
        first = CrowPage("hidden-canary-912", "c" * 40, "Сверка", "Проводки за квартал", "Описание")
        self.assertEqual(search_crow_pages("квартал", [first]), [first.knowledge_id])
        self.assertEqual(search_crow_pages("hidden-canary-912", [first]), [])
        with self.assertRaises(ValueError):
            search_crow_pages("квартал", [first, first])
        with self.assertRaises(ValueError):
            replace(first, revision="HEAD")

    def test_wrong_version_is_explicit(self):
        with patch("llmw2.__version__", "1.1.0"), self.assertRaises(CrowUnavailable):
            search_crow_pages("поиск", [page("k1", "поиск")])

    def test_typed_client_sends_only_the_two_documents_and_the_fixed_question(self):
        left, right = page("opaque-1", "Лимит 3."), page("opaque-2", "Лимит 5.")
        captured = []

        def reply(request):
            captured.append(request)
            data = json.loads(request.content)
            self.assertEqual(json.loads(data["state"]), [
                {"title": left.title, "body": left.body}, {"title": right.title, "body": right.body},
            ])
            options = data["questions"]["q"]["criteria"]
            probabilities = {key: float(key == "conflicts") for key in options}
            return httpx.Response(200, json={"answers": {"q": {"choice": "conflicts", "probabilities": probabilities}}})

        client = httpx.Client(transport=httpx.MockTransport(reply))
        with patch("httpx.Client", return_value=client) as factory:
            result = classify_crow_relation(left, right, config=CrowDecisionConfig("custom", base_url="http://127.0.0.1:8001/v1"))
        self.assertFalse(factory.call_args.kwargs["trust_env"])
        self.assertFalse(factory.call_args.kwargs["follow_redirects"])
        self.assertEqual(str(captured[0].url), "http://127.0.0.1:8001/v1/systemone")
        self.assertEqual(result, {"relation": "conflicts", "probability": 1.0, "model": "typed-decisions"})

    def test_proposal_is_compared_locally_in_its_own_typed_question(self):
        current = CrowPage("private-id", "e" * 40, "Регламент", "private description", "Срок 3 дня.")
        proposal = "Срок для филиалов составляет 5 дней."

        def reply(request):
            data = json.loads(request.content)
            self.assertEqual(json.loads(data["state"]), {
                "article": {"title": current.title, "body": current.body}, "proposal": proposal,
            })
            keys = set(data["questions"]["q"]["criteria"])
            self.assertEqual(keys, {"already_covered", "extends", "conflicts", "unrelated", "uncertain"})
            return httpx.Response(200, json={"answers": {"q": {
                "choice": "extends", "probabilities": {key: float(key == "extends") for key in keys},
            }}})

        client = httpx.Client(transport=httpx.MockTransport(reply))
        with patch("httpx.Client", return_value=client):
            result = classify_proposed_change(
                current, proposal, config=CrowDecisionConfig("custom", base_url="http://127.0.0.1:8001/v1"),
            )
        self.assertEqual(result, {"relation": "extends", "probability": 1.0, "model": "typed-decisions"})
        with patch("httpx.Client", side_effect=AssertionError("unexpected network")):
            for settings, text in (
                (CrowDecisionConfig("openrouter", api_key="secret"), proposal),
                (CrowDecisionConfig("custom", base_url="http://127.0.0.1:8001/v1"), "  "),
            ):
                with self.assertRaises(ValueError):
                    classify_proposed_change(current, text, config=settings)

    def test_rejections_do_not_construct_an_http_client(self):
        left, right = page("a", "one"), page("b", "two")
        with patch("httpx.Client", side_effect=AssertionError("rejected input attempted network")):
            for settings in (
                CrowDecisionConfig("openrouter", api_key="secret"),
                CrowDecisionConfig("custom", base_url="http://192.0.2.99/v1"),
                CrowDecisionConfig("custom", base_url="http://127.0.0.1@evil.invalid/v1"),
            ):
                with self.subTest(provider=settings.provider, url=settings.base_url), self.assertRaises(ValueError):
                    classify_crow_relation(left, right, config=settings)
            with self.assertRaises(CrowUnavailable):
                classify_crow_relation(left, right, config=CrowDecisionConfig(""))
            with self.assertRaises(CrowUnavailable):
                classify_crow_relation(left, right, config=CrowDecisionConfig("typesafe"), allow_external=True)
            with self.assertRaises(ValueError):
                classify_crow_relation(left, right, config=CrowDecisionConfig("typesafe", base_url="https://example.org", api_key="secret"), allow_external=True)
            with self.assertRaises(ValueError):
                classify_crow_relation(left, replace(right, body="x" * 90_000), config=CrowDecisionConfig("custom", base_url="http://127.0.0.1:8001/v1"))

    def test_malformed_provider_reply_does_not_echo_remote_content(self):
        settings = CrowDecisionConfig("custom", base_url="http://[::1]:8001/v1")
        def reply(request):
            return httpx.Response(200, json={"answers": {"q": {"choice": "SECRET", "probabilities": {"SECRET": 9}}}})
        client = httpx.Client(transport=httpx.MockTransport(reply))
        with patch("httpx.Client", return_value=client), self.assertRaises(CrowUnavailable) as error:
            classify_crow_relation(page("a", "one"), page("b", "two"), config=settings)
        self.assertNotIn("SECRET", str(error.exception))
