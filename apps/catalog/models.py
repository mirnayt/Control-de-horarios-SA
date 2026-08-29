from django.db import models

from apps.core.models import TimeStampedModel


class Salon(TimeStampedModel):
    nombre = models.CharField(max_length=64, unique=True)
    activo = models.BooleanField(default=True)
    notas = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Salón"
        verbose_name_plural = "Salones"

    def __str__(self):
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
