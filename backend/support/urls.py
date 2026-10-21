from django.urls import path

from . import api

urlpatterns = [
    path("support/tickets/", api.TicketListCreateView.as_view(), name="api_tickets"),
    path("support/tickets/<int:pk>/", api.TicketDetailView.as_view(), name="api_ticket"),
    path("support/tickets/<int:pk>/messages/", api.TicketMessageView.as_view(), name="api_ticket_messages"),
    path("support/tickets/<int:pk>/status/", api.TicketStatusView.as_view(), name="api_ticket_status"),
    path("support/tickets/<int:pk>/assign/", api.TicketAssignView.as_view(), name="api_ticket_assign"),
    path("support/tickets/<int:pk>/priority/", api.TicketPriorityView.as_view(), name="api_ticket_priority"),
    path("support/tickets/<int:pk>/escalate/", api.TicketEscalateView.as_view(), name="api_ticket_escalate"),
    path("support/complaints/", api.ComplaintListCreateView.as_view(), name="api_complaints"),
    path("support/complaints/<int:pk>/", api.ComplaintDetailView.as_view(), name="api_complaint"),
    path("support/complaints/<int:pk>/comments/", api.ComplaintCommentView.as_view(), name="api_complaint_comment"),
    path("support/complaints/<int:pk>/assign/", api.ComplaintAssignView.as_view(), name="api_complaint_assign"),
    path("support/complaints/<int:pk>/request-info/", api.ComplaintInfoRequestView.as_view(), name="api_complaint_info"),
    path("support/complaints/<int:pk>/escalate/", api.ComplaintEscalateView.as_view(), name="api_complaint_escalate"),
    path("support/complaints/<int:pk>/take-over/", api.ComplaintTakeOverView.as_view(), name="api_complaint_takeover"),
    path("support/complaints/<int:pk>/resolve/", api.ComplaintResolveView.as_view(), name="api_complaint_resolve"),
    path("support/complaints/<int:pk>/reject/", api.ComplaintRejectView.as_view(), name="api_complaint_reject"),
    path("support/complaints/<int:pk>/close/", api.ComplaintCloseView.as_view(), name="api_complaint_close"),
    path("support/complaints/<int:pk>/reopen/", api.ComplaintReopenView.as_view(), name="api_complaint_reopen"),
    path("support/attachments/<str:kind>/<int:pk>/file/", api.AttachmentFileView.as_view(), name="api_support_attachment"),
    path("support/agents/", api.AgentListView.as_view(), name="api_support_agents"),
    path("support/summary/", api.SupportSummaryView.as_view(), name="api_support_summary"),
]
