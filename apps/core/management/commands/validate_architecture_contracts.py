from django.conf import settings
from django.core.management.base import BaseCommand

from apps.core.json_utils import (
    load_json_file,
    validate_change_plan_payload,
    validate_dataset_registry_payload,
    validate_integration_registry_payload,
    validate_role_rules_payload,
    validate_task_brief_payload,
    validate_workflow_rules_payload,
)


class Command(BaseCommand):
    help = "Validate AI-first / Code-first JSON contracts used by the project."

    def handle(self, *args, **options):
        workflow_payload = load_json_file(settings.LOCAL_BUSINESS_WORKFLOW_RULES_FILE)
        validate_workflow_rules_payload(workflow_payload)
        role_payload = load_json_file(settings.LOCAL_BUSINESS_ROLE_RULES_FILE)
        validate_role_rules_payload(role_payload, workflow_payload=workflow_payload)
        validate_integration_registry_payload(load_json_file(settings.LOCAL_BUSINESS_INTEGRATION_REGISTRY_FILE))
        validate_dataset_registry_payload(load_json_file(settings.LOCAL_BUSINESS_ANALYTICS_DATASETS_FILE))
        validate_task_brief_payload(load_json_file(settings.LOCAL_BUSINESS_TASK_BRIEF_TEMPLATE_FILE))
        validate_change_plan_payload(load_json_file(settings.LOCAL_BUSINESS_CHANGE_PLAN_TEMPLATE_FILE))
        self.stdout.write(self.style.SUCCESS("Architecture contracts are valid."))
