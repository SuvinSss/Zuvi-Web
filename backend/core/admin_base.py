"""Shared building blocks for the Zuuvi Django admin.

Records that carry business rules (deliveries, reviews, tickets ...) are viewed here but changed only
through the same service functions the REST API uses. Nothing in this module edits a row directly.
"""
from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.template.response import TemplateResponse

from accounts.decorators import can_access_management_portal


def is_management(request) -> bool:
    return can_access_management_portal(request.user)


class ManagementOnlyMixin:
    """Visible only to ADMIN / SUPER_ADMIN staff that also hold the model's Django view permission."""

    def has_module_permission(self, request):
        return self.has_view_permission(request)

    def has_view_permission(self, request, obj=None):
        return is_management(request) and request.user.has_perm(f"{self.opts.app_label}.view_{self.opts.model_name}")


class ReadOnlyAdmin(ManagementOnlyMixin, admin.ModelAdmin):
    """No add / edit / delete from the admin: the service layer owns every write."""

    actions = None
    list_per_page = 50
    show_full_result_count = False

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return list(super().get_readonly_fields(request, obj)) or [f.name for f in self.model._meta.fields]


class ReadOnlyInline(admin.TabularInline):
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class ActionAdmin(ReadOnlyAdmin):
    """Read-only admin whose bulk actions call service functions. An action needs the model's
    ``change`` permission (granted through Groups) on top of being a management account."""

    actions = ()

    def has_moderate_permission(self, request):
        return is_management(request) and request.user.has_perm(f"{self.opts.app_label}.change_{self.opts.model_name}")

    def get_actions(self, request):
        if not self.has_moderate_permission(request):
            return {}
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


class ReasonForm(forms.Form):
    reason = forms.CharField(max_length=255, label="Reason", widget=forms.Textarea(attrs={"rows": 3}))


class NoteForm(forms.Form):
    reason = forms.CharField(max_length=255, label="Note (optional)", required=False, widget=forms.Textarea(attrs={"rows": 2}))


class EmptyForm(forms.Form):
    pass


def run_confirmed(modeladmin, request, queryset, *, title, verb, form_class, apply, intro=""):
    """Two-step bulk action: show a confirmation page, then apply ``apply(obj, cleaned_data)`` to each
    selected record in its own transaction and report every success and failure."""
    if not modeladmin.has_moderate_permission(request):
        raise PermissionDenied
    objects = list(queryset)
    if request.method == "POST" and "apply" in request.POST:
        form = form_class(request.POST)
        if form.is_valid():
            done, failed = 0, []
            for obj in objects:
                try:
                    with transaction.atomic():
                        apply(obj, form.cleaned_data)
                    done += 1
                except (ValidationError, PermissionDenied) as exc:
                    detail = "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc)
                    failed.append(f"{obj}: {detail or 'not allowed'}")
            if done:
                modeladmin.message_user(request, f"{verb}: {done} record(s).", messages.SUCCESS)
            for line in failed:
                modeladmin.message_user(request, f"Skipped {line}", messages.ERROR)
            return None
    else:
        form = form_class()
    context = {
        **modeladmin.admin_site.each_context(request),
        "title": title,
        "intro": intro,
        "form": form,
        "objects": objects,
        "opts": modeladmin.model._meta,
        "action_name": request.POST.get("action"),
        "selected": request.POST.getlist("_selected_action"),
        "verb": verb,
    }
    return TemplateResponse(request, "admin/zuuvi/confirm_action.html", context)
