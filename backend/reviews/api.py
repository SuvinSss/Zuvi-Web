from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import NotFound
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from catalog.models import Product
from core.pagination import StandardPagination
from core.permissions import IsCustomer, IsManagement, IsDeliveryPartner, IsStoreUser, get_customer, get_delivery_partner, get_store_membership
from orders.models import StoreOrder
from stores.models import Store

from . import services
from .models import Review, ReviewReply, ReviewReport, ReviewStatus, TargetType


class ReplySerializer(serializers.ModelSerializer):
    class Meta:
        model = ReviewReply
        fields = ["body", "created_at"]


def reviewer_label(review) -> str:
    user = review.customer.user
    first = (user.first_name or "Customer").strip()
    return f"{first} {user.last_name[:1]}.".strip() if user.last_name else first


class PublicReviewSerializer(serializers.ModelSerializer):
    reviewer = serializers.SerializerMethodField()
    reply = ReplySerializer(read_only=True)

    class Meta:
        model = Review
        fields = ["id", "rating", "title", "comment", "reviewer", "reply", "created_at", "edited_at"]

    def get_reviewer(self, obj) -> str:
        return reviewer_label(obj)


class MyReviewSerializer(serializers.ModelSerializer):
    reply = ReplySerializer(read_only=True)
    store_order_number = serializers.CharField(source="store_order.store_order_number", read_only=True)

    class Meta:
        model = Review
        fields = ["id", "target_type", "store", "product", "partner", "store_order", "store_order_number", "rating",
                  "title", "comment", "status", "moderation_reason", "reply", "created_at", "edited_at"]


class CreateReviewSerializer(serializers.Serializer):
    store_order = serializers.IntegerField()
    target_type = serializers.ChoiceField(choices=TargetType.choices)
    product = serializers.IntegerField(required=False)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    title = serializers.CharField(required=False, allow_blank=True, max_length=120)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class UpdateReviewSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5, required=False)
    title = serializers.CharField(required=False, allow_blank=True, max_length=120)
    comment = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(required=False, allow_blank=True, max_length=255)


class ReportSerializer(serializers.Serializer):
    reason = serializers.ChoiceField(choices=ReviewReport.Reason.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=500)


class ReplyInputSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=1000)


def _published(qs):
    return qs.filter(status=ReviewStatus.PUBLISHED).select_related("customer__user", "reply")


class _PublicList(generics.ListAPIView):
    serializer_class = PublicReviewSerializer
    permission_classes = [AllowAny]
    pagination_class = StandardPagination
    target_type = None

    def target(self):
        raise NotImplementedError

    def get_queryset(self):
        return _published(Review.objects.filter(**self.target_filter())).order_by("-created_at")

    def list(self, request, *args, **kwargs):
        response = super().list(request, *args, **kwargs)
        response.data["rating"] = services.aggregate_for(self.target_type, self.kwargs["pk"])
        return response


class StoreReviewsView(_PublicList):
    target_type = TargetType.STORE

    def target_filter(self):
        store = get_object_or_404(Store, pk=self.kwargs["pk"], is_active=True)
        return {"target_type": TargetType.STORE, "store": store}


class ProductReviewsView(_PublicList):
    target_type = TargetType.PRODUCT

    def target_filter(self):
        product = get_object_or_404(Product, pk=self.kwargs["pk"], status="APPROVED", store__is_active=True)
        return {"target_type": TargetType.PRODUCT, "product": product}


class CreateReviewView(APIView):
    permission_classes = [IsCustomer]

    @extend_schema(request=CreateReviewSerializer, responses=MyReviewSerializer)
    def post(self, request):
        data = CreateReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        customer = get_customer(request.user)
        # Scoped to the caller's own orders, so another customer's store order is simply "not found".
        store_order = get_object_or_404(StoreOrder.objects.select_related("order", "store"), pk=v["store_order"], order__customer=customer)
        product = Product.objects.filter(pk=v["product"]).first() if v.get("product") else None
        review = services.create_review(customer=customer, store_order=store_order, target_type=v["target_type"],
                                        rating=v["rating"], title=v.get("title", ""), comment=v.get("comment", ""), product=product)
        return Response(MyReviewSerializer(review).data, status=201)


class MyReviewsView(generics.ListAPIView):
    serializer_class = MyReviewSerializer
    permission_classes = [IsCustomer]
    pagination_class = StandardPagination

    def get_queryset(self):
        return Review.objects.filter(customer=get_customer(self.request.user)).select_related("reply", "store_order")


class MyReviewDetailView(APIView):
    permission_classes = [IsCustomer]

    def _review(self, request, pk):
        return get_object_or_404(Review, pk=pk, customer=get_customer(request.user))

    @extend_schema(request=UpdateReviewSerializer, responses=MyReviewSerializer)
    def patch(self, request, pk):
        data = UpdateReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        review = services.update_review(self._review(request, pk), customer=get_customer(request.user), **data.validated_data)
        return Response(MyReviewSerializer(review).data)

    @extend_schema(responses=MyReviewSerializer)
    def delete(self, request, pk):
        review = services.withdraw_review(self._review(request, pk), customer=get_customer(request.user))
        return Response(MyReviewSerializer(review).data)


class ReportReviewView(APIView):
    @extend_schema(request=ReportSerializer, responses={201: None})
    def post(self, request, pk):
        review = get_object_or_404(Review.objects.select_related("customer__user"), pk=pk, status=ReviewStatus.PUBLISHED)
        data = ReportSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.report_review(review, reporter=request.user, **data.validated_data)
        return Response(status=201)


class StoreReviewListView(generics.ListAPIView):
    serializer_class = PublicReviewSerializer
    permission_classes = [IsStoreUser]
    pagination_class = StandardPagination

    def get_queryset(self):
        store = get_store_membership(self.request.user).store
        return _published(Review.objects.filter(target_type=TargetType.STORE, store=store))


class StoreReplyView(APIView):
    permission_classes = [IsStoreUser]

    @extend_schema(request=ReplyInputSerializer, responses=ReplySerializer)
    def post(self, request, pk):
        membership = get_store_membership(request.user)
        review = get_object_or_404(Review, pk=pk, target_type=TargetType.STORE, store=membership.store)
        data = ReplyInputSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        reply = services.reply_to_review(review, user=request.user, store=membership.store, body=data.validated_data["body"])
        return Response(ReplySerializer(reply).data, status=201)


class PartnerRatingsView(generics.ListAPIView):
    serializer_class = PublicReviewSerializer
    permission_classes = [IsDeliveryPartner]
    pagination_class = StandardPagination

    def get_queryset(self):
        partner = get_delivery_partner(self.request.user)
        return _published(Review.objects.filter(target_type=TargetType.DELIVERY_PARTNER, partner=partner))


class AdminReviewSerializer(MyReviewSerializer):
    reviewer = serializers.SerializerMethodField()
    report_count = serializers.IntegerField(read_only=True)

    class Meta(MyReviewSerializer.Meta):
        fields = MyReviewSerializer.Meta.fields + ["reviewer", "report_count", "moderated_at"]

    def get_reviewer(self, obj) -> str:
        return obj.customer.user.get_username()


class AdminReviewListView(generics.ListAPIView):
    serializer_class = AdminReviewSerializer
    permission_classes = [IsManagement]
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Review.objects.select_related("customer__user", "reply", "store_order")
        p = self.request.query_params
        for key, field in (("status", "status"), ("target_type", "target_type"), ("store", "store_id"), ("product", "product_id")):
            if p.get(key):
                qs = qs.filter(**{field: p[key]})
        if p.get("reported") in {"1", "true"}:
            qs = qs.filter(report_count__gt=0)
        return qs


class _Moderate(APIView):
    permission_classes = [IsManagement]
    action = None

    @extend_schema(request=ReasonSerializer, responses=AdminReviewSerializer)
    def post(self, request, pk):
        review = get_object_or_404(Review, pk=pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        review = services.moderate_review(review, action=self.action, actor=request.user,
                                          reason=data.validated_data.get("reason", ""), request=request)
        return Response(AdminReviewSerializer(review).data)


class HideView(_Moderate):
    action = "hide"


class RejectView(_Moderate):
    action = "reject"


class RestoreView(_Moderate):
    action = "restore"
