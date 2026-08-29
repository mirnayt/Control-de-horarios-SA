from django.urls import path

from . import views

urlpatterns = [
    path("", views.alumnos_list, name="alumnos_list"),
    path("nuevo/", views.alumno_alta, name="alumno_alta"),
    path("<int:pk>/", views.alumno_detail, name="alumno_detail"),
]
