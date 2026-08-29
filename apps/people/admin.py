from django.contrib import admin

from .models import Alumno, Tutor


@admin.register(Tutor)
class TutorAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "telefono", "parentesco", "updated_at")
    search_fields = ("nombre_completo", "telefono")


@admin.register(Alumno)
class AlumnoAdmin(admin.ModelAdmin):
    list_display = ("nombre_completo", "tipo", "estado", "tutor", "updated_at")
    list_filter = ("tipo", "estado")
    search_fields = ("nombre_completo",)
    raw_id_fields = ("tutor",)
