from django.contrib import admin

from .models import EjecucionCobranza, LineaCobro, Pago, PagoAplicacion


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


class PagoAplicacionInline(admin.TabularInline):
    model = PagoAplicacion
    extra = 0
    readonly_fields = ("linea", "monto", "created_at")
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
        "requiere_factura",
    )
    list_filter = ("estado", "metodo", "fecha_pago", "requiere_factura")
    search_fields = ("alumno__nombre_completo", "referencia")
    raw_id_fields = ("alumno", "metodo", "parametro_version")
    readonly_fields = (
        "alumno",
        "metodo",
        "monto_total",
        "monto_base",
        "monto_iva",
        "fecha_pago",
        "parametro_version",
        "reglas_aplicadas",
        "referencia",
        "created_at",
        "updated_at",
    )
    inlines = [PagoAplicacionInline, LineaCobroInline]


@admin.register(LineaCobro)
class LineaCobroAdmin(admin.ModelAdmin):
    list_display = ("periodo", "concepto", "monto", "estado", "pago")
    list_filter = ("concepto", "estado")
    raw_id_fields = ("periodo", "pago", "parametro_version", "alumno")
    readonly_fields = (
        "periodo",
        "concepto",
        "monto_calculado",
        "parametro_version",
        "reglas_aplicadas",
        "created_at",
        "updated_at",
    )


@admin.register(EjecucionCobranza)
class EjecucionCobranzaAdmin(admin.ModelAdmin):
    list_display = ("fecha", "ejecutado_en")
    readonly_fields = ("fecha", "ejecutado_en", "detalle", "created_at", "updated_at")
