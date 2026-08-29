from decimal import Decimal

from django.core.exceptions import ValidationError
from django.utils import timezone

from .models import BloqueTarifaAdulto, MetodoPagoCatalogo, ParametroVersion, VigenciaFlexi

# Tabla comercial inicial documentada.
VIGENCIAS_FLEXI_INICIAL = (
    (5, 5, 1),
    (6, 10, 2),
    (11, 15, 3),
    (16, 20, 4),
    (21, 25, 5),
    (26, 30, 6),
)

BLOQUES_ADULTO_INICIAL = (
    (1, 12, Decimal("120.00")),
    (2, 12, Decimal("110.00")),
    (3, 12, Decimal("100.00")),
)

METODOS_PAGO_INICIAL = (
    ("efectivo", "Efectivo"),
    ("transferencia", "Transferencia"),
)


def seed_parametros_iniciales(*, force: bool = False) -> ParametroVersion:
    """Crea la primera versión de parámetros si no existe ninguna."""
    existing = ParametroVersion.objects.order_by("vigente_desde").first()
    if existing and not force:
        return existing

    version = ParametroVersion.objects.create(
        vigente_desde=timezone.now(),
        notas="Seed inicial MVP v1.0",
    )
    for orden, horas, tarifa in BLOQUES_ADULTO_INICIAL:
        BloqueTarifaAdulto.objects.create(
            parametro_version=version,
            orden=orden,
            horas_max=horas,
            tarifa_hora=tarifa,
        )
    for smin, smax, meses in VIGENCIAS_FLEXI_INICIAL:
        VigenciaFlexi.objects.create(
            parametro_version=version,
            sesiones_min=smin,
            sesiones_max=smax,
            meses_vigencia=meses,
        )
    for codigo, nombre in METODOS_PAGO_INICIAL:
        MetodoPagoCatalogo.objects.get_or_create(
            codigo=codigo,
            defaults={"nombre": nombre, "activo": True},
        )
    return version


class PricingService:
    """
    Tarifas Regular / Flexi / suelta según ParametroVersion vigente.

    Adulto Regular: bloques progresivos sin descuento retroactivo.
    Sábado adulto y alta post-día 7: tarifa base adulto fija (sin bloques).
    Niño Regular: tarifa niño plana. Flexi: tarifa flexi/h. Suelta: precio fijo.
    """

    @staticmethod
    def _version(version: ParametroVersion | None = None) -> ParametroVersion:
        v = version or ParametroVersion.vigente()
        if v is None:
            raise ValidationError("No hay versión de parámetros vigente.")
        return v

    @staticmethod
    def horas_desde_duracion(
        duracion_minutos: int,
        ocurrencias: int,
    ) -> Decimal:
        """Convierte duración configurable × ocurrencias a horas decimales."""
        if duracion_minutos < 1:
            raise ValidationError("duracion_minutos debe ser al menos 1.")
        if ocurrencias < 0:
            raise ValidationError("ocurrencias no puede ser negativa.")
        return (Decimal(duracion_minutos) * Decimal(ocurrencias)) / Decimal(60)

    @classmethod
    def monto_regular_adulto(
        cls,
        horas: Decimal | int | float,
        *,
        version: ParametroVersion | None = None,
        es_sabado: bool = False,
        alta_parcial: bool = False,
    ) -> Decimal:
        """
        Mensualidad Regular adulto.

        - Alta parcial (después del día 7): siempre tarifa base, sin bloques.
        - Sábado (si sabado_adulto_sin_descuento_progresivo): siempre tarifa base.
        - Resto: bloques progresivos en orden (sin retroactivo).
        """
        v = cls._version(version)
        h = Decimal(str(horas))
        if h < 0:
            raise ValidationError("horas no puede ser negativa.")
        if h == 0:
            return Decimal("0.00")

        flat = alta_parcial or (
            es_sabado and v.sabado_adulto_sin_descuento_progresivo
        )
        if flat:
            return (h * v.tarifa_hora_adulto).quantize(Decimal("0.01"))

        return cls._monto_bloques_adulto(h, v)

    @classmethod
    def _monto_bloques_adulto(cls, horas: Decimal, version: ParametroVersion) -> Decimal:
        restantes = horas
        total = Decimal("0.00")
        bloques = list(version.bloques_adulto.order_by("orden"))
        if not bloques:
            return (horas * version.tarifa_hora_adulto).quantize(Decimal("0.01"))

        for bloque in bloques:
            if restantes <= 0:
                break
            cupo = Decimal(bloque.horas_max)
            tomadas = min(restantes, cupo)
            total += tomadas * bloque.tarifa_hora
            restantes -= tomadas

        if restantes > 0:
            # Horas más allá del último bloque: última tarifa (no retroactivo).
            total += restantes * bloques[-1].tarifa_hora

        return total.quantize(Decimal("0.01"))

    @classmethod
    def monto_regular_nino(
        cls,
        horas: Decimal | int | float,
        *,
        version: ParametroVersion | None = None,
        alta_parcial: bool = False,
    ) -> Decimal:
        """Niño Regular: siempre tarifa niño/h (alta parcial igual)."""
        v = cls._version(version)
        h = Decimal(str(horas))
        if h < 0:
            raise ValidationError("horas no puede ser negativa.")
        # alta_parcial no cambia la tarifa niño; se acepta por simetría de API.
        _ = alta_parcial
        return (h * v.tarifa_hora_nino).quantize(Decimal("0.01"))

    @classmethod
    def monto_flexi(
        cls,
        horas: Decimal | int | float,
        *,
        version: ParametroVersion | None = None,
    ) -> Decimal:
        v = cls._version(version)
        h = Decimal(str(horas))
        if h < 0:
            raise ValidationError("horas no puede ser negativa.")
        return (h * v.flexi_tarifa_hora).quantize(Decimal("0.01"))

    @classmethod
    def monto_clase_suelta(
        cls,
        *,
        version: ParametroVersion | None = None,
    ) -> Decimal:
        return cls._version(version).precio_clase_suelta

    @classmethod
    def monto_regular(
        cls,
        *,
        tipo_alumno: str,
        horas: Decimal | int | float,
        version: ParametroVersion | None = None,
        es_sabado: bool = False,
        alta_parcial: bool = False,
    ) -> Decimal:
        """Despacha adulto/niño Regular."""
        if tipo_alumno == "adulto":
            return cls.monto_regular_adulto(
                horas,
                version=version,
                es_sabado=es_sabado,
                alta_parcial=alta_parcial,
            )
        if tipo_alumno == "nino":
            return cls.monto_regular_nino(
                horas,
                version=version,
                alta_parcial=alta_parcial,
            )
        raise ValidationError(f"tipo_alumno inválido para Regular: {tipo_alumno}")

    @classmethod
    def monto_regular_adulto_mixto(
        cls,
        *,
        horas_semana: Decimal | int | float = 0,
        horas_sabado: Decimal | int | float = 0,
        version: ParametroVersion | None = None,
        alta_parcial: bool = False,
    ) -> Decimal:
        """
        Combina horas entre semana (bloques) y sábado (tarifa fija si aplica).
        Alta parcial: todo a tarifa base adulto.
        """
        v = cls._version(version)
        hs = Decimal(str(horas_semana))
        hsab = Decimal(str(horas_sabado))
        if alta_parcial:
            return ((hs + hsab) * v.tarifa_hora_adulto).quantize(Decimal("0.01"))
        total = Decimal("0.00")
        if hs:
            total += cls.monto_regular_adulto(hs, version=v, es_sabado=False)
        if hsab:
            total += cls.monto_regular_adulto(hsab, version=v, es_sabado=True)
        return total.quantize(Decimal("0.01"))
