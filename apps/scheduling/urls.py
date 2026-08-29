from django.urls import path

from . import views

urlpatterns = [
    path("", views.horarios_list, name="horarios_list"),
]
