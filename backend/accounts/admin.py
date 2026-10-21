from django.contrib import admin
from django.contrib.admin.utils import unquote
from django.contrib.auth.admin import GroupAdmin as DjangoGroupAdmin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin
from django.contrib.auth.forms import AdminUserCreationForm, UserChangeForm
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError

from .decorators import can_access_management_portal
from .models import AdminAuditLog, AdminProfile, Role, User


def _is_super_admin(user):
    return bool(
        user
        and can_access_management_portal(user)
        and user.role == Role.SUPER_ADMIN
    )


class SensitiveAccountAdminMixin:
    """Generic Django permissions cannot authorize account privilege changes."""

    def has_view_permission(self, request, obj=None):
        if _is_super_admin(request.user):
            return super().has_view_permission(request, obj)
        return bool(
            request.user
            and can_access_management_portal(request.user)
            and request.user.has_perm(
                f"{self.opts.app_label}.view_{self.opts.model_name}"
            )
        )

    def has_add_permission(self, request):
        return _is_super_admin(request.user) and super().has_add_permission(request)

    def has_change_permission(self, request, obj=None):
        return _is_super_admin(request.user) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return _is_super_admin(request.user) and super().has_delete_permission(request, obj)

    def has_module_permission(self, request):
        return self.has_view_permission(request) or self.has_add_permission(request)

    def save_model(self, request, obj, form, change):
        if not _is_super_admin(request.user):
            raise PermissionDenied("Only Super Admins may manage accounts and permissions.")
        super().save_model(request, obj, form, change)


def _validate_admin_role_flags(role, is_staff, is_superuser):
    if role == Role.SUPER_ADMIN and not (is_staff and is_superuser):
        raise ValidationError("A SUPER_ADMIN must have staff and superuser status.")
    if role == Role.ADMIN and (not is_staff or is_superuser):
        raise ValidationError("An ADMIN must have staff status without superuser status.")


class AdminRoleFormMixin:
    def clean(self):
        data = super().clean()
        _validate_admin_role_flags(
            data.get("role", self.instance.role),
            data.get("is_staff", self.instance.is_staff),
            data.get("is_superuser", self.instance.is_superuser),
        )
        return data


class ZuuViUserCreationForm(AdminRoleFormMixin, AdminUserCreationForm):
    pass


class ZuuViUserChangeForm(AdminRoleFormMixin, UserChangeForm):
    pass


@admin.register(User)
class UserAdmin(SensitiveAccountAdminMixin, DjangoUserAdmin):
    form = ZuuViUserChangeForm
    add_form = ZuuViUserCreationForm
    actions = None
    list_display = ("username", "email", "phone_number", "role", "is_active", "is_staff")
    list_filter = ("role", "is_staff", "is_active")
    search_fields = ("username", "email", "phone_number")
    ordering = ("username",)

    fieldsets = DjangoUserAdmin.fieldsets + (
        ("Profile", {"fields": ("role", "phone_number")}),
    )
    add_fieldsets = DjangoUserAdmin.add_fieldsets + (
        (
            "Profile",
            {
                "classes": ("wide",),
                "fields": (
                    "email", "role", "phone_number", "is_active",
                    "is_staff", "is_superuser",
                ),
            },
        ),
    )

    def has_delete_permission(self, request, obj=None):
        # Authentication accounts are deactivated, never deleted in admin.
        return False

    def get_form(self, request, obj=None, **kwargs):
        form_class = super().get_form(request, obj, **kwargs)
        if obj is not None and obj.pk == request.user.pk:
            class SelfProtectedForm(form_class):
                def clean(self):
                    data = super().clean()
                    if (
                        data.get("role") != Role.SUPER_ADMIN
                        or not data.get("is_staff")
                        or not data.get("is_superuser")
                        or not data.get("is_active")
                    ):
                        raise ValidationError(
                            "You cannot remove your own active Super Admin access."
                        )
                    return data

            return SelfProtectedForm
        return form_class

    def user_change_password(self, request, id, form_url=""):
        if not self.has_change_permission(request):
            raise PermissionDenied
        target = self.get_object(request, unquote(id))
        if (
            request.method == "POST"
            and target is not None
            and request.user.pk == target.pk
            and request.POST.get("usable_password") == "false"
        ):
            raise PermissionDenied("You cannot disable your own password authentication.")
        return super().user_change_password(request, id, form_url)

    def _has_customer_profile(self, obj):
        if obj is None or not obj.pk:
            return False
        return User.objects.filter(
            pk=obj.pk,
            customer_profile__isnull=False,
        ).exists()

    def get_readonly_fields(self, request, obj=None):
        readonly = list(super().get_readonly_fields(request, obj))
        if self._has_customer_profile(obj):
            for field in ("role", "is_staff", "is_superuser"):
                if field not in readonly:
                    readonly.append(field)
        return readonly

    def save_model(self, request, obj, form, change):
        if not _is_super_admin(request.user):
            raise PermissionDenied
        if obj.pk == request.user.pk and (
            obj.role != Role.SUPER_ADMIN
            or not obj.is_staff
            or not obj.is_superuser
            or not obj.is_active
        ):
            raise PermissionDenied("You cannot remove your own active Super Admin access.")
        if self._has_customer_profile(obj):
            obj.role = Role.CUSTOMER
            obj.is_staff = False
            obj.is_superuser = False
        elif obj.role == Role.CUSTOMER:
            obj.is_staff = False
            obj.is_superuser = False
        _validate_admin_role_flags(obj.role, obj.is_staff, obj.is_superuser)
        obj.full_clean()
        super().save_model(request, obj, form, change)


@admin.register(AdminProfile)
class AdminProfileAdmin(SensitiveAccountAdminMixin, admin.ModelAdmin):
    list_display = ("user", "employee_id", "designation", "created_by", "created_at")
    search_fields = ("user__username", "user__email", "employee_id", "designation")
    list_filter = ("designation", "created_at")
    autocomplete_fields = ("user", "created_by")


admin.site.unregister(Group)


@admin.register(Group)
class GroupAdmin(SensitiveAccountAdminMixin, DjangoGroupAdmin):
    pass


@admin.register(AdminAuditLog)
class AdminAuditLogAdmin(admin.ModelAdmin):
    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    list_display = ("action", "actor", "target_user", "ip_address", "created_at")
    search_fields = ("actor__username", "target_user__username", "description")
    list_filter = ("action", "created_at")
    readonly_fields = (
        "actor",
        "action",
        "target_user",
        "description",
        "metadata",
        "ip_address",
        "created_at",
    )
    autocomplete_fields = ("actor", "target_user")
