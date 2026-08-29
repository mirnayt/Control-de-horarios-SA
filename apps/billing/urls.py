from django.urls import path

from . import views

urlpatterns = [
    path("", views.pagos_list, name="pagos_list"),
    path("periodo/<int:periodo_id>/", views.pago_periodo, name="pago_periodo"),
]
