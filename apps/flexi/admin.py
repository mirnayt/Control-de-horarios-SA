from django.contrib import admin

from .models import EjecucionVencimientoFlexi, PaqueteFlexi, ReservaFlexi


class ReservaFlexiInline(admin.TabularInline):
    model = ReservaFlexi
    extra = 0
    raw_id_fields = ("horario",)
    readonly_fields = (
        "fecha_clase",
        "hora_inicio",
        "sesiones_usadas",
        "estado",
        "reservada_en",
        "cancelada_en",
        "created_at",
    )
    can_delete = False
    show_change_link = True


@admin.register(PaqueteFlexi)
class PaqueteFlexiAdmin(admin.ModelAdmin):
    list_display = (
        "alumno",
        "sesiones_compradas",
        "sesiones_disponibles",
        "estado",
        "fecha_compra",
        "fecha_fin",
        "monto",
    )
    list_filter = ("estado", "es_renovacion")
    search_fields = ("alumno__nombre_completo",)
    raw_id_fields = ("alumno", "parametro_version", "pago")
    readonly_fields = (
        "sesiones_consumidas",
        "sesiones_vencidas",
        "meses_vigencia",
        "monto",
        "vencido_en",
        "detalle",
        "created_at",
        "updated_at",
    )
    inlines = [ReservaFlexiInline]


@admin.register(ReservaFlexi)
class ReservaFlexiAdmin(admin.ModelAdmin):
    list_display = (
        "paquete",
        "horario",
        "fecha_clase",
        "estado",
        "sesiones_usadas",
    )
    list_filter = ("estado",)
    raw_id_fields = ("paquete", "horario")
    search_fields = ("paquete__alumno__nombre_completo",)


@admin.register(EjecucionVencimientoFlexi)
class EjecucionVencimientoFlexiAdmin(admin.ModelAdmin):
    list_display = ("fecha", "ejecutado_en")
    readonly_fields = (
        "fecha",
        "ejecutado_en",
        "detalle",
        "created_at",
        "updated_at",
    )
