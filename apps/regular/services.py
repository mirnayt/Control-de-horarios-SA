"""Alta Regular, cálculo mensual y liberación lógica de lugares."""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.params.models import ParametroVersion
from apps.params.services import PricingService
from apps.people.models import Alumno, EstadoAlumno, TipoAlumno
from apps.scheduling.models import DiaSemana, Modalidad, TipoAlumno as TipoHorario
from apps.scheduling.services import CalendarService, CapacityService

from .models import (
    AsignacionRegular,
    EstadoPeriodoCobro,
    EstadoRegular,
    PeriodoCobroRegular,
    Regular,
)

MAX_HORARIOS_REGULAR = 3


def _es_alta_parcial(fecha: date, *, version: ParametroVersion) -> bool:
    """Alta después del día de pago normal (default 7) → cobro proporcional flat."""
    return fecha.day > version.dia_pago_normal_fin


def _horario_acepta_tipo(horario, tipo_alumno: str) -> bool:
    if horario.tipo_alumno == TipoHorario.AMBOS:
        return True
    return horario.tipo_alumno == tipo_alumno


def _validar_horarios_alta(alumno: Alumno, horarios: list) -> None:
    if not horarios:
        raise ValidationError("Debes indicar al menos un horario.")
    if len(horarios) > MAX_HORARIOS_REGULAR:
        raise ValidationError(
            f"Regular permite como máximo {MAX_HORARIOS_REGULAR} horarios."
        )
    if len({h.pk for h in horarios}) != len(horarios):
        raise ValidationError("No se pueden repetir horarios en la misma alta.")

    dias = [h.dia for h in horarios]
    if len(set(dias)) != len(dias):
        raise ValidationError("Cada día de la semana solo puede usarse una vez.")

    for horario in horarios:
        if not horario.activo:
            raise ValidationError(f"El horario no está activo: {horario}.")
        modalidades = horario.modalidades or []
        if Modalidad.REGULAR not in modalidades:
            raise ValidationError(f"El horario no acepta modalidad Regular: {horario}.")
        if not _horario_acepta_tipo(horario, alumno.tipo):
            raise ValidationError(
                f"El horario no admite tipo '{alumno.tipo}': {horario}."
            )
        CapacityService.assert_tiene_cupo(horario, plazas=1)


def _horas_asignacion(
    asignacion: AsignacionRegular,
    year: int,
    month: int,
    *,
    desde: date | None,
) -> tuple[Decimal, list[str]]:
    horario = asignacion.horario
    fechas = CalendarService.ocurrencias_en_mes(
        horario, year, month, desde=desde
    )
    horas = CalendarService.horas_en_mes(
        horario, year, month, desde=desde
    )
    return horas, [f.isoformat() for f in fechas]


def calcular_monto_regular(
    regular: Regular,
    year: int,
    month: int,
    *,
    version: ParametroVersion | None = None,
    desde: date | None = None,
    alta_parcial: bool | None = None,
    asignaciones: list[AsignacionRegular] | None = None,
) -> dict:
    """
    Calcula mensualidad con CalendarService + PricingService.
    Devuelve dict listo para persistir en PeriodoCobroRegular (snapshot).
    """
    v = version or ParametroVersion.vigente()
    if v is None:
        raise ValidationError("No hay versión de parámetros vigente.")

    asig = asignaciones
    if asig is None:
        asig = list(
            regular.asignaciones.filter(activa=True).select_related("horario")
        )
    if not asig:
        raise ValidationError("El Regular no tiene asignaciones activas.")

    if alta_parcial is None:
        # Solo el mes de alta puede ser parcial.
        fi = regular.fecha_inicio
        alta_parcial = (
            fi.year == year
            and fi.month == month
            and _es_alta_parcial(fi, version=v)
        )

    if desde is None and alta_parcial:
        desde = regular.fecha_inicio

    horas_semana = Decimal("0")
    horas_sabado = Decimal("0")
    detalle_horarios: list[dict] = []

    for a in asig:
        horas, fechas_iso = _horas_asignacion(a, year, month, desde=desde)
        es_sabado = int(a.horario.dia) == DiaSemana.SABADO
        if es_sabado:
            horas_sabado += horas
        else:
            horas_semana += horas
        detalle_horarios.append(
            {
                "asignacion_id": a.pk,
                "horario_id": a.horario_id,
                "dia": int(a.horario.dia),
                "es_sabado": es_sabado,
                "duracion_minutos": a.horario.duracion_minutos,
                "ocurrencias": len(fechas_iso),
                "fechas": fechas_iso,
                "horas": str(horas),
            }
        )

    horas_total = horas_semana + horas_sabado
    tipo = regular.alumno.tipo

    if tipo == TipoAlumno.ADULTO:
        monto = PricingService.monto_regular_adulto_mixto(
            horas_semana=horas_semana,
            horas_sabado=horas_sabado,
            version=v,
            alta_parcial=alta_parcial,
        )
    elif tipo == TipoAlumno.NINO:
        monto = PricingService.monto_regular_nino(
            horas_total, version=v, alta_parcial=alta_parcial
        )
    else:
        raise ValidationError(f"Tipo de alumno no soportado en Regular: {tipo}")

    return {
        "parametro_version": v,
        "alta_parcial": alta_parcial,
        "horas_semana": horas_semana.quantize(Decimal("0.01")),
        "horas_sabado": horas_sabado.quantize(Decimal("0.01")),
        "horas_total": horas_total.quantize(Decimal("0.01")),
        "monto": monto,
        "detalle_calculo": {
            "tipo_alumno": tipo,
            "desde": desde.isoformat() if desde else None,
            "alta_parcial": alta_parcial,
            "parametro_version_id": v.pk,
            "tarifa_hora_adulto": str(v.tarifa_hora_adulto),
            "tarifa_hora_nino": str(v.tarifa_hora_nino),
            "bloques_adulto": [
                {
                    "orden": b.orden,
                    "horas_max": b.horas_max,
                    "tarifa_hora": str(b.tarifa_hora),
                }
                for b in v.bloques_adulto.order_by("orden")
            ],
            "sabado_adulto_sin_descuento_progresivo": (
                v.sabado_adulto_sin_descuento_progresivo
            ),
            "horarios": detalle_horarios,
            "horas_semana": str(horas_semana.quantize(Decimal("0.01"))),
            "horas_sabado": str(horas_sabado.quantize(Decimal("0.01"))),
            "horas_total": str(horas_total.quantize(Decimal("0.01"))),
            "monto": str(monto),
        },
    }


@transaction.atomic
def alta_regular(
    *,
    alumno: Alumno,
    horarios: list,
    fecha_inicio: date | None = None,
    notas: str = "",
    crear_periodo: bool = True,
) -> Regular:
    """
    Alta Regular a 1, 2 o 3 horarios fijos.
    Si fecha_inicio.day > 7, el periodo del mes es parcial (sesiones restantes).
    """
    if alumno.estado != EstadoAlumno.ACTIVO:
        raise ValidationError("El alumno debe estar activo para alta Regular.")
    if Regular.objects.filter(alumno=alumno, estado=EstadoRegular.ACTIVO).exists():
        raise ValidationError("El alumno ya tiene un Regular activo.")

    fecha = fecha_inicio or timezone.localdate()
    _validar_horarios_alta(alumno, list(horarios))

    version = ParametroVersion.vigente()
    if version is None:
        raise ValidationError("No hay versión de parámetros vigente.")

    regular = Regular.objects.create(
        alumno=alumno,
        fecha_inicio=fecha,
        estado=EstadoRegular.ACTIVO,
        notas=notas,
    )

    for horario in horarios:
        # Revalidar cupo bajo lock de transacción (otra alta concurrente).
        CapacityService.assert_tiene_cupo(horario, plazas=1)
        AsignacionRegular.objects.create(
            regular=regular,
            horario=horario,
            activa=True,
            fecha_inicio=fecha,
        )

    if crear_periodo:
        generar_periodo_cobro(regular, fecha.year, fecha.month, version=version)

    return regular


@transaction.atomic
def generar_periodo_cobro(
    regular: Regular,
    year: int,
    month: int,
    *,
    version: ParametroVersion | None = None,
    recalcular: bool = False,
) -> PeriodoCobroRegular:
    """Crea (o recalcula) el periodo del mes con snapshot inmutable de tarifas."""
    if not (1 <= month <= 12):
        raise ValidationError("mes debe estar entre 1 y 12.")

    existente = PeriodoCobroRegular.objects.filter(
        regular=regular, anio=year, mes=month
    ).first()
    if existente and not recalcular:
        _sync_linea_mensualidad(existente)
        return existente
    if existente and existente.estado == EstadoPeriodoCobro.LIBERADO:
        raise ValidationError("No se puede recalcular un periodo liberado.")

    calc = calcular_monto_regular(regular, year, month, version=version)
    ahora = timezone.now()

    if existente:
        existente.estado = EstadoPeriodoCobro.PENDIENTE
        existente.alta_parcial = calc["alta_parcial"]
        existente.horas_semana = calc["horas_semana"]
        existente.horas_sabado = calc["horas_sabado"]
        existente.horas_total = calc["horas_total"]
        existente.monto = calc["monto"]
        existente.parametro_version = calc["parametro_version"]
        existente.detalle_calculo = calc["detalle_calculo"]
        existente.calculado_en = ahora
        existente.save()
        _sync_linea_mensualidad(existente)
        return existente

    periodo = PeriodoCobroRegular.objects.create(
        regular=regular,
        anio=year,
        mes=month,
        estado=EstadoPeriodoCobro.PENDIENTE,
        alta_parcial=calc["alta_parcial"],
        horas_semana=calc["horas_semana"],
        horas_sabado=calc["horas_sabado"],
        horas_total=calc["horas_total"],
        monto=calc["monto"],
        parametro_version=calc["parametro_version"],
        detalle_calculo=calc["detalle_calculo"],
        calculado_en=ahora,
    )
    _sync_linea_mensualidad(periodo)
    return periodo


def _sync_linea_mensualidad(periodo: PeriodoCobroRegular) -> None:
    """Etapa 6: crea LineaCobro de mensualidad si billing esta instalado."""
    try:
        from apps.billing.services import asegurar_linea_mensualidad
    except ImportError:
        return
    asegurar_linea_mensualidad(periodo)


def monto_periodo_desde_snapshot(periodo: PeriodoCobroRegular) -> Decimal:
    """
    Relee el snapshot almacenado (no la tarifa vigente).
    Garantiza reproducibilidad tras cambios de ParametroVersion.
    """
    return periodo.monto


def marcar_estado_periodo(
    periodo: PeriodoCobroRegular,
    estado: str,
) -> PeriodoCobroRegular:
    if estado not in EstadoPeriodoCobro.values:
        raise ValidationError(f"Estado de periodo inválido: {estado}")
    periodo.estado = estado
    periodo.save(update_fields=["estado", "updated_at"])
    return periodo


def estado_esperado_por_dia(
    dia: int,
    *,
    version: ParametroVersion | None = None,
    pagado: bool = False,
    con_recargo: bool = False,
) -> str:
    """
    Regla documental 1–7 / 8–10 / 11 (sin pagos reales aún).
    Útil para jobs de Etapa 6.
    """
    v = version or ParametroVersion.vigente()
    if v is None:
        raise ValidationError("No hay versión de parámetros vigente.")

    if pagado:
        return (
            EstadoPeriodoCobro.PAGADO_CON_RECARGO
            if con_recargo
            else EstadoPeriodoCobro.PAGADO_A_TIEMPO
        )

    if dia <= v.dia_pago_normal_fin:
        return EstadoPeriodoCobro.PENDIENTE
    if v.dia_recargo_inicio <= dia <= v.dia_recargo_fin:
        return EstadoPeriodoCobro.VENCIDO
    if dia >= v.dia_liberacion:
        return EstadoPeriodoCobro.LIBERADO
    return EstadoPeriodoCobro.VENCIDO


@transaction.atomic
def liberar_lugar_logico(
    regular: Regular,
    *,
    fecha: date | None = None,
    periodo: PeriodoCobroRegular | None = None,
    motivo: str = "liberacion_impago",
) -> Regular:
    """
    Liberación lógica del cupo (preparada para Etapa 6 / día 11).
    Desactiva asignaciones; marca periodo liberado; baja administrativa del alumno.
    No elimina historial ni periodos.
    """
    fecha = fecha or timezone.localdate()

    asignaciones = list(regular.asignaciones.filter(activa=True))
    for a in asignaciones:
        a.activa = False
        a.fecha_fin = fecha
        a.save(update_fields=["activa", "fecha_fin", "updated_at"])

    regular.estado = EstadoRegular.LIBERADO
    regular.save(update_fields=["estado", "updated_at"])

    if periodo is None:
        periodo = (
            PeriodoCobroRegular.objects.filter(regular=regular)
            .order_by("-anio", "-mes")
            .first()
        )
    if periodo is not None:
        periodo.estado = EstadoPeriodoCobro.LIBERADO
        detalle = dict(periodo.detalle_calculo or {})
        detalle["liberacion"] = {
            "fecha": fecha.isoformat(),
            "motivo": motivo,
        }
        periodo.detalle_calculo = detalle
        periodo.save(update_fields=["estado", "detalle_calculo", "updated_at"])

    alumno = regular.alumno
    if alumno.estado == EstadoAlumno.ACTIVO:
        alumno.estado = EstadoAlumno.BAJA_ADMINISTRATIVA
        alumno.save(update_fields=["estado", "updated_at"])

    return regular


def fin_de_mes(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])
