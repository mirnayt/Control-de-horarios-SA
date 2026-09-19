from django.contrib import admin

from .models import (
    BloqueTarifaAdulto,
    MetodoPagoCatalogo,
    ParametroVersion,
    TarifaSucursal,
    VigenciaFlexi,
)


class BloqueTarifaAdultoInline(admin.TabularInline):
    model = BloqueTarifaAdulto
    extra = 0


class VigenciaFlexiInline(admin.TabularInline):
    model = VigenciaFlexi
    extra = 0


class TarifaSucursalInline(admin.TabularInline):
    model = TarifaSucursal
    extra = 0


@admin.register(ParametroVersion)
class ParametroVersionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "vigente_desde",
        "tarifa_hora_adulto",
        "tarifa_hora_nino",
        "flexi_min_sesiones",
        "flexi_max_sesiones",
        "sabado_adulto_sin_descuento_progresivo",
    )
    inlines = [BloqueTarifaAdultoInline, VigenciaFlexiInline, TarifaSucursalInline]


@admin.register(MetodoPagoCatalogo)
class MetodoPagoCatalogoAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "activo")
    list_filter = ("activo",)
