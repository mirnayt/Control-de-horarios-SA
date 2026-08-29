from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel


class TipoAlumno(models.TextChoices):
    ADULTO = "adulto", "Adulto"
    NINO = "nino", "Niño"


class EstadoAlumno(models.TextChoices):
    ACTIVO = "activo", "Activo"
    PENDIENTE_RENOVACION = "pendiente_renovacion", "Pendiente renovación"
    PAGO_VENCIDO = "pago_vencido", "Pago vencido"
    BAJA_ADMINISTRATIVA = "baja_administrativa", "Baja administrativa"
    BAJA_VOLUNTARIA = "baja_voluntaria", "Baja voluntaria"
    INACTIVO = "inactivo", "Inactivo"


class Tutor(TimeStampedModel):
    """Responsable opcional (mínimo). Sin expediente completo."""

    nombre_completo = models.CharField(max_length=200)
    telefono = models.CharField(max_length=32, blank=True)
    parentesco = models.CharField(max_length=64, blank=True)
    notas = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nombre_completo"]
        verbose_name = "Tutor"
        verbose_name_plural = "Tutores"

    def __str__(self):
        return self.nombre_completo


class Alumno(TimeStampedModel):
    nombre_completo = models.CharField(max_length=200)
    tipo = models.CharField(max_length=16, choices=TipoAlumno.choices)
    estado = models.CharField(
        max_length=32,
        choices=EstadoAlumno.choices,
        default=EstadoAlumno.ACTIVO,
    )
    tutor = models.ForeignKey(
        Tutor,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="alumnos",
    )
    notas = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["nombre_completo"]
        verbose_name = "Alumno"
        verbose_name_plural = "Alumnos"

    def __str__(self):
        return self.nombre_completo

    def clean(self):
        if not (self.nombre_completo or "").strip():
            raise ValidationError({"nombre_completo": "El nombre completo es obligatorio."})
