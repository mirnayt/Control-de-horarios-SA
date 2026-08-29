from django.db import models

from apps.core.models import TimeStampedModel


class Inscripcion(TimeStampedModel):
    """
    Inscripción única por alumno.
    fecha_original y monto quedan como historial permanente;
    un regreso post-baja no crea otra fila ni nuevo cobro.
    """

    alumno = models.OneToOneField(
        "people.Alumno",
        on_delete=models.PROTECT,
        related_name="inscripcion",
    )
    fecha_original = models.DateField(
        help_text="Fecha de la primera inscripción (inmutable en reglas de negocio).",
    )
    monto = models.DecimalField(
        max_digits=10,
        decimal_places=2,
        help_text="Cuota cobrada al alta (snapshot; configurable vía ParametroVersion).",
    )
    pagada = models.BooleanField(default=True)
    parametro_version = models.ForeignKey(
        "params.ParametroVersion",
        on_delete=models.PROTECT,
        related_name="inscripciones",
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = "Inscripción"
        verbose_name_plural = "Inscripciones"

    def __str__(self):
        return f"Inscripción {self.alumno} ({self.fecha_original})"
