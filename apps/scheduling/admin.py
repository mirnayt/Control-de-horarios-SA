from django.contrib import admin

from .models import Horario


@admin.register(Horario)
class HorarioAdmin(admin.ModelAdmin):
    list_display = (
        "dia",
        "hora_inicio",
        "hora_fin",
        "duracion_minutos",
        "capacidad",
        "tipo_alumno",
        "activo",
        "salon",
        "profesor",
    )
    list_filter = ("activo", "dia", "tipo_alumno", "salon", "profesor")
    search_fields = ("salon__nombre", "profesor__nombre")
