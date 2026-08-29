"""Seed reproducible de catálogo y horarios operativos Spirit Academia."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from apps.catalog.models import Profesor, Salon
from apps.params.services import seed_parametros_iniciales
from apps.scheduling.models import Horario

from .operacion_config import (
    CAPACIDAD_PLACEHOLDER,
    HORARIOS_OPERACION,
    PROFESOR_DEMO,
    SALON_DEFAULT,
    SALONES,
)


@dataclass
class OperacionSeedResult:
    salones: int
    horarios: int
    horarios_creados: int
    horarios_actualizados: int
    parametros_version_id: int


def _duracion_minutos(hora_inicio, hora_fin) -> int:
    delta = datetime.combine(datetime.min, hora_fin) - datetime.combine(
        datetime.min, hora_inicio
    )
    return int(delta.total_seconds() // 60)


def seed_operacion_spirit(*, force: bool = False) -> OperacionSeedResult:
    """
    Carga salones, profesor demo, horarios y parámetros vigentes.

    Idempotente: si los horarios ya existen (misma clave natural), no los modifica
    salvo con force=True.
    """
    version = seed_parametros_iniciales(force=force)

    for nombre in SALONES:
        Salon.objects.get_or_create(nombre=nombre, defaults={"activo": True})

    profesor_demo, _ = Profesor.objects.get_or_create(
        nombre=PROFESOR_DEMO,
        defaults={"activo": True, "notas": "Provisional — reemplazar en admin."},
    )

    salon_default = Salon.objects.get(nombre=SALON_DEFAULT)
    creados = 0
    actualizados = 0

    for slot in HORARIOS_OPERACION:
        salon_nombre = slot.get("salon", SALON_DEFAULT)
        salon = Salon.objects.get(nombre=salon_nombre)
        profesor_nombre = slot.get("profesor", PROFESOR_DEMO)
        profesor = (
            profesor_demo
            if profesor_nombre == PROFESOR_DEMO
            else Profesor.objects.get(nombre=profesor_nombre)
        )
        capacidad = slot.get("capacidad", CAPACIDAD_PLACEHOLDER)
        hora_inicio = slot["hora_inicio"]
        hora_fin = slot["hora_fin"]
        duracion = _duracion_minutos(hora_inicio, hora_fin)

        lookup = {
            "dia": slot["dia"],
            "hora_inicio": hora_inicio,
            "hora_fin": hora_fin,
            "tipo_alumno": slot["tipo_alumno"],
        }
        defaults = {
            "duracion_minutos": duracion,
            "capacidad": capacidad,
            "modalidades": list(slot["modalidades"]),
            "activo": True,
            "salon": salon,
            "profesor": profesor,
        }

        horario, created = Horario.objects.get_or_create(**lookup, defaults=defaults)
        if created:
            creados += 1
            continue

        if force:
            for field, value in defaults.items():
                setattr(horario, field, value)
            horario.save()
            actualizados += 1

    return OperacionSeedResult(
        salones=Salon.objects.filter(nombre__in=SALONES).count(),
        horarios=Horario.objects.count(),
        horarios_creados=creados,
        horarios_actualizados=actualizados,
        parametros_version_id=version.pk,
    )
