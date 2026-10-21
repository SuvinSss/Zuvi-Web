from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from rest_framework import generics, serializers
from rest_framework.response import Response
from rest_framework.views import APIView

from core.pagination import StandardPagination

from . import services
from .models import Notification, NotificationPreference


class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Notification
        fields = ["id", "kind", "title", "body", "data", "is_read", "read_at", "created_at"]
        read_only_fields = fields


class NotificationListView(generics.ListAPIView):
    serializer_class = NotificationSerializer
    pagination_class = StandardPagination

    def get_queryset(self):
        qs = Notification.objects.filter(recipient=self.request.user)
        unread = self.request.query_params.get("unread")
        if unread in {"1", "true", "True"}:
            qs = qs.filter(is_read=False)
        return qs


class NotificationReadView(APIView):
    @extend_schema(request=None, responses=NotificationSerializer)
    def post(self, request, pk):
        notification = get_object_or_404(Notification, pk=pk, recipient=request.user)  # ownership
        services.mark_read(request.user, pk)
        notification.refresh_from_db()
        return Response(NotificationSerializer(notification).data)


class NotificationReadAllView(APIView):
    @extend_schema(request=None, responses=dict)
    def post(self, request):
        return Response({"updated": services.mark_all_read(request.user)})


class UnreadCountView(APIView):
    @extend_schema(responses=dict)
    def get(self, request):
        return Response({"unread": Notification.objects.filter(recipient=request.user, is_read=False).count()})


class PreferenceSerializer(serializers.Serializer):
    email_enabled = serializers.BooleanField()


class PreferenceView(APIView):
    @extend_schema(responses=PreferenceSerializer)
    def get(self, request):
        pref = NotificationPreference.objects.filter(user=request.user).first()
        return Response({"email_enabled": pref.email_enabled if pref else True})

    @extend_schema(request=PreferenceSerializer, responses=PreferenceSerializer)
    def put(self, request):
        serializer = PreferenceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        NotificationPreference.objects.update_or_create(user=request.user, defaults=serializer.validated_data)
        return Response(serializer.validated_data)
