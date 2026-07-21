"""Тесты валидации identity_model реестра AI."""
from apps.ai.tests._common import *  # noqa: F401,F403


class IdentityModelValidationTests(TestCase):
    databases = RUNTIME_DATABASES
    """Tests for identity model alignment validation in json_utils."""

    def test_validate_ai_identity_model_alignment_passes_complete_fields(self):
        from apps.ai.contracts import validate_ai_identity_model_alignment
        registry = {
            "identity_model": {
                "propagate_user_identity": True,
                "minimum_fields": [
                    "user_id", "roles", "session_id", "conversation_id", "request_id"
                ]
            }
        }
        # Should not raise
        validate_ai_identity_model_alignment(registry)

    def test_validate_ai_identity_model_alignment_catches_missing_fields(self):
        from apps.ai.contracts import validate_ai_identity_model_alignment
        from django.core.exceptions import ValidationError
        registry = {
            "identity_model": {
                "minimum_fields": ["user_id"]  # missing most fields
            }
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_identity_model_alignment(registry)
        self.assertIn("conversation_id", str(ctx.exception))
        self.assertIn("request_id", str(ctx.exception))

    def test_validate_ai_identity_model_alignment_catches_empty_minimum_fields(self):
        from apps.ai.contracts import validate_ai_identity_model_alignment
        from django.core.exceptions import ValidationError
        registry = {
            "identity_model": {
                "minimum_fields": []
            }
        }
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_identity_model_alignment(registry)
        self.assertIn("user_id", str(ctx.exception))

    def test_validate_ai_identity_model_alignment_catches_no_identity_model(self):
        from apps.ai.contracts import validate_ai_identity_model_alignment
        from django.core.exceptions import ValidationError
        registry = {}  # no identity_model key
        with self.assertRaises(ValidationError) as ctx:
            validate_ai_identity_model_alignment(registry)
        self.assertIn("conversation_id", str(ctx.exception))
