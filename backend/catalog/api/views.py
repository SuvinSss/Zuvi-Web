"""Management product API (``/api/v1/products/``).

Thin layer: authentication, permissions and (de)serialisation live here, while
every write goes through ``catalog.services`` / ``catalog.product_import`` so the
rules in AGENTS.md (pricing, status, inventory, audit) stay in one place.
"""
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Exists, OuterRef, Q
from django.http import Http404, HttpResponse
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from catalog.decorators import user_has_catalog_permission
from catalog.models import Brand, Product, ProductCategory, ProductImage, ProductImportBatch, ProductStatus, ProductUnit, Tag
from catalog.product_import import reports, service as import_service
from catalog.product_import.template import build_template
from catalog.services import (
    add_product_image, create_product, delete_product_image, set_primary_product_image, update_product,
)
from catalog.validators import MAX_IMAGES_PER_PRODUCT
from config.storage_errors import STORAGE_ERRORS, STORAGE_ERROR_MESSAGE
from stores.models import Store

from .pagination import StandardPagination
from .permissions import CatalogManagementPermission
from .serializers import (
    ProductDetailSerializer, ProductImageSerializer, ProductListSerializer, ProductWriteSerializer, to_drf_error,
)

logger = logging.getLogger(__name__)

ORDERING = {"name", "sku", "store_price", "created_at", "updated_at", "status", "product_code"}


def products_queryset():
    return Product.objects.select_related("store", "category", "brand").prefetch_related("tags", "images")


def _storage_unavailable():
    logger.exception("Image storage operation failed")
    return Response({"detail": STORAGE_ERROR_MESSAGE}, status=status.HTTP_503_SERVICE_UNAVAILABLE)


def _get_product(pk):
    try:
        return products_queryset().get(pk=pk)
    except Product.DoesNotExist:
        raise Http404 from None


def _flag(value, default=False):
    if value is None:
        return default
    return str(value).lower() in {"1", "true", "on", "yes"}


class ProductListCreateView(APIView):
    permission_classes = [CatalogManagementPermission]
    parser_classes = [JSONParser]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, description="Search name, SKU or product code"),
            OpenApiParameter("status", str), OpenApiParameter("category", int), OpenApiParameter("store", int),
            OpenApiParameter("brand", int), OpenApiParameter("is_active", bool),
            OpenApiParameter("has_image", bool),
            OpenApiParameter("ordering", str, description="One of: " + ", ".join(sorted(ORDERING)) + " (prefix - for descending)"),
        ],
        responses=ProductListSerializer(many=True),
    )
    def get(self, request):
        queryset = products_queryset()
        params = request.query_params
        query = (params.get("q") or "").strip()[:100]
        if query:
            queryset = queryset.filter(Q(name__icontains=query) | Q(sku__icontains=query) | Q(product_code__icontains=query))
        for name, lookup in (("category", "category_id"), ("store", "store_id"), ("brand", "brand_id")):
            value = params.get(name)
            if value:
                queryset = queryset.filter(**{lookup: int(value)}) if value.isdigit() else queryset.none()
        if params.get("status") in ProductStatus.values:
            queryset = queryset.filter(status=params["status"])
        if params.get("is_active") in {"true", "false"}:
            queryset = queryset.filter(is_active=params["is_active"] == "true")
        if params.get("has_image") in {"true", "false"}:
            has = Exists(ProductImage.objects.filter(product=OuterRef("pk")).exclude(image=""))
            queryset = queryset.filter(has) if params["has_image"] == "true" else queryset.exclude(has)
        ordering = params.get("ordering", "-created_at")
        if ordering.lstrip("-") not in ORDERING:
            ordering = "-created_at"
        queryset = queryset.order_by(ordering, "-pk")
        paginator = StandardPagination()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return paginator.get_paginated_response(ProductListSerializer(page, many=True, context={"request": request}).data)

    @extend_schema(request=ProductWriteSerializer, responses={201: ProductDetailSerializer})
    def post(self, request):
        serializer = ProductWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        store, tags = data.pop("store"), data.pop("tags", [])
        as_draft = data.pop("save_as_draft", False)
        if data.get("brand") is None:
            data.pop("brand", None)
        if not user_has_catalog_permission(request.user, "catalog.change_product"):
            data.pop("is_featured", None)  # featured is a management privilege
        try:
            product = create_product(
                store=store, product_data=data, created_by=request.user, tag_ids=[t.pk for t in tags],
                initial_status=ProductStatus.DRAFT if as_draft else ProductStatus.PENDING, request=request,
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        return Response(ProductDetailSerializer(_get_product(product.pk)).data, status=status.HTTP_201_CREATED)


class ProductDetailView(APIView):
    permission_classes = [CatalogManagementPermission]
    parser_classes = [JSONParser]

    @extend_schema(responses=ProductDetailSerializer)
    def get(self, request, pk):
        return Response(ProductDetailSerializer(_get_product(pk)).data)

    @extend_schema(request=ProductWriteSerializer, responses=ProductDetailSerializer)
    def patch(self, request, pk):
        product = _get_product(pk)
        serializer = ProductWriteSerializer(product, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        data.pop("store", None)
        data.pop("save_as_draft", None)
        tags = data.pop("tags", None)
        try:
            update_product(
                product=product, product_data=data, updated_by=request.user,
                tag_ids=None if tags is None else [t.pk for t in tags], request=request,
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        return Response(ProductDetailSerializer(_get_product(pk)).data)


class ProductMetaView(APIView):
    """Reference data for forms and filters, in one cacheable-sized response."""

    permission_classes = [CatalogManagementPermission]

    @extend_schema(responses=dict)
    def get(self, request):
        return Response({
            "stores": list(Store.objects.order_by("name").values("id", "name", "store_code")),
            "categories": [{"id": c.pk, "name": str(c), "slug": c.slug}
                           for c in ProductCategory.objects.filter(is_active=True).select_related("parent__parent")],
            "brands": list(Brand.objects.filter(is_active=True).values("id", "name")),
            "tags": list(Tag.objects.filter(is_active=True).values("id", "name")),
            "units": [{"value": v, "label": l} for v, l in ProductUnit.choices],
            "statuses": [{"value": v, "label": l} for v, l in ProductStatus.choices],
            "max_images": MAX_IMAGES_PER_PRODUCT,
            "can": {perm: user_has_catalog_permission(request.user, f"catalog.{perm}_product")
                    for perm in ("view", "add", "change")},
        })


class ProductImagesView(APIView):
    permission_classes = [CatalogManagementPermission]
    parser_classes = [MultiPartParser, FormParser]
    required_permission = "catalog.change_product"

    @extend_schema(request={"multipart/form-data": {"type": "object", "properties": {
        "image": {"type": "string", "format": "binary"}, "alt_text": {"type": "string"},
        "is_primary": {"type": "boolean"}}, "required": ["image"]}}, responses={201: ProductImageSerializer})
    def post(self, request, pk):
        product = _get_product(pk)
        upload = request.FILES.get("image")
        if upload is None:
            return Response({"image": ["Choose an image file."]}, status=400)
        try:
            image = add_product_image(
                product=product, image=upload, alt_text=(request.data.get("alt_text") or "")[:200],
                is_primary=_flag(request.data.get("is_primary")), changed_by=request.user, request=request,
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        except STORAGE_ERRORS:
            return _storage_unavailable()
        return Response(ProductImageSerializer(image).data, status=status.HTTP_201_CREATED)


class ProductImageDetailView(APIView):
    permission_classes = [CatalogManagementPermission]
    required_permission = "catalog.change_product"

    def delete(self, request, pk, image_id):
        product = _get_product(pk)
        try:
            delete_product_image(product=product, image_id=image_id, changed_by=request.user, request=request)
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        except STORAGE_ERRORS:
            return _storage_unavailable()
        return Response(status=status.HTTP_204_NO_CONTENT)


class ProductImagePrimaryView(APIView):
    permission_classes = [CatalogManagementPermission]
    required_permission = "catalog.change_product"

    @extend_schema(request=None, responses=ProductImageSerializer)
    def post(self, request, pk, image_id):
        product = _get_product(pk)
        try:
            image = set_primary_product_image(product=product, image_id=image_id)
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        return Response(ProductImageSerializer(image).data)


class ImageSuggestionsView(APIView):
    """Brand-aware image suggestions.

    Deliberately inert until a licensed source is configured: scraping retailer
    sites or hot-linking manufacturer images is not permitted, and brand name
    alone cannot identify a model. Manual upload always works.
    """

    permission_classes = [CatalogManagementPermission]
    required_permission = "catalog.change_product"

    @extend_schema(responses=dict)
    def get(self, request, pk):
        _get_product(pk)
        return Response({
            "available": False, "candidates": [],
            "reason": "No licensed product-image source is configured. Upload an image instead.",
        })


# ----- Bulk import -----------------------------------------------------------

def _batch_for(request, batch_id):
    try:
        batch = ProductImportBatch.objects.get(pk=batch_id)
    except (ProductImportBatch.DoesNotExist, ValueError, DjangoValidationError):
        raise Http404 from None
    if batch.created_by_id != request.user.pk and not request.user.is_superuser:
        raise Http404  # do not reveal other users' imports
    return batch


def batch_payload(batch, analysis=None):
    data = {
        "id": str(batch.pk), "status": batch.status, "mode": batch.mode, "all_or_nothing": batch.all_or_nothing,
        "initial_status": batch.initial_status, "allow_image_urls": batch.allow_image_urls,
        "source_name": batch.source_name, "created_at": batch.created_at, "committed_at": batch.committed_at,
        "counts": {"total": batch.total_rows, "valid": batch.valid_rows, "invalid": batch.invalid_rows,
                   "duplicates": batch.duplicate_rows},
        "summary": batch.summary, "errors": batch.errors,
        "already_imported": import_service.already_imported(batch) if batch.status == "PREVIEWED" else False,
    }
    if analysis is not None:
        data["counts"].update(analysis.counts)
        data["rows"] = [row.public() for row in analysis.rows]
        data["ignored_columns"] = analysis.ignored_columns
    return data


class ImportTemplateView(APIView):
    permission_classes = [CatalogManagementPermission]
    required_permission = "catalog.add_product"

    @extend_schema(responses={200: bytes})
    def get(self, request):
        response = HttpResponse(
            build_template(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = 'attachment; filename="zuvi-product-import-template.xlsx"'
        return response


class ImportPreviewView(APIView):
    permission_classes = [CatalogManagementPermission]
    required_permission = "catalog.add_product"
    parser_classes = [MultiPartParser, FormParser]
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "import"

    @extend_schema(request={"multipart/form-data": {"type": "object", "properties": {
        "file": {"type": "string", "format": "binary"}, "images_zip": {"type": "string", "format": "binary"},
        "mode": {"type": "string", "enum": ["create", "skip", "update"]}, "all_or_nothing": {"type": "boolean"},
        "initial_status": {"type": "string", "enum": ["DRAFT", "PENDING"]},
        "allow_image_urls": {"type": "boolean"}}, "required": ["file"]}}, responses=dict)
    def post(self, request):
        workbook = request.FILES.get("file")
        if workbook is None:
            return Response({"file": ["Choose an .xlsx or .csv file."]}, status=400)
        mode = request.data.get("mode") or ProductImportBatch.Mode.CREATE
        allow_urls = _flag(request.data.get("allow_image_urls"))
        # Updating existing products and fetching URLs are change-level actions.
        if (mode == ProductImportBatch.Mode.UPDATE or allow_urls) and not user_has_catalog_permission(
            request.user, "catalog.change_product"
        ):
            raise PermissionDenied("You need permission to change products for this import option.")
        try:
            batch, analysis = import_service.create_preview(
                user=request.user, workbook=workbook, images_zip=request.FILES.get("images_zip"), mode=mode,
                all_or_nothing=_flag(request.data.get("all_or_nothing"), True),
                initial_status=request.data.get("initial_status") or ProductStatus.DRAFT,
                allow_image_urls=allow_urls,
            )
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        except STORAGE_ERRORS:
            return _storage_unavailable()
        return Response(batch_payload(batch, analysis), status=status.HTTP_201_CREATED)


class ImportDetailView(APIView):
    permission_classes = [CatalogManagementPermission]
    required_permission = "catalog.add_product"

    @extend_schema(responses=dict)
    def get(self, request, batch_id):
        return Response(batch_payload(_batch_for(request, batch_id)))


class ImportCommitView(APIView):
    permission_classes = [CatalogManagementPermission]
    required_permission = "catalog.add_product"
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "import"

    @extend_schema(request=None, responses=dict)
    def post(self, request, batch_id):
        batch = _batch_for(request, batch_id)
        if batch.mode == ProductImportBatch.Mode.UPDATE or batch.allow_image_urls:
            if not user_has_catalog_permission(request.user, "catalog.change_product"):
                raise PermissionDenied("You need permission to change products for this import option.")
        try:
            batch = import_service.commit(batch.pk, user=request.user, request=request)
        except import_service.ImportBlocked as exc:
            return Response({"detail": str(exc), "code": exc.code,
                             "import": batch_payload(ProductImportBatch.objects.get(pk=batch.pk))}, status=status.HTTP_409_CONFLICT)
        except DjangoValidationError as exc:
            raise to_drf_error(exc) from exc
        except STORAGE_ERRORS:
            return _storage_unavailable()
        return Response(batch_payload(batch))


class ImportErrorReportView(APIView):
    permission_classes = [CatalogManagementPermission]
    required_permission = "catalog.add_product"

    @extend_schema(parameters=[OpenApiParameter("type", str, enum=["xlsx", "csv"])], responses={200: bytes})
    def get(self, request, batch_id):
        batch = _batch_for(request, batch_id)
        if request.query_params.get("type") == "csv":
            return reports.csv_response(batch)
        return reports.xlsx_response(batch)
