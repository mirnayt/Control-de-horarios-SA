from django.urls import path

from . import views

urlpatterns = [
    path("", views.asistencias_list, name="asistencias_list"),
    path("programar/", views.asistencia_programar, name="asistencia_programar"),
    path("<int:pk>/accion/", views.asistencia_accion, name="asistencia_accion"),
    path(
        "compensaciones/",
        views.compensaciones_list,
        name="compensaciones_list",
    ),
    path(
        "compensaciones/<int:pk>/accion/",
        views.compensacion_accion,
        name="compensacion_accion",
    ),
]
