from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AdminAuditLog, AdminProfile, Role, User


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
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
                "fields": ("email", "role", "phone_number"),
            },
        ),
    )

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
        if self._has_customer_profile(obj):
            obj.role = Role.CUSTOMER
            obj.is_staff = False
            obj.is_superuser = False
        elif obj.role == Role.CUSTOMER:
            obj.is_staff = False
            obj.is_superuser = False
        obj.full_clean()
        super().save_model(request, obj, form, change)


@admin.register(AdminProfile)
class AdminProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "employee_id", "designation", "created_by", "created_at")
    search_fields = ("user__username", "user__email", "employee_id", "designation")
    list_filter = ("designation", "created_at")
    autocomplete_fields = ("user", "created_by")


@admin.register(AdminAuditLog)
class AdminAuditLogAdmin(admin.ModelAdmin):
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
