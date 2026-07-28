from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import AdminAuditLog, AdminProfile, User


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
