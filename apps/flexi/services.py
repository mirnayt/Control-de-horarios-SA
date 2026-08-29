"""Compra Flexi, reservas, cancelación, no-show y vencimiento."""

from __future__ import annotations

from calendar import monthrange
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.params.models import ParametroVersion, VigenciaFlexi
from apps.params.services import PricingService
from apps.people.models import Alumno, EstadoAlumno, TipoAlumno
from apps.scheduling.models import Modalidad, TipoAlumno as TipoHorario
from apps.scheduling.services import CapacityService

from .models import (
    EstadoPaqueteFlexi,
    EstadoReservaFlexi,
    EjecucionVencimientoFlexi,
    PaqueteFlexi,
    ReservaFlexi,
)


def _hoy_local() -> date:
    return timezone.localdate()


def _ahora() -> datetime:
    return timezone.now()


def _version(version: ParametroVersion | None = None) -> ParametroVersion:
    v = version or ParametroVersion.vigente()
    if v is None:
        raise ValidationError("No hay versión de parámetros vigente.")
    return v


def add_months(d: date, months: int) -> date:
    """Suma meses civiles conservando el día (tope al último del mes)."""
    m0 = d.month - 1 + months
    year = d.year + m0 // 12
    month = m0 % 12 + 1
    day = min(d.day, monthrange(year, month)[1])
    return date(year, month, day)


def meses_vigencia_para(
    sesiones: int,
    *,
    version: ParametroVersion | None = None,
) -> int:
    v = _version(version)
    fila = (
        VigenciaFlexi.objects.filter(
            parametro_version=v,
            sesiones_min__lte=sesiones,
            sesiones_max__gte=sesiones,
        )
        .order_by("sesiones_min")
        .first()
    )
    if fila is None:
        raise ValidationError(
            f"No hay vigencia Flexi configurada para {sesiones} sesiones."
        )
    return fila.meses_vigencia


def fecha_fin_vigencia(fecha_compra: date, meses: int) -> date:
    """Último día inclusive: compra + N meses − 1 día."""
    return add_months(fecha_compra, meses) - timedelta(days=1)


def sesiones_por_horario(horario) -> int:
    """1 sesión Flexi = 1 hora; duración debe ser hora(s) enteras."""
    mins = int(horario.duracion_minutos)
    if mins < 60 or mins % 60 != 0:
        raise ValidationError(
            "Flexi solo admite horarios con duración en horas enteras."
        )
    return mins // 60


def paquete_activo(alumno: Alumno) -> PaqueteFlexi | None:
    return (
        PaqueteFlexi.objects.filter(
            alumno=alumno, estado=EstadoPaqueteFlexi.ACTIVO
        )
        .order_by("-fecha_compra", "-id")
        .first()
    )


def ultimo_paquete(alumno: Alumno) -> PaqueteFlexi | None:
    return (
        PaqueteFlexi.objects.filter(alumno=alumno)
        .order_by("-fecha_compra", "-id")
        .first()
    )


def _mes_siguiente(d: date) -> date:
    return add_months(date(d.year, d.month, 1), 1)


def puede_comprar_flexi(
    alumno: Alumno,
    *,
    fecha: date | None = None,
    version: ParametroVersion | None = None,
) -> tuple[bool, str]:
    """
    Primera compra: cualquier día (sin paquete activo).
    Renovación: solo tras agotado/vencido, en días 1–7 del mes siguiente
    (o meses posteriores 1–7).
    """
    fecha = fecha or _hoy_local()
    v = _version(version)

    if alumno.estado != EstadoAlumno.ACTIVO:
        return False, "El alumno debe estar activo."
    if alumno.tipo != TipoAlumno.ADULTO:
        return False, "Flexi solo aplica a alumnos adultos."

    activo = paquete_activo(alumno)
    if activo is not None:
        return False, "El alumno ya tiene un paquete Flexi activo."

    prev = ultimo_paquete(alumno)
    if prev is None:
        return True, ""

    if prev.estado not in (
        EstadoPaqueteFlexi.AGOTADO,
        EstadoPaqueteFlexi.VENCIDO,
    ):
        return False, f"Paquete previo en estado '{prev.estado}'."

    if not (1 <= fecha.day <= v.dia_pago_normal_fin):
        return False, (
            f"Renovación Flexi solo en días 1–{v.dia_pago_normal_fin}."
        )

    ref = prev.fecha_fin
    if prev.estado == EstadoPaqueteFlexi.AGOTADO:
        # Agotado puede ser antes de fecha_fin; ventana desde el mes siguiente
        # al evento de agotado (aproximado: mes de última actualización útil).
        detalle = prev.detalle or {}
        agotado_iso = detalle.get("agotado_en_fecha")
        if agotado_iso:
            ref = date.fromisoformat(agotado_iso)
        else:
            ref = min(prev.fecha_fin, fecha)

    inicio_ventana = _mes_siguiente(ref)
    if fecha < inicio_ventana:
        return False, (
            "Renovación solo en el siguiente periodo "
            f"(desde {inicio_ventana.isoformat()})."
        )
    return True, ""


def _validar_horario_flexi(alumno: Alumno, horario) -> None:
    if not horario.activo:
        raise ValidationError(f"El horario no está activo: {horario}.")
    modalidades = horario.modalidades or []
    if Modalidad.FLEXI not in modalidades:
        raise ValidationError(f"El horario no acepta modalidad Flexi: {horario}.")
    if horario.tipo_alumno == TipoHorario.NINO:
        raise ValidationError("Flexi no aplica a horarios solo niño.")
    if horario.tipo_alumno == TipoHorario.ADULTO and alumno.tipo != TipoAlumno.ADULTO:
        raise ValidationError("El horario es solo adulto.")
    if horario.tipo_alumno not in (
        TipoHorario.ADULTO,
        TipoHorario.AMBOS,
    ):
        raise ValidationError(f"Tipo de horario no compatible con Flexi: {horario}.")


def _inicio_clase_aware(fecha_clase: date, hora: time) -> datetime:
    naive = datetime.combine(fecha_clase, hora)
    if timezone.is_naive(naive):
        return timezone.make_aware(naive, timezone.get_current_timezone())
    return naive


@transaction.atomic
def comprar_paquete_flexi(
    *,
    alumno: Alumno,
    sesiones: int,
    metodo_codigo: str,
    fecha_compra: date | None = None,
    referencia: str = "",
    notas: str = "",
    version: ParametroVersion | None = None,
) -> PaqueteFlexi:
    """
    Compra 5–30 sesiones a tarifa Flexi $/h (sin descuentos).
    No requiere reserva. Integra Pago en billing.
    """
    fecha = fecha_compra or _hoy_local()
    v = _version(version)

    ok, motivo = puede_comprar_flexi(alumno, fecha=fecha, version=v)
    if not ok:
        raise ValidationError(motivo)

    if not (v.flexi_min_sesiones <= sesiones <= v.flexi_max_sesiones):
        raise ValidationError(
            f"Flexi permite entre {v.flexi_min_sesiones} y "
            f"{v.flexi_max_sesiones} sesiones."
        )

    meses = meses_vigencia_para(sesiones, version=v)
    fin = fecha_fin_vigencia(fecha, meses)
    monto = PricingService.monto_flexi(sesiones, version=v)
    es_renovacion = ultimo_paquete(alumno) is not None

    from apps.billing.services import registrar_pago_flexi

    pago = registrar_pago_flexi(
        alumno=alumno,
        monto=monto,
        metodo_codigo=metodo_codigo,
        fecha_pago=fecha,
        referencia=referencia,
        notas=notas,
        version=v,
        contexto={
            "origen": "paquete_flexi",
            "sesiones": sesiones,
            "meses_vigencia": meses,
            "fecha_fin": fin.isoformat(),
            "es_renovacion": es_renovacion,
            "tarifa_hora": str(v.flexi_tarifa_hora),
        },
    )

    return PaqueteFlexi.objects.create(
        alumno=alumno,
        sesiones_compradas=sesiones,
        sesiones_disponibles=sesiones,
        sesiones_consumidas=0,
        sesiones_vencidas=0,
        meses_vigencia=meses,
        fecha_compra=fecha,
        fecha_fin=fin,
        estado=EstadoPaqueteFlexi.ACTIVO,
        monto=monto,
        parametro_version=v,
        pago=pago,
        es_renovacion=es_renovacion,
        detalle={
            "tarifa_hora": str(v.flexi_tarifa_hora),
            "parametro_version_id": v.pk,
            "meses_vigencia": meses,
        },
    )


@transaction.atomic
def reservar_flexi(
    *,
    paquete: PaqueteFlexi,
    horario,
    fecha_clase: date,
    ahora: datetime | None = None,
) -> ReservaFlexi:
    """Reserva posterior según cupo; descuenta sesiones (horas del horario)."""
    ahora = ahora or _ahora()
    hoy = timezone.localdate(ahora)

    if paquete.estado != EstadoPaqueteFlexi.ACTIVO:
        raise ValidationError("El paquete Flexi no está activo.")
    if hoy > paquete.fecha_fin:
        raise ValidationError("El paquete Flexi está vencido.")
    if fecha_clase < hoy:
        raise ValidationError("No se puede reservar en fecha pasada.")
    if fecha_clase > paquete.fecha_fin:
        raise ValidationError("La clase está fuera de la vigencia del paquete.")

    alumno = paquete.alumno
    _validar_horario_flexi(alumno, horario)

    if int(horario.dia) != fecha_clase.weekday():
        raise ValidationError(
            "fecha_clase no coincide con el día del horario."
        )

    sesiones = sesiones_por_horario(horario)
    if paquete.sesiones_disponibles < sesiones:
        raise ValidationError(
            f"Sesiones insuficientes (disponibles={paquete.sesiones_disponibles}, "
            f"requeridas={sesiones})."
        )

    CapacityService.assert_tiene_cupo(horario, plazas=1)

    if ReservaFlexi.objects.filter(
        paquete=paquete,
        horario=horario,
        fecha_clase=fecha_clase,
        estado=EstadoReservaFlexi.RESERVADA,
    ).exists():
        raise ValidationError("Ya existe una reserva activa para ese horario/fecha.")

    paquete.sesiones_disponibles -= sesiones
    paquete.sesiones_consumidas += sesiones
    update = ["sesiones_disponibles", "sesiones_consumidas", "updated_at"]
    if paquete.sesiones_disponibles == 0:
        paquete.estado = EstadoPaqueteFlexi.AGOTADO
        detalle = dict(paquete.detalle or {})
        detalle["agotado_en_fecha"] = hoy.isoformat()
        paquete.detalle = detalle
        update.extend(["estado", "detalle"])
    paquete.save(update_fields=update)

    return ReservaFlexi.objects.create(
        paquete=paquete,
        horario=horario,
        fecha_clase=fecha_clase,
        hora_inicio=horario.hora_inicio,
        sesiones_usadas=sesiones,
        estado=EstadoReservaFlexi.RESERVADA,
        reservada_en=ahora,
        detalle={"sesiones": sesiones},
    )


@transaction.atomic
def cancelar_reserva_flexi(
    reserva: ReservaFlexi,
    *,
    ahora: datetime | None = None,
    version: ParametroVersion | None = None,
) -> ReservaFlexi:
    """
    ≥ flexi_cancelacion_horas (default 24): conserva sesión.
    < umbral: consume sesión (libera cupo).
    """
    ahora = ahora or _ahora()
    v = _version(version or reserva.paquete.parametro_version)

    if reserva.estado != EstadoReservaFlexi.RESERVADA:
        raise ValidationError(f"La reserva no está activa ({reserva.estado}).")

    inicio = _inicio_clase_aware(reserva.fecha_clase, reserva.hora_inicio)
    anticipacion = inicio - ahora
    umbral = timedelta(hours=v.flexi_cancelacion_horas)
    conserva = anticipacion >= umbral

    paquete = reserva.paquete
    if conserva:
        reserva.estado = EstadoReservaFlexi.CANCELADA
        paquete.sesiones_disponibles += reserva.sesiones_usadas
        paquete.sesiones_consumidas = max(
            0, paquete.sesiones_consumidas - reserva.sesiones_usadas
        )
        campos = ["sesiones_disponibles", "sesiones_consumidas", "updated_at"]
        if paquete.estado == EstadoPaqueteFlexi.AGOTADO and hoy_ok(
            paquete, hoy=timezone.localdate(ahora)
        ):
            paquete.estado = EstadoPaqueteFlexi.ACTIVO
            campos.append("estado")
        paquete.save(update_fields=campos)
    else:
        reserva.estado = EstadoReservaFlexi.CANCELADA_TARDE
        # Sesión ya consumida al reservar; solo libera cupo.

    reserva.cancelada_en = ahora
    detalle = dict(reserva.detalle or {})
    detalle["cancelacion"] = {
        "ahora": ahora.isoformat(),
        "inicio_clase": inicio.isoformat(),
        "horas_anticipo": str(anticipacion.total_seconds() / 3600),
        "umbral_horas": v.flexi_cancelacion_horas,
        "conserva_sesion": conserva,
    }
    reserva.detalle = detalle
    reserva.save(
        update_fields=["estado", "cancelada_en", "detalle", "updated_at"]
    )
    return reserva


def hoy_ok(paquete: PaqueteFlexi, *, hoy: date | None = None) -> bool:
    hoy = hoy or _hoy_local()
    return hoy <= paquete.fecha_fin


@transaction.atomic
def marcar_no_show(
    reserva: ReservaFlexi,
    *,
    ahora: datetime | None = None,
) -> ReservaFlexi:
    """No-show: consume sesión (ya descontada) y libera cupo."""
    ahora = ahora or _ahora()
    if reserva.estado != EstadoReservaFlexi.RESERVADA:
        raise ValidationError(f"La reserva no está activa ({reserva.estado}).")

    reserva.estado = EstadoReservaFlexi.NO_SHOW
    detalle = dict(reserva.detalle or {})
    detalle["no_show_en"] = ahora.isoformat()
    reserva.detalle = detalle
    reserva.save(update_fields=["estado", "detalle", "updated_at"])
    return reserva


@transaction.atomic
def marcar_consumida(
    reserva: ReservaFlexi,
    *,
    ahora: datetime | None = None,
) -> ReservaFlexi:
    """Asistió: sesión ya descontada al reservar; no vuelve a consumir."""
    ahora = ahora or _ahora()
    if reserva.estado == EstadoReservaFlexi.CONSUMIDA:
        return reserva
    if reserva.estado != EstadoReservaFlexi.RESERVADA:
        raise ValidationError(f"La reserva no está activa ({reserva.estado}).")

    reserva.estado = EstadoReservaFlexi.CONSUMIDA
    detalle = dict(reserva.detalle or {})
    detalle["consumida_en"] = ahora.isoformat()
    reserva.detalle = detalle
    reserva.save(update_fields=["estado", "detalle", "updated_at"])
    return reserva


@transaction.atomic
def devolver_por_cancelacion_spirit(
    reserva: ReservaFlexi,
    *,
    ahora: datetime | None = None,
) -> ReservaFlexi:
    """
    Spirit cancela: no consume sesión (devuelve si estaba reservada).
    Idempotente respecto al saldo si ya no está reservada.
    """
    ahora = ahora or _ahora()
    if reserva.estado != EstadoReservaFlexi.RESERVADA:
        detalle = dict(reserva.detalle or {})
        detalle["cancelacion_spirit"] = {
            "ahora": ahora.isoformat(),
            "omitido": True,
            "estado_previo": reserva.estado,
        }
        reserva.detalle = detalle
        reserva.save(update_fields=["detalle", "updated_at"])
        return reserva

    paquete = reserva.paquete
    paquete.sesiones_disponibles += reserva.sesiones_usadas
    paquete.sesiones_consumidas = max(
        0, paquete.sesiones_consumidas - reserva.sesiones_usadas
    )
    campos = ["sesiones_disponibles", "sesiones_consumidas", "updated_at"]
    if paquete.estado == EstadoPaqueteFlexi.AGOTADO and hoy_ok(
        paquete, hoy=timezone.localdate(ahora)
    ):
        paquete.estado = EstadoPaqueteFlexi.ACTIVO
        campos.append("estado")
    paquete.save(update_fields=campos)

    reserva.estado = EstadoReservaFlexi.CANCELADA
    reserva.cancelada_en = ahora
    detalle = dict(reserva.detalle or {})
    detalle["cancelacion_spirit"] = {
        "ahora": ahora.isoformat(),
        "sesiones_devueltas": reserva.sesiones_usadas,
    }
    reserva.detalle = detalle
    reserva.save(
        update_fields=["estado", "cancelada_en", "detalle", "updated_at"]
    )
    return reserva


@transaction.atomic
def vencer_paquete(
    paquete: PaqueteFlexi,
    *,
    fecha: date | None = None,
    ahora: datetime | None = None,
) -> PaqueteFlexi:
    """
    Sobrantes → vencidas (no se acumulan). Idempotente si ya vencido.
    """
    fecha = fecha or _hoy_local()
    ahora = ahora or _ahora()

    if paquete.estado == EstadoPaqueteFlexi.VENCIDO:
        return paquete
    if paquete.estado == EstadoPaqueteFlexi.AGOTADO:
        return paquete
    if fecha <= paquete.fecha_fin:
        return paquete

    sobrantes = paquete.sesiones_disponibles
    paquete.sesiones_vencidas += sobrantes
    paquete.sesiones_disponibles = 0
    paquete.estado = EstadoPaqueteFlexi.VENCIDO
    paquete.vencido_en = ahora
    detalle = dict(paquete.detalle or {})
    detalle["vencimiento"] = {
        "fecha": fecha.isoformat(),
        "sesiones_vencidas": sobrantes,
    }
    paquete.detalle = detalle
    paquete.save(
        update_fields=[
            "sesiones_disponibles",
            "sesiones_vencidas",
            "estado",
            "vencido_en",
            "detalle",
            "updated_at",
        ]
    )

    # Cancelar reservas futuras vigentes (liberar cupo); sesiones ya no aplican.
    futuras = ReservaFlexi.objects.filter(
        paquete=paquete,
        estado=EstadoReservaFlexi.RESERVADA,
        fecha_clase__gt=fecha,
    )
    for r in futuras:
        r.estado = EstadoReservaFlexi.CANCELADA_TARDE
        det = dict(r.detalle or {})
        det["motivo"] = "paquete_vencido"
        r.detalle = det
        r.cancelada_en = ahora
        r.save(
            update_fields=["estado", "detalle", "cancelada_en", "updated_at"]
        )

    return paquete


@transaction.atomic
def ejecutar_vencimiento_flexi(
    *,
    fecha: date | None = None,
    forzar: bool = False,
) -> EjecucionVencimientoFlexi:
    """Job diario idempotente: vence paquetes con fecha_fin < hoy."""
    fecha = fecha or _hoy_local()
    existente = EjecucionVencimientoFlexi.objects.filter(fecha=fecha).first()
    if existente and not forzar:
        return existente

    detalle = {
        "fecha": fecha.isoformat(),
        "vencidos": [],
        "omitidos": [],
    }

    qs = PaqueteFlexi.objects.filter(
        estado=EstadoPaqueteFlexi.ACTIVO,
        fecha_fin__lt=fecha,
    )
    for paquete in qs:
        antes = paquete.sesiones_disponibles
        vencer_paquete(paquete, fecha=fecha)
        paquete.refresh_from_db()
        detalle["vencidos"].append(
            {
                "paquete_id": paquete.pk,
                "sesiones_vencidas": paquete.sesiones_vencidas,
                "sobrantes_al_vencer": antes,
            }
        )

    # Idempotencia a nivel paquete: re-correr no cambia ya vencidos.
    ya = PaqueteFlexi.objects.filter(
        estado=EstadoPaqueteFlexi.VENCIDO,
        fecha_fin__lt=fecha,
        vencido_en__isnull=False,
    )
    for p in ya:
        if not any(x["paquete_id"] == p.pk for x in detalle["vencidos"]):
            detalle["omitidos"].append(
                {"paquete_id": p.pk, "motivo": "ya_vencido"}
            )

    ahora = _ahora()
    if existente:
        existente.ejecutado_en = ahora
        existente.detalle = detalle
        existente.save(update_fields=["ejecutado_en", "detalle", "updated_at"])
        return existente

    return EjecucionVencimientoFlexi.objects.create(
        fecha=fecha,
        ejecutado_en=ahora,
        detalle=detalle,
    )


def job_vencimiento_flexi(
    *, fecha: date | None = None, forzar: bool = False
) -> EjecucionVencimientoFlexi:
    return ejecutar_vencimiento_flexi(fecha=fecha, forzar=forzar)
