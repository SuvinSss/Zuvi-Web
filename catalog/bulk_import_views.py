from django.core.exceptions import PermissionDenied, ValidationError
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.http import require_POST

from config.storage_errors import STORAGE_ERRORS
from stores.models import Store, StoreStatus
from .bulk_import import import_row
from .decorators import catalog_permission_required, user_has_catalog_permission

DEFAULT_STORE_NAME = "Zuuvi Grocery"


@catalog_permission_required("catalog.add_product")
def workspace(request):
    stores = Store.objects.filter(is_active=True, status=StoreStatus.ACTIVE).order_by("name")
    default = next((s.pk for s in stores if s.name.lower() == DEFAULT_STORE_NAME.lower()), None)
    return render(
        request,
        "management/products/bulk_import.html",
        {
            "stores": stores,
            "default_store": default,
            "can_add_category": user_has_catalog_permission(
                request.user, "catalog.add_productcategory"
            ),
        },
    )


@catalog_permission_required("catalog.add_product")
@require_POST
def import_item(request):
    try:
        result = import_row(
            store_id=request.POST.get("store"),
            sl_no=request.POST.get("sl_no", ""),
            name=request.POST.get("name", ""),
            category_name=request.POST.get("category", ""),
            image=request.FILES.get("image"),
            actor=request.user,
            request=request,
        )
    except ValidationError as exc:
        messages = exc.message_dict if hasattr(exc, "message_dict") else exc.messages
        return JsonResponse({"error": messages}, status=400)
    except PermissionDenied as exc:
        return JsonResponse({"error": str(exc)}, status=403)
    except STORAGE_ERRORS:
        return JsonResponse(
            {"error": "Image storage is unavailable. Retry this row."}, status=503
        )
    return JsonResponse(result)
