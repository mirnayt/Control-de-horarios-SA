from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel


class ConceptoLinea(models.TextChoices):
    MENSUALIDAD = "mensualidad", "Mensualidad"
    RECARGO = "recargo", "Recargo"
    INSCRIPCION = "inscripcion", "Inscripción"


class EstadoLineaCobro(models.TextChoices):
    PENDIENTE = "pendiente", "Pendiente"
    PAGADA = "pagada", "Pagada"
    CANCELADA = "cancelada", "Cancelada"


class EstadoPago(models.TextChoices):
    CONFIRMADO = "confirmado", "Confirmado"
    ANULADO = "anulado", "Anulado"


class LineaCobro(TimeStampedModel):
    """
    Concepto cobrable con snapshot inmutable de monto y reglas.

    - Regular: Unique (periodo, concepto) cuando hay periodo.
    - Inscripción: Unique (alumno, concepto=inscripcion); sin periodo.
    """

    periodo = models.ForeignKey(
        "regular.PeriodoCobroRegular",
        on_delete=models.PROTECT,
        related_name="lineas_cobro",
        null=True,
        blank=True,
    )
    alumno = models.ForeignKey(
        "people.Alumno",
        on_delete=models.PROTECT,
        related_name="lineas_cobro",
        null=True,
        blank=True,
        help_text="Obligatorio para inscripción; en líneas de periodo se deriva del Regular.",
    )
    concepto = models.CharField(max_length=32, choices=ConceptoLinea.choices)
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    estado = models.CharField(
        max_length=16,
        choices=EstadoLineaCobro.choices,
        default=EstadoLineaCobro.PENDIENTE,
    )
    parametro_version = models.ForeignKey(
        "params.ParametroVersion",
        on_delete=models.PROTECT,
        related_name="lineas_cobro",
    )
    reglas_aplicadas = models.JSONField(
        default=dict,
        blank=True,
        help_text="Snapshot de tarifas/días/reglas al crear la línea.",
    )
    pago = models.ForeignKey(
        "billing.Pago",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="lineas",
    )

    class Meta:
        ordering = ["periodo_id", "concepto"]
        verbose_name = "Línea de cobro"
        verbose_name_plural = "Líneas de cobro"
        constraints = [
            models.UniqueConstraint(
                fields=["periodo", "concepto"],
                condition=models.Q(periodo__isnull=False),
                name="uniq_linea_cobro_periodo_concepto",
            ),
            models.UniqueConstraint(
                fields=["alumno", "concepto"],
                condition=models.Q(concepto="inscripcion"),
                name="uniq_linea_cobro_inscripcion_alumno",
            ),
        ]

    def __str__(self):
        if self.periodo_id:
            return f"{self.concepto} {self.periodo} = {self.monto}"
        return f"{self.concepto} alumno={self.alumno_id} = {self.monto}"

    def save(self, *args, **kwargs):
        if self.pk:
            prev = LineaCobro.objects.filter(pk=self.pk).values(
                "monto",
                "reglas_aplicadas",
                "concepto",
                "periodo_id",
                "alumno_id",
                "parametro_version_id",
            ).first()
            if prev and (
                prev["monto"] != self.monto
                or prev["reglas_aplicadas"] != self.reglas_aplicadas
                or prev["concepto"] != self.concepto
                or prev["periodo_id"] != self.periodo_id
                or prev["alumno_id"] != self.alumno_id
                or prev["parametro_version_id"] != self.parametro_version_id
            ):
                raise ValidationError(
                    "LineaCobro es inmutable en monto, reglas, concepto, periodo y alumno."
                )
        super().save(*args, **kwargs)


class Pago(TimeStampedModel):
    """Registro inmutable de un pago (MVP: efectivo / transferencia)."""

    alumno = models.ForeignKey(
        "people.Alumno",
        on_delete=models.PROTECT,
        related_name="pagos",
    )
    metodo = models.ForeignKey(
        "params.MetodoPagoCatalogo",
        on_delete=models.PROTECT,
        related_name="pagos",
    )
    estado = models.CharField(
        max_length=16,
        choices=EstadoPago.choices,
        default=EstadoPago.CONFIRMADO,
    )
    monto_total = models.DecimalField(max_digits=12, decimal_places=2)
    fecha_pago = models.DateField(
        help_text="Fecha civil del pago (America/Mexico_City).",
    )
    referencia = models.CharField(max_length=128, blank=True)
    notas = models.CharField(max_length=255, blank=True)
    parametro_version = models.ForeignKey(
        "params.ParametroVersion",
        on_delete=models.PROTECT,
        related_name="pagos",
    )
    reglas_aplicadas = models.JSONField(
        default=dict,
        blank=True,
        help_text="Snapshot del contexto de cobranza al registrar el pago.",
    )

    class Meta:
        ordering = ["-fecha_pago", "-id"]
        verbose_name = "Pago"
        verbose_name_plural = "Pagos"

    def __str__(self):
        return f"Pago {self.alumno} {self.monto_total} ({self.fecha_pago})"

    def save(self, *args, **kwargs):
        if self.pk:
            prev = Pago.objects.filter(pk=self.pk).values(
                "alumno_id",
                "metodo_id",
                "monto_total",
                "fecha_pago",
                "parametro_version_id",
                "reglas_aplicadas",
                "referencia",
            ).first()
            if prev and (
                prev["alumno_id"] != self.alumno_id
                or prev["metodo_id"] != self.metodo_id
                or prev["monto_total"] != self.monto_total
                or prev["fecha_pago"] != self.fecha_pago
                or prev["parametro_version_id"] != self.parametro_version_id
                or prev["reglas_aplicadas"] != self.reglas_aplicadas
                or prev["referencia"] != self.referencia
            ):
                raise ValidationError(
                    "Pago es historial inmutable; solo se permite cambiar estado/notas."
                )
        super().save(*args, **kwargs)


class EjecucionCobranza(TimeStampedModel):
    """Marca de corrida diaria (idempotencia a nivel fecha local)."""

    fecha = models.DateField(
        unique=True,
        help_text="Día civil America/Mexico_City procesado.",
    )
    ejecutado_en = models.DateTimeField()
    detalle = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Ejecución de cobranza"
        verbose_name_plural = "Ejecuciones de cobranza"

    def __str__(self):
        return f"Cobranza {self.fecha}"
