from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel


class ModalidadAsistencia(models.TextChoices):
    REGULAR = "regular", "Regular"
    FLEXI = "flexi", "Flexi"


class EstadoAsistencia(models.TextChoices):
    PROGRAMADA = "programada", "Programada"
    ASISTIO = "asistio", "Asistió"
    AUSENTE_ALUMNO = "ausente_alumno", "Ausente (alumno)"
    CANCELADA_POR_SPIRIT = "cancelada_por_spirit", "Cancelada por Spirit"
    PENDIENTE_COMPENSACION = "pendiente_compensacion", "Pendiente compensación"


class TipoCompensacion(models.TextChoices):
    REEMBOLSO = "reembolso", "Reembolso"
    REPOSICION_SIN_COSTO = "reposicion_sin_costo", "Reposición sin costo"
    REPOSICION_CON_DIFERENCIA = "reposicion_con_diferencia", "Reposición con diferencia"


class MotivoCompensacion(models.TextChoices):
    CANCELACION_SPIRIT = "cancelacion_spirit", "Cancelación por Spirit"
    AVISO_ALUMNO = "aviso_alumno", "Aviso de falta del alumno"


class EstadoCompensacion(models.TextChoices):
    PENDIENTE = "pendiente", "Pendiente"
    AGENDADA = "agendada", "Reposición agendada"
    RESUELTA = "resuelta", "Resuelta"


class Asistencia(TimeStampedModel):
    """
    Registro de sesión Regular o Flexi.
    Regular: ausencia del alumno = clase perdida.
    Spirit cancela → pendiente_compensacion (no ausencia, no consume).
    """

    alumno = models.ForeignKey(
        "people.Alumno",
        on_delete=models.PROTECT,
        related_name="asistencias",
    )
    horario = models.ForeignKey(
        "scheduling.Horario",
        on_delete=models.PROTECT,
        related_name="asistencias",
    )
    fecha = models.DateField()
    modalidad = models.CharField(max_length=16, choices=ModalidadAsistencia.choices)
    estado = models.CharField(
        max_length=32,
        choices=EstadoAsistencia.choices,
        default=EstadoAsistencia.PROGRAMADA,
    )
    asignacion_regular = models.ForeignKey(
        "regular.AsignacionRegular",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asistencias",
    )
    reserva_flexi = models.ForeignKey(
        "flexi.ReservaFlexi",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asistencias",
    )
    observaciones = models.CharField(max_length=255, blank=True)
    es_reposicion = models.BooleanField(default=False)
    registrado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="asistencias_registradas",
    )
    registrado_en = models.DateTimeField(null=True, blank=True)
    detalle = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-fecha", "horario__hora_inicio", "-id"]
        verbose_name = "Asistencia"
        verbose_name_plural = "Asistencias"
        constraints = [
            models.UniqueConstraint(
                fields=["alumno", "horario", "fecha"],
                name="uniq_asistencia_alumno_horario_fecha",
            ),
        ]

    def __str__(self):
        return f"{self.alumno} {self.fecha} {self.modalidad} ({self.estado})"

    def clean(self):
        if self.modalidad == ModalidadAsistencia.REGULAR and not self.asignacion_regular_id:
            raise ValidationError(
                {"asignacion_regular": "Obligatoria para modalidad Regular."}
            )
        if self.modalidad == ModalidadAsistencia.FLEXI and not self.reserva_flexi_id:
            raise ValidationError(
                {"reserva_flexi": "Obligatoria para modalidad Flexi."}
            )


class Compensacion(TimeStampedModel):
    """
    Compensación por cancelación de Spirit.
    Dirección autoriza reembolso; Recepción puede registrar reposición sin costo.
    Historial inmutable vía JSON (eventos append-only).
    """

    asistencia = models.OneToOneField(
        Asistencia,
        on_delete=models.PROTECT,
        related_name="compensacion",
    )
    motivo = models.CharField(
        max_length=32,
        choices=MotivoCompensacion.choices,
        default=MotivoCompensacion.CANCELACION_SPIRIT,
    )
    tipo = models.CharField(
        max_length=32,
        choices=TipoCompensacion.choices,
        null=True,
        blank=True,
    )
    estado = models.CharField(
        max_length=16,
        choices=EstadoCompensacion.choices,
        default=EstadoCompensacion.PENDIENTE,
    )
    monto = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Monto de reembolso (si aplica).",
    )
    monto_diferencia = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Cargo por reponer en otra sucursal o duración.",
    )
    asistencia_reposicion = models.ForeignKey(
        Asistencia,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compensacion_origen",
    )
    linea_cobro = models.ForeignKey(
        "billing.LineaCobro",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compensaciones",
    )
    autorizada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compensaciones_autorizadas",
    )
    resuelta_por = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="compensaciones_resueltas",
    )
    resuelta_en = models.DateTimeField(null=True, blank=True)
    notas = models.CharField(max_length=255, blank=True)
    historial = models.JSONField(
        default=list,
        blank=True,
        help_text="Eventos append-only (creación, resolución).",
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = "Compensación"
        verbose_name_plural = "Compensaciones"

    def __str__(self):
        tipo = self.tipo or "sin_tipo"
        return f"Compensación {self.asistencia_id} {tipo} ({self.estado})"
