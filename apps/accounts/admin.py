from django import forms
from django.contrib import admin, messages
from django.contrib.auth.admin import GroupAdmin, UserAdmin
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import ExternalIdentity, GroupProfile, User
from .selectors import contract_role_names, selected_role_names_for_user
from .services import apply_role_assignment, preview_role_assignment


class AdminAccessAssignmentForm(forms.Form):
    roles = forms.ModelMultipleChoiceField(
        label="Контрактные роли",
        queryset=Group.objects.none(),
        required=False,
        widget=forms.CheckboxSelectMultiple,
    )
    is_staff = forms.BooleanField(label="Доступ к Django Admin", required=False)
    is_superuser = forms.BooleanField(label="Суперпользователь", required=False)
    reason = forms.CharField(
        label="Причина резервного изменения",
        max_length=1000,
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    preview_token = forms.CharField(widget=forms.HiddenInput, required=False)
    confirm_risk = forms.BooleanField(
        label="Подтверждаю риск и применение показанных изменений",
        required=False,
    )

    def __init__(self, *args, target_user=None, **kwargs):
        super().__init__(*args, **kwargs)
        role_names = contract_role_names()
        self.fields["roles"].queryset = Group.objects.filter(name__in=role_names).order_by("name")
        if target_user is not None and not self.is_bound:
            self.initial.update(
                {
                    "roles": list(
                        target_user.groups.filter(name__in=role_names).values_list("pk", flat=True)
                    ),
                    "is_staff": target_user.is_staff,
                    "is_superuser": target_user.is_superuser,
                }
            )

    def clean(self):
        cleaned = super().clean()
        if cleaned.get("is_superuser") and not cleaned.get("is_staff"):
            self.add_error("is_staff", "Суперпользователю необходим доступ к Django Admin.")
        return cleaned


class ExternalIdentityInline(admin.TabularInline):
    model = ExternalIdentity
    extra = 0
    readonly_fields = ("last_synced_at", "created_at", "updated_at")


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    fieldsets = UserAdmin.fieldsets + (
        ("Организация", {"fields": ("department",)}),
        ("Управляемый доступ", {"fields": ("managed_access_link",)}),
    )
    list_display = ("username", "email", "first_name", "last_name", "department", "is_staff", "is_active")
    list_filter = UserAdmin.list_filter + ("department",)
    inlines = [ExternalIdentityInline]
    readonly_fields = tuple(UserAdmin.readonly_fields) + (
        "groups",
        "user_permissions",
        "is_staff",
        "is_superuser",
        "is_active",
        "department",
        "managed_access_link",
    )

    @admin.display(description="Резервное изменение")
    def managed_access_link(self, obj):
        if not obj or not obj.pk:
            return "Сначала сохраните пользователя."
        url = reverse("admin:accounts_user_access_assignment", args=[obj.pk])
        return format_html('<a class="button" href="{}">Изменить через preview и аудит</a>', url)

    def get_urls(self):
        return [
            path(
                "<path:object_id>/access-assignment/",
                self.admin_site.admin_view(self.access_assignment_view),
                name="accounts_user_access_assignment",
            )
        ] + super().get_urls()

    def access_assignment_view(self, request, object_id):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied("Резервное изменение доступно только суперпользователю.")
        target_user = get_object_or_404(User, pk=object_id)
        form = AdminAccessAssignmentForm(request.POST or None, target_user=target_user)
        preview = None
        if request.method == "POST" and form.is_valid():
            selected_roles = [group.name for group in form.cleaned_data["roles"]]
            action = request.POST.get("action")
            try:
                if action == "preview":
                    preview = preview_role_assignment(
                        actor=request.user,
                        target_user=target_user,
                        selected_role_names=selected_roles,
                        is_staff=form.cleaned_data["is_staff"],
                        is_superuser=form.cleaned_data["is_superuser"],
                        source="django_admin_break_glass",
                        reason=form.cleaned_data["reason"],
                    )
                    data = form.data.copy()
                    data["preview_token"] = preview["preview_token"]
                    form.data = data
                elif action == "apply":
                    _updated, audit = apply_role_assignment(
                        actor=request.user,
                        target_user=target_user,
                        selected_role_names=selected_roles,
                        is_staff=form.cleaned_data["is_staff"],
                        is_superuser=form.cleaned_data["is_superuser"],
                        preview_token=form.cleaned_data["preview_token"],
                        risk_confirmed=form.cleaned_data["confirm_risk"],
                        source="django_admin_break_glass",
                        reason=form.cleaned_data["reason"],
                    )
                    self.message_user(
                        request,
                        f"Резервное изменение применено. Аудит #{audit.pk}.",
                        messages.SUCCESS,
                    )
                    return HttpResponseRedirect(
                        reverse("admin:accounts_user_change", args=[target_user.pk])
                    )
            except (PermissionDenied, ValidationError) as exc:
                form.add_error(None, exc)
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "original": target_user,
            "title": f"Резервное изменение доступа: {target_user}",
            "form": form,
            "preview": preview,
            "current_roles": selected_role_names_for_user(target_user),
        }
        return TemplateResponse(request, "settings_center/admin_access_assignment.html", context)

    def user_change_password(self, request, id, form_url=""):
        if not request.user.is_active or not request.user.is_superuser:
            raise PermissionDenied(
                "Резервная смена пароля доступна только активному суперпользователю."
            )
        return super().user_change_password(request, id, form_url)

    def has_delete_permission(self, request, obj=None):
        if obj is not None and obj.is_superuser:
            return False
        return super().has_delete_permission(request, obj=obj)

    def delete_queryset(self, request, queryset):
        if queryset.filter(is_superuser=True).exists():
            raise PermissionDenied("Нельзя удалить суперпользователя массовым действием.")
        return super().delete_queryset(request, queryset)


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(admin.ModelAdmin):
    list_display = ("user", "provider", "domain", "username", "upn", "sync_status", "last_synced_at")
    list_filter = ("provider", "domain", "sync_status")
    search_fields = ("user__username", "username", "upn", "subject_id", "distinguished_name")


class GroupProfileInline(admin.StackedInline):
    model = GroupProfile
    can_delete = False
    fields = ("title", "description", "is_predefined")


admin.site.unregister(Group)


@admin.register(Group)
class GroupAdminWithProfile(GroupAdmin):
    inlines = [GroupProfileInline]
    list_display = ("name", "profile_title", "profile_description_short")
    readonly_fields = ("permissions",)

    def get_readonly_fields(self, request, obj=None):
        fields = list(super().get_readonly_fields(request, obj=obj))
        if obj is not None:
            fields.append("name")
        return tuple(fields)

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Название")
    def profile_title(self, obj):
        profile = getattr(obj, "profile", None)
        return getattr(profile, "title", "") or ""

    @admin.display(description="Комментарий")
    def profile_description_short(self, obj):
        profile = getattr(obj, "profile", None)
        description = getattr(profile, "description", "") or ""
        if len(description) > 80:
            return description[:80].rstrip() + "…"
        return description
