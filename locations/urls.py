from django.urls import path

from . import views

app_name = "locations"

urlpatterns = [
    path("location/set/", views.set_delivery_location_view, name="set_delivery_location"),
    path(
        "location/clear/",
        views.clear_delivery_location_view,
        name="clear_delivery_location",
    ),
]
