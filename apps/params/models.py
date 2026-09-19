from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.core.models import TimeStampedModel


class ParametroVersion(TimeStampedModel):
    """
    Snapshot versionado de reglas configurables.
    Los cobros futuros deben apuntar a la versión vigente al momento del pago.
    """

    vigente_desde = models.DateTimeField(
        help_text="Inicio de vigencia (America/Mexico_City vía USE_TZ).",
    )
    notas = models.CharField(max_length=255, blank=True)

    # Tarifas base
    tarifa_hora_adulto = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("120.00"))
    tarifa_hora_nino = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("110.00"))
    precio_clase_suelta = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("500.00"))
    cuota_inscripcion = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("500.00"))
    monto_recargo = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("100.00"))

    # Cobranza (días del mes civil)
    dia_pago_normal_fin = models.PositiveSmallIntegerField(default=7)
    dia_recargo_inicio = models.PositiveSmallIntegerField(default=8)
    dia_recargo_fin = models.PositiveSmallIntegerField(default=10)
    dia_liberacion = models.PositiveSmallIntegerField(default=11)

    # Flexi
    flexi_min_sesiones = models.PositiveSmallIntegerField(default=5)
    flexi_max_sesiones = models.PositiveSmallIntegerField(default=30)
    flexi_tarifa_hora = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("120.00"))
    flexi_cancelacion_horas = models.PositiveSmallIntegerField(
        default=24,
        help_text="Horas de anticipación para cancelar sin perder sesión.",
    )

    # Regular sábado adulto: siempre tarifa base, sin bloques progresivos.
    sabado_adulto_sin_descuento_progresivo = models.BooleanField(default=True)

    tasa_iva = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=Decimal("0.1600"),
        help_text="IVA a agregar cuando el cliente requiere factura (0.16 = 16%).",
    )
    horas_aviso_reposicion = models.PositiveSmallIntegerField(
        default=24,
        help_text="Horas de anticipación para avisar falta y conservar reposición.",
    )

    class Meta:
        ordering = ["-vigente_desde"]
        verbose_name = "Versión de parámetros"
        verbose_name_plural = "Versiones de parámetros"

    def __str__(self):
        return f"Params desde {self.vigente_desde.isoformat()}"

    def clean(self):
        if self.flexi_min_sesiones > self.flexi_max_sesiones:
            raise ValidationError("flexi_min_sesiones no puede ser mayor que flexi_max_sesiones.")
        if not (1 <= self.dia_pago_normal_fin < self.dia_recargo_inicio <= self.dia_recargo_fin < self.dia_liberacion <= 31):
            raise ValidationError("Días de cobranza inconsistentes (1–7 / 8–10 / 11).")

    @classmethod
    def vigente(cls, en=None):
        """Devuelve la versión vigente en el instante dado (default: ahora)."""
        en = en or timezone.now()
        return (
            cls.objects.filter(vigente_desde__lte=en)
            .order_by("-vigente_desde")
            .first()
        )


class BloqueTarifaAdulto(models.Model):
    """Tramos progresivos Regular adultos (no aplica a sábado adulto)."""

    parametro_version = models.ForeignKey(
        ParametroVersion,
        on_delete=models.CASCADE,
        related_name="bloques_adulto",
    )
    orden = models.PositiveSmallIntegerField()
    horas_max = models.PositiveSmallIntegerField(help_text="Horas cubiertas por este bloque.")
    tarifa_hora = models.DecimalField(max_digits=10, decimal_places=2)

    class Meta:
        ordering = ["orden"]
        unique_together = [("parametro_version", "orden")]
        verbose_name = "Bloque tarifa adulto"
        verbose_name_plural = "Bloques tarifa adulto"

    def __str__(self):
        return f"Bloque {self.orden}: {self.horas_max}h @ {self.tarifa_hora}"


class VigenciaFlexi(models.Model):
    """Tabla N sesiones → meses de vigencia."""

    parametro_version = models.ForeignKey(
        ParametroVersion,
        on_delete=models.CASCADE,
        related_name="vigencias_flexi",
    )
    sesiones_min = models.PositiveSmallIntegerField()
    sesiones_max = models.PositiveSmallIntegerField()
    meses_vigencia = models.PositiveSmallIntegerField()

    class Meta:
        ordering = ["sesiones_min"]
        verbose_name = "Vigencia Flexi"
        verbose_name_plural = "Vigencias Flexi"

    def __str__(self):
        return f"{self.sesiones_min}-{self.sesiones_max} → {self.meses_vigencia} mes(es)"

    def clean(self):
        if self.sesiones_min > self.sesiones_max:
            raise ValidationError("sesiones_min no puede ser mayor que sesiones_max.")


class CodigoTarifa(models.TextChoices):
    MENSUAL_2H = "mensual_2h", "Mensualidad 2 horas"
    MENSUAL_3H = "mensual_3h", "Mensualidad 3 horas"
    PACK_NUEVO_4X3 = "pack_nuevo_4x3", "Pack nuevo 4 sesiones × 3 h"
    SESION_3H = "sesion_3h", "Sesión 3 horas"
    MENSUAL_FUNDADOR = "mensual_fundador", "Mensualidad fundador"
    MENSUAL_SIGUIENTE = "mensual_siguiente", "Mensualidad siguiente"


class TarifaSucursal(models.Model):
    """Monto de catálogo por sucursal (snapshot vía ParametroVersion)."""

    parametro_version = models.ForeignKey(
        ParametroVersion,
        on_delete=models.CASCADE,
        related_name="tarifas_sucursal",
    )
    sucursal = models.ForeignKey(
        "catalog.Sucursal",
        on_delete=models.PROTECT,
        related_name="tarifas",
    )
    codigo = models.SlugField(max_length=32, choices=CodigoTarifa.choices)
    monto = models.DecimalField(max_digits=10, decimal_places=2)
    horas_semana = models.PositiveSmallIntegerField(null=True, blank=True)
    sesiones = models.PositiveSmallIntegerField(null=True, blank=True)

    class Meta:
        ordering = ["sucursal__nombre", "codigo"]
        unique_together = [("parametro_version", "sucursal", "codigo")]
        verbose_name = "Tarifa por sucursal"
        verbose_name_plural = "Tarifas por sucursal"

    def __str__(self):
        return f"{self.sucursal} {self.codigo} = {self.monto}"


class MetodoPagoCatalogo(TimeStampedModel):
    """Catálogo configurable de métodos de pago (MVP: efectivo, transferencia)."""

    codigo = models.SlugField(max_length=32, unique=True)
    nombre = models.CharField(max_length=64)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ["nombre"]
        verbose_name = "Método de pago"
        verbose_name_plural = "Métodos de pago"

    def __str__(self):
        return self.nombre
