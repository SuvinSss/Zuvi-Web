from django.contrib import admin
from django.core.exceptions import ValidationError

from .models import Customer, CustomerAddress


class CustomerAddressInline(admin.TabularInline):
    model = CustomerAddress
    extra = 0
    autocomplete_fields = ("address",)
    fields = (
        "label",
        "recipient_name",
        "phone_number",
        "address",
        "delivery_instructions",
        "is_default",
        "is_active",
    )
    show_change_link = True


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = (
        "customer_code",
        "user",
        "registration_source",
        "verification_status",
        "created_by",
        "created_at",
    )
    list_filter = (
        "registration_source",
        "verification_status",
        "created_at",
        "user__is_active",
    )
    search_fields = (
        "customer_code",
        "user__username",
        "user__email",
        "user__phone_number",
        "user__first_name",
        "user__last_name",
        "notes",
    )
    autocomplete_fields = ("user", "created_by")
    readonly_fields = ("customer_code", "created_at", "updated_at")
    inlines = (CustomerAddressInline,)
    ordering = ("-created_at",)

    def save_formset(self, request, form, formset, change):
        """Keep at most one active default address when saving inlines."""
        if formset.model is not CustomerAddress:
            super().save_formset(request, form, formset, change)
            return

        instances = formset.save(commit=False)
        customer = form.instance
        default_instances = [
            instance
            for instance in instances
            if instance.is_default and instance.is_active
        ]
        if len(default_instances) > 1:
            raise ValidationError(
                "A customer can have only one active default address."
            )

        for obj in formset.deleted_objects:
            obj.delete()

        if default_instances:
            CustomerAddress.objects.filter(
                customer=customer,
                is_default=True,
                is_active=True,
            ).exclude(
                pk__in=[
                    instance.pk for instance in default_instances if instance.pk
                ]
            ).update(is_default=False)

        for instance in instances:
            instance.full_clean()
            instance.save()

        formset.save_m2m()


@admin.register(CustomerAddress)
class CustomerAddressAdmin(admin.ModelAdmin):
    list_display = (
        "customer",
        "label",
        "recipient_name",
        "phone_number",
        "is_default",
        "is_active",
        "city",
        "created_at",
    )
    list_filter = ("label", "is_default", "is_active", "created_at")
    search_fields = (
        "customer__customer_code",
        "customer__user__username",
        "customer__user__email",
        "recipient_name",
        "phone_number",
        "address__line1",
        "address__city",
        "address__state",
        "address__postal_code",
    )
    autocomplete_fields = ("customer", "address")
    readonly_fields = ("created_at", "updated_at")
    ordering = ("-is_default", "-is_active", "-created_at")

    @admin.display(description="City", ordering="address__city")
    def city(self, obj):
        return obj.address.city
