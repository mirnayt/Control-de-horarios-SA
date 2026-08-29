from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel


class EstadoPaqueteFlexi(models.TextChoices):
    ACTIVO = "activo", "Activo"
    AGOTADO = "agotado", "Agotado"
    VENCIDO = "vencido", "Vencido"


class EstadoReservaFlexi(models.TextChoices):
    RESERVADA = "reservada", "Reservada"
    CANCELADA = "cancelada", "Cancelada (con devolución)"
    CANCELADA_TARDE = "cancelada_tarde", "Cancelada (<24h, consume)"
    NO_SHOW = "no_show", "No-show (consume)"
    CONSUMIDA = "consumida", "Consumida"


class PaqueteFlexi(TimeStampedModel):
    """
    Paquete de sesiones Flexi (5–30), tarifa fija $/h, vigencia por tabla.
    Pago sin reserva; Regular + Flexi simultáneos permitidos.
    """

    alumno = models.ForeignKey(
        "people.Alumno",
        on_delete=models.PROTECT,
        related_name="paquetes_flexi",
    )
    sesiones_compradas = models.PositiveSmallIntegerField()
    sesiones_disponibles = models.PositiveSmallIntegerField()
    sesiones_consumidas = models.PositiveSmallIntegerField(default=0)
    sesiones_vencidas = models.PositiveSmallIntegerField(default=0)
    meses_vigencia = models.PositiveSmallIntegerField()
    fecha_compra = models.DateField()
    fecha_fin = models.DateField(
        help_text="Último día de vigencia inclusive (America/Mexico_City).",
    )
    estado = models.CharField(
        max_length=16,
        choices=EstadoPaqueteFlexi.choices,
        default=EstadoPaqueteFlexi.ACTIVO,
    )
    monto = models.DecimalField(max_digits=12, decimal_places=2)
    parametro_version = models.ForeignKey(
        "params.ParametroVersion",
        on_delete=models.PROTECT,
        related_name="paquetes_flexi",
    )
    pago = models.ForeignKey(
        "billing.Pago",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="paquetes_flexi",
    )
    es_renovacion = models.BooleanField(default=False)
    detalle = models.JSONField(default=dict, blank=True)
    vencido_en = models.DateTimeField(
        null=True,
        blank=True,
        help_text="Marca de vencimiento (idempotencia del job).",
    )

    class Meta:
        ordering = ["-fecha_compra", "-id"]
        verbose_name = "Paquete Flexi"
        verbose_name_plural = "Paquetes Flexi"
        constraints = [
            models.CheckConstraint(
                check=models.Q(sesiones_compradas__gte=1),
                name="paquete_flexi_sesiones_compradas_positivo",
            ),
            models.CheckConstraint(
                check=models.Q(sesiones_disponibles__gte=0),
                name="paquete_flexi_sesiones_disponibles_no_neg",
            ),
        ]

    def __str__(self):
        return (
            f"Flexi {self.alumno} {self.sesiones_compradas}ses "
            f"({self.estado})"
        )

    @property
    def activo(self) -> bool:
        return self.estado == EstadoPaqueteFlexi.ACTIVO

    def clean(self):
        total = (
            self.sesiones_disponibles
            + self.sesiones_consumidas
            + self.sesiones_vencidas
        )
        if self.sesiones_compradas and total != self.sesiones_compradas:
            raise ValidationError(
                "disponibles + consumidas + vencidas debe igualar compradas."
            )


class ReservaFlexi(TimeStampedModel):
    """Reserva puntual contra cupo; cancela ≥24h devuelve sesión."""

    paquete = models.ForeignKey(
        PaqueteFlexi,
        on_delete=models.PROTECT,
        related_name="reservas",
    )
    horario = models.ForeignKey(
        "scheduling.Horario",
        on_delete=models.PROTECT,
        related_name="reservas_flexi",
    )
    fecha_clase = models.DateField()
    hora_inicio = models.TimeField()
    sesiones_usadas = models.PositiveSmallIntegerField(
        default=1,
        help_text="Horas enteras del horario consumidas como sesiones.",
    )
    estado = models.CharField(
        max_length=32,
        choices=EstadoReservaFlexi.choices,
        default=EstadoReservaFlexi.RESERVADA,
    )
    reservada_en = models.DateTimeField()
    cancelada_en = models.DateTimeField(null=True, blank=True)
    detalle = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["fecha_clase", "hora_inicio", "-id"]
        verbose_name = "Reserva Flexi"
        verbose_name_plural = "Reservas Flexi"
        constraints = [
            models.UniqueConstraint(
                fields=["paquete", "horario", "fecha_clase"],
                condition=models.Q(estado="reservada"),
                name="uniq_reserva_flexi_activa",
            ),
        ]

    def __str__(self):
        return (
            f"{self.paquete.alumno} → {self.horario} "
            f"{self.fecha_clase} ({self.estado})"
        )

    def clean(self):
        if self.sesiones_usadas < 1:
            raise ValidationError({"sesiones_usadas": "Debe ser al menos 1."})


class EjecucionVencimientoFlexi(TimeStampedModel):
    """Marca de corrida diaria de vencimiento (idempotencia por fecha local)."""

    fecha = models.DateField(
        unique=True,
        help_text="Día civil America/Mexico_City procesado.",
    )
    ejecutado_en = models.DateTimeField()
    detalle = models.JSONField(default=dict, blank=True)

    class Meta:
        ordering = ["-fecha"]
        verbose_name = "Ejecución vencimiento Flexi"
        verbose_name_plural = "Ejecuciones vencimiento Flexi"

    def __str__(self):
        return f"Vencimiento Flexi {self.fecha}"
