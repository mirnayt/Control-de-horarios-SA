from django.contrib import admin

from .models import Profesor, Salon, Sucursal


@admin.register(Sucursal)
class SucursalAdmin(admin.ModelAdmin):
    list_display = ("nombre", "codigo", "activo", "updated_at")
    list_filter = ("activo",)
    search_fields = ("nombre", "codigo")


@admin.register(Salon)
class SalonAdmin(admin.ModelAdmin):
    list_display = ("nombre", "sucursal", "activo", "updated_at")
    list_filter = ("activo", "sucursal")
    search_fields = ("nombre",)


@admin.register(Profesor)
class ProfesorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo", "updated_at")
    list_filter = ("activo",)
    search_fields = ("nombre",)
