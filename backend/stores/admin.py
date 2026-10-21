from django.contrib import admin, messages
from django.core.exceptions import ValidationError

from catalog.models import Product
from catalog.services import guard_product_image_cascade
from config.storage_errors import ImageAdminErrorMixin

from .management import approve_managed_store, set_verification
from .models import Store, StoreCategory, StoreDocument, StoreStatusHistory, StoreUser, StoreStatus, VerificationStatus
from .decorators import user_has_store_permission


class StoreDocumentInline(admin.TabularInline):
    """Uploaded business documents. Read-only: uploading never verifies a store."""

    model = StoreDocument
    extra = 0
    can_delete = False
    fields = ("kind", "title", "file", "uploaded_by", "created_at")
    readonly_fields = fields

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(StoreCategory)
class StoreCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_active", "updated_at")
    list_filter = ("is_active",)
    search_fields = ("name", "slug", "description")
    prepopulated_fields = {"slug": ("name",)}
    readonly_fields = ("created_at", "updated_at")
    ordering = ("name",)


class StoreUserInline(admin.TabularInline):
    model = StoreUser
    extra = 0
    autocomplete_fields = ("user", "created_by")
    fields = (
        "user",
        "is_primary",
        "is_active",
        "can_manage_inventory",
        "can_manage_orders",
        "designation",
        "created_by",
    )
    show_change_link = True


class StoreStatusHistoryInline(admin.TabularInline):
    model = StoreStatusHistory
    extra = 0
    can_delete = False
    autocomplete_fields = ("changed_by",)
    readonly_fields = (
        "old_status",
        "new_status",
        "changed_by",
        "reason",
        "ip_address",
        "created_at",
    )
    fields = readonly_fields

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Store)
class StoreAdmin(ImageAdminErrorMixin, admin.ModelAdmin):
    list_display = (
        "name",
        "store_code",
        "store_type",
        "status",
        "verification_status",
        "ordering_enabled",
        "is_active",
        "category",
        "email",
        "contact_phone",
        "commission_percentage",
        "created_at",
    )
    list_filter = ("status", "verification_status", "ordering_enabled", "creation_source", "is_active", "store_type", "category", "created_at")
    search_fields = (
        "name",
        "store_code",
        "email",
        "contact_phone",
        "alternative_phone",
        "description",
        "address__city",
        "address__state",
        "address__postal_code",
    )
    autocomplete_fields = ("category", "address", "created_by")
    # Status changes must go through management portal (validate + history + audit).
    readonly_fields = (
        "store_code", "status", "verification_status", "verified_by", "verified_at",
        "approved_by", "approved_at", "creation_source", "missing_requirements",
        "ordering_enabled", "created_at", "updated_at",
    )
    inlines = (StoreUserInline, StoreDocumentInline, StoreStatusHistoryInline)
    actions = ("approve_stores", "verify_stores")

    @admin.action(description="Approve selected stores (checks requirements)")
    def approve_stores(self, request, queryset):
        if not user_has_store_permission(request.user, "stores.approve_store"):
            self.message_user(request, "You do not have permission to approve stores.", messages.ERROR)
            return
        done, blocked = 0, []
        for store in queryset.filter(status__in=[StoreStatus.PENDING, StoreStatus.DRAFT]):
            try:
                approve_managed_store(actor=request.user, store=store, request=request)
                done += 1
            except ValidationError as exc:
                blocked.append(f"{store.store_code}: {'; '.join(exc.messages)}")
        if done:
            self.message_user(request, f"Approved {done} store(s).", messages.SUCCESS)
        for line in blocked[:10]:
            self.message_user(request, f"Not approved — {line}", messages.WARNING)
        if not done and not blocked:
            self.message_user(request, "Only Pending or Draft stores can be approved.", messages.INFO)

    @admin.action(description="Mark selected stores as verified")
    def verify_stores(self, request, queryset):
        if not user_has_store_permission(request.user, "stores.approve_store"):
            self.message_user(request, "You do not have permission to verify stores.", messages.ERROR)
            return
        count = 0
        for store in queryset.exclude(verification_status=VerificationStatus.VERIFIED):
            set_verification(actor=request.user, store=store, status=VerificationStatus.VERIFIED, request=request)
            count += 1
        self.message_user(request, f"Verified {count} store(s).", messages.SUCCESS)
    ordering = ("-created_at",)

    def save_formset(self, request, form, formset, change):
        """Keep at most one primary StoreUser when saving inline memberships."""
        if formset.model is not StoreUser:
            super().save_formset(request, form, formset, change)
            return

        instances = formset.save(commit=False)
        store = form.instance
        primary_instances = [
            instance for instance in instances if instance.is_primary
        ]
        if len(primary_instances) > 1:
            raise ValidationError("A store can have only one primary Store User.")

        for obj in formset.deleted_objects:
            obj.delete()

        if primary_instances:
            StoreUser.objects.filter(store=store, is_primary=True).exclude(
                pk__in=[instance.pk for instance in primary_instances if instance.pk]
            ).update(is_primary=False)

        for instance in instances:
            instance.full_clean()
            instance.save()
        formset.save_m2m()

    def delete_model(self, request, obj):
        guard_product_image_cascade(Product.objects.filter(store=obj).order_by("pk"))
        super().delete_model(request, obj)

    def delete_queryset(self, request, queryset):
        guard_product_image_cascade(Product.objects.filter(store__in=queryset).order_by("pk"))
        super().delete_queryset(request, queryset)


@admin.register(StoreUser)
class StoreUserAdmin(admin.ModelAdmin):
    list_display = (
        "user",
        "store",
        "designation",
        "is_primary",
        "is_active",
        "can_manage_inventory",
        "can_manage_orders",
        "created_by",
        "created_at",
    )
    list_filter = (
        "is_primary",
        "is_active",
        "can_manage_inventory",
        "can_manage_orders",
        "created_at",
    )
    search_fields = (
        "user__username",
        "user__email",
        "designation",
        "store__name",
        "store__store_code",
    )
    autocomplete_fields = ("store", "user", "created_by")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-is_primary", "user__username")

    def save_model(self, request, obj, form, change):
        if obj.is_primary and obj.store_id:
            StoreUser.objects.filter(store_id=obj.store_id, is_primary=True).exclude(
                pk=obj.pk
            ).update(is_primary=False)
        super().save_model(request, obj, form, change)

@admin.register(StoreStatusHistory)
class StoreStatusHistoryAdmin(admin.ModelAdmin):
    actions = None

    def has_delete_permission(self, request, obj=None):
        return False

    list_display = (
        "store",
        "old_status",
        "new_status",
        "changed_by",
        "ip_address",
        "created_at",
    )
    list_filter = ("old_status", "new_status", "created_at")
    search_fields = (
        "store__name",
        "store__store_code",
        "changed_by__username",
        "reason",
    )
    autocomplete_fields = ("store", "changed_by")
    readonly_fields = (
        "store",
        "old_status",
        "new_status",
        "changed_by",
        "reason",
        "ip_address",
        "created_at",
    )
    ordering = ("-created_at",)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
