from django.urls import path

from . import api

urlpatterns = [
    # delivery partner
    path("delivery/me/", api.PartnerProfileView.as_view(), name="api_partner_me"),
    path("delivery/me/online/", api.PartnerOnlineView.as_view(), name="api_partner_online"),
    path("delivery/assignments/", api.MyDeliveriesView.as_view(), name="api_partner_assignments"),
    path("deliveries/<int:pk>/", api.DeliveryDetailView.as_view(), name="api_delivery_detail"),
    path("deliveries/<int:pk>/accept/", api.AcceptView.as_view(), name="api_delivery_accept"),
    path("deliveries/<int:pk>/reject/", api.RejectView.as_view(), name="api_delivery_reject"),
    path("deliveries/<int:pk>/arrive-store/", api.ArriveStoreView.as_view(), name="api_delivery_arrive_store"),
    path("deliveries/<int:pk>/pickup/", api.PickupView.as_view(), name="api_delivery_pickup"),
    path("deliveries/<int:pk>/arrive/", api.ArriveCustomerView.as_view(), name="api_delivery_arrive"),
    path("deliveries/<int:pk>/complete/", api.CompleteView.as_view(), name="api_delivery_complete"),
    path("deliveries/<int:pk>/fail/", api.FailView.as_view(), name="api_delivery_fail"),
    path("deliveries/<int:pk>/location/", api.LocationView.as_view(), name="api_delivery_location"),
    path("deliveries/<int:pk>/tracking-history/", api.TrackingHistoryView.as_view(), name="api_delivery_history"),
    path("deliveries/<int:pk>/evidence/", api.DeliveryEvidenceView.as_view(), name="api_delivery_evidence"),
    path("evidence-photos/<int:pk>/file/", api.EvidencePhotoFileView.as_view(), name="api_evidence_photo"),
    # customer
    path("orders/<int:pk>/tracking/", api.OrderTrackingView.as_view(), name="api_order_tracking"),
    # store
    path("store/deliveries/", api.StoreDeliveriesView.as_view(), name="api_store_deliveries"),
    path("store/deliveries/<int:pk>/confirm-pickup/", api.StoreConfirmPickupView.as_view(), name="api_store_confirm_pickup"),
    # admin
    path("admin/deliveries/", api.AdminDeliveryListView.as_view(), name="api_admin_deliveries"),
    path("admin/deliveries/<int:pk>/", api.AdminDeliveryDetailView.as_view(), name="api_admin_delivery"),
    path("admin/deliveries/<int:pk>/assign/", api.AdminAssignView.as_view(), name="api_admin_delivery_assign"),
    path("admin/deliveries/<int:pk>/retry/", api.AdminRetryView.as_view(), name="api_admin_delivery_retry"),
    path("admin/deliveries/<int:pk>/cancel/", api.AdminCancelView.as_view(), name="api_admin_delivery_cancel"),
    path("admin/deliveries/<int:pk>/attempts/", api.AdminAttemptsView.as_view(), name="api_admin_delivery_attempts"),
    path("admin/delivery-partners/", api.AdminPartnerListView.as_view(), name="api_admin_partners"),
    path("admin/delivery-partners/<int:pk>/approve/", api.ApprovePartnerView.as_view(), name="api_admin_partner_approve"),
    path("admin/delivery-partners/<int:pk>/reject/", api.RejectPartnerView.as_view(), name="api_admin_partner_reject"),
    path("admin/delivery-partners/<int:pk>/suspend/", api.SuspendPartnerView.as_view(), name="api_admin_partner_suspend"),
]
