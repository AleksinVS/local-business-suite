from __future__ import annotations

import copy
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase, TestCase, override_settings

from apps.accounts.access_contracts import capability_group_code, role_is_protected
from apps.accounts.access_contracts import role_definition_read_model
from apps.core.contract_store import _reset_for_tests, get_contract
from apps.core.json_utils import load_json_file
from apps.core.models import Department
from apps.workorders.contracts import capability_values, validate_role_rules_payload
from apps.workorders.policies import superuser_rules
from apps.warehouse.models import Warehouse
from apps.warehouse.policies import (
    WAREHOUSE_ADJUST_SCOPE,
    WAREHOUSE_MANAGE_LOCATIONS_SCOPE,
    WAREHOUSE_OPERATE_SCOPE,
    WAREHOUSE_VIEW_SCOPE,
    can_access_warehouse,
    can_manage_warehouse_catalog,
    department_ids_for_warehouse_scope,
    require_warehouse_scope,
)
from apps.warehouse.selectors import (
    adjustable_warehouses_queryset,
    manageable_location_warehouses_queryset,
    operable_warehouses_queryset,
    visible_warehouses_queryset,
)


GIT_ROLE_RULES = Path(settings.BASE_DIR) / "contracts" / "role_rules.json"


class WarehouseRoleContractTests(SimpleTestCase):
    def test_git_contract_declares_closed_existing_roles_and_expected_warehouse_roles(self):
        rules = load_json_file(GIT_ROLE_RULES)
        workflow = load_json_file(Path(settings.BASE_DIR) / "contracts" / "workflow_rules.json")

        validate_role_rules_payload(rules, workflow_payload=workflow)
        self.assertEqual(
            set(capability_values("warehouse_scopes")),
            {"none", "own_department", "department_branch", "all"},
        )
        for role_name in ("viewer", "customer", "technician", "manager", "admin", "doctor"):
            role = rules[role_name]
            self.assertEqual(role["warehouse_view_scope"], "none")
            self.assertEqual(role["warehouse_operate_scope"], "none")
            self.assertEqual(role["warehouse_adjust_scope"], "none")
            self.assertEqual(role["warehouse_manage_locations_scope"], "none")
            self.assertEqual(role["warehouse_manage_report_profiles_scope"], "none")
            self.assertIs(role["warehouse_manage_catalog"], False)

        self.assertEqual(rules["warehouse_operator"]["warehouse_operate_scope"], "department_branch")
        self.assertEqual(rules["warehouse_controller"]["warehouse_adjust_scope"], "department_branch")
        self.assertEqual(rules["warehouse_administrator"]["warehouse_view_scope"], "all")
        self.assertEqual(rules["warehouse_administrator"]["warehouse_operate_scope"], "none")
        self.assertIs(rules["warehouse_administrator"]["warehouse_manage_catalog"], True)
        root_rules = superuser_rules(rules_payload=rules)
        self.assertEqual(root_rules["warehouse_view_scope"], "all")
        self.assertEqual(root_rules["warehouse_adjust_scope"], "all")
        self.assertIs(root_rules["warehouse_manage_catalog"], True)

    def test_warehouse_capabilities_have_a_dedicated_editor_group_and_critical_ceiling(self):
        rules = load_json_file(GIT_ROLE_RULES)
        catalog = rules["$capabilities"]

        for capability in (
            "warehouse_view_scope",
            "warehouse_operate_scope",
            "warehouse_adjust_scope",
            "warehouse_manage_locations_scope",
            "warehouse_manage_report_profiles_scope",
            "warehouse_manage_catalog",
        ):
            self.assertEqual(capability_group_code(capability, catalog[capability]), "warehouse")
        self.assertFalse(role_is_protected(rules["warehouse_operator"], catalog=catalog))
        self.assertTrue(role_is_protected(rules["warehouse_controller"], catalog=catalog))
        self.assertTrue(role_is_protected(rules["warehouse_administrator"], catalog=catalog))


@override_settings(LOCAL_BUSINESS_ROLE_RULES_FILE=GIT_ROLE_RULES)
class WarehouseAccessPolicyTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.organization = Department.objects.create(name="Организация")
        cls.own = Department.objects.create(name="Складская служба", parent=cls.organization)
        cls.child = Department.objects.create(name="Аптека", parent=cls.own)
        cls.sibling = Department.objects.create(name="Соседнее отделение", parent=cls.organization)
        cls.own_warehouse = Warehouse.objects.create(department=cls.own, code="OWN", name="Основной")
        cls.child_warehouse = Warehouse.objects.create(department=cls.child, code="CHILD", name="Дочерний")
        cls.sibling_warehouse = Warehouse.objects.create(
            department=cls.sibling, code="SIBLING", name="Соседний"
        )

        for role_name in (
            "manager",
            "warehouse_operator",
            "warehouse_controller",
            "warehouse_administrator",
        ):
            Group.objects.get_or_create(name=role_name)

        cls.operator = cls._user("warehouse-operator", cls.own, "warehouse_operator")
        cls.controller = cls._user("warehouse-controller", cls.own, "warehouse_controller")
        cls.administrator = cls._user(
            "warehouse-administrator", cls.own, "warehouse_administrator"
        )
        cls.manager = cls._user("ordinary-manager", cls.own, "manager")
        cls.roleless = cls._user("warehouse-roleless", cls.own)
        cls.staff_only = cls._user("warehouse-staff-only", cls.own, is_staff=True)
        cls.inactive = cls._user(
            "warehouse-inactive", cls.own, "warehouse_operator", is_active=False
        )
        cls.root = cls._user(
            "warehouse-root", cls.own, is_staff=True, is_superuser=True
        )

    @classmethod
    def _user(cls, username, department, role_name=None, **flags):
        user = get_user_model().objects.create_user(
            username=username,
            department=department,
            **flags,
        )
        if role_name:
            user.groups.add(Group.objects.get(name=role_name))
        return user

    def setUp(self):
        _reset_for_tests()

    def tearDown(self):
        _reset_for_tests()

    def test_role_matrix_and_branch_selectors(self):
        branch_ids = {self.own.pk, self.child.pk}
        self.assertEqual(
            department_ids_for_warehouse_scope(self.operator, WAREHOUSE_VIEW_SCOPE),
            branch_ids,
        )
        self.assertEqual(
            set(visible_warehouses_queryset(self.operator).values_list("pk", flat=True)),
            {self.own_warehouse.pk, self.child_warehouse.pk},
        )
        self.assertEqual(
            set(operable_warehouses_queryset(self.operator).values_list("pk", flat=True)),
            {self.own_warehouse.pk, self.child_warehouse.pk},
        )
        self.assertFalse(adjustable_warehouses_queryset(self.operator).exists())
        self.assertFalse(manageable_location_warehouses_queryset(self.operator).exists())

        self.assertEqual(
            set(adjustable_warehouses_queryset(self.controller).values_list("pk", flat=True)),
            {self.own_warehouse.pk, self.child_warehouse.pk},
        )
        self.assertEqual(
            set(
                manageable_location_warehouses_queryset(self.controller).values_list(
                    "pk", flat=True
                )
            ),
            {self.own_warehouse.pk, self.child_warehouse.pk},
        )
        self.assertFalse(can_manage_warehouse_catalog(self.controller))

        self.assertIsNone(
            department_ids_for_warehouse_scope(self.administrator, WAREHOUSE_VIEW_SCOPE)
        )
        self.assertFalse(operable_warehouses_queryset(self.administrator).exists())
        self.assertFalse(adjustable_warehouses_queryset(self.administrator).exists())
        self.assertEqual(
            set(
                manageable_location_warehouses_queryset(self.administrator).values_list(
                    "pk", flat=True
                )
            ),
            {
                self.own_warehouse.pk,
                self.child_warehouse.pk,
                self.sibling_warehouse.pk,
            },
        )
        self.assertTrue(can_manage_warehouse_catalog(self.administrator))

    def test_role_editor_read_model_exposes_warehouse_section_and_all_scope_choices(self):
        from apps.settings_center.forms import RoleDefinitionForm

        model = role_definition_read_model("warehouse_operator")
        section = next(item for item in model["sections"] if item["code"] == "warehouse")
        self.assertEqual(len(section["capabilities"]), 6)
        form = RoleDefinitionForm(
            role_read_model=model,
            actor=self.root,
            initial={"base_hash": model["base_hash"]},
        )
        choices = dict(form.fields["capability__warehouse_view_scope"].choices)
        self.assertEqual(choices["own_department"], "Только своё подразделение")
        self.assertEqual(choices["department_branch"], "Ветка подразделения")

    def test_roleless_staff_existing_role_inactive_and_unknown_capability_fail_closed(self):
        for actor in (self.roleless, self.staff_only, self.manager, self.inactive):
            self.assertFalse(can_access_warehouse(actor))
            self.assertEqual(
                department_ids_for_warehouse_scope(actor, WAREHOUSE_VIEW_SCOPE), set()
            )
            self.assertFalse(visible_warehouses_queryset(actor).exists())
        self.assertEqual(
            department_ids_for_warehouse_scope(self.operator, "manage_inventory"), set()
        )
        self.assertIsNone(
            department_ids_for_warehouse_scope(self.root, WAREHOUSE_ADJUST_SCOPE)
        )

    def test_multiple_roles_do_not_launder_global_view_into_operations(self):
        self.administrator.groups.add(Group.objects.get(name="warehouse_operator"))

        self.assertIsNone(
            department_ids_for_warehouse_scope(self.administrator, WAREHOUSE_VIEW_SCOPE)
        )
        self.assertEqual(
            department_ids_for_warehouse_scope(
                self.administrator, WAREHOUSE_OPERATE_SCOPE
            ),
            {self.own.pk, self.child.pk},
        )
        self.assertEqual(
            department_ids_for_warehouse_scope(
                self.administrator, WAREHOUSE_ADJUST_SCOPE
            ),
            set(),
        )

    def test_own_department_scope_excludes_children(self):
        rules = copy.deepcopy(get_contract("role_rules"))
        own_role = copy.deepcopy(rules["warehouse_operator"])
        own_role["warehouse_view_scope"] = "own_department"
        rules["warehouse_own_only"] = own_role
        group = Group.objects.create(name="warehouse_own_only")
        actor = self._user("warehouse-own-only", self.own)
        actor.groups.add(group)

        self.assertEqual(
            department_ids_for_warehouse_scope(
                actor,
                WAREHOUSE_VIEW_SCOPE,
                rules_payload=rules,
            ),
            {self.own.pk},
        )

    def test_require_scope_reloads_actor_and_denies_foreign_or_revoked_access(self):
        require_warehouse_scope(
            actor=self.operator,
            capability=WAREHOUSE_OPERATE_SCOPE,
            department=self.child,
        )
        with self.assertRaises(PermissionDenied):
            require_warehouse_scope(
                actor=self.operator,
                capability=WAREHOUSE_OPERATE_SCOPE,
                department=self.sibling,
            )

        get_user_model().objects.filter(pk=self.operator.pk).update(is_active=False)
        with self.assertRaises(PermissionDenied):
            require_warehouse_scope(
                actor=self.operator,
                capability=WAREHOUSE_OPERATE_SCOPE,
                department=self.own,
            )

    def test_require_scope_observes_group_revocation_and_department_change(self):
        self.operator.groups.clear()
        with self.assertRaises(PermissionDenied):
            require_warehouse_scope(
                actor=self.operator,
                capability=WAREHOUSE_OPERATE_SCOPE,
                department=self.own,
            )

        self.operator.groups.add(Group.objects.get(name="warehouse_operator"))
        get_user_model().objects.filter(pk=self.operator.pk).update(
            department=self.sibling
        )
        with self.assertRaises(PermissionDenied):
            require_warehouse_scope(
                actor=self.operator,
                capability=WAREHOUSE_OPERATE_SCOPE,
                department=self.child,
            )
        require_warehouse_scope(
            actor=self.operator,
            capability=WAREHOUSE_OPERATE_SCOPE,
            department=self.sibling,
        )

    def test_unassigned_non_superuser_is_quarantined_even_with_global_role(self):
        unassigned = get_user_model().objects.create_user(username="warehouse-unassigned")
        unassigned.groups.add(Group.objects.get(name="warehouse_administrator"))

        self.assertFalse(can_access_warehouse(unassigned))
        self.assertFalse(can_manage_warehouse_catalog(unassigned))
        self.assertEqual(
            department_ids_for_warehouse_scope(unassigned, WAREHOUSE_VIEW_SCOPE), set()
        )
