from decimal import Decimal, InvalidOperation

from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from customers.decorators import customer_portal_required, portal_customer_addresses_queryset


def select_customer_address(request, customer_address):
    address = customer_address.address
    request.session["delivery_location"] = {
        "latitude": str(address.latitude),
        "longitude": str(address.longitude),
        "label": str(address)[:255],
        "address_id": customer_address.pk,
        "address_type": customer_address.get_label_display(),
    }


@require_POST
@customer_portal_required
def select_saved_address_view(request, pk):
    address = get_object_or_404(
        portal_customer_addresses_queryset(request.user), pk=pk, is_active=True
    )
    select_customer_address(request, address)
    if _is_ajax(request):
        return JsonResponse({"ok": True})
    return redirect(_safe_next(request))


def _safe_next(request, fallback="/"):
    next_url = request.POST.get("next") or request.GET.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        url=next_url,
        allowed_hosts={request.get_host()},
        require_https=request.is_secure(),
    ):
        return next_url
    return fallback


def _is_ajax(request):
    return request.headers.get("x-requested-with") == "XMLHttpRequest"


@require_POST
def set_delivery_location_view(request):
    """
    Store the shopper's chosen delivery point in the session.

    Only captures where the shopper wants delivery. Matching it to a
    serviceable store or delivery radius is left for the backend
    integration that will apply real geofencing rules.
    """
    try:
        latitude = Decimal(request.POST.get("latitude", ""))
        longitude = Decimal(request.POST.get("longitude", ""))
    except (InvalidOperation, TypeError):
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": "Invalid coordinates."}, status=400)
        return redirect(_safe_next(request))

    if (
        not latitude.is_finite()
        or not longitude.is_finite()
        or not Decimal("-90") <= latitude <= Decimal("90")
        or not Decimal("-180") <= longitude <= Decimal("180")
    ):
        if _is_ajax(request):
            return JsonResponse({"ok": False, "error": "Coordinates out of range."}, status=400)
        return redirect(_safe_next(request))

    label = (request.POST.get("label") or "").strip()[:255]
    request.session["delivery_location"] = {
        "latitude": str(latitude),
        "longitude": str(longitude),
        "label": label or "Selected location",
    }

    if _is_ajax(request):
        return JsonResponse(
            {"ok": True, "label": request.session["delivery_location"]["label"]}
        )
    return redirect(_safe_next(request))


@require_POST
def clear_delivery_location_view(request):
    request.session.pop("delivery_location", None)
    if _is_ajax(request):
        return JsonResponse({"ok": True})
    return redirect(_safe_next(request))
