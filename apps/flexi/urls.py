from django.urls import path

from . import views

urlpatterns = [
    path("", views.flexi_list, name="flexi_list"),
    path("comprar/", views.flexi_comprar, name="flexi_comprar"),
    path("reservar/", views.flexi_reservar, name="flexi_reservar"),
    path(
        "reservas/<int:reserva_id>/cancelar/",
        views.flexi_cancelar,
        name="flexi_cancelar",
    ),
]
