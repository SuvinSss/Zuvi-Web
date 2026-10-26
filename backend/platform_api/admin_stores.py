"""Management store APIs: list/filter/export, create (wizard), detail/edit, staff, documents, verification."""
import csv
from decimal import Decimal
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import Count, Q
from django.http import StreamingHttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import serializers, status as http
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role, User
from catalog.models import Product, ProductStatus
from core.pagination import StandardPagination
from core.permissions import IsManagement
from orders.models import StoreOrder
from reviews.models import RatingAggregate, TargetType
from stores import management as svc
from stores.decorators import user_has_store_permission
from stores.models import Store, StoreCategory, StoreDocument, StoreStatus, StoreType, StoreUser, VerificationStatus
from logistics.services import store_location_problems
from stores.status import allowed_next_statuses

from .analytics import _safe

MAX_DOC_BYTES = 8 * 1024 * 1024
DOC_EXTENSIONS = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
SORTS = {"name", "-name", "created_at", "-created_at", "status", "-status", "city", "-city"}


def _need(user, perm):
    if not user_has_store_permission(user, perm):
        raise PermissionDenied("You do not have permission to perform this action.")


def _errors(exc):
    return Response(exc.message_dict if hasattr(exc, "error_dict") else {"detail": exc.messages}, status=http.HTTP_400_BAD_REQUEST)


def store_row(s, rating=None):
    return {
        "id": s.pk, "store_code": s.store_code, "name": s.name, "slug": s.slug, "status": s.status, "is_active": s.is_active,
        "store_type": s.store_type, "city": s.address.city, "state": s.address.state,
        "category": s.category.name if s.category_id else None, "category_id": s.category_id,
        "verification_status": s.verification_status, "ordering_enabled": s.ordering_enabled,
        "missing_requirements": s.missing_requirements, "contact_phone": s.contact_phone, "created_at": s.created_at,
        "image": s.image.url if s.image else None,
        "rating": {"average": float(rating.average), "count": rating.count} if rating else {"average": 0.0, "count": 0},
    }


def filtered_stores(params):
    qs = Store.objects.select_related("address", "category")
    if params.get("status") in StoreStatus.values:
        qs = qs.filter(status=params["status"])
    if params.get("store_type") in StoreType.values:
        qs = qs.filter(store_type=params["store_type"])
    if params.get("verification") in VerificationStatus.values:
        qs = qs.filter(verification_status=params["verification"])
    if (params.get("category") or "").isdigit():
        qs = qs.filter(category_id=int(params["category"]))
    if params.get("city"):
        qs = qs.filter(address__city__iexact=params["city"].strip())
    if params.get("ordering_enabled") in {"true", "false"}:
        qs = qs.filter(ordering_enabled=params["ordering_enabled"] == "true")
    q = (params.get("q") or "").strip()[:100]
    if q:
        qs = qs.filter(Q(name__icontains=q) | Q(store_code__icontains=q) | Q(contact_phone__icontains=q) | Q(address__city__icontains=q))
    ordering = params.get("ordering", "name")
    ordering = ordering if ordering in SORTS else "name"
    ordering = ordering.replace("city", "address__city")
    return qs.order_by(ordering, "pk")


class AddressIn(serializers.Serializer):
    line1 = serializers.CharField(max_length=255, allow_blank=True, required=False)
    line2 = serializers.CharField(max_length=255, allow_blank=True, required=False)
    landmark = serializers.CharField(max_length=255, allow_blank=True, required=False)
    city = serializers.CharField(max_length=100, allow_blank=True, required=False)
    district = serializers.CharField(max_length=100, allow_blank=True, required=False)
    state = serializers.CharField(max_length=100, allow_blank=True, required=False)
    postal_code = serializers.CharField(max_length=20, allow_blank=True, required=False)
    country = serializers.CharField(max_length=100, required=False)
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90, required=False)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180, required=False)
    # Not stored on the address: records that a manager checked the pin (see Store.location_confirmed_at).
    confirm_location = serializers.BooleanField(required=False)


class OwnerIn(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    email = serializers.EmailField()
    first_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    last_name = serializers.CharField(max_length=150, required=False, allow_blank=True)
    phone_number = serializers.CharField(max_length=20, required=False, allow_null=True, allow_blank=True)
    password = serializers.CharField(write_only=True, required=False, allow_blank=True, style={"input_type": "password"})
    designation = serializers.CharField(max_length=100, required=False, allow_blank=True)


class StoreIn(serializers.Serializer):
    """Whitelist of client-writable fields. Status, approval, verification and gates are never accepted."""
    name = serializers.CharField(max_length=200)
    store_type = serializers.ChoiceField(choices=StoreType.choices)
    category = serializers.PrimaryKeyRelatedField(queryset=StoreCategory.objects.filter(is_active=True))
    contact_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    alternative_phone = serializers.CharField(max_length=20, required=False, allow_blank=True)
    email = serializers.EmailField(required=False, allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True, max_length=5000)
    business_name = serializers.CharField(max_length=200, required=False, allow_blank=True)
    gstin = serializers.CharField(max_length=15, required=False, allow_blank=True)
    commission_percentage = serializers.DecimalField(max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False)
    accepts_orders = serializers.BooleanField(required=False)
    offers_delivery = serializers.BooleanField(required=False)
    offers_pickup = serializers.BooleanField(required=False)
    min_order_amount = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0, required=False, allow_null=True)
    service_radius_km = serializers.DecimalField(max_digits=6, decimal_places=2, min_value=0, required=False, allow_null=True)
    opening_hours = serializers.JSONField(required=False)
    closures = serializers.JSONField(required=False)
    address = AddressIn(required=False)
    owner = OwnerIn(required=False)
    existing_owner = serializers.IntegerField(required=False, min_value=1)
    save_draft = serializers.BooleanField(required=False, default=False)


def _split(validated):
    data = dict(validated)
    return data, data.pop("address", None), data.pop("owner", None), data.pop("save_draft", False), data.pop("existing_owner", None)


class AdminStoresView(APIView):
    permission_classes = [IsManagement]
    parser_classes = [JSONParser]

    def get(self, request):
        qs = filtered_stores(request.query_params)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request, view=self)
        ratings = {a.target_id: a for a in RatingAggregate.objects.filter(target_type=TargetType.STORE, target_id__in=[s.pk for s in page])}
        return paginator.get_paginated_response([store_row(s, ratings.get(s.pk)) for s in page])

    def post(self, request):
        _need(request.user, "stores.add_store")
        ser = StoreIn(data=request.data)
        ser.is_valid(raise_exception=True)
        data, address, owner, draft, existing = _split(ser.validated_data)
        address = dict(address or {})
        try:
            # (0, 0) means "location not set yet": allowed for drafts, never counted as a real location.
            address.setdefault("latitude", Decimal("0"))
            address.setdefault("longitude", Decimal("0"))
            store, outcome = svc.create_managed_store(actor=request.user, data=data, address=address, owner=owner, existing_owner=existing, save_draft=draft, request=request._request)
        except DjangoValidationError as exc:
            return _errors(exc)
        return Response({"id": store.pk, "store_code": store.store_code, **outcome}, status=http.HTTP_201_CREATED)


class AdminStoreDetailView(APIView):
    permission_classes = [IsManagement]
    parser_classes = [JSONParser]

    def get(self, request, pk):
        s = get_object_or_404(Store.objects.select_related("address", "category", "approved_by", "verified_by", "created_by"), pk=pk)
        products = dict(Product.objects.filter(store=s).values_list("status").annotate(n=Count("id")))
        orders = StoreOrder.objects.filter(store=s)
        a = s.address
        return Response({
            **store_row(s, RatingAggregate.objects.filter(target_type=TargetType.STORE, target_id=s.pk).first()),
            "description": s.description, "business_name": s.business_name, "gstin": s.gstin, "email": s.email,
            "alternative_phone": s.alternative_phone, "banner": s.banner.url if s.banner else None,
            "commission_percentage": str(s.commission_percentage), "accepts_orders": s.accepts_orders,
            "offers_delivery": s.offers_delivery, "offers_pickup": s.offers_pickup,
            "min_order_amount": str(s.min_order_amount) if s.min_order_amount is not None else None,
            "service_radius_km": str(s.service_radius_km) if s.service_radius_km is not None else None,
            "opening_hours": s.opening_hours, "closures": s.closures, "creation_source": s.creation_source,
            "approved_by": s.approved_by.get_username() if s.approved_by_id else None, "approved_at": s.approved_at,
            "verified_by": s.verified_by.get_username() if s.verified_by_id else None, "verified_at": s.verified_at,
            "created_by": s.created_by.get_username() if s.created_by_id else None,
            "address": {k: (str(getattr(a, k)) if k in ("latitude", "longitude") else getattr(a, k)) for k in svc.ADDRESS_FIELDS},
            "operational_gaps": svc.operational_gaps(s),
            "location": {
                "confirmed": s.location_confirmed_at is not None,
                "confirmed_at": s.location_confirmed_at,
                "confirmed_by": s.location_confirmed_by.get_username() if s.location_confirmed_by_id else None,
                "problems": store_location_problems(s),
            },
            "next_statuses": sorted(allowed_next_statuses(s.status)),
            "counts": {"products": sum(products.values()), "products_by_status": products,
                       "orders": orders.count(),
                       "staff": s.store_users.count(), "documents": s.documents.count()},
            "history": [{"old": h.old_status, "new": h.new_status, "reason": h.reason, "by": h.changed_by.get_username(), "at": h.created_at}
                        for h in s.status_history.select_related("changed_by")[:30]],
        })

    def patch(self, request, pk):
        _need(request.user, "stores.change_store")
        store = get_object_or_404(Store, pk=pk)
        ser = StoreIn(data=request.data, partial=True)
        ser.is_valid(raise_exception=True)
        data, address, owner, _draft, _existing = _split(ser.validated_data)
        if owner:
            raise serializers.ValidationError({"owner": "Add staff from the Owner & Staff tab."})
        try:
            svc.update_managed_store(actor=request.user, store=store, data=data, address=address, request=request._request)
        except DjangoValidationError as exc:
            return _errors(exc)
        return self.get(request, pk)


class AdminStoreMetaView(APIView):
    permission_classes = [IsManagement]

    def get(self, request):
        return Response({
            "categories": [{"id": c.pk, "name": c.name} for c in StoreCategory.objects.filter(is_active=True)],
            "types": [{"value": v, "label": l} for v, l in StoreType.choices],
            "statuses": [{"value": v, "label": l} for v, l in StoreStatus.choices],
            "days": list(svc.DAYS),
            "can_add": user_has_store_permission(request.user, "stores.add_store"),
            "can_change": user_has_store_permission(request.user, "stores.change_store"),
            "can_approve": user_has_store_permission(request.user, "stores.approve_store"),
        })


class AdminStoreStaffView(APIView):
    permission_classes = [IsManagement]
    parser_classes = [JSONParser]

    def get(self, request, pk):
        store = get_object_or_404(Store, pk=pk)
        return Response([{"id": m.pk, "user_id": m.user_id, "username": m.user.get_username(), "name": m.user.get_full_name(), "email": m.user.email,
                          "is_primary": m.is_primary, "is_active": m.is_active, "designation": m.designation, "setup_pending": not m.user.has_usable_password(),
                          "can_manage_inventory": m.can_manage_inventory, "can_manage_orders": m.can_manage_orders}
                         for m in StoreUser.objects.filter(store=store).select_related("user")])

    def post(self, request, pk):
        _need(request.user, "stores.change_store")
        store = get_object_or_404(Store, pk=pk)
        ser = OwnerIn(data=request.data)
        ser.is_valid(raise_exception=True)
        primary = bool(request.data.get("is_primary"))
        try:
            m, u = svc.add_managed_staff(actor=request.user, store=store, user_data=dict(ser.validated_data), is_primary=primary, request=request._request)
        except DjangoValidationError as exc:
            return _errors(exc)
        return Response({"id": m.pk, "username": u.get_username(), "owner_setup": getattr(u, "setup_invite", None)}, status=http.HTTP_201_CREATED)


class AdminStoreInviteView(APIView):
    """Issue a fresh one-time setup link for a member who has not chosen a password."""
    permission_classes = [IsManagement]
    parser_classes = [JSONParser]

    def post(self, request, pk):
        _need(request.user, "stores.change_store")
        store = get_object_or_404(Store, pk=pk)
        try:
            setup = svc.resend_owner_invite(actor=request.user, store=store, user_id=int(request.data.get("user") or 0), request=request._request)
        except DjangoValidationError as exc:
            return _errors(exc)
        return Response({"owner_setup": setup})


class AdminOwnerCandidatesView(APIView):
    """Search existing Store User accounts that may be assigned as an owner."""
    permission_classes = [IsManagement]

    def get(self, request):
        _need(request.user, "stores.add_store")
        q = (request.query_params.get("q") or "").strip()[:100]
        if len(q) < 2:
            return Response([])
        users = User.objects.filter(role=Role.STORE_USER, is_active=True).filter(
            Q(username__icontains=q) | Q(email__icontains=q) | Q(first_name__icontains=q) | Q(last_name__icontains=q))[:10]
        return Response([{"id": u.pk, "username": u.get_username(), "name": u.get_full_name(), "email": u.email,
                          "stores": list(StoreUser.objects.filter(user=u).values_list("store__name", flat=True)[:3])} for u in users])


class AdminStoreDocumentsView(APIView):
    permission_classes = [IsManagement]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request, pk):
        store = get_object_or_404(Store, pk=pk)
        return Response([{"id": d.pk, "kind": d.kind, "title": d.title, "url": d.file.url, "uploaded_at": d.created_at,
                          "uploaded_by": d.uploaded_by.get_username() if d.uploaded_by_id else None} for d in store.documents.select_related("uploaded_by")])

    def post(self, request, pk):
        _need(request.user, "stores.change_store")
        store = get_object_or_404(Store, pk=pk)
        upload = request.FILES.get("file")
        kind = request.data.get("kind")
        if upload is None or kind not in StoreDocument.Kind.values:
            return Response({"detail": "Choose a document type and a file."}, status=400)
        if PurePosixPath(upload.name).suffix.lower() not in DOC_EXTENSIONS:
            return Response({"file": "Upload a PDF, JPG, PNG or WebP file."}, status=400)
        if upload.size > MAX_DOC_BYTES:
            return Response({"file": "Files must be 8 MB or smaller."}, status=400)
        head = upload.read(8)
        upload.seek(0)
        if not (head.startswith(b"%PDF") or head.startswith(b"\xff\xd8") or head.startswith(b"\x89PNG") or head[:4] == b"RIFF"):
            return Response({"file": "The file content does not match an allowed type."}, status=400)
        doc = StoreDocument.objects.create(store=store, kind=kind, title=str(request.data.get("title", ""))[:120], file=upload, uploaded_by=request.user)
        from stores.services import log_store_audit
        from accounts.models import AdminAuditLog
        log_store_audit(actor=request.user, action=AdminAuditLog.Action.STORE_UPDATED, request=request._request,
                        description=f"Uploaded {kind} document for '{store.store_code}'.", metadata={"store_id": store.pk, "document_id": doc.pk})
        return Response({"id": doc.pk}, status=http.HTTP_201_CREATED)


class AdminStoreImagesView(APIView):
    permission_classes = [IsManagement]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, pk):
        _need(request.user, "stores.change_store")
        store = get_object_or_404(Store, pk=pk)
        changed = []
        try:
            for field in ("image", "banner"):
                if field in request.FILES:
                    setattr(store, field, request.FILES[field])
                    changed.append(field)
            if not changed:
                return Response({"detail": "Choose a logo or banner image."}, status=400)
            store.full_clean(exclude=["slug", "store_code"])
        except DjangoValidationError as exc:
            return _errors(exc)
        store.save(update_fields=[*changed, "updated_at"])
        return Response({"image": store.image.url if store.image else None, "banner": store.banner.url if store.banner else None})


class VerifySerializer(serializers.Serializer):
    verification_status = serializers.ChoiceField(choices=[VerificationStatus.VERIFIED, VerificationStatus.REJECTED])


class AdminStoreVerifyView(APIView):
    permission_classes = [IsManagement]

    def post(self, request, pk):
        _need(request.user, "stores.approve_store")
        store = get_object_or_404(Store, pk=pk)
        ser = VerifySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        svc.set_verification(actor=request.user, store=store, status=ser.validated_data["verification_status"], request=request._request)
        return Response({"verification_status": ser.validated_data["verification_status"]})


class AdminStoresExportView(APIView):
    permission_classes = [IsManagement]

    def get(self, request):
        _need(request.user, "stores.view_store")
        qs = filtered_stores(request.query_params)[:20000]

        class Echo:
            def write(self, v):
                return v

        w = csv.writer(Echo())

        def rows():
            yield w.writerow(["Code", "Name", "Type", "Category", "City", "State", "Status", "Verification", "Ordering enabled", "Phone", "Created"])
            for s in qs.iterator(chunk_size=500):
                yield w.writerow([_safe(s.store_code), _safe(s.name), s.store_type, _safe(s.category.name), _safe(s.address.city), _safe(s.address.state),
                                  s.status, s.verification_status, s.ordering_enabled, _safe(s.contact_phone), s.created_at.date().isoformat()])

        resp = StreamingHttpResponse(rows(), content_type="text/csv")
        resp["Content-Disposition"] = 'attachment; filename="stores.csv"'
        return resp
