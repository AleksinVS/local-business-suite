import pytest
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.core.right_panels import (
    RIGHT_PANEL_COMMAND_OPEN,
    RIGHT_PANEL_FORM_COMMAND_OPEN,
    RightPanelDescriptor,
    RightPanelFormDescriptor,
    build_human_right_panel_form_descriptor,
    build_right_panel_descriptor,
    clear_right_panel_providers,
    register_right_panel_provider,
    registered_right_panel_providers,
)


pytestmark = pytest.mark.unit


class RightPanelFormContractTests(SimpleTestCase):
    def setUp(self):
        self.original_providers = registered_right_panel_providers()
        clear_right_panel_providers()

    def tearDown(self):
        clear_right_panel_providers()
        for provider in self.original_providers.values():
            register_right_panel_provider(provider, replace=True)
        super().tearDown()

    @staticmethod
    def form_provider():
        class FormProvider:
            source_code = "demo"
            object_type = "record"
            supported_modes = ("create", "edit")

            def can_open(self, user, object_id, mode="edit"):
                return user == "allowed" and object_id in {"new", "42"}

            def build_panel(self, user, object_id, mode="edit"):
                return RightPanelDescriptor(
                    source_code=self.source_code,
                    object_type=self.object_type,
                    object_id=object_id,
                    mode=mode,
                    title="Demo form",
                    htmx_url=f"/demo/{object_id}/{mode}/panel/",
                    drawer_size="workspace",
                )

        return FormProvider()

    def test_human_form_descriptor_is_separate_from_view_command(self):
        register_right_panel_provider(self.form_provider())

        form = build_human_right_panel_form_descriptor(
            user="allowed",
            source_code="demo",
            object_type="record",
            object_id="42",
            mode="edit",
        )

        payload = form.as_dict()
        self.assertEqual(payload["type"], RIGHT_PANEL_FORM_COMMAND_OPEN)
        self.assertEqual(payload["mode"], "edit")
        self.assertEqual(payload["drawer_size"], "workspace")
        self.assertEqual(payload["htmx_url"], "/demo/42/edit/panel/")

    def test_create_form_is_resolved_by_registered_domain_provider(self):
        register_right_panel_provider(self.form_provider())

        form = build_human_right_panel_form_descriptor(
            user="allowed",
            source_code="demo",
            object_type="record",
            object_id="new",
            mode="create",
        )

        self.assertEqual(form.panel.object_id, "new")
        self.assertEqual(form.panel.mode, "create")

    def test_human_form_rejects_view_mode(self):
        register_right_panel_provider(self.form_provider())

        with self.assertRaisesMessage(ValidationError, "только create/edit"):
            build_human_right_panel_form_descriptor(
                user="allowed",
                source_code="demo",
                object_type="record",
                object_id="42",
                mode="view",
            )

    def test_provider_cannot_declare_arbitrary_crud_mode(self):
        provider = self.form_provider()
        provider.supported_modes = ("approve",)

        with self.assertRaisesMessage(ValidationError, "Режим правой панели не поддерживается"):
            register_right_panel_provider(provider)

    def test_view_descriptor_keeps_ai_command_type_and_cannot_be_wrapped_as_form(self):
        descriptor = RightPanelDescriptor(
            source_code="demo",
            object_type="record",
            object_id="42",
            mode="view",
            title="Demo",
            htmx_url="/demo/42/",
        )

        self.assertEqual(descriptor.as_dict()["type"], RIGHT_PANEL_COMMAND_OPEN)
        with self.assertRaisesMessage(ValidationError, "только создание или редактирование"):
            RightPanelFormDescriptor(panel=descriptor)

    def test_existing_builder_still_checks_provider_modes(self):
        register_right_panel_provider(self.form_provider())

        with self.assertRaisesMessage(ValidationError, "Режим правой панели не поддерживается"):
            build_right_panel_descriptor(
                user="allowed",
                source_code="demo",
                object_type="record",
                object_id="42",
                mode="view",
            )

    def test_descriptor_accepts_only_safe_relative_same_origin_paths(self):
        descriptor = RightPanelDescriptor(
            source_code="demo",
            object_type="record",
            object_id="42",
            title="Demo",
            htmx_url="/demo/42/?section=main",
        )

        self.assertEqual(descriptor.htmx_url, "/demo/42/?section=main")
        unsafe_paths = (
            "https://example.test/demo/42/",
            "//example.test/demo/42/",
            "/\\example.test/demo/42/",
            "/%5C%5Cexample.test/demo/42/",
            "/%255C%255Cexample.test/demo/42/",
            "/%2F%2Fexample.test/demo/42/",
            "/%252F%252Fexample.test/demo/42/",
            "/demo/42/#fragment",
            "/demo/42/%23fragment",
            "/demo/42/\x00",
        )
        for unsafe_path in unsafe_paths:
            with self.subTest(unsafe_path=unsafe_path):
                with self.assertRaisesMessage(ValidationError, "безопасным локальным путем"):
                    RightPanelDescriptor(
                        source_code="demo",
                        object_type="record",
                        object_id="42",
                        title="Demo",
                        htmx_url=unsafe_path,
                    )

    def test_outer_html_swap_is_rejected_because_the_stable_host_uses_inner_html(self):
        with self.assertRaisesMessage(ValidationError, "Режим замены правой панели не поддерживается"):
            RightPanelDescriptor(
                source_code="demo",
                object_type="record",
                object_id="42",
                title="Demo",
                htmx_url="/demo/42/",
                swap="outerHTML",
            )
