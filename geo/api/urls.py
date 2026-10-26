from django.urls import path

from . import views_customer as c
from . import views_ops as o
from . import views_public as p

app_name = "geo_api"

urlpatterns = [
    # Configuration, session and geocoding
    path("config/maps/", p.MapsConfigView.as_view(), name="maps_config"),
    path("auth/session/", p.SessionView.as_view(), name="session"),
    path("auth/login/", p.LoginView.as_view(), name="login"),
    path("auth/logout/", p.LogoutView.as_view(), name="logout"),
    path("geo/reverse-geocode/", p.ReverseGeocodeView.as_view(), name="reverse_geocode"),
    path("geo/geocode/", p.ForwardGeocodeView.as_view(), name="geocode"),
    path("stores/nearby/", p.NearbyStoresView.as_view(), name="nearby_stores"),
    # Customer
    path("customer/addresses/", c.AddressListCreateView.as_view(), name="addresses"),
    path("customer/addresses/<int:pk>/", c.AddressDetailView.as_view(), name="address_detail"),
    path("customer/addresses/<int:pk>/default/", c.AddressDefaultView.as_view(), name="address_default"),
    path("customer/checkout/summary/", c.CheckoutSummaryView.as_view(), name="checkout_summary"),
    path("customer/delivery-quote/", c.DeliveryQuoteView.as_view(), name="delivery_quote"),
    path("customer/checkout/", c.PlaceOrderView.as_view(), name="checkout"),
    path("customer/orders/<str:order_number>/tracking/", c.OrderTrackingView.as_view(), name="order_tracking"),
    # Store portal
    path("store/location/", o.StoreLocationView.as_view(), name="store_location"),
    path("store/orders/", o.StoreOrdersView.as_view(), name="store_orders"),
    # Delivery partner
    path("rider/assignments/", o.RiderAssignmentsView.as_view(), name="rider_assignments"),
    path("rider/assignments/<int:pk>/", o.RiderAssignmentDetailView.as_view(), name="rider_assignment"),
    path("rider/assignments/<int:pk>/advance/", o.RiderAdvanceView.as_view(), name="rider_advance"),
    # Administration
    path("admin/maps/status/", o.MapsStatusView.as_view(), name="admin_maps_status"),
    path("admin/maps/health-check/", o.MapsHealthCheckView.as_view(), name="admin_health_check"),
    path("admin/stores/locations/", o.AdminStoreLocationsView.as_view(), name="admin_store_locations"),
    path("admin/stores/<int:pk>/location/", o.AdminStoreLocationDetailView.as_view(), name="admin_store_location"),
    path("admin/pricing/configs/", o.PricingConfigView.as_view(), name="admin_pricing_configs"),
    path("admin/pricing/simulate/", o.PricingSimulatorView.as_view(), name="admin_pricing_simulate"),
    path("admin/assignments/", o.AdminAssignmentsView.as_view(), name="admin_assignments"),
]
