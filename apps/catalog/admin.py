from django.contrib import admin

from .models import Profesor, Salon


@admin.register(Salon)
class SalonAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo", "updated_at")
    list_filter = ("activo",)
    search_fields = ("nombre",)


@admin.register(Profesor)
class ProfesorAdmin(admin.ModelAdmin):
    list_display = ("nombre", "activo", "updated_at")
    list_filter = ("activo",)
    search_fields = ("nombre",)
