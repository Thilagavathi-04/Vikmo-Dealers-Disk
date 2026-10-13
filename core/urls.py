
from django.urls import path

from . import views

urlpatterns = [
    path("health/", views.health),
    path("products/", views.products),
    path("products/<str:sku>/", views.product_detail),
    path("inventory/<str:sku>/", views.inventory_update),
    path("dealers/", views.dealers),
    path("dealers/<int:dealer_id>/", views.dealer_detail),
    path("orders/", views.orders),
    path("orders/<str:order_number>/", views.order_detail),
    path("assistant/chat/", views.assistant_chat),
    path("forecast/<str:sku>/", views.forecast_detail),
    path("reorder-suggestions/", views.reorder_suggestions),
]
