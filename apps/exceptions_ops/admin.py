from django.contrib import admin

from .models import ExcepcionAutorizada


@admin.register(ExcepcionAutorizada)
class ExcepcionAutorizadaAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "alumno",
        "tipo",
        "estado",
        "fecha_inicio",
        "fecha_fin",
        "autorizador",
    )
    list_filter = ("tipo", "estado")
    search_fields = ("alumno__nombre_completo", "motivo")
    raw_id_fields = ("alumno", "autorizador")
    readonly_fields = ("historial", "created_at", "updated_at")
