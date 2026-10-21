from django.db.models import Q
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination
from core.permissions import get_store_membership, is_management, is_support_staff

from . import services
from .models import Feedback, FeedbackKind, FeedbackStatus, FeedbackSubject


def staff(user) -> bool:
    return is_support_staff(user) or is_management(user)


class FeedbackSerializer(serializers.ModelSerializer):
    author_name = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()
    ticket_reference = serializers.CharField(source="ticket.reference", read_only=True, default=None)
    store_name = serializers.CharField(source="store.name", read_only=True, default=None)

    class Meta:
        model = Feedback
        fields = ["id", "reference", "kind", "subject_type", "store", "store_name", "order", "message", "status", "author_name",
                  "ticket", "ticket_reference", "replies", "created_at", "updated_at"]

    def _viewer(self):
        return self.context["request"].user

    def get_author_name(self, obj) -> str:
        user = self._viewer()
        if staff(user) or obj.author_id == user.pk:
            return obj.author.get_full_name() or obj.author.get_username()
        first = obj.author.first_name or "Customer"
        return f"{first} {obj.author.last_name[:1]}.".strip() if obj.author.last_name else first

    def get_replies(self, obj):
        rows = obj.replies.select_related("author")
        if not staff(self._viewer()):
            rows = rows.filter(is_internal=False)
        return [{"id": r.pk, "body": r.body, "is_internal": r.is_internal, "created_at": r.created_at,
                 "from_support": staff(r.author)} for r in rows]

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if not staff(self._viewer()):
            data.pop("ticket", None)
        return data


class FeedbackCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=FeedbackKind.choices)
    subject_type = serializers.ChoiceField(choices=FeedbackSubject.choices, default=FeedbackSubject.PLATFORM)
    store = serializers.IntegerField(required=False, allow_null=True)
    order = serializers.IntegerField(required=False, allow_null=True)
    message = serializers.CharField(max_length=3000)


class ReplySerializer(serializers.Serializer):
    body = serializers.CharField(max_length=3000)
    is_internal = serializers.BooleanField(required=False, default=False)


class StatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=FeedbackStatus.choices)


def visible(user):
    qs = Feedback.objects.select_related("author", "store", "ticket")
    if staff(user):
        return qs
    membership = get_store_membership(user)
    if membership:  # stores see feedback about themselves, never other stores'
        return qs.filter(Q(store_id=membership.store_id) | Q(author=user))
    return qs.filter(author=user)


class FeedbackListCreateView(generics.ListCreateAPIView):
    pagination_class = StandardPagination

    def get_serializer_class(self):
        return FeedbackCreateSerializer if self.request.method == "POST" else FeedbackSerializer

    def get_serializer_context(self):
        return {"request": self.request}

    def get_queryset(self):
        qs = visible(self.request.user)
        for param, lookup in (("status", "status"), ("kind", "kind"), ("subject_type", "subject_type"), ("store", "store_id")):
            if self.request.query_params.get(param):
                qs = qs.filter(**{lookup: self.request.query_params[param]})
        return qs

    @extend_schema(request=FeedbackCreateSerializer, responses=FeedbackSerializer)
    def create(self, request, *args, **kwargs):
        data = FeedbackCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        feedback = services.submit_feedback(user=request.user, kind=v["kind"], subject_type=v["subject_type"], message=v["message"],
                                            store_id=v.get("store"), order_id=v.get("order"))
        return Response(FeedbackSerializer(feedback, context={"request": request}).data, status=201)


class FeedbackDetailView(generics.RetrieveAPIView):
    serializer_class = FeedbackSerializer

    def get_queryset(self):
        return visible(self.request.user)


class _Action(APIView):
    def feedback(self, request, pk):
        return get_object_or_404(visible(request.user), pk=pk)

    def out(self, request, feedback):
        return Response(FeedbackSerializer(visible(request.user).get(pk=feedback.pk), context={"request": request}).data)


class ReplyView(_Action):
    @extend_schema(request=ReplySerializer, responses=FeedbackSerializer)
    def post(self, request, pk):
        feedback = self.feedback(request, pk)
        data = ReplySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.reply(feedback.pk, author=request.user, body=data.validated_data["body"], internal=data.validated_data["is_internal"])
        return self.out(request, feedback)


class StatusView(_Action):
    @extend_schema(request=StatusSerializer, responses=FeedbackSerializer)
    def post(self, request, pk):
        feedback = self.feedback(request, pk)
        data = StatusSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.set_status(feedback.pk, actor=request.user, status=data.validated_data["status"])
        return self.out(request, feedback)


class EscalateView(_Action):
    @extend_schema(request=None, responses=FeedbackSerializer)
    def post(self, request, pk):
        feedback = self.feedback(request, pk)
        services.escalate_to_ticket(feedback.pk, actor=request.user)
        return self.out(request, feedback)
