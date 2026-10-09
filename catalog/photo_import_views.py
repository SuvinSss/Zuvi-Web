import hashlib
import json
import uuid
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.db import transaction
from django.http import JsonResponse, FileResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_POST, require_GET
from django.urls import reverse

from stores.models import Store, StoreStatus
from .decorators import catalog_permission_required, user_has_catalog_permission
from .models import (
    PhotoImportBatch,
    PhotoImportItem,
    PhotoImportImage,
    ProductCategory,
    Brand,
    ProductUnit,
)
from .photo_import import import_item
from .validators import validate_product_image
from config.storage_errors import STORAGE_ERRORS


def batches(user):
    qs = PhotoImportBatch.objects.all()
    return qs if user.is_superuser else qs.filter(created_by=user)


def payload(request):
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        raise ValidationError("Invalid JSON payload.")
    if not isinstance(data, dict):
        raise ValidationError("Expected an object.")
    return data


def item_json(item):
    return {
        "id": item.pk,
        "source_key": item.source_key,
        "source_hash": item.source_hash,
        "details": item.details,
        "product_id": item.product_id,
        "imported_at": item.imported_at.isoformat() if item.imported_at else None,
        "photos": [
            {
                "id": p.pk,
                "url": reverse(
                    "catalog:photo_import_photo", args=[item.batch_id, item.pk, p.pk]
                ),
                "name": p.original_name,
                "sha256": p.sha256,
                "selected": p.selected,
            }
            for p in item.photos.all()
        ],
    }


def errors(exc):
    return JsonResponse(
        {"error": exc.message_dict if hasattr(exc, "message_dict") else exc.messages},
        status=400,
    )


@catalog_permission_required("catalog.add_product")
def workspace(request):
    return render(
        request,
        "management/products/photo_import.html",
        {
            "batches": batches(request.user).order_by("-pk")[:50],
            "stores": Store.objects.filter(is_active=True, status=StoreStatus.ACTIVE),
            "categories": ProductCategory.objects.filter(is_active=True),
            "brands": Brand.objects.filter(is_active=True),
            "units": ProductUnit.choices,
            "can_publish": user_has_catalog_permission(
                request.user, "catalog.approve_product"
            ),
            "can_price": user_has_catalog_permission(
                request.user, "catalog.manage_product_pricing"
            ),
        },
    )


@catalog_permission_required("catalog.add_product")
@require_POST
def create_batch(request):
    try:
        data = payload(request)
        name = str(data.get("name", "Photo import")).strip()[:120]
        batch = PhotoImportBatch.objects.create(
            name=name or "Photo import", created_by=request.user
        )
        return JsonResponse({"id": batch.pk, "name": batch.name})
    except ValidationError as exc:
        return errors(exc)


@catalog_permission_required("catalog.add_product")
def batch_detail(request, pk):
    batch = get_object_or_404(batches(request.user), pk=pk)
    if request.method == "GET":
        return JsonResponse(
            {
                "id": batch.pk,
                "name": batch.name,
                "store_id": batch.store_id,
                "items": [item_json(i) for i in batch.items.prefetch_related("photos")],
            }
        )
    if request.method != "POST":
        return JsonResponse({"error": "POST required."}, status=405)
    try:
        data = payload(request)
        with transaction.atomic():
            batch = PhotoImportBatch.objects.select_for_update().get(pk=batch.pk)
            store = get_object_or_404(
                Store,
                pk=data.get("store_id"),
                status=StoreStatus.ACTIVE,
                is_active=True,
            )
            if (
                batch.items.filter(product__isnull=False).exists()
                and batch.store_id != store.pk
            ):
                raise ValidationError(
                    "An imported batch cannot be moved to another Store."
                )
            batch.store = store
            batch.save(update_fields=["store"])
        return JsonResponse({"store_id": batch.store_id})
    except (ValidationError, ValueError, TypeError) as exc:
        return errors(
            exc
            if isinstance(exc, ValidationError)
            else ValidationError("Select a valid Store.")
        )


@catalog_permission_required("catalog.add_product")
@require_POST
def upsert_item(request, pk):
    batch = get_object_or_404(batches(request.user), pk=pk)
    try:
        data = payload(request)
        key = str(data.get("source_key", "")).strip()
        digest = str(data.get("source_hash", ""))
        if (
            not key
            or len(key) > 200
            or len(digest) != 64
            or any(c not in "0123456789abcdef" for c in digest)
        ):
            raise ValidationError(
                "Provide a product group and a valid source fingerprint."
            )
        with transaction.atomic():
            PhotoImportBatch.objects.select_for_update().get(pk=batch.pk)
            item, created = PhotoImportItem.objects.get_or_create(
                batch=batch, source_key=key, defaults={"source_hash": digest}
            )
            if item.source_hash != digest:
                raise ValidationError(
                    "These files differ from the saved group. Start a new batch for changed source photos."
                )
        return JsonResponse(item_json(item))
    except ValidationError as exc:
        return errors(exc)


@catalog_permission_required("catalog.add_product")
@require_POST
def item_action(request, pk, item_id):
    batch = get_object_or_404(batches(request.user), pk=pk)
    item = get_object_or_404(PhotoImportItem, batch=batch, pk=item_id)
    saved_file = None
    try:
        action = (
            request.POST.get("action")
            if request.content_type.startswith("multipart/")
            else payload(request).get("action")
        )
        if action == "upload":
            with transaction.atomic():
                item = PhotoImportItem.objects.select_for_update().get(pk=item.pk)
                if item.product_id:
                    raise ValidationError(
                        "Imported products must be edited in the catalogue."
                    )
                f = request.FILES.get("image")
                if not f:
                    raise ValidationError("Select an image.")
                validate_product_image(f)
                digest = hashlib.sha256(f.read()).hexdigest()
                f.seek(0)
                # A resumed folder must not copy photos back after a variant split.
                if not PhotoImportImage.objects.filter(
                    item__batch=batch, sha256=digest
                ).exists():
                    if item.photos.count() >= 30:
                        raise ValidationError(
                            "A preparation group supports up to 30 photos. Split larger folders before upload."
                        )
                    original = PurePosixPath(f.name).name[:255]
                    f.name = uuid.uuid4().hex + PurePosixPath(f.name).suffix.lower()
                    photo = PhotoImportImage(
                        item=item,
                        image=f,
                        sha256=digest,
                        original_name=original,
                        selected=item.photos.filter(selected=True).count() < 5,
                    )
                    photo.full_clean()
                    photo.save()
                    saved_file = photo.image
            saved_file = None
        else:
            data = payload(request)
            if action in ("save", "remove_photo", "split"):
                with transaction.atomic():
                    item = PhotoImportItem.objects.select_for_update().get(pk=item.pk)
                    if item.product_id:
                        raise ValidationError(
                            "Imported products must be edited in the catalogue."
                        )
                    if action == "save":
                        details = data.get("details", {})
                        if (
                            not isinstance(details, dict)
                            or len(json.dumps(details)) > 40000
                        ):
                            raise ValidationError(
                                "Product details are too large or invalid."
                            )
                        # Drafts may be incomplete; import validates every field again.
                        allowed = {
                            "name",
                            "description",
                            "category",
                            "brand",
                            "unit",
                            "unit_value",
                            "store_price",
                            "pricing_policy",
                            "stock",
                            "identity_verified",
                            "offers_verified",
                            "offers",
                            "notes",
                            "ocr_text",
                        }
                        item.details = {
                            k: v for k, v in details.items() if k in allowed
                        }
                        item.save(update_fields=["details", "updated_at"])
                        selected = data.get("selected_photo_ids")
                        if selected is not None:
                            if (
                                not isinstance(selected, list)
                                or len(selected) > 30
                                or any(not isinstance(p, int) for p in selected)
                                or item.photos.filter(pk__in=selected).count()
                                != len(set(selected))
                            ):
                                raise ValidationError("Invalid photo selection.")
                            item.photos.update(selected=False)
                            item.photos.filter(pk__in=selected).update(selected=True)
                    elif action == "split":
                        key = str(data.get("source_key", "")).strip()
                        selected = data.get("photo_ids", [])
                        if (
                            not key
                            or len(key) > 200
                            or not isinstance(selected, list)
                            or any(not isinstance(p, int) for p in selected)
                        ):
                            raise ValidationError(
                                "Enter a new group name and select photos to move."
                            )
                        photos = list(item.photos.filter(pk__in=selected))
                        if (
                            not photos
                            or len(photos) != len(set(selected))
                            or batch.items.filter(source_key=key).exists()
                        ):
                            raise ValidationError(
                                "Choose photos from this group and an unused group name."
                            )
                        digest = hashlib.sha256(
                            "".join(sorted(p.sha256 for p in photos)).encode()
                        ).hexdigest()
                        new = PhotoImportItem.objects.create(
                            batch=batch, source_key=key, source_hash=digest
                        )
                        for index, photo in enumerate(photos):
                            photo.item = new
                            photo.selected = index < 5
                            photo.save(update_fields=["item", "selected"])
                        item.details = {
                            **item.details,
                            "identity_verified": False,
                            "offers_verified": False,
                        }
                        item.save(update_fields=["details", "updated_at"])
                    else:
                        photo = get_object_or_404(item.photos, pk=data.get("photo_id"))
                        storage, name = photo.image.storage, photo.image.name
                        photo.delete()
                        transaction.on_commit(lambda: storage.delete(name))
            elif action in ("dry_run", "import"):
                result = import_item(
                    item_id=item.pk,
                    actor=request.user,
                    publish=data.get("publish") is True,
                    dry_run=action == "dry_run",
                    request=request,
                )
                return JsonResponse(result)
            else:
                raise ValidationError("Unknown import action.")
        return JsonResponse(item_json(item))
    except STORAGE_ERRORS:
        return JsonResponse(
            {
                "error": "Image storage is unavailable. Your saved progress is safe; retry this item."
            },
            status=503,
        )
    except ValidationError as exc:
        if saved_file:
            saved_file.storage.delete(saved_file.name)
        return errors(exc)


@catalog_permission_required("catalog.add_product")
@require_GET
def photo_content(request, pk, item_id, photo_id):
    batch = get_object_or_404(batches(request.user), pk=pk)
    photo = get_object_or_404(
        PhotoImportImage, item__batch=batch, item_id=item_id, pk=photo_id
    )
    response = FileResponse(
        photo.image.open("rb"),
        content_type="image/"
        + (
            "jpeg"
            if photo.image.name.lower().endswith((".jpg", ".jpeg"))
            else PurePosixPath(photo.image.name).suffix[1:]
        ),
    )
    response["Cache-Control"] = "private, no-store"
    return response


@catalog_permission_required("catalog.add_product")
@require_POST
def retailer_offer(request):
    from .retailer_prices import fetch_offer

    try:
        return JsonResponse(fetch_offer(payload(request).get("url", "")))
    except ValidationError as exc:
        return errors(exc)
