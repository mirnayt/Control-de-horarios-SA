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
    SALON_RENAMES,
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

    Clave natural: dia + hora_inicio + tipo_alumno.
    Siempre alinea hora_fin, duración y modalidades (p. ej. Flexi 180 min).
    capacidad/profesor solo se sobrescriben con force=True.
    """
    version = seed_parametros_iniciales(force=force)

    for old_name, new_name in SALON_RENAMES:
        Salon.objects.filter(nombre=old_name).update(nombre=new_name)

    for nombre in SALONES:
        Salon.objects.get_or_create(nombre=nombre, defaults={"activo": True})

    profesor_demo, _ = Profesor.objects.get_or_create(
        nombre=PROFESOR_DEMO,
        defaults={"activo": True, "notas": "Provisional — reemplazar en admin."},
    )

    from apps.catalog.models import Sucursal

    iztacalco = Sucursal.objects.filter(codigo="iztacalco").first()
    if iztacalco:
        Salon.objects.filter(sucursal__isnull=True).update(sucursal=iztacalco)

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
        modalidades = list(slot["modalidades"])

        clave = {
            "dia": slot["dia"],
            "hora_inicio": hora_inicio,
            "tipo_alumno": slot["tipo_alumno"],
        }
        horario = (
            Horario.objects.filter(**clave).order_by("id").first()
        )
        if horario is None:
            Horario.objects.create(
                **clave,
                hora_fin=hora_fin,
                duracion_minutos=duracion,
                capacidad=capacidad,
                modalidades=modalidades,
                activo=True,
                salon=salon,
                profesor=profesor,
            )
            creados += 1
            continue

        changed = False
        if horario.hora_fin != hora_fin:
            horario.hora_fin = hora_fin
            changed = True
        if horario.duracion_minutos != duracion:
            horario.duracion_minutos = duracion
            changed = True
        if list(horario.modalidades or []) != modalidades:
            horario.modalidades = modalidades
            changed = True
        if horario.salon_id != salon.id:
            horario.salon = salon
            changed = True
        if not horario.activo:
            horario.activo = True
            changed = True
        if force:
            if horario.capacidad != capacidad:
                horario.capacidad = capacidad
                changed = True
            if horario.profesor_id != profesor.id:
                horario.profesor = profesor
                changed = True
        if changed:
            horario.save()
            actualizados += 1

        # Evita duplicados del mismo slot con hora_fin antigua.
        Horario.objects.filter(**clave).exclude(pk=horario.pk).delete()

    return OperacionSeedResult(
        salones=Salon.objects.filter(nombre__in=SALONES).count(),
        horarios=Horario.objects.count(),
        horarios_creados=creados,
        horarios_actualizados=actualizados,
        parametros_version_id=version.pk,
    )
