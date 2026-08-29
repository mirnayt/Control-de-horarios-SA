from django.contrib import admin

from .models import EjecucionCobranza, LineaCobro, Pago


class LineaCobroInline(admin.TabularInline):
    model = LineaCobro
    extra = 0
    readonly_fields = (
        "periodo",
        "concepto",
        "monto",
        "estado",
        "parametro_version",
        "reglas_aplicadas",
        "created_at",
    )
    can_delete = False


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "alumno",
        "monto_total",
        "metodo",
        "estado",
        "fecha_pago",
    )
    list_filter = ("estado", "metodo", "fecha_pago")
    search_fields = ("alumno__nombre_completo", "referencia")
    raw_id_fields = ("alumno", "metodo", "parametro_version")
    readonly_fields = (
        "alumno",
        "metodo",
        "monto_total",
        "fecha_pago",
        "parametro_version",
        "reglas_aplicadas",
        "referencia",
        "created_at",
        "updated_at",
    )
    inlines = [LineaCobroInline]


@admin.register(LineaCobro)
class LineaCobroAdmin(admin.ModelAdmin):
    list_display = ("periodo", "concepto", "monto", "estado", "pago")
    list_filter = ("concepto", "estado")
    raw_id_fields = ("periodo", "pago", "parametro_version")
    readonly_fields = (
        "periodo",
        "concepto",
        "monto",
        "parametro_version",
        "reglas_aplicadas",
        "created_at",
        "updated_at",
    )


@admin.register(EjecucionCobranza)
class EjecucionCobranzaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "ejecutado_en")
    readonly_fields = ("fecha", "ejecutado_en", "detalle", "created_at", "updated_at")
