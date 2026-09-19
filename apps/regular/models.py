from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel


class EstadoRegular(models.TextChoices):
    ACTIVO = "activo", "Activo"
    BAJA_VOLUNTARIA = "baja_voluntaria", "Baja voluntaria"
    LIBERADO = "liberado", "Lugar liberado"
    INACTIVO = "inactivo", "Inactivo"


class EstadoPeriodoCobro(models.TextChoices):
    """Estados del ciclo 1–7 / 8–10 / 11 (pagos reales en etapas posteriores)."""

    PENDIENTE = "pendiente", "Pendiente"
    PARCIAL = "parcial", "Abono parcial"
    PAGADO_A_TIEMPO = "pagado_a_tiempo", "Pagado a tiempo"
    PAGADO_CON_RECARGO = "pagado_con_recargo", "Pagado con recargo"
    VENCIDO = "vencido", "Vencido"
    LIBERADO = "liberado", "Lugar liberado"


class Regular(TimeStampedModel):
    """
    Plan Regular de un alumno: 1–3 horarios fijos.
    La inasistencia del alumno pierde la clase (asistencias: etapa posterior).
    """

    alumno = models.ForeignKey(
        "people.Alumno",
        on_delete=models.PROTECT,
        related_name="regulares",
    )
    sucursal = models.ForeignKey(
        "catalog.Sucursal",
        on_delete=models.PROTECT,
        related_name="regulares",
        null=True,
        blank=True,
    )
    plan_horas_semana = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Horas semanales del plan (2 o 3 en Iztacalco).",
    )
    es_tarifa_fundadora = models.BooleanField(
        default=False,
        help_text="Del Valle: primeros alumnos ($1440). Si False, tarifa siguiente ($1500).",
    )
    codigo_tarifa = models.SlugField(max_length=32, blank=True)
    fecha_inicio = models.DateField()
    estado = models.CharField(
        max_length=32,
        choices=EstadoRegular.choices,
        default=EstadoRegular.ACTIVO,
    )
    notas = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-fecha_inicio", "-id"]
        verbose_name = "Regular"
        verbose_name_plural = "Regulares"

    def __str__(self):
        return f"Regular {self.alumno} ({self.fecha_inicio})"

    @property
    def activo(self) -> bool:
        return self.estado == EstadoRegular.ACTIVO


class AsignacionRegular(TimeStampedModel):
    """Lugar fijo en un horario. `activa=False` libera el cupo (Etapa 6)."""

    regular = models.ForeignKey(
        Regular,
        on_delete=models.CASCADE,
        related_name="asignaciones",
    )
    horario = models.ForeignKey(
        "scheduling.Horario",
        on_delete=models.PROTECT,
        related_name="asignaciones_regular",
    )
    activa = models.BooleanField(default=True)
    fecha_inicio = models.DateField()
    fecha_fin = models.DateField(
        null=True,
        blank=True,
        help_text="Fecha de liberación lógica del lugar (si aplica).",
    )

    class Meta:
        ordering = ["horario__dia", "horario__hora_inicio"]
        verbose_name = "Asignación Regular"
        verbose_name_plural = "Asignaciones Regular"
        constraints = [
            models.UniqueConstraint(
                fields=["regular", "horario"],
                condition=models.Q(activa=True),
                name="uniq_asignacion_regular_activa",
            ),
        ]

    def __str__(self):
        estado = "activa" if self.activa else "liberada"
        return f"{self.regular.alumno} → {self.horario} ({estado})"

    def clean(self):
        if self.fecha_fin and self.fecha_inicio and self.fecha_fin < self.fecha_inicio:
            raise ValidationError({"fecha_fin": "No puede ser anterior a fecha_inicio."})


class PeriodoCobroRegular(TimeStampedModel):
    """
    Mensualidad calculada con snapshot de tarifas y desglose.
    Reproducible aunque cambien ParametroVersion después.
    """

    regular = models.ForeignKey(
        Regular,
        on_delete=models.CASCADE,
        related_name="periodos_cobro",
    )
    anio = models.PositiveSmallIntegerField()
    mes = models.PositiveSmallIntegerField()
    estado = models.CharField(
        max_length=32,
        choices=EstadoPeriodoCobro.choices,
        default=EstadoPeriodoCobro.PENDIENTE,
    )
    alta_parcial = models.BooleanField(
        default=False,
        help_text="True si el alta del mes fue después del día 7 (cobro proporcional).",
    )
    horas_semana = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    horas_sabado = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    horas_total = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    monto = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    parametro_version = models.ForeignKey(
        "params.ParametroVersion",
        on_delete=models.PROTECT,
        related_name="periodos_cobro_regular",
    )
    detalle_calculo = models.JSONField(
        default=dict,
        blank=True,
        help_text="Snapshot: ocurrencias por horario, tarifas usadas, reglas aplicadas.",
    )
    calculado_en = models.DateTimeField()

    class Meta:
        ordering = ["-anio", "-mes"]
        verbose_name = "Periodo de cobro Regular"
        verbose_name_plural = "Periodos de cobro Regular"
        constraints = [
            models.UniqueConstraint(
                fields=["regular", "anio", "mes"],
                name="uniq_periodo_cobro_regular_mes",
            ),
            models.CheckConstraint(
                check=models.Q(mes__gte=1, mes__lte=12),
                name="periodo_cobro_regular_mes_valido",
            ),
        ]

    def __str__(self):
        return f"{self.regular.alumno} {self.anio}-{self.mes:02d} ({self.estado})"
