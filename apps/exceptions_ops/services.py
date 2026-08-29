"""Excepciones operativas manuales: solicitud Recepción, decisión Dirección."""

from __future__ import annotations

from datetime import date, datetime

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.roles import user_is_direccion, user_is_recepcion
from apps.people.models import Alumno

from .models import EstadoExcepcion, ExcepcionAutorizada, TipoExcepcion


def _ahora() -> datetime:
    return timezone.now()


def _append_historial(exc: ExcepcionAutorizada, evento: dict) -> None:
    hist = list(exc.historial or [])
    hist.append({**evento, "en": _ahora().isoformat()})
    exc.historial = hist


def _assert_solicitada(exc: ExcepcionAutorizada) -> None:
    if exc.estado != EstadoExcepcion.SOLICITADA:
        raise ValidationError(
            f"La excepción no está solicitada ({exc.estado})."
        )


@transaction.atomic
def crear_solicitud(
    *,
    alumno: Alumno,
    tipo: str,
    motivo: str,
    fecha_inicio: date,
    usuario,
    fecha_fin: date | None = None,
    notas: str = "",
) -> ExcepcionAutorizada:
    """Recepción (o Dirección) crea solicitud de excepción. Sin efectos automáticos."""
    if not (user_is_recepcion(usuario) or user_is_direccion(usuario)):
        raise PermissionDenied(
            "Solo Recepción o Dirección pueden crear solicitudes de excepción."
        )
    if tipo not in TipoExcepcion.values:
        raise ValidationError({"tipo": f"Tipo inválido: {tipo}"})
    motivo_limpio = (motivo or "").strip()
    if not motivo_limpio:
        raise ValidationError({"motivo": "El motivo es obligatorio."})

    exc = ExcepcionAutorizada(
        alumno=alumno,
        tipo=tipo,
        motivo=motivo_limpio,
        fecha_inicio=fecha_inicio,
        fecha_fin=fecha_fin,
        estado=EstadoExcepcion.SOLICITADA,
        notas=notas or "",
        historial=[],
    )
    exc.full_clean()
    exc.save()
    _append_historial(
        exc,
        {
            "evento": "solicitada",
            "usuario_id": usuario.pk,
            "tipo": tipo,
            "motivo": motivo_limpio,
        },
    )
    exc.save(update_fields=["historial", "updated_at"])
    return exc


@transaction.atomic
def autorizar(
    excepcion: ExcepcionAutorizada,
    *,
    usuario,
    notas: str = "",
    ahora: datetime | None = None,
) -> ExcepcionAutorizada:
    """Solo Dirección autoriza. No congela ni aplica reglas médicas automáticamente."""
    ahora = ahora or _ahora()
    if not user_is_direccion(usuario):
        raise PermissionDenied("Solo Dirección puede autorizar excepciones.")
    _assert_solicitada(excepcion)

    excepcion.estado = EstadoExcepcion.AUTORIZADA
    excepcion.autorizador = usuario
    if notas:
        excepcion.notas = notas
    _append_historial(
        excepcion,
        {
            "evento": "autorizada",
            "usuario_id": usuario.pk,
            "notas": notas,
        },
    )
    excepcion.save()
    return excepcion


@transaction.atomic
def rechazar(
    excepcion: ExcepcionAutorizada,
    *,
    usuario,
    notas: str = "",
    ahora: datetime | None = None,
) -> ExcepcionAutorizada:
    """Solo Dirección rechaza."""
    ahora = ahora or _ahora()
    if not user_is_direccion(usuario):
        raise PermissionDenied("Solo Dirección puede rechazar excepciones.")
    _assert_solicitada(excepcion)

    excepcion.estado = EstadoExcepcion.RECHAZADA
    excepcion.autorizador = usuario
    if notas:
        excepcion.notas = notas
    _append_historial(
        excepcion,
        {
            "evento": "rechazada",
            "usuario_id": usuario.pk,
            "notas": notas,
        },
    )
    excepcion.save()
    return excepcion
