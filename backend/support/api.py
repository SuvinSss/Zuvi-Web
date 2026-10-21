from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import Role
from core.files import private_file_response
from core.pagination import StandardPagination
from core.permissions import IsSupportSupervisor, is_management, is_support_staff, is_support_supervisor

from . import services
from .models import (
    AgainstType, Complaint, ComplaintAttachment, ComplaintCategory, ComplaintEvent, ComplaintStatus, Priority,
    Ticket, TicketAttachment, TicketCategory, TicketStatus,
)

User = get_user_model()


def staff_view(request) -> bool:
    return services.is_staff_user(request.user)


# ------------------------------------------------------------------ serializers

class AttachmentSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    original_name = serializers.CharField()
    content_type = serializers.CharField()
    size = serializers.IntegerField()
    created_at = serializers.DateTimeField()
    is_internal = serializers.BooleanField()
    url = serializers.SerializerMethodField()

    def get_url(self, obj) -> str:
        kind = "ticket" if isinstance(obj, TicketAttachment) else "complaint"
        return f"/api/v1/support/attachments/{kind}/{obj.pk}/file/"


def _person(user):
    if user is None:
        return None
    return {"id": user.pk, "name": user.get_full_name() or user.get_username(), "role": user.role}


class TicketListSerializer(serializers.ModelSerializer):
    requester = serializers.SerializerMethodField()
    assigned_to = serializers.SerializerMethodField()
    sla = serializers.SerializerMethodField()
    order_number = serializers.CharField(source="order.order_number", read_only=True, default=None)

    class Meta:
        model = Ticket
        fields = ["id", "reference", "subject", "category", "priority", "status", "escalated", "requester", "assigned_to",
                  "order", "order_number", "sla", "created_at", "updated_at"]

    def get_requester(self, obj):
        return _person(obj.requester)

    def get_assigned_to(self, obj):
        return _person(obj.assigned_to) if staff_view(self.context["request"]) or obj.assigned_to_id is None else {"name": "Support team"}

    def get_sla(self, obj):
        return services.ticket_sla(obj) if staff_view(self.context["request"]) else None


class TicketDetailSerializer(TicketListSerializer):
    messages = serializers.SerializerMethodField()
    events = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()

    class Meta(TicketListSerializer.Meta):
        fields = TicketListSerializer.Meta.fields + ["description", "messages", "events", "attachments", "first_responded_at", "resolved_at", "closed_at"]

    def _staff(self):
        return staff_view(self.context["request"])

    def get_messages(self, obj):
        rows = obj.messages.select_related("author") if self._staff() else obj.messages.filter(is_internal=False).select_related("author")
        return [{"id": m.pk, "author": _person(m.author) if self._staff() or m.author_id == obj.requester_id else {"name": "Support"},
                 "body": m.body, "is_internal": m.is_internal, "created_at": m.created_at} for m in rows]

    def get_events(self, obj):
        rows = obj.events.all() if self._staff() else obj.events.filter(is_internal=False)
        return [{"kind": e.kind, "detail": e.detail, "created_at": e.created_at} for e in rows]

    def get_attachments(self, obj):
        rows = obj.attachments.all() if self._staff() else obj.attachments.filter(is_internal=False)
        return AttachmentSerializer(rows, many=True).data


class TicketCreateSerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=TicketCategory.choices, default=TicketCategory.OTHER)
    subject = serializers.CharField(max_length=200)
    description = serializers.CharField(max_length=5000)
    order = serializers.IntegerField(required=False, allow_null=True)


class MessageSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=5000)
    is_internal = serializers.BooleanField(required=False, default=False)


class StatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=TicketStatus.choices)
    note = serializers.CharField(required=False, allow_blank=True, max_length=255)


class AssignSerializer(serializers.Serializer):
    assignee = serializers.IntegerField(required=False, help_text="Support user id; omit to claim for yourself.")


class PrioritySerializer(serializers.Serializer):
    priority = serializers.ChoiceField(choices=Priority.choices)


class ReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)


class ComplaintListSerializer(serializers.ModelSerializer):
    complainant = serializers.SerializerMethodField()
    assigned_to = serializers.SerializerMethodField()
    sla = serializers.SerializerMethodField()
    order_number = serializers.CharField(source="order.order_number", read_only=True, default=None)
    store_name = serializers.CharField(source="store.name", read_only=True, default=None)

    class Meta:
        model = Complaint
        fields = ["id", "reference", "against_type", "category", "severity", "status", "complainant", "assigned_to", "order",
                  "order_number", "store", "store_name", "partner", "product", "sla", "created_at", "updated_at"]

    def get_complainant(self, obj):
        return _person(obj.complainant)

    def get_assigned_to(self, obj):
        return _person(obj.assigned_to) if staff_view(self.context["request"]) or obj.assigned_to_id is None else {"name": "Support team"}

    def get_sla(self, obj):
        return services.complaint_sla(obj) if staff_view(self.context["request"]) else None


class ComplaintDetailSerializer(ComplaintListSerializer):
    timeline = serializers.SerializerMethodField()
    attachments = serializers.SerializerMethodField()

    class Meta(ComplaintListSerializer.Meta):
        fields = ComplaintListSerializer.Meta.fields + ["description", "desired_resolution", "resolution", "escalation_reason",
                                                         "timeline", "attachments", "acknowledged_at", "resolved_at", "closed_at"]

    def to_representation(self, obj):
        data = super().to_representation(obj)
        if not staff_view(self.context["request"]):
            data.pop("escalation_reason", None)  # internal reasoning stays internal
        return data

    def get_timeline(self, obj):
        staff = staff_view(self.context["request"])
        rows = obj.events.select_related("actor") if staff else obj.events.filter(is_internal=False).exclude(kind="ESCALATED").select_related("actor")
        return [{"id": e.pk, "kind": e.kind, "body": e.body, "from_status": e.from_status, "to_status": e.to_status,
                 "is_internal": e.is_internal, "created_at": e.created_at,
                 "actor": (_person(e.actor) if staff or e.actor_id == obj.complainant_id else {"name": "Support"}) if e.actor else None}
                for e in rows]

    def get_attachments(self, obj):
        rows = obj.attachments.all() if staff_view(self.context["request"]) else obj.attachments.filter(is_internal=False)
        return AttachmentSerializer(rows, many=True).data


class ComplaintCreateSerializer(serializers.Serializer):
    against_type = serializers.ChoiceField(choices=AgainstType.choices)
    category = serializers.ChoiceField(choices=ComplaintCategory.choices)
    description = serializers.CharField(max_length=5000)
    desired_resolution = serializers.CharField(required=False, allow_blank=True, max_length=255)
    order = serializers.IntegerField(required=False, allow_null=True)
    store = serializers.IntegerField(required=False, allow_null=True)
    partner = serializers.IntegerField(required=False, allow_null=True)
    product = serializers.IntegerField(required=False, allow_null=True)


class ResolveSerializer(serializers.Serializer):
    resolution = serializers.CharField(max_length=5000)


class InfoRequestSerializer(serializers.Serializer):
    message = serializers.CharField(max_length=5000)


# ------------------------------------------------------------------ visibility

def visible_tickets(user):
    qs = Ticket.objects.select_related("requester", "assigned_to", "order")
    if is_support_supervisor(user):
        return qs
    if is_support_staff(user):
        return qs.filter(Q(assigned_to=user) | Q(assigned_to__isnull=True) | Q(requester=user))
    return qs.filter(requester=user)


def visible_complaints(user):
    qs = Complaint.objects.select_related("complainant", "assigned_to", "order", "store")
    if is_support_supervisor(user):
        return qs
    if is_support_staff(user):
        return qs.filter(Q(assigned_to=user) | Q(assigned_to__isnull=True) | Q(complainant=user))
    return qs.filter(complainant=user)


def _files(request):
    return request.FILES.getlist("attachments")


def _filters(qs, request, mapping):
    for param, lookup in mapping.items():
        value = request.query_params.get(param)
        if value:
            qs = qs.filter(**{lookup: value})
    return qs


# ------------------------------------------------------------------ tickets

class TicketListCreateView(generics.ListCreateAPIView):
    pagination_class = StandardPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_serializer_class(self):
        return TicketCreateSerializer if self.request.method == "POST" else TicketListSerializer

    def get_serializer_context(self):
        return {"request": self.request}

    def get_queryset(self):
        qs = _filters(visible_tickets(self.request.user), self.request,
                      {"status": "status", "priority": "priority", "category": "category", "assigned_to": "assigned_to_id"})
        p = self.request.query_params
        if p.get("unassigned") in {"1", "true"} and staff_view(self.request):
            qs = qs.filter(assigned_to__isnull=True)
        if p.get("mine") in {"1", "true"}:
            qs = qs.filter(assigned_to=self.request.user)
        if p.get("escalated") in {"1", "true"}:
            qs = qs.filter(escalated=True)
        if p.get("q"):
            qs = qs.filter(Q(reference__icontains=p["q"]) | Q(subject__icontains=p["q"]))
        return qs

    @extend_schema(request=TicketCreateSerializer, responses=TicketDetailSerializer)
    def create(self, request, *args, **kwargs):
        data = TicketCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        ticket = services.create_ticket(user=request.user, category=v["category"], subject=v["subject"], description=v["description"],
                                        order_id=v.get("order"), attachments=_files(request))
        return Response(TicketDetailSerializer(ticket, context={"request": request}).data, status=201)


class TicketDetailView(generics.RetrieveAPIView):
    serializer_class = TicketDetailSerializer

    def get_queryset(self):
        return visible_tickets(self.request.user)


class _TicketAction(APIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def ticket(self, request, pk):
        return get_object_or_404(visible_tickets(request.user), pk=pk)

    def out(self, request, ticket):
        ticket = visible_tickets(request.user).get(pk=ticket.pk)
        return Response(TicketDetailSerializer(ticket, context={"request": request}).data)


class TicketMessageView(_TicketAction):
    @extend_schema(request=MessageSerializer, responses=TicketDetailSerializer)
    def post(self, request, pk):
        ticket = self.ticket(request, pk)
        data = MessageSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.add_ticket_message(ticket.pk, author=request.user, body=data.validated_data["body"],
                                    internal=data.validated_data["is_internal"], attachments=_files(request))
        return self.out(request, ticket)


class TicketStatusView(_TicketAction):
    @extend_schema(request=StatusSerializer, responses=TicketDetailSerializer)
    def post(self, request, pk):
        ticket = self.ticket(request, pk)
        data = StatusSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.change_ticket_status(ticket.pk, actor=request.user, new_status=data.validated_data["status"], note=data.validated_data.get("note", ""))
        return self.out(request, ticket)


class TicketAssignView(_TicketAction):
    @extend_schema(request=AssignSerializer, responses=TicketDetailSerializer)
    def post(self, request, pk):
        ticket = self.ticket(request, pk)
        data = AssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        assignee = request.user if not data.validated_data.get("assignee") else get_object_or_404(User, pk=data.validated_data["assignee"])
        services.assign_ticket(ticket.pk, actor=request.user, assignee=assignee)
        return self.out(request, ticket)


class TicketPriorityView(_TicketAction):
    @extend_schema(request=PrioritySerializer, responses=TicketDetailSerializer)
    def post(self, request, pk):
        ticket = self.ticket(request, pk)
        data = PrioritySerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.change_ticket_priority(ticket.pk, actor=request.user, priority=data.validated_data["priority"])
        return self.out(request, ticket)


class TicketEscalateView(_TicketAction):
    @extend_schema(request=ReasonSerializer, responses=TicketDetailSerializer)
    def post(self, request, pk):
        ticket = self.ticket(request, pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.escalate_ticket(ticket.pk, actor=request.user, reason=data.validated_data["reason"])
        return self.out(request, ticket)


# ------------------------------------------------------------------ complaints

class ComplaintListCreateView(generics.ListCreateAPIView):
    pagination_class = StandardPagination
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_serializer_class(self):
        return ComplaintCreateSerializer if self.request.method == "POST" else ComplaintListSerializer

    def get_serializer_context(self):
        return {"request": self.request}

    def get_queryset(self):
        qs = _filters(visible_complaints(self.request.user), self.request,
                      {"status": "status", "severity": "severity", "category": "category", "against_type": "against_type", "store": "store_id"})
        p = self.request.query_params
        if p.get("unassigned") in {"1", "true"} and staff_view(self.request):
            qs = qs.filter(assigned_to__isnull=True)
        if p.get("mine") in {"1", "true"}:
            qs = qs.filter(assigned_to=self.request.user)
        if p.get("q"):
            qs = qs.filter(Q(reference__icontains=p["q"]) | Q(description__icontains=p["q"]))
        return qs

    @extend_schema(request=ComplaintCreateSerializer, responses=ComplaintDetailSerializer)
    def create(self, request, *args, **kwargs):
        data = ComplaintCreateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        v = data.validated_data
        complaint = services.submit_complaint(
            user=request.user, against_type=v["against_type"], category=v["category"], description=v["description"],
            desired_resolution=v.get("desired_resolution", ""), order_id=v.get("order"), store_id=v.get("store"),
            partner_id=v.get("partner"), product_id=v.get("product"), attachments=_files(request))
        return Response(ComplaintDetailSerializer(complaint, context={"request": request}).data, status=201)


class ComplaintDetailView(generics.RetrieveAPIView):
    serializer_class = ComplaintDetailSerializer

    def get_queryset(self):
        return visible_complaints(self.request.user)


class _ComplaintAction(APIView):
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def complaint(self, request, pk):
        return get_object_or_404(visible_complaints(request.user), pk=pk)

    def out(self, request, complaint):
        complaint = visible_complaints(request.user).get(pk=complaint.pk)
        return Response(ComplaintDetailSerializer(complaint, context={"request": request}).data)


class ComplaintCommentView(_ComplaintAction):
    @extend_schema(request=MessageSerializer, responses=ComplaintDetailSerializer)
    def post(self, request, pk):
        complaint = self.complaint(request, pk)
        data = MessageSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.comment_on_complaint(complaint.pk, actor=request.user, body=data.validated_data["body"],
                                      internal=data.validated_data["is_internal"], attachments=_files(request))
        return self.out(request, complaint)


class ComplaintAssignView(_ComplaintAction):
    @extend_schema(request=AssignSerializer, responses=ComplaintDetailSerializer)
    def post(self, request, pk):
        complaint = self.complaint(request, pk)
        data = AssignSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        assignee = request.user if not data.validated_data.get("assignee") else get_object_or_404(User, pk=data.validated_data["assignee"])
        services.assign_complaint(complaint.pk, actor=request.user, assignee=assignee)
        return self.out(request, complaint)


class ComplaintInfoRequestView(_ComplaintAction):
    @extend_schema(request=InfoRequestSerializer, responses=ComplaintDetailSerializer)
    def post(self, request, pk):
        complaint = self.complaint(request, pk)
        data = InfoRequestSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.request_complaint_info(complaint.pk, actor=request.user, message=data.validated_data["message"])
        return self.out(request, complaint)


class ComplaintEscalateView(_ComplaintAction):
    @extend_schema(request=ReasonSerializer, responses=ComplaintDetailSerializer)
    def post(self, request, pk):
        complaint = self.complaint(request, pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.escalate_complaint(complaint.pk, actor=request.user, reason=data.validated_data["reason"])
        return self.out(request, complaint)


class ComplaintTakeOverView(_ComplaintAction):
    @extend_schema(request=None, responses=ComplaintDetailSerializer)
    def post(self, request, pk):
        complaint = self.complaint(request, pk)
        services.take_over_complaint(complaint.pk, actor=request.user)
        return self.out(request, complaint)


class ComplaintResolveView(_ComplaintAction):
    @extend_schema(request=ResolveSerializer, responses=ComplaintDetailSerializer)
    def post(self, request, pk):
        complaint = self.complaint(request, pk)
        data = ResolveSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.resolve_complaint(complaint.pk, actor=request.user, resolution=data.validated_data["resolution"])
        return self.out(request, complaint)


class ComplaintRejectView(_ComplaintAction):
    @extend_schema(request=ReasonSerializer, responses=ComplaintDetailSerializer)
    def post(self, request, pk):
        complaint = self.complaint(request, pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.reject_complaint(complaint.pk, actor=request.user, reason=data.validated_data["reason"])
        return self.out(request, complaint)


class ComplaintCloseView(_ComplaintAction):
    @extend_schema(request=None, responses=ComplaintDetailSerializer)
    def post(self, request, pk):
        complaint = self.complaint(request, pk)
        services.close_complaint(complaint.pk, actor=request.user)
        return self.out(request, complaint)


class ComplaintReopenView(_ComplaintAction):
    @extend_schema(request=ReasonSerializer, responses=ComplaintDetailSerializer)
    def post(self, request, pk):
        complaint = self.complaint(request, pk)
        data = ReasonSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        services.reopen_complaint(complaint.pk, actor=request.user, reason=data.validated_data["reason"])
        return self.out(request, complaint)


# ------------------------------------------------------------------ attachments, staff directory, reports

class AttachmentFileView(APIView):
    @extend_schema(responses={200: bytes})
    def get(self, request, kind, pk):
        if kind == "ticket":
            attachment = get_object_or_404(TicketAttachment, pk=pk)
            parent = get_object_or_404(visible_tickets(request.user), pk=attachment.ticket_id)
        elif kind == "complaint":
            attachment = get_object_or_404(ComplaintAttachment, pk=pk)
            parent = get_object_or_404(visible_complaints(request.user), pk=attachment.complaint_id)
        else:
            raise PermissionDenied()
        if attachment.is_internal and not staff_view(request):
            from django.http import Http404

            raise Http404
        return private_file_response(attachment.file)


class AgentListView(APIView):
    """Support staff directory for assignment (supervisors/admins)."""

    permission_classes = [IsSupportSupervisor]

    @extend_schema(responses={200: dict})
    def get(self, request):
        users = User.objects.filter(is_active=True, role__in=[Role.SUPPORT_AGENT, Role.SUPPORT_SUPERVISOR]).order_by("first_name", "username")
        open_t = dict(Ticket.objects.exclude(status__in=["RESOLVED", "CLOSED"]).values_list("assigned_to").annotate(n=Count("pk")))
        open_c = dict(Complaint.objects.exclude(status__in=["RESOLVED", "REJECTED", "CLOSED"]).values_list("assigned_to").annotate(n=Count("pk")))
        return Response([{**_person(u), "open_tickets": open_t.get(u.pk, 0), "open_complaints": open_c.get(u.pk, 0)} for u in users])


class SupportSummaryView(APIView):
    permission_classes = [IsSupportSupervisor]

    @extend_schema(responses={200: dict})
    def get(self, request):
        now = timezone.now()
        open_tickets = Ticket.objects.exclude(status__in=["RESOLVED", "CLOSED"])
        open_complaints = Complaint.objects.exclude(status__in=["RESOLVED", "REJECTED", "CLOSED"])
        return Response({
            "tickets": {
                "by_status": dict(Ticket.objects.values_list("status").annotate(n=Count("pk"))),
                "unassigned": open_tickets.filter(assigned_to__isnull=True).count(),
                "escalated": open_tickets.filter(escalated=True).count(),
                "first_response_breached": open_tickets.filter(first_responded_at__isnull=True, first_response_due__lt=now).count(),
                "resolution_breached": open_tickets.filter(resolution_due__lt=now).count(),
            },
            "complaints": {
                "by_status": dict(Complaint.objects.values_list("status").annotate(n=Count("pk"))),
                "unassigned": open_complaints.filter(assigned_to__isnull=True).count(),
                "escalated": open_complaints.filter(status="ESCALATED").count(),
                "acknowledgement_breached": open_complaints.filter(acknowledged_at__isnull=True, acknowledge_due__lt=now).count(),
                "resolution_breached": open_complaints.filter(resolution_due__lt=now).count(),
            },
        })
