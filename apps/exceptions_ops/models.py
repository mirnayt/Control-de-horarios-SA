from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel


class TipoExcepcion(models.TextChoices):
    MEDICO_PROLONGADO = "medico_prolongado", "Médico prolongado"
    OTRO = "otro", "Otro"


class EstadoExcepcion(models.TextChoices):
    SOLICITADA = "solicitada", "Solicitada"
    AUTORIZADA = "autorizada", "Autorizada"
    RECHAZADA = "rechazada", "Rechazada"


class ExcepcionAutorizada(TimeStampedModel):
    """
    Excepción manual (p. ej. médico prolongado).
    Recepción solicita; solo Dirección autoriza o rechaza.
    Sin automatizar congelaciones ni reglas médicas.
    Historial append-only vía JSON.
    """

    alumno = models.ForeignKey(
        "people.Alumno",
        on_delete=models.PROTECT,
        related_name="excepciones",
    )
    tipo = models.CharField(max_length=32, choices=TipoExcepcion.choices)
    motivo = models.CharField(max_length=255)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(null=True, blank=True)
    estado = models.CharField(
        max_length=16,
        choices=EstadoExcepcion.choices,
        default=EstadoExcepcion.SOLICITADA,
    )
    autorizador = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="excepciones_autorizadas",
    )
    notas = models.CharField(max_length=255, blank=True)
    historial = models.JSONField(
        default=list,
        blank=True,
        help_text="Eventos append-only (creación, autorización, rechazo).",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Excepción autorizada"
        verbose_name_plural = "Excepciones autorizadas"

    def __str__(self):
        return f"{self.alumno} {self.tipo} ({self.estado})"

    def clean(self):
        if self.fecha_fin and self.fecha_inicio and self.fecha_fin < self.fecha_inicio:
            raise ValidationError(
                {"fecha_fin": "fecha_fin no puede ser anterior a fecha_inicio."}
            )
