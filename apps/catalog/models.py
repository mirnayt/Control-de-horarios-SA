from django.db import models

from apps.core.models import TimeStampedModel


class Sucursal(TimeStampedModel):
    IZTACALCO = "iztacalco"
    DEL_VALLE = "del_valle"

    codigo = models.SlugField(max_length=32, unique=True)
    nombre = models.CharField(max_length=64)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Sucursal"
        verbose_name_plural = "Sucursales"

    def __str__(self):
        return self.nombre


class Salon(TimeStampedModel):
    nombre = models.CharField(max_length=64, unique=True)
    sucursal = models.ForeignKey(
        Sucursal,
        on_delete=models.PROTECT,
        related_name="salones",
        null=True,
        blank=True,
    )
    activo = models.BooleanField(default=True)
    notas = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Salón"
        verbose_name_plural = "Salones"

    def __str__(self):
        if self.sucursal_id:
            return f"{self.nombre} ({self.sucursal.nombre})"
        return self.nombre


class Profesor(TimeStampedModel):
    nombre = models.CharField(max_length=120)
    activo = models.BooleanField(default=True)
    notas = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Profesor"
        verbose_name_plural = "Profesores"

    def __str__(self):
        return self.nombre
