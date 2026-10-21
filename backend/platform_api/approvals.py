"""Approval Center and safe bulk actions.

Every bulk action is a preview/apply pair. Preview classifies each record as eligible or blocked (with the
reasons) and nothing changes. Apply re-checks every record against current data, one transaction per record,
and reports successful / skipped / failed separately. Selecting "everything that matches" is resolved on the
server from whitelisted filters and must be confirmed with the count the person saw.
"""
import logging

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import Q
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import ScopedRateThrottle

from accounts.models import Role
from catalog.decorators import user_has_catalog_permission
from catalog.models import Product, ProductImportBatch, ProductStatus
from catalog.services import record_product_status_change
from catalog.status import permission_for_transition as product_permission, validate_status_transition as validate_product
from core.audit import audit
from core.permissions import IsManagement
from deliveries import services as delivery_services
from deliveries.models import DeliveryPartner, PartnerStatus
from reviews import services as review_services
from reviews.models import Review, ReviewStatus
from stores import management as store_management
from stores.decorators import user_has_store_permission
from stores.models import Store, StoreStatus
from stores.services import record_status_change
from stores.status import permission_for_transition as store_permission, validate_status_transition as validate_store

logger = logging.getLogger(__name__)
MAX_BULK = 500
PREVIEW_LIST = 100


def _has(user, perm):
    return user.role == Role.SUPER_ADMIN or user.has_perm(perm)


def _messages(exc):
    if hasattr(exc, "message_dict"):
        return [m for msgs in exc.message_dict.values() for m in msgs]
    return list(exc.messages)


# ---- modules: each provides queryset(filters), label(obj), check(obj, action, user, reason), do(obj, action, user, reason, request)

class ProductModule:
    name = "products"
    ACTIONS = {"approve": ProductStatus.APPROVED, "reject": ProductStatus.REJECTED, "deactivate": ProductStatus.INACTIVE,
               "reactivate": ProductStatus.APPROVED, "resubmit": ProductStatus.PENDING, "set_pricing": None}
    NEEDS_REASON = {"reject"}
    FILTERS = ("status", "store", "category", "q")

    @staticmethod
    def queryset(f):
        qs = Product.objects.select_related("store", "category").order_by("pk")
        if f.get("status") in ProductStatus.values:
            qs = qs.filter(status=f["status"])
        for key in ("store", "category"):
            if str(f.get(key) or "").isdigit():
                qs = qs.filter(**{f"{key}_id": int(f[key])})
        if f.get("q"):
            qs = qs.filter(Q(name__icontains=f["q"][:100]) | Q(sku__icontains=f["q"][:100]))
        return qs

    @staticmethod
    def label(p):
        return f"{p.name} ({p.sku}) · {p.store.name}"

    @classmethod
    def check(cls, p, action, user, reason, params=None):
        if action == "set_pricing":
            return cls._check_pricing(p, user, params or {})
        target = cls.ACTIONS[action]
        problems = []
        if action == "reactivate" and p.status != ProductStatus.INACTIVE:
            return ["Only inactive products can be reactivated."]
        if action == "approve" and p.status == ProductStatus.INACTIVE:
            return ["Use Reactivate for inactive products."]
        try:
            validate_product(current_status=p.status, new_status=target, reason=reason, product=p)
        except DjangoValidationError as exc:
            problems += _messages(exc)
        perm = product_permission(p.status, target)
        if perm and not user_has_catalog_permission(user, perm):
            problems.append("You do not have permission for this change.")
        return problems

    @staticmethod
    def _pricing_args(params):
        return dict(margin_type=params.get("margin_type") or None, margin=params.get("margin") or None,
                    discount_type=params.get("discount_type") or "", discount_value=params.get("discount_value") or None)

    @classmethod
    def _check_pricing(cls, p, user, params):
        from django.conf import settings
        from catalog.pricing import calculate_prices
        if not user_has_catalog_permission(user, "catalog.manage_product_pricing"):
            return ["You do not have permission to set prices."]
        if not params.get("margin_type") or params.get("margin") in (None, ""):
            return ["Choose a margin type and enter a margin."]
        try:
            a = cls._pricing_args(params)
            _selling, final = calculate_prices(store_price=p.store_price, profit_margin_type=a["margin_type"], profit_margin=a["margin"],
                                               discount_type=a["discount_type"], discount_value=a["discount_value"])
        except (DjangoValidationError, ArithmeticError, ValueError) as exc:
            return _messages(exc) if isinstance(exc, DjangoValidationError) else ["Enter valid numbers."]
        if final < p.store_price and not getattr(settings, "PRICING_ALLOW_BELOW_COST", False):
            return ["The final price would be below the store price."]
        return []

    @classmethod
    def warnings(cls, p):
        return [f"Generated by import: {', '.join(p.generated_fields)}"] if p.generated_fields else []

    @classmethod
    def do(cls, p, action, user, reason, request, params=None):
        if action == "set_pricing":
            from catalog.services import set_product_pricing
            a = cls._pricing_args(params or {})
            set_product_pricing(product=p, actor=user, reason=reason or "Bulk pricing", request=request, **a)
            return
        record_product_status_change(product=p, new_status=cls.ACTIONS[action], changed_by=user, reason=reason, request=request)


class StoreModule:
    name = "stores"
    ACTIONS = {"approve": StoreStatus.ACTIVE, "reject": StoreStatus.REJECTED, "suspend": StoreStatus.SUSPENDED,
               "reactivate": StoreStatus.ACTIVE, "reopen": StoreStatus.PENDING}
    NEEDS_REASON = {"reject", "suspend"}
    FILTERS = ("status", "category", "q")

    @staticmethod
    def queryset(f):
        qs = Store.objects.select_related("address").order_by("pk")
        if f.get("status") in StoreStatus.values:
            qs = qs.filter(status=f["status"])
        if str(f.get("category") or "").isdigit():
            qs = qs.filter(category_id=int(f["category"]))
        if f.get("q"):
            qs = qs.filter(Q(name__icontains=f["q"][:100]) | Q(store_code__icontains=f["q"][:100]))
        return qs

    @staticmethod
    def label(s):
        return f"{s.name} ({s.store_code})"

    @classmethod
    def check(cls, s, action, user, reason, params=None):
        target = cls.ACTIONS[action]
        problems = []
        try:
            validate_store(current_status=s.status, new_status=target, reason=reason)
        except DjangoValidationError as exc:
            problems += _messages(exc)
        perm = store_permission(s.status, target)
        if perm and not user_has_store_permission(user, perm):
            problems.append("You do not have permission for this change.")
        if target == StoreStatus.ACTIVE and s.creation_source == "ADMIN" and not problems:
            from stores.management import approval_requirements
            missing = approval_requirements(s)
            if missing:
                problems.append("Missing: " + ", ".join(missing))
        return problems

    @classmethod
    def warnings(cls, s):
        out = []
        if s.verification_status != "VERIFIED":
            out.append("Store is not verified (approval does not verify it).")
        return out

    @classmethod
    def do(cls, s, action, user, reason, request, params=None):
        target = cls.ACTIONS[action]
        if target == StoreStatus.ACTIVE and s.status in (StoreStatus.PENDING, StoreStatus.DRAFT):
            store_management.approve_managed_store(actor=user, store=s, reason=reason, request=request)
        else:
            record_status_change(store=s, new_status=target, changed_by=user, reason=reason, request=request)


class PartnerModule:
    name = "partners"
    ACTIONS = {"approve": "APPROVED", "reject": "REJECTED", "suspend": "SUSPENDED"}
    NEEDS_REASON = {"reject", "suspend"}
    FILTERS = ("status", "q")

    @staticmethod
    def queryset(f):
        qs = DeliveryPartner.objects.select_related("user").order_by("pk")
        if f.get("status") in PartnerStatus.values:
            qs = qs.filter(status=f["status"])
        if f.get("q"):
            qs = qs.filter(Q(user__username__icontains=f["q"][:100]) | Q(user__email__icontains=f["q"][:100]))
        return qs

    @staticmethod
    def label(p):
        return f"{p.user.get_full_name() or p.user.get_username()} ({p.user.get_username()})"

    @classmethod
    def check(cls, p, action, user, reason, params=None):
        target = cls.ACTIONS[action]
        rule = delivery_services.PARTNER_TRANSITIONS[target]
        problems = []
        if p.status not in rule["from"]:
            problems.append(f"A {p.status.lower()} partner cannot be set to {target.lower()}.")
        if rule["reason"] and not (reason or "").strip():
            problems.append("A reason is required.")
        if not _has(user, "deliveries.change_deliverypartner"):
            problems.append("You do not have permission for this change.")
        return problems

    @classmethod
    def warnings(cls, p):
        return []

    @classmethod
    def do(cls, p, action, user, reason, request, params=None):
        delivery_services.decide_partner(p.pk, cls.ACTIONS[action], actor=user, reason=reason)


class ReviewModule:
    name = "reviews"
    ACTIONS = {"hide": "hide", "reject": "reject", "restore": "restore"}
    NEEDS_REASON = {"hide", "reject"}
    FILTERS = ("status", "reported")

    @staticmethod
    def queryset(f):
        qs = Review.objects.select_related("customer__user").order_by("pk")
        if f.get("status") in ReviewStatus.values:
            qs = qs.filter(status=f["status"])
        if f.get("reported") in ("1", "true", True):
            qs = qs.filter(report_count__gt=0)
        return qs

    @staticmethod
    def label(r):
        return f"Review #{r.pk} by {r.customer.user.get_username()}"

    @classmethod
    def check(cls, r, action, user, reason, params=None):
        problems = []
        target = review_services.MODERATION[cls.ACTIONS[action]]
        if r.status == ReviewStatus.WITHDRAWN:
            problems.append("The customer withdrew this review.")
        elif r.status == target:
            problems.append(f"The review is already {target.lower()}.")
        if action in cls.NEEDS_REASON and not (reason or "").strip():
            problems.append("A reason is required.")
        if not _has(user, "reviews.change_review"):
            problems.append("You do not have permission for this change.")
        return problems

    @classmethod
    def warnings(cls, r):
        return [f"{r.report_count} report(s)"] if r.report_count else []

    @classmethod
    def do(cls, r, action, user, reason, request, params=None):
        review_services.moderate_review(r, action=cls.ACTIONS[action], actor=user, reason=reason, request=request)


MODULES = {m.name: m for m in (ProductModule, StoreModule, PartnerModule, ReviewModule)}


class BulkIn(serializers.Serializer):
    action = serializers.CharField(max_length=32)
    ids = serializers.ListField(child=serializers.IntegerField(min_value=1), required=False, max_length=MAX_BULK)
    select_all = serializers.BooleanField(required=False, default=False)
    filters = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False, default=dict)
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255, default="")
    confirm = serializers.BooleanField(required=False, default=False)
    expected_count = serializers.IntegerField(required=False, min_value=0)
    params = serializers.DictField(child=serializers.CharField(allow_blank=True), required=False, default=dict)


def _resolve(module, data):
    if data["action"] not in module.ACTIONS:
        raise serializers.ValidationError({"action": f"Unknown action. Choose one of: {', '.join(sorted(module.ACTIONS))}."})
    if data["select_all"]:
        qs = module.queryset({k: v for k, v in data["filters"].items() if k in module.FILTERS})
        if qs.count() > MAX_BULK:
            raise serializers.ValidationError({"detail": f"That is more than {MAX_BULK} records. Narrow the filters and try again."})
        objs = list(qs)
    else:
        ids = list(dict.fromkeys(data.get("ids") or []))
        if not ids:
            raise serializers.ValidationError({"ids": "Select at least one record."})
        by_id = {o.pk: o for o in module.queryset({}).filter(pk__in=ids)}
        objs = [by_id[i] for i in ids if i in by_id]
    return objs


class _BulkBase(APIView):
    permission_classes = [IsManagement]

    def parse(self, request, module):
        if module not in MODULES:
            raise serializers.ValidationError({"detail": "Unknown module."})
        ser = BulkIn(data=request.data)
        ser.is_valid(raise_exception=True)
        mod = MODULES[module]
        objs = _resolve(mod, ser.validated_data)
        return mod, ser.validated_data, objs


class BulkPreviewView(_BulkBase):
    def post(self, request, module):
        mod, data, objs = self.parse(request, module)
        reason = data["reason"]
        eligible, blocked = [], []
        for obj in objs:
            problems = mod.check(obj, data["action"], request.user, reason, data["params"])
            entry = {"id": obj.pk, "label": mod.label(obj)}
            if problems:
                blocked.append({**entry, "reasons": problems})
            else:
                eligible.append({**entry, "warnings": mod.warnings(obj)})
        needs_reason = data["action"] in mod.NEEDS_REASON
        return Response({
            "module": module, "action": data["action"], "total": len(objs), "needs_reason": needs_reason,
            "eligible_count": len(eligible), "blocked_count": len(blocked),
            "eligible": eligible[:PREVIEW_LIST], "blocked": blocked[:PREVIEW_LIST],
            "warning_count": sum(1 for e in eligible if e["warnings"]),
        })


class BulkApplyView(_BulkBase):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = "bulk"

    def post(self, request, module):
        mod, data, objs = self.parse(request, module)
        if not data["confirm"]:
            raise serializers.ValidationError({"confirm": "Confirm the action after reviewing the preview."})
        if data["select_all"] and data.get("expected_count") != len(objs):
            raise serializers.ValidationError({"expected_count": f"The selection changed ({len(objs)} records now match). Review the preview again."})
        if data["action"] in mod.NEEDS_REASON and not data["reason"].strip():
            raise serializers.ValidationError({"reason": "A reason is required for this action."})
        successful, skipped, failed = [], [], []
        for obj in objs:
            entry = {"id": obj.pk, "label": mod.label(obj)}
            try:
                with transaction.atomic():
                    fresh = mod.queryset({}).select_for_update(of=("self",)).get(pk=obj.pk)  # current state, not the preview's
                    problems = mod.check(fresh, data["action"], request.user, data["reason"], data["params"])
                    if problems:
                        skipped.append({**entry, "reasons": problems})
                        continue
                    mod.do(fresh, data["action"], request.user, data["reason"], request._request, data["params"])
                successful.append(entry)
            except DjangoValidationError as exc:
                skipped.append({**entry, "reasons": _messages(exc)})
            except Exception:  # one record never fails the others; details stay in the log
                logger.exception("Bulk %s %s failed for %s", module, data["action"], obj.pk)
                failed.append({**entry, "reasons": ["Could not be saved. See the server log."]})
        audit(request.user, f"bulk.{module}.{data['action']}", None, object_type=module, object_id="bulk",
              summary=f"Bulk {data['action']} on {module}: {len(successful)} done, {len(skipped)} skipped, {len(failed)} failed",
              request=request._request, succeeded=[e["id"] for e in successful][:200], skipped=len(skipped), failed=len(failed),
              select_all=data["select_all"], reason=data["reason"][:255])
        return Response({"module": module, "action": data["action"], "successful": successful, "skipped": skipped, "failed": failed,
                         "counts": {"successful": len(successful), "skipped": len(skipped), "failed": len(failed)}})


class ApprovalCenterView(APIView):
    """What needs a decision, grouped, with the first few items of each queue."""
    permission_classes = [IsManagement]

    def get(self, request):
        def queue(key, title, qs, link, label, extra=None, note=None):
            return {"key": key, "title": title, "count": qs.count(), "link": link, "note": note,
                    "items": [{"id": o.pk, "label": label(o), **(extra(o) if extra else {})} for o in qs[:5]]}

        products = Product.objects.filter(status=ProductStatus.PENDING).select_related("store").order_by("created_at")
        imports = ProductImportBatch.objects.filter(
            Q(status=ProductImportBatch.Status.PREVIEWED, invalid_rows__gt=0) | Q(status__in=["COMMITTED", "FAILED"], summary__failed__gt=0)
        ).exclude(workbook_path="").order_by("-created_at")
        if not request.user.is_superuser:
            imports = imports.filter(created_by=request.user)
        queues = [
            queue("products", "Products awaiting approval", products, "/admin/approvals/products", lambda p: f"{p.name} · {p.store.name}",
                  lambda p: {"generated": p.generated_fields}),
            queue("imports", "Imports needing attention", imports, "/admin/imports", lambda b: b.source_name or "Import",
                  lambda b: {"status": b.status, "invalid": b.invalid_rows}),
            queue("stores_pending", "Store applications", Store.objects.filter(status=StoreStatus.PENDING).order_by("created_at"),
                  "/admin/approvals/stores", lambda s: f"{s.name} ({s.store_code})"),
            queue("stores_info", "Stores needing information", Store.objects.filter(status=StoreStatus.NEEDS_INFO).order_by("created_at"),
                  "/admin/stores?status=NEEDS_INFO", lambda s: f"{s.name} ({s.store_code})", lambda s: {"missing": s.missing_requirements}),
            queue("stores_unverified", "Active stores not yet verified",
                  Store.objects.filter(status=StoreStatus.ACTIVE, verification_status="UNVERIFIED").order_by("created_at"),
                  "/admin/stores?verification=UNVERIFIED", lambda s: f"{s.name} ({s.store_code})"),
            queue("partners", "Delivery partner applications", DeliveryPartner.objects.filter(status=PartnerStatus.PENDING).select_related("user").order_by("created_at"),
                  "/admin/approvals/partners", lambda p: p.user.get_username()),
            queue("reviews", "Reported reviews", Review.objects.filter(status=ReviewStatus.PUBLISHED, report_count__gt=0).select_related("customer__user").order_by("-report_count"),
                  "/admin/reviews?reported=1", lambda r: ReviewModule.label(r), lambda r: {"reports": r.report_count}),
        ]
        return Response({"queues": queues, "total": sum(q["count"] for q in queues),
                         "not_available": ["Promotions (the platform has no promotions yet)"]})
