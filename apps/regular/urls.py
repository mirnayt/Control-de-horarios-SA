from django.urls import path

from . import views

urlpatterns = [
    path("", views.regular_list, name="regular_list"),
    path("nuevo/", views.regular_alta, name="regular_alta"),
]
