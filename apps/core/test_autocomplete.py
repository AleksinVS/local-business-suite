import json
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from django.core.exceptions import ValidationError
from django.test import RequestFactory, SimpleTestCase

from .autocomplete import (
    AutocompleteOption,
    AutocompleteView,
    register_autocomplete_provider,
    unregister_autocomplete_provider,
)


pytestmark = pytest.mark.unit


@dataclass
class StubProvider:
    code: str = "tests.autocomplete"
    mode: str = "entity"
    context_keys: tuple[str, ...] = ("department",)
    result_limit: int = 20
    allowed: bool = True

    def __post_init__(self):
        self.calls = []

    def can_use(self, user):
        return self.allowed

    def search(self, *, user, query, context, limit):
        self.calls.append(
            {"user": user, "query": query, "context": context, "limit": limit}
        )
        return [
            AutocompleteOption(
                value=index,
                label=f"Вариант {index}",
                secondary="Дополнение",
                metadata={"department_id": index},
            )
            for index in range(25)
        ]


class AutocompleteRegistryTests(SimpleTestCase):
    def tearDown(self):
        unregister_autocomplete_provider("tests.autocomplete")

    def test_rejects_unsafe_provider_contract(self):
        with self.assertRaises(ValidationError):
            register_autocomplete_provider(StubProvider(code="unsafe/model"))
        with self.assertRaises(ValidationError):
            register_autocomplete_provider(StubProvider(mode="arbitrary"))
        with self.assertRaises(ValidationError):
            register_autocomplete_provider(StubProvider(result_limit=21))

    def test_duplicate_registration_requires_explicit_replace(self):
        provider = StubProvider()
        register_autocomplete_provider(provider)
        with self.assertRaises(ValidationError):
            register_autocomplete_provider(StubProvider())


class AutocompleteViewTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.user = SimpleNamespace(is_authenticated=True)
        self.provider = StubProvider()
        register_autocomplete_provider(self.provider, replace=True)
        self.view = AutocompleteView.as_view(provider_code=self.provider.code)

    def tearDown(self):
        unregister_autocomplete_provider(self.provider.code)

    def get(self, params=None, *, user=None):
        request = self.factory.get("/options/", params or {})
        request.user = self.user if user is None else user
        return self.view(request)

    def test_passes_only_allowlisted_context_and_clamps_limit(self):
        response = self.get(
            {
                "q": f"  {'x' * 120}  ",
                "department": "42",
                "model": "accounts.User",
                "lookup": "password__icontains",
                "limit": "999",
            }
        )

        self.assertEqual(response.status_code, 200)
        call = self.provider.calls[0]
        self.assertEqual(call["query"], "x" * 100)
        self.assertEqual(call["context"], {"department": "42"})
        self.assertEqual(call["limit"], 20)
        payload = json.loads(response.content)
        self.assertEqual(payload["mode"], "entity")
        self.assertEqual(len(payload["results"]), 20)
        self.assertEqual(payload["results"][0]["value"], "0")
        self.assertEqual(payload["results"][0]["department_id"], 0)
        self.assertEqual(payload["results"][0]["metadata"], {"department_id": 0})
        self.assertIn("private", response["Cache-Control"])
        self.assertIn("no-store", response["Cache-Control"])

    def test_rejects_anonymous_and_unauthorized_users_without_searching(self):
        anonymous = self.get(user=SimpleNamespace(is_authenticated=False))
        self.provider.allowed = False
        forbidden = self.get()

        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(self.provider.calls, [])
        self.assertIn("no-store", anonymous["Cache-Control"])
        self.assertIn("no-store", forbidden["Cache-Control"])

    def test_unknown_registered_code_is_not_resolved_from_client_input(self):
        view = AutocompleteView.as_view(provider_code="tests.missing")
        request = self.factory.get(
            "/options/",
            {"provider": "tests.autocomplete", "model": "auth.User"},
        )
        request.user = self.user

        response = view(request)

        self.assertEqual(response.status_code, 404)
        self.assertEqual(self.provider.calls, [])

    def test_suggestion_mode_is_declared_by_server_provider(self):
        self.provider.mode = "suggestion"
        register_autocomplete_provider(self.provider, replace=True)

        response = self.get()

        self.assertEqual(json.loads(response.content)["mode"], "suggestion")
