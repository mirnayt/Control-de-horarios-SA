"""Registro de asistencias Regular/Flexi y compensaciones por Spirit."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.roles import user_is_direccion, user_is_recepcion
from apps.flexi.models import EstadoReservaFlexi, ReservaFlexi
from apps.flexi.services import (
    devolver_por_cancelacion_spirit,
    marcar_consumida,
    marcar_no_show,
)
from apps.params.models import ParametroVersion
from apps.params.services import PricingService
from apps.regular.models import AsignacionRegular
from apps.scheduling.models import Horario
from apps.scheduling.services import CapacityService

from .models import (
    Asistencia,
    Compensacion,
    EstadoAsistencia,
    EstadoCompensacion,
    ModalidadAsistencia,
    MotivoCompensacion,
    TipoCompensacion,
)


def _ahora() -> datetime:
    return timezone.now()


def _append_historial(comp: Compensacion, evento: dict) -> None:
    hist = list(comp.historial or [])
    hist.append({**evento, "en": _ahora().isoformat()})
    comp.historial = hist


def _assert_programada(asistencia: Asistencia) -> None:
    if asistencia.estado != EstadoAsistencia.PROGRAMADA:
        raise ValidationError(
            f"La asistencia no está programada ({asistencia.estado})."
        )


@transaction.atomic
def programar_asistencia_regular(
    *,
    asignacion: AsignacionRegular,
    fecha: date,
) -> Asistencia:
    """Crea (o reutiliza) asistencia Regular en estado programada."""
    if not asignacion.activa:
        raise ValidationError("La asignación Regular no está activa.")
    horario = asignacion.horario
    if int(horario.dia) != fecha.weekday():
        raise ValidationError("fecha no coincide con el día del horario.")
    if fecha < asignacion.fecha_inicio:
        raise ValidationError("fecha anterior al inicio de la asignación.")
    if asignacion.fecha_fin and fecha > asignacion.fecha_fin:
        raise ValidationError("fecha posterior al fin de la asignación.")

    alumno = asignacion.regular.alumno
    existente = Asistencia.objects.filter(
        alumno=alumno, horario=horario, fecha=fecha
    ).first()
    if existente:
        return existente

    return Asistencia.objects.create(
        alumno=alumno,
        horario=horario,
        fecha=fecha,
        modalidad=ModalidadAsistencia.REGULAR,
        estado=EstadoAsistencia.PROGRAMADA,
        asignacion_regular=asignacion,
        detalle={"origen": "regular"},
    )


@transaction.atomic
def programar_asistencia_flexi(*, reserva: ReservaFlexi) -> Asistencia:
    """Vincula asistencia a una reserva Flexi vigente o ya creada."""
    if reserva.estado not in (
        EstadoReservaFlexi.RESERVADA,
        EstadoReservaFlexi.CONSUMIDA,
        EstadoReservaFlexi.NO_SHOW,
    ):
        raise ValidationError(
            f"Reserva Flexi no apta para asistencia ({reserva.estado})."
        )

    alumno = reserva.paquete.alumno
    existente = Asistencia.objects.filter(
        alumno=alumno,
        horario=reserva.horario,
        fecha=reserva.fecha_clase,
    ).first()
    if existente:
        if existente.reserva_flexi_id and existente.reserva_flexi_id != reserva.pk:
            raise ValidationError("Ya existe asistencia distinta para esa fecha.")
        return existente

    return Asistencia.objects.create(
        alumno=alumno,
        horario=reserva.horario,
        fecha=reserva.fecha_clase,
        modalidad=ModalidadAsistencia.FLEXI,
        estado=EstadoAsistencia.PROGRAMADA,
        reserva_flexi=reserva,
        detalle={"origen": "flexi", "reserva_id": reserva.pk},
    )


@transaction.atomic
def marcar_asistio(
    asistencia: Asistencia,
    *,
    usuario=None,
    observaciones: str = "",
    ahora: datetime | None = None,
) -> Asistencia:
    ahora = ahora or _ahora()
    _assert_programada(asistencia)

    if asistencia.modalidad == ModalidadAsistencia.FLEXI:
        if not asistencia.reserva_flexi_id:
            raise ValidationError("Asistencia Flexi sin reserva.")
        # Sesión ya descontada al reservar → solo marca consumida.
        marcar_consumida(asistencia.reserva_flexi, ahora=ahora)

    asistencia.estado = EstadoAsistencia.ASISTIO
    asistencia.registrado_por = usuario
    asistencia.registrado_en = ahora
    if observaciones:
        asistencia.observaciones = observaciones
    detalle = dict(asistencia.detalle or {})
    detalle["asistio_en"] = ahora.isoformat()
    asistencia.detalle = detalle
    asistencia.save(
        update_fields=[
            "estado",
            "registrado_por",
            "registrado_en",
            "observaciones",
            "detalle",
            "updated_at",
        ]
    )
    if asistencia.es_reposicion:
        origen = Compensacion.objects.filter(
            asistencia_reposicion=asistencia,
            estado=EstadoCompensacion.AGENDADA,
        ).first()
        if origen:
            origen.estado = EstadoCompensacion.RESUELTA
            origen.resuelta_en = ahora
            origen.resuelta_por = usuario
            _append_historial(
                origen,
                {
                    "evento": "resuelta",
                    "tipo": origen.tipo,
                    "usuario_id": getattr(usuario, "pk", None),
                },
            )
            origen.save()
            orig_asist = origen.asistencia
            if orig_asist.estado == EstadoAsistencia.PENDIENTE_COMPENSACION:
                orig_asist.estado = EstadoAsistencia.CANCELADA_POR_SPIRIT
                orig_asist.save(update_fields=["estado", "updated_at"])
    return asistencia


@transaction.atomic
def marcar_ausente_alumno(
    asistencia: Asistencia,
    *,
    usuario=None,
    observaciones: str = "",
    ahora: datetime | None = None,
) -> Asistencia:
    """
    Regular: clase perdida (sin compensación).
    Flexi: no-show vía servicio existente (sin doble consumo).
    """
    ahora = ahora or _ahora()
    _assert_programada(asistencia)

    if asistencia.modalidad == ModalidadAsistencia.FLEXI:
        if not asistencia.reserva_flexi_id:
            raise ValidationError("Asistencia Flexi sin reserva.")
        marcar_no_show(asistencia.reserva_flexi, ahora=ahora)

    asistencia.estado = EstadoAsistencia.AUSENTE_ALUMNO
    asistencia.registrado_por = usuario
    asistencia.registrado_en = ahora
    if observaciones:
        asistencia.observaciones = observaciones
    detalle = dict(asistencia.detalle or {})
    detalle["ausente_en"] = ahora.isoformat()
    detalle["clase_perdida"] = asistencia.modalidad == ModalidadAsistencia.REGULAR
    asistencia.detalle = detalle
    asistencia.save(
        update_fields=[
            "estado",
            "registrado_por",
            "registrado_en",
            "observaciones",
            "detalle",
            "updated_at",
        ]
    )
    return asistencia


@transaction.atomic
def cancelar_por_spirit(
    asistencia: Asistencia,
    *,
    usuario=None,
    observaciones: str = "",
    ahora: datetime | None = None,
) -> tuple[Asistencia, Compensacion]:
    """
    Spirit cancela: no consume sesión, no cuenta como ausencia,
    genera Compensacion pendiente. Asistencia → pendiente_compensacion.
    """
    ahora = ahora or _ahora()
    _assert_programada(asistencia)

    if asistencia.modalidad == ModalidadAsistencia.FLEXI:
        if not asistencia.reserva_flexi_id:
            raise ValidationError("Asistencia Flexi sin reserva.")
        devolver_por_cancelacion_spirit(asistencia.reserva_flexi, ahora=ahora)

    asistencia.estado = EstadoAsistencia.PENDIENTE_COMPENSACION
    asistencia.registrado_por = usuario
    asistencia.registrado_en = ahora
    if observaciones:
        asistencia.observaciones = observaciones
    detalle = dict(asistencia.detalle or {})
    detalle["cancelada_por_spirit_en"] = ahora.isoformat()
    asistencia.detalle = detalle
    asistencia.save(
        update_fields=[
            "estado",
            "registrado_por",
            "registrado_en",
            "observaciones",
            "detalle",
            "updated_at",
        ]
    )

    existente = Compensacion.objects.filter(asistencia=asistencia).first()
    if existente:
        return asistencia, existente

    comp = Compensacion.objects.create(
        asistencia=asistencia,
        motivo=MotivoCompensacion.CANCELACION_SPIRIT,
        estado=EstadoCompensacion.PENDIENTE,
        historial=[],
    )
    _append_historial(
        comp,
        {
            "evento": "creada",
            "motivo": MotivoCompensacion.CANCELACION_SPIRIT,
            "usuario_id": getattr(usuario, "pk", None),
        },
    )
    comp.save(update_fields=["historial", "updated_at"])
    return asistencia, comp


def _assert_pendiente(comp: Compensacion) -> None:
    if comp.estado != EstadoCompensacion.PENDIENTE:
        raise ValidationError(f"La compensación no está pendiente ({comp.estado}).")
    if comp.asistencia.estado != EstadoAsistencia.PENDIENTE_COMPENSACION:
        raise ValidationError(
            f"Asistencia no pendiente de compensación ({comp.asistencia.estado})."
        )


@transaction.atomic
def autorizar_reembolso(
    compensacion: Compensacion,
    *,
    usuario,
    monto: Decimal | None = None,
    notas: str = "",
    ahora: datetime | None = None,
) -> Compensacion:
    """Solo Dirección autoriza reembolso."""
    ahora = ahora or _ahora()
    if not user_is_direccion(usuario):
        raise PermissionDenied("Solo Dirección puede autorizar reembolso.")
    _assert_pendiente(compensacion)

    if monto is not None and monto < 0:
        raise ValidationError("El monto de reembolso no puede ser negativo.")

    compensacion.tipo = TipoCompensacion.REEMBOLSO
    compensacion.estado = EstadoCompensacion.RESUELTA
    compensacion.monto = monto
    compensacion.autorizada_por = usuario
    compensacion.resuelta_por = usuario
    compensacion.resuelta_en = ahora
    if notas:
        compensacion.notas = notas
    _append_historial(
        compensacion,
        {
            "evento": "resuelta",
            "tipo": TipoCompensacion.REEMBOLSO,
            "monto": str(monto) if monto is not None else None,
            "usuario_id": usuario.pk,
            "notas": notas,
        },
    )
    compensacion.save()

    asist = compensacion.asistencia
    asist.estado = EstadoAsistencia.CANCELADA_POR_SPIRIT
    det = dict(asist.detalle or {})
    det["compensacion_resuelta"] = {
        "tipo": TipoCompensacion.REEMBOLSO,
        "en": ahora.isoformat(),
    }
    asist.detalle = det
    asist.save(update_fields=["estado", "detalle", "updated_at"])
    return compensacion


@transaction.atomic
def registrar_reposicion_sin_costo(
    compensacion: Compensacion,
    *,
    usuario,
    notas: str = "",
    ahora: datetime | None = None,
) -> Compensacion:
    """Recepción (o Dirección) registra reposición sin costo."""
    ahora = ahora or _ahora()
    if not (user_is_recepcion(usuario) or user_is_direccion(usuario)):
        raise PermissionDenied(
            "Solo Recepción o Dirección pueden registrar reposición sin costo."
        )
    _assert_pendiente(compensacion)

    compensacion.tipo = TipoCompensacion.REPOSICION_SIN_COSTO
    compensacion.estado = EstadoCompensacion.RESUELTA
    compensacion.resuelta_por = usuario
    compensacion.resuelta_en = ahora
    if notas:
        compensacion.notas = notas
    _append_historial(
        compensacion,
        {
            "evento": "resuelta",
            "tipo": TipoCompensacion.REPOSICION_SIN_COSTO,
            "usuario_id": usuario.pk,
            "notas": notas,
        },
    )
    compensacion.save()

    asist = compensacion.asistencia
    asist.estado = EstadoAsistencia.CANCELADA_POR_SPIRIT
    det = dict(asist.detalle or {})
    det["compensacion_resuelta"] = {
        "tipo": TipoCompensacion.REPOSICION_SIN_COSTO,
        "en": ahora.isoformat(),
    }
    asist.detalle = det
    asist.save(update_fields=["estado", "detalle", "updated_at"])
    return compensacion


def _inicio_clase(asistencia: Asistencia) -> datetime:
    return timezone.make_aware(
        datetime.combine(asistencia.fecha, asistencia.horario.hora_inicio)
    )


@transaction.atomic
def avisar_falta_alumno(
    asistencia: Asistencia,
    *,
    usuario=None,
    observaciones: str = "",
    ahora: datetime | None = None,
) -> tuple[Asistencia, Compensacion]:
    """
    Aviso anticipado: genera compensación/reposición.
    Si avisa tarde, queda como ausencia (clase perdida).
    """
    ahora = ahora or _ahora()
    _assert_programada(asistencia)
    version = ParametroVersion.vigente()
    horas = version.horas_aviso_reposicion if version else 24
    inicio = _inicio_clase(asistencia)
    if ahora >= inicio - timedelta(hours=horas):
        raise ValidationError(
            f"El aviso requiere {horas} h de anticipación. Marque ausencia (clase perdida)."
        )

    asistencia.estado = EstadoAsistencia.PENDIENTE_COMPENSACION
    asistencia.registrado_por = usuario
    asistencia.registrado_en = ahora
    if observaciones:
        asistencia.observaciones = observaciones
    detalle = dict(asistencia.detalle or {})
    detalle["aviso_falta_en"] = ahora.isoformat()
    detalle["horas_aviso_requeridas"] = horas
    asistencia.detalle = detalle
    asistencia.save(
        update_fields=[
            "estado",
            "registrado_por",
            "registrado_en",
            "observaciones",
            "detalle",
            "updated_at",
        ]
    )
    existente = Compensacion.objects.filter(asistencia=asistencia).first()
    if existente:
        return asistencia, existente
    comp = Compensacion.objects.create(
        asistencia=asistencia,
        motivo=MotivoCompensacion.AVISO_ALUMNO,
        estado=EstadoCompensacion.PENDIENTE,
        historial=[],
    )
    _append_historial(
        comp,
        {
            "evento": "creada",
            "motivo": MotivoCompensacion.AVISO_ALUMNO,
            "usuario_id": getattr(usuario, "pk", None),
        },
    )
    comp.save(update_fields=["historial", "updated_at"])
    return asistencia, comp


@transaction.atomic
def agendar_reposicion(
    compensacion: Compensacion,
    *,
    horario: Horario,
    fecha: date,
    usuario,
    ahora: datetime | None = None,
) -> tuple[Compensacion, Asistencia]:
    """Agenda reposición el mismo día u otra fecha, con cupo. Cobra diferencia si aplica."""
    ahora = ahora or _ahora()
    if not (user_is_recepcion(usuario) or user_is_direccion(usuario)):
        raise PermissionDenied(
            "Solo Recepción o Dirección pueden agendar reposición."
        )
    _assert_pendiente(compensacion)

    if int(horario.dia) != fecha.weekday():
        raise ValidationError("La fecha no coincide con el día del horario.")
    CapacityService.assert_tiene_cupo(horario, plazas=1, fecha_clase=fecha)

    origen = compensacion.asistencia
    suc_origen = getattr(origen.horario.salon, "sucursal", None)
    suc_destino = getattr(horario.salon, "sucursal", None)
    plan_horas = None
    if origen.asignacion_regular_id:
        plan_horas = origen.asignacion_regular.regular.plan_horas_semana

    diferencia = PricingService.monto_diferencia_reposicion(
        sucursal_origen=suc_origen,
        sucursal_destino=suc_destino,
        duracion_origen_minutos=origen.horario.duracion_minutos,
        duracion_destino_minutos=horario.duracion_minutos,
        plan_horas_semana=plan_horas,
    )

    linea = None
    tipo = TipoCompensacion.REPOSICION_SIN_COSTO
    if diferencia > 0:
        from apps.billing.models import ConceptoLinea
        from apps.billing.services import asegurar_linea_cargo_alumno

        tipo = TipoCompensacion.REPOSICION_CON_DIFERENCIA
        linea = asegurar_linea_cargo_alumno(
            alumno=origen.alumno,
            concepto=ConceptoLinea.DIFERENCIA_REPOSICION,
            monto=diferencia,
            reglas={
                "origen": "reposicion_cruce_sucursal",
                "compensacion_id": compensacion.pk,
                "asistencia_origen_id": origen.pk,
                "sucursal_origen_id": getattr(suc_origen, "pk", None),
                "sucursal_destino_id": getattr(suc_destino, "pk", None),
                "horario_destino_id": horario.pk,
                "fecha": fecha.isoformat(),
            },
        )

    reposicion = Asistencia.objects.create(
        alumno=origen.alumno,
        horario=horario,
        fecha=fecha,
        modalidad=origen.modalidad,
        estado=EstadoAsistencia.PROGRAMADA,
        asignacion_regular=origen.asignacion_regular,
        reserva_flexi=origen.reserva_flexi,
        es_reposicion=True,
        observaciones=f"Reposición de {origen.fecha}",
        detalle={
            "origen": "reposicion",
            "asistencia_origen_id": origen.pk,
            "compensacion_id": compensacion.pk,
        },
    )

    compensacion.tipo = tipo
    compensacion.estado = EstadoCompensacion.AGENDADA
    compensacion.monto_diferencia = diferencia
    compensacion.asistencia_reposicion = reposicion
    compensacion.linea_cobro = linea
    compensacion.resuelta_por = usuario
    _append_historial(
        compensacion,
        {
            "evento": "agendada",
            "tipo": tipo,
            "horario_id": horario.pk,
            "fecha": fecha.isoformat(),
            "diferencia": str(diferencia),
            "usuario_id": usuario.pk,
        },
    )
    compensacion.save()
    return compensacion, reposicion
