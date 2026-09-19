from django.contrib import admin

from .models import AsignacionRegular, PeriodoCobroRegular, Regular


class AsignacionRegularInline(admin.TabularInline):
    model = AsignacionRegular
    extra = 0
    raw_id_fields = ("horario",)
    readonly_fields = ("created_at", "updated_at")


class PeriodoCobroRegularInline(admin.TabularInline):
    model = PeriodoCobroRegular
    extra = 0
    readonly_fields = (
        "anio",
        "mes",
        "estado",
        "alta_parcial",
        "horas_total",
        "monto",
        "parametro_version",
        "calculado_en",
    )
    can_delete = False
    show_change_link = True


@admin.register(Regular)
class RegularAdmin(admin.ModelAdmin):
    list_display = ("alumno", "sucursal", "plan_horas_semana", "fecha_inicio", "estado", "updated_at")
    list_filter = ("estado", "sucursal")
    search_fields = ("alumno__nombre_completo",)
    raw_id_fields = ("alumno",)
    inlines = [AsignacionRegularInline, PeriodoCobroRegularInline]
    readonly_fields = ("created_at", "updated_at")


@admin.register(AsignacionRegular)
class AsignacionRegularAdmin(admin.ModelAdmin):
    list_display = ("regular", "horario", "activa", "fecha_inicio", "fecha_fin")
    list_filter = ("activa",)
    raw_id_fields = ("regular", "horario")
    search_fields = ("regular__alumno__nombre_completo",)


@admin.register(PeriodoCobroRegular)
class PeriodoCobroRegularAdmin(admin.ModelAdmin):
    list_display = (
        "regular",
        "anio",
        "mes",
        "estado",
        "alta_parcial",
        "horas_total",
        "monto",
        "parametro_version",
    )
    list_filter = ("estado", "alta_parcial", "anio")
    raw_id_fields = ("regular", "parametro_version")
    readonly_fields = (
        "horas_semana",
        "horas_sabado",
        "horas_total",
        "monto",
        "detalle_calculo",
        "calculado_en",
        "created_at",
        "updated_at",
    )
