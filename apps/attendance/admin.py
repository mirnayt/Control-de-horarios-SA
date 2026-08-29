from django.contrib import admin

from .models import Asistencia, Compensacion


@admin.register(Asistencia)
class AsistenciaAdmin(admin.ModelAdmin):
    list_display = (
        "alumno",
        "fecha",
        "horario",
        "modalidad",
        "estado",
    )
    list_filter = ("modalidad", "estado")
    search_fields = ("alumno__nombre_completo",)
    raw_id_fields = (
        "alumno",
        "horario",
        "asignacion_regular",
        "reserva_flexi",
        "registrado_por",
    )
    readonly_fields = (
        "detalle",
        "registrado_en",
        "created_at",
        "updated_at",
    )


@admin.register(Compensacion)
class CompensacionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "asistencia",
        "tipo",
        "estado",
        "monto",
        "resuelta_en",
    )
    list_filter = ("tipo", "estado")
    raw_id_fields = (
        "asistencia",
        "autorizada_por",
        "resuelta_por",
    )
    readonly_fields = (
        "historial",
        "resuelta_en",
        "created_at",
        "updated_at",
    )
