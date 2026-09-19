"""Pagos Regular, recargo, liberacion dia 11 y reactivacion con cupo."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.params.models import MetodoPagoCatalogo, ParametroVersion
from apps.params.services import PricingService
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
    PagoAplicacion,
)

METODOS_MVP = frozenset({"efectivo", "transferencia", "link"})
ESTADOS_PERIODO_PAGADO = (
    EstadoPeriodoCobro.PAGADO_A_TIEMPO,
    EstadoPeriodoCobro.PAGADO_CON_RECARGO,
)
ESTADOS_LINEA_ABIERTA = (EstadoLineaCobro.PENDIENTE, EstadoLineaCobro.PARCIAL)


def pagado_linea(linea: LineaCobro) -> Decimal:
    total = linea.aplicaciones.filter(
        pago__estado=EstadoPago.CONFIRMADO
    ).aggregate(t=Sum("monto"))["t"]
    return total or Decimal("0.00")


def saldo_linea(linea: LineaCobro) -> Decimal:
    if linea.estado == EstadoLineaCobro.CANCELADA:
        return Decimal("0.00")
    if linea.estado == EstadoLineaCobro.PAGADA and not linea.aplicaciones.exists():
        return Decimal("0.00")
    saldo = (linea.monto or Decimal("0.00")) - pagado_linea(linea)
    return saldo if saldo > 0 else Decimal("0.00")


def _desglose_iva(
    base: Decimal,
    *,
    requiere_factura: bool,
    version: ParametroVersion,
) -> dict:
    base = Decimal(base).quantize(Decimal("0.01"))
    iva = (
        PricingService.monto_iva(base, version=version)
        if requiere_factura
        else Decimal("0.00")
    )
    return {
        "monto_base": base,
        "monto_iva": iva,
        "tasa_iva": version.tasa_iva if requiere_factura else Decimal("0"),
        "monto_total": (base + iva).quantize(Decimal("0.01")),
        "requiere_factura": requiere_factura,
    }


def ajustar_monto_linea(
    linea: LineaCobro,
    monto_nuevo: Decimal,
    *,
    motivo: str = "",
    usuario=None,
) -> LineaCobro:
    """Ajusta el cargo pendiente (sin abonos). Conserva monto_calculado."""
    if monto_nuevo <= 0:
        raise ValidationError("El monto ajustado debe ser positivo.")
    if pagado_linea(linea) > 0:
        raise ValidationError("No se puede ajustar una línea con abonos.")
    if linea.estado not in ESTADOS_LINEA_ABIERTA:
        raise ValidationError("Solo se ajustan líneas pendientes.")
    anterior = linea.monto
    reglas = dict(linea.reglas_aplicadas or {})
    historial = list(reglas.get("ajustes") or [])
    historial.append(
        {
            "de": str(anterior),
            "a": str(monto_nuevo),
            "motivo": motivo,
            "usuario_id": getattr(usuario, "pk", None),
        }
    )
    reglas["ajustes"] = historial
    linea.monto = Decimal(monto_nuevo).quantize(Decimal("0.01"))
    linea.reglas_aplicadas = reglas
    linea._allow_ajuste = True
    linea.save(update_fields=["monto", "reglas_aplicadas", "updated_at"])
    return linea


def _aplicar_a_linea(pago: Pago, linea: LineaCobro, monto: Decimal) -> None:
    monto = Decimal(monto).quantize(Decimal("0.01"))
    if monto <= 0:
        return
    PagoAplicacion.objects.create(pago=pago, linea=linea, monto=monto)
    saldo = saldo_linea(linea)
    if saldo <= 0:
        linea.estado = EstadoLineaCobro.PAGADA
    else:
        linea.estado = EstadoLineaCobro.PARCIAL
    linea.pago = pago
    linea.save(update_fields=["estado", "pago", "updated_at"])


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
    return (
        LineaCobro.objects.filter(
            alumno=alumno,
            concepto=ConceptoLinea.INSCRIPCION,
            estado__in=ESTADOS_LINEA_ABIERTA,
        )
        .order_by("id")
        .first()
    )


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
    monto: Decimal | None = None,
    requiere_factura: bool | None = None,
    monto_override: Decimal | None = None,
    motivo_ajuste: str = "",
    usuario=None,
) -> Pago:
    """Paga (o abona) la línea de inscripción pendiente."""
    fecha = fecha_pago or _hoy_local()
    v = _version(version)
    metodo = _metodo_mvp(metodo_codigo)

    linea = linea_inscripcion_pendiente(alumno)
    if linea is None:
        raise ValidationError("No hay cuota de inscripción pendiente para este alumno.")

    if monto_override is not None:
        ajustar_monto_linea(
            linea, Decimal(monto_override), motivo=motivo_ajuste, usuario=usuario
        )
        linea.refresh_from_db()

    saldo = saldo_linea(linea)
    a_pagar = Decimal(monto).quantize(Decimal("0.01")) if monto is not None else saldo
    if a_pagar <= 0:
        raise ValidationError("El abono debe ser positivo.")
    if a_pagar > saldo:
        raise ValidationError(f"El abono (${a_pagar}) supera el saldo (${saldo}).")

    factura = (
        bool(requiere_factura)
        if requiere_factura is not None
        else bool(alumno.requiere_factura)
    )
    iva = _desglose_iva(a_pagar, requiere_factura=factura, version=v)

    reglas = {
        "origen": "inscripcion",
        "fecha_pago": fecha.isoformat(),
        "inscripcion_id": (linea.reglas_aplicadas or {}).get("inscripcion_id"),
        "linea_id": linea.pk,
        "abono": str(a_pagar),
        "saldo_previo": str(saldo),
        "parametro_version_id": v.pk,
        "requiere_factura": factura,
        "monto_iva": str(iva["monto_iva"]),
    }
    pago = Pago.objects.create(
        alumno=alumno,
        metodo=metodo,
        estado=EstadoPago.CONFIRMADO,
        monto_total=iva["monto_total"],
        monto_base=iva["monto_base"],
        monto_iva=iva["monto_iva"],
        tasa_iva=iva["tasa_iva"],
        requiere_factura=factura,
        fecha_pago=fecha,
        referencia=referencia,
        notas=notas,
        parametro_version=v,
        reglas_aplicadas=reglas,
    )
    _aplicar_a_linea(pago, linea, a_pagar)
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
            periodo=periodo, estado__in=ESTADOS_LINEA_ABIERTA
        ).order_by("concepto")
    )


def monto_pendiente(periodo: PeriodoCobroRegular) -> Decimal:
    return sum((saldo_linea(ln) for ln in lineas_pendientes(periodo)), Decimal("0.00"))


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
    monto: Decimal | None = None,
    requiere_factura: bool | None = None,
    monto_override: Decimal | None = None,
    motivo_ajuste: str = "",
    usuario=None,
) -> Pago:
    """
    Registra pago o abono de lineas pendientes del periodo.
    Dias 1-7: sin recargo. 8-10: incluye recargo.
    Post-liberacion: reactiva solo con cupo y saldo en ceros.
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

    if monto_override is not None:
        mensual = next(
            (ln for ln in lineas if ln.concepto == ConceptoLinea.MENSUALIDAD),
            None,
        )
        if mensual is None:
            raise ValidationError("No hay mensualidad para ajustar.")
        ajustar_monto_linea(
            mensual, Decimal(monto_override), motivo=motivo_ajuste, usuario=usuario
        )
        lineas = lineas_pendientes(periodo)

    saldo_total = sum((saldo_linea(ln) for ln in lineas), Decimal("0.00"))
    a_pagar = (
        Decimal(monto).quantize(Decimal("0.01")) if monto is not None else saldo_total
    )
    if a_pagar <= 0:
        raise ValidationError("El abono debe ser positivo.")
    if a_pagar > saldo_total:
        raise ValidationError(
            f"El abono (${a_pagar}) supera el saldo (${saldo_total})."
        )

    con_recargo = any(ln.concepto == ConceptoLinea.RECARGO for ln in lineas)
    factura = (
        bool(requiere_factura)
        if requiere_factura is not None
        else bool(regular.alumno.requiere_factura)
    )
    iva = _desglose_iva(a_pagar, requiere_factura=factura, version=v)

    reactivado = False
    sin_cupo = False
    liquida = a_pagar == saldo_total
    if liquida and estaba_liberado and reactivar_si_liberado:
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
        "abono": str(a_pagar),
        "saldo_previo": str(saldo_total),
        "parcial": not liquida,
        "requiere_factura": factura,
        "lineas": [
            {"id": ln.pk, "concepto": ln.concepto, "monto": str(ln.monto), "saldo": str(saldo_linea(ln))}
            for ln in lineas
        ],
        "parametro_version_id": v.pk,
        "monto_recargo_catalogo": str(v.monto_recargo),
    }

    pago = Pago.objects.create(
        alumno=regular.alumno,
        metodo=metodo,
        estado=EstadoPago.CONFIRMADO,
        monto_total=iva["monto_total"],
        monto_base=iva["monto_base"],
        monto_iva=iva["monto_iva"],
        tasa_iva=iva["tasa_iva"],
        requiere_factura=factura,
        fecha_pago=fecha,
        referencia=referencia,
        notas=notas,
        parametro_version=v,
        reglas_aplicadas=reglas,
    )

    restante = a_pagar
    for ln in lineas:
        if restante <= 0:
            break
        aplicar = min(saldo_linea(ln), restante)
        _aplicar_a_linea(pago, ln, aplicar)
        restante -= aplicar

    if liquida:
        periodo.estado = (
            EstadoPeriodoCobro.PAGADO_CON_RECARGO
            if con_recargo
            else EstadoPeriodoCobro.PAGADO_A_TIEMPO
        )
    elif periodo.estado not in (
        EstadoPeriodoCobro.VENCIDO,
        EstadoPeriodoCobro.LIBERADO,
    ):
        periodo.estado = EstadoPeriodoCobro.PARCIAL
    periodo.save(update_fields=["estado", "updated_at"])

    if reactivado:
        reactivar_regular_si_hay_cupo(regular, fecha=fecha)
    elif liquida and not estaba_liberado and regular.estado == EstadoRegular.ACTIVO:
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
        monto_base=monto,
        monto_iva=Decimal("0.00"),
        fecha_pago=fecha,
        referencia=referencia,
        notas=notas,
        parametro_version=v,
        reglas_aplicadas=reglas,
    )


@transaction.atomic
def asegurar_linea_cargo_alumno(
    *,
    alumno: Alumno,
    concepto: str,
    monto: Decimal,
    reglas: dict | None = None,
    version: ParametroVersion | None = None,
) -> LineaCobro:
    """Línea suelta (pack intro, diferencia de reposición) sin periodo Regular."""
    v = _version(version)
    if monto <= 0:
        raise ValidationError("El monto del cargo debe ser positivo.")
    existente = LineaCobro.objects.filter(
        alumno=alumno,
        concepto=concepto,
        periodo__isnull=True,
        estado__in=ESTADOS_LINEA_ABIERTA,
    ).first()
    if existente:
        return existente
    return LineaCobro.objects.create(
        periodo=None,
        alumno=alumno,
        concepto=concepto,
        monto=monto,
        monto_calculado=monto,
        estado=EstadoLineaCobro.PENDIENTE,
        parametro_version=v,
        reglas_aplicadas=reglas or {},
    )


def crear_pack_intro_iztacalco(*, alumno: Alumno) -> LineaCobro:
    from apps.catalog.models import Sucursal
    from apps.params.models import CodigoTarifa

    sucursal = alumno.sucursal
    if sucursal is None:
        sucursal = Sucursal.objects.filter(codigo="iztacalco").first()
    tarifa = PricingService.tarifa_sucursal(sucursal, CodigoTarifa.PACK_NUEVO_4X3)
    if tarifa is None:
        raise ValidationError("No hay tarifa de pack intro para Iztacalco.")
    return asegurar_linea_cargo_alumno(
        alumno=alumno,
        concepto=ConceptoLinea.PACK_INTRO,
        monto=tarifa.monto,
        reglas={
            "origen": "pack_intro_iztacalco",
            "codigo_tarifa": CodigoTarifa.PACK_NUEVO_4X3,
            "sesiones": 4,
            "horas": 3,
            "sucursal_id": sucursal.pk if sucursal else None,
        },
    )
