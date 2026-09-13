"""Pagos Regular, recargo, liberacion dia 11 y reactivacion con cupo."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.params.models import MetodoPagoCatalogo, ParametroVersion
from apps.people.models import Alumno, EstadoAlumno
from apps.regular.models import (
    AsignacionRegular,
    EstadoPeriodoCobro,
    EstadoRegular,
    PeriodoCobroRegular,
    Regular,
)
from apps.regular.services import liberar_lugar_logico
from apps.scheduling.services import CapacityService

from .models import (
    ConceptoLinea,
    EstadoLineaCobro,
    EstadoPago,
    EjecucionCobranza,
    LineaCobro,
    Pago,
)

METODOS_MVP = frozenset({"efectivo", "transferencia", "link"})


def _hoy_local() -> date:
    return timezone.localdate()


def _version(version: ParametroVersion | None = None) -> ParametroVersion:
    v = version or ParametroVersion.vigente()
    if v is None:
        raise ValidationError("No hay version de parametros vigente.")
    return v


def _metodo_mvp(codigo: str) -> MetodoPagoCatalogo:
    if codigo not in METODOS_MVP:
        raise ValidationError(
            f"Metodo no soportado en MVP: {codigo}. Use efectivo, transferencia o link."
        )
    metodo = MetodoPagoCatalogo.objects.filter(codigo=codigo, activo=True).first()
    if metodo is None:
        raise ValidationError(f"Metodo de pago no configurado: {codigo}")
    return metodo


def en_ventana_recargo(dia: int, *, version: ParametroVersion) -> bool:
    return version.dia_recargo_inicio <= dia <= version.dia_recargo_fin


def en_ventana_pago_normal(dia: int, *, version: ParametroVersion) -> bool:
    return 1 <= dia <= version.dia_pago_normal_fin


def debe_liberar(dia: int, *, version: ParametroVersion) -> bool:
    return dia >= version.dia_liberacion


def asegurar_linea_mensualidad(periodo: PeriodoCobroRegular) -> LineaCobro:
    """Crea (idempotente) la linea de mensualidad desde el snapshot del periodo."""
    existente = LineaCobro.objects.filter(
        periodo=periodo, concepto=ConceptoLinea.MENSUALIDAD
    ).first()
    if existente:
        return existente

    version = periodo.parametro_version
    reglas = {
        "origen": "periodo_cobro_regular",
        "periodo_id": periodo.pk,
        "anio": periodo.anio,
        "mes": periodo.mes,
        "monto_periodo": str(periodo.monto),
        "alta_parcial": periodo.alta_parcial,
        "horas_total": str(periodo.horas_total),
        "parametro_version_id": version.pk,
        "detalle_calculo": periodo.detalle_calculo,
    }
    return LineaCobro.objects.create(
        periodo=periodo,
        alumno=periodo.regular.alumno,
        concepto=ConceptoLinea.MENSUALIDAD,
        monto=periodo.monto,
        estado=EstadoLineaCobro.PENDIENTE,
        parametro_version=version,
        reglas_aplicadas=reglas,
    )


def asegurar_linea_inscripcion(
    *,
    alumno: Alumno,
    monto: Decimal,
    inscripcion_id: int,
    version: ParametroVersion | None = None,
) -> LineaCobro:
    """
    Crea (idempotente) la línea de cuota de inscripción.
    No importa enrollment: el vínculo es reglas_aplicadas['inscripcion_id'].
    """
    existente = LineaCobro.objects.filter(
        alumno=alumno, concepto=ConceptoLinea.INSCRIPCION
    ).first()
    if existente:
        return existente

    v = _version(version)
    if monto <= 0:
        raise ValidationError("El monto de inscripción debe ser positivo.")

    reglas = {
        "origen": "inscripcion",
        "inscripcion_id": inscripcion_id,
        "alumno_id": alumno.pk,
        "monto": str(monto),
        "parametro_version_id": v.pk,
    }
    return LineaCobro.objects.create(
        periodo=None,
        alumno=alumno,
        concepto=ConceptoLinea.INSCRIPCION,
        monto=monto,
        estado=EstadoLineaCobro.PENDIENTE,
        parametro_version=v,
        reglas_aplicadas=reglas,
    )


def linea_inscripcion_pendiente(alumno: Alumno) -> LineaCobro | None:
    return LineaCobro.objects.filter(
        alumno=alumno,
        concepto=ConceptoLinea.INSCRIPCION,
        estado=EstadoLineaCobro.PENDIENTE,
    ).first()


def inscripcion_pagada(alumno: Alumno) -> bool:
    """Fuente de verdad: LineaCobro de inscripción en estado pagada."""
    return LineaCobro.objects.filter(
        alumno=alumno,
        concepto=ConceptoLinea.INSCRIPCION,
        estado=EstadoLineaCobro.PAGADA,
    ).exists()


@transaction.atomic
def registrar_pago_inscripcion(
    *,
    alumno: Alumno,
    metodo_codigo: str,
    fecha_pago: date | None = None,
    referencia: str = "",
    notas: str = "",
    version: ParametroVersion | None = None,
) -> Pago:
    """Paga la línea de inscripción pendiente (operación separada del alta)."""
    fecha = fecha_pago or _hoy_local()
    v = _version(version)
    metodo = _metodo_mvp(metodo_codigo)

    linea = linea_inscripcion_pendiente(alumno)
    if linea is None:
        raise ValidationError("No hay cuota de inscripción pendiente para este alumno.")

    reglas = {
        "origen": "inscripcion",
        "fecha_pago": fecha.isoformat(),
        "inscripcion_id": (linea.reglas_aplicadas or {}).get("inscripcion_id"),
        "linea_id": linea.pk,
        "parametro_version_id": v.pk,
    }
    pago = Pago.objects.create(
        alumno=alumno,
        metodo=metodo,
        estado=EstadoPago.CONFIRMADO,
        monto_total=linea.monto,
        fecha_pago=fecha,
        referencia=referencia,
        notas=notas,
        parametro_version=v,
        reglas_aplicadas=reglas,
    )
    linea.estado = EstadoLineaCobro.PAGADA
    linea.pago = pago
    linea.save(update_fields=["estado", "pago", "updated_at"])
    return pago


def _crear_linea_recargo(
    periodo: PeriodoCobroRegular,
    *,
    fecha: date,
    version: ParametroVersion,
) -> LineaCobro:
    existente = LineaCobro.objects.filter(
        periodo=periodo, concepto=ConceptoLinea.RECARGO
    ).first()
    if existente:
        return existente

    reglas = {
        "origen": "recargo_impago",
        "fecha": fecha.isoformat(),
        "dia": fecha.day,
        "ventana": [version.dia_recargo_inicio, version.dia_recargo_fin],
        "monto_recargo": str(version.monto_recargo),
        "parametro_version_id": version.pk,
    }
    return LineaCobro.objects.create(
        periodo=periodo,
        alumno=periodo.regular.alumno,
        concepto=ConceptoLinea.RECARGO,
        monto=version.monto_recargo,
        estado=EstadoLineaCobro.PENDIENTE,
        parametro_version=version,
        reglas_aplicadas=reglas,
    )


@transaction.atomic
def aplicar_recargo_si_corresponde(
    periodo: PeriodoCobroRegular,
    *,
    fecha: date | None = None,
    version: ParametroVersion | None = None,
) -> LineaCobro | None:
    """
    Recargo (default 100) en dias 8-10 si el periodo sigue impago.
    Idempotente: no duplica la linea RECARGO.
    """
    fecha = fecha or _hoy_local()
    v = _version(version or periodo.parametro_version)

    if periodo.estado in (
        EstadoPeriodoCobro.PAGADO_A_TIEMPO,
        EstadoPeriodoCobro.PAGADO_CON_RECARGO,
    ):
        return LineaCobro.objects.filter(
            periodo=periodo, concepto=ConceptoLinea.RECARGO
        ).first()

    existente = LineaCobro.objects.filter(
        periodo=periodo, concepto=ConceptoLinea.RECARGO
    ).first()
    if existente:
        return existente

    if fecha.year != periodo.anio or fecha.month != periodo.mes:
        return None

    if not en_ventana_recargo(fecha.day, version=v):
        return None

    asegurar_linea_mensualidad(periodo)

    if periodo.estado == EstadoPeriodoCobro.PENDIENTE:
        periodo.estado = EstadoPeriodoCobro.VENCIDO
        periodo.save(update_fields=["estado", "updated_at"])

    return _crear_linea_recargo(periodo, fecha=fecha, version=v)


def asegurar_recargo_adeudado(
    periodo: PeriodoCobroRegular,
    *,
    fecha: date | None = None,
    version: ParametroVersion | None = None,
) -> LineaCobro | None:
    """
    Si ya paso el dia 7 y sigue impago, garantiza linea de recargo.
    Idempotente.
    """
    fecha = fecha or _hoy_local()
    v = _version(version or periodo.parametro_version)

    if periodo.estado in (
        EstadoPeriodoCobro.PAGADO_A_TIEMPO,
        EstadoPeriodoCobro.PAGADO_CON_RECARGO,
    ):
        return LineaCobro.objects.filter(
            periodo=periodo, concepto=ConceptoLinea.RECARGO
        ).first()

    existente = LineaCobro.objects.filter(
        periodo=periodo, concepto=ConceptoLinea.RECARGO
    ).first()
    if existente:
        return existente

    if fecha.year != periodo.anio or fecha.month != periodo.mes:
        return None
    if fecha.day <= v.dia_pago_normal_fin:
        return None

    asegurar_linea_mensualidad(periodo)
    dia_snap = min(max(fecha.day, v.dia_recargo_inicio), v.dia_recargo_fin)
    return _crear_linea_recargo(
        periodo,
        fecha=date(periodo.anio, periodo.mes, dia_snap),
        version=v,
    )


def lineas_pendientes(periodo: PeriodoCobroRegular) -> list[LineaCobro]:
    asegurar_linea_mensualidad(periodo)
    return list(
        LineaCobro.objects.filter(
            periodo=periodo, estado=EstadoLineaCobro.PENDIENTE
        ).order_by("concepto")
    )


def monto_pendiente(periodo: PeriodoCobroRegular) -> Decimal:
    return sum((ln.monto for ln in lineas_pendientes(periodo)), Decimal("0.00"))


def _horarios_para_reactivar(regular: Regular) -> list:
    asignaciones = list(
        AsignacionRegular.objects.filter(regular=regular)
        .select_related("horario")
        .order_by("horario_id", "-id")
    )
    vistos: set[int] = set()
    resultado = []
    for a in asignaciones:
        if a.horario_id in vistos:
            continue
        vistos.add(a.horario_id)
        resultado.append(a)
    return resultado


def hay_cupo_para_reactivar(regular: Regular) -> bool:
    asignaciones = _horarios_para_reactivar(regular)
    if not asignaciones:
        return False
    for a in asignaciones:
        if a.activa:
            continue
        if CapacityService.cupo_disponible(a.horario) < 1:
            return False
    return True


@transaction.atomic
def reactivar_regular_si_hay_cupo(
    regular: Regular,
    *,
    fecha: date | None = None,
) -> Regular:
    """Reactiva asignaciones y alumno solo si hay cupo en todos los horarios."""
    fecha = fecha or _hoy_local()
    if regular.estado not in (EstadoRegular.LIBERADO, EstadoRegular.INACTIVO):
        if regular.estado == EstadoRegular.ACTIVO:
            return regular
        raise ValidationError(
            f"No se puede reactivar Regular en estado '{regular.estado}'."
        )

    asignaciones = _horarios_para_reactivar(regular)
    if not asignaciones:
        raise ValidationError(
            "El Regular no tiene asignaciones historicas para reactivar."
        )

    for a in asignaciones:
        if not a.activa:
            CapacityService.assert_tiene_cupo(a.horario, plazas=1)

    for a in asignaciones:
        if not a.activa:
            a.activa = True
            a.fecha_fin = None
            a.fecha_inicio = fecha
            a.save(
                update_fields=["activa", "fecha_fin", "fecha_inicio", "updated_at"]
            )

    regular.estado = EstadoRegular.ACTIVO
    regular.save(update_fields=["estado", "updated_at"])

    alumno = regular.alumno
    if alumno.estado != EstadoAlumno.ACTIVO:
        alumno.estado = EstadoAlumno.ACTIVO
        alumno.save(update_fields=["estado", "updated_at"])

    return regular


@transaction.atomic
def registrar_pago_periodo(
    *,
    periodo: PeriodoCobroRegular,
    metodo_codigo: str,
    fecha_pago: date | None = None,
    referencia: str = "",
    notas: str = "",
    version: ParametroVersion | None = None,
    reactivar_si_liberado: bool = True,
) -> Pago:
    """
    Registra pago inmutable de lineas pendientes del periodo.
    Dias 1-7: sin recargo. 8-10: incluye recargo.
    Post-liberacion: reactiva solo con cupo.
    """
    fecha = fecha_pago or _hoy_local()
    v = _version(version)
    metodo = _metodo_mvp(metodo_codigo)
    regular = periodo.regular

    if fecha.year == periodo.anio and fecha.month == periodo.mes:
        if en_ventana_recargo(fecha.day, version=v):
            aplicar_recargo_si_corresponde(periodo, fecha=fecha, version=v)
        elif fecha.day > v.dia_recargo_fin:
            asegurar_recargo_adeudado(periodo, fecha=fecha, version=v)

    periodo.refresh_from_db()
    estaba_liberado = periodo.estado == EstadoPeriodoCobro.LIBERADO or (
        regular.estado == EstadoRegular.LIBERADO
    )

    lineas = lineas_pendientes(periodo)
    if not lineas:
        raise ValidationError("No hay lineas pendientes para este periodo.")

    monto = sum((ln.monto for ln in lineas), Decimal("0.00"))
    con_recargo = any(ln.concepto == ConceptoLinea.RECARGO for ln in lineas)

    reactivado = False
    sin_cupo = False
    if estaba_liberado and reactivar_si_liberado:
        if hay_cupo_para_reactivar(regular):
            reactivado = True
        else:
            sin_cupo = True

    reglas = {
        "fecha_pago": fecha.isoformat(),
        "dia": fecha.day,
        "anio": periodo.anio,
        "mes": periodo.mes,
        "ventana_normal_fin": v.dia_pago_normal_fin,
        "ventana_recargo": [v.dia_recargo_inicio, v.dia_recargo_fin],
        "dia_liberacion": v.dia_liberacion,
        "con_recargo": con_recargo,
        "estaba_liberado": estaba_liberado,
        "reactivado": reactivado,
        "sin_cupo_para_reactivar": sin_cupo,
        "lineas": [
            {"id": ln.pk, "concepto": ln.concepto, "monto": str(ln.monto)}
            for ln in lineas
        ],
        "parametro_version_id": v.pk,
        "monto_recargo_catalogo": str(v.monto_recargo),
    }

    pago = Pago.objects.create(
        alumno=regular.alumno,
        metodo=metodo,
        estado=EstadoPago.CONFIRMADO,
        monto_total=monto,
        fecha_pago=fecha,
        referencia=referencia,
        notas=notas,
        parametro_version=v,
        reglas_aplicadas=reglas,
    )

    for ln in lineas:
        ln.estado = EstadoLineaCobro.PAGADA
        ln.pago = pago
        ln.save(update_fields=["estado", "pago", "updated_at"])

    periodo.estado = (
        EstadoPeriodoCobro.PAGADO_CON_RECARGO
        if con_recargo
        else EstadoPeriodoCobro.PAGADO_A_TIEMPO
    )
    periodo.save(update_fields=["estado", "updated_at"])

    if reactivado:
        reactivar_regular_si_hay_cupo(regular, fecha=fecha)
    elif not estaba_liberado and regular.estado == EstadoRegular.ACTIVO:
        alumno = regular.alumno
        if alumno.estado == EstadoAlumno.PAGO_VENCIDO:
            alumno.estado = EstadoAlumno.ACTIVO
            alumno.save(update_fields=["estado", "updated_at"])

    return pago


@transaction.atomic
def liberar_periodo_impago(
    periodo: PeriodoCobroRegular,
    *,
    fecha: date | None = None,
) -> PeriodoCobroRegular:
    """Dia 11+: libera lugar si el periodo sigue sin pagar."""
    fecha = fecha or _hoy_local()
    if periodo.estado in (
        EstadoPeriodoCobro.PAGADO_A_TIEMPO,
        EstadoPeriodoCobro.PAGADO_CON_RECARGO,
        EstadoPeriodoCobro.LIBERADO,
    ):
        return periodo

    asegurar_linea_mensualidad(periodo)
    asegurar_recargo_adeudado(periodo, fecha=fecha)

    liberar_lugar_logico(
        periodo.regular,
        fecha=fecha,
        periodo=periodo,
        motivo="liberacion_impago_dia_11",
    )
    periodo.refresh_from_db()
    return periodo


@transaction.atomic
def ejecutar_cobranza_diaria(
    *,
    fecha: date | None = None,
    forzar: bool = False,
) -> EjecucionCobranza:
    """
    Job diario idempotente (America/Mexico_City).
    Dias 8-10: aplica recargo sin duplicar.
    Dia >=11: libera periodos impagos del mes.
    """
    fecha = fecha or _hoy_local()
    v = _version()

    existente = EjecucionCobranza.objects.filter(fecha=fecha).first()
    if existente and not forzar:
        try:
            from apps.flexi.services import ejecutar_vencimiento_flexi

            ejecutar_vencimiento_flexi(fecha=fecha, forzar=False)
        except ImportError:
            pass
        return existente

    detalle = {
        "fecha": fecha.isoformat(),
        "dia": fecha.day,
        "recargos_aplicados": [],
        "liberaciones": [],
        "omitidos": [],
    }

    periodos = PeriodoCobroRegular.objects.filter(
        anio=fecha.year,
        mes=fecha.month,
    ).select_related("regular", "parametro_version")

    for periodo in periodos:
        if periodo.estado in (
            EstadoPeriodoCobro.PAGADO_A_TIEMPO,
            EstadoPeriodoCobro.PAGADO_CON_RECARGO,
        ):
            detalle["omitidos"].append({"periodo_id": periodo.pk, "motivo": "pagado"})
            continue

        if en_ventana_recargo(fecha.day, version=v):
            linea = aplicar_recargo_si_corresponde(periodo, fecha=fecha, version=v)
            if linea:
                detalle["recargos_aplicados"].append(
                    {
                        "periodo_id": periodo.pk,
                        "linea_id": linea.pk,
                        "monto": str(linea.monto),
                    }
                )

        if debe_liberar(fecha.day, version=v):
            periodo.refresh_from_db()
            if periodo.estado not in (
                EstadoPeriodoCobro.PAGADO_A_TIEMPO,
                EstadoPeriodoCobro.PAGADO_CON_RECARGO,
                EstadoPeriodoCobro.LIBERADO,
            ):
                liberar_periodo_impago(periodo, fecha=fecha)
                detalle["liberaciones"].append({"periodo_id": periodo.pk})

    # Etapa 7: vencimiento Flexi (idempotente; independiente del early-return).
    try:
        from apps.flexi.services import ejecutar_vencimiento_flexi

        flexi_run = ejecutar_vencimiento_flexi(fecha=fecha, forzar=forzar)
        detalle["vencimiento_flexi"] = {
            "ejecucion_id": flexi_run.pk,
            "vencidos": flexi_run.detalle.get("vencidos", []),
        }
    except ImportError:
        pass

    ahora = timezone.now()
    if existente:
        existente.ejecutado_en = ahora
        existente.detalle = detalle
        existente.save(update_fields=["ejecutado_en", "detalle", "updated_at"])
        return existente

    return EjecucionCobranza.objects.create(
        fecha=fecha,
        ejecutado_en=ahora,
        detalle=detalle,
    )


def job_cobranza_diaria(
    *, fecha: date | None = None, forzar: bool = False
) -> EjecucionCobranza:
    return ejecutar_cobranza_diaria(fecha=fecha, forzar=forzar)


@transaction.atomic
def registrar_pago_flexi(
    *,
    alumno,
    monto: Decimal,
    metodo_codigo: str,
    fecha_pago: date | None = None,
    referencia: str = "",
    notas: str = "",
    version: ParametroVersion | None = None,
    contexto: dict | None = None,
) -> Pago:
    """Pago inmutable de paquete Flexi (sin LineaCobro de periodo Regular)."""
    fecha = fecha_pago or _hoy_local()
    v = _version(version)
    metodo = _metodo_mvp(metodo_codigo)
    if monto <= 0:
        raise ValidationError("El monto Flexi debe ser positivo.")

    reglas = {
        "origen": "flexi",
        "fecha_pago": fecha.isoformat(),
        "parametro_version_id": v.pk,
        "flexi_tarifa_hora": str(v.flexi_tarifa_hora),
        **(contexto or {}),
    }

    return Pago.objects.create(
        alumno=alumno,
        metodo=metodo,
        estado=EstadoPago.CONFIRMADO,
        monto_total=monto,
        fecha_pago=fecha,
        referencia=referencia,
        notas=notas,
        parametro_version=v,
        reglas_aplicadas=reglas,
    )
