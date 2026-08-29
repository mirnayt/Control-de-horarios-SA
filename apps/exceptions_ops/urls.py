from django.urls import path

from . import views

urlpatterns = [
    path("", views.excepciones_list, name="excepciones_list"),
    path("nueva/", views.excepcion_nueva, name="excepcion_nueva"),
    path("<int:pk>/accion/", views.excepcion_accion, name="excepcion_accion"),
]
