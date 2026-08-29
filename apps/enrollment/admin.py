from django.contrib import admin

from .models import Inscripcion


@admin.register(Inscripcion)
class InscripcionAdmin(admin.ModelAdmin):
    list_display = ("alumno", "fecha_original", "monto", "pagada", "updated_at")
    list_filter = ("pagada",)
    search_fields = ("alumno__nombre_completo",)
    raw_id_fields = ("alumno", "parametro_version")
    readonly_fields = ("fecha_original", "monto", "parametro_version", "created_at", "updated_at")
