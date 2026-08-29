"""
Configuración editable de operación Spirit Academia (Etapa 14).

Valores CONFIRMADOS (negocio): horarios, modalidades por tipo/día, tarifas (vía seed_params).
Valores PROVISIONALES (editar aquí o en admin tras el seed):
  - CAPACIDAD_PLACEHOLDER
  - SALON_DEFAULT
  - PROFESOR_DEMO
  - asignación salon/profesor/capacidad por horario (si no se sobreescribe abajo)
"""

from __future__ import annotations

from datetime import time
from typing import TypedDict

from apps.scheduling.models import DiaSemana, Modalidad, TipoAlumno

# --- Provisionales (no son reglas de negocio; solo defaults del seed) ---
CAPACIDAD_PLACEHOLDER = 8
SALON_DEFAULT = "Sala multiusos"
PROFESOR_DEMO = "Por asignar"

SALONES = (
    "Recepción / espacio pequeño",
    "Sala multiusos",
    "Sala grande de pintura",
)


class HorarioOperacion(TypedDict, total=False):
    dia: int
    hora_inicio: time
    hora_fin: time
    tipo_alumno: str
    modalidades: list[str]
    capacidad: int
    salon: str
    profesor: str


def _t(h: int, m: int = 0) -> time:
    return time(h, m)


_MOD_REGULAR_FLEXI_SUELTA = [Modalidad.REGULAR, Modalidad.FLEXI, Modalidad.SUELTA]
_MOD_REGULAR = [Modalidad.REGULAR]

# Horarios confirmados Spirit Academia.
HORARIOS_OPERACION: tuple[HorarioOperacion, ...] = (
    # Adultos entre semana
    {
        "dia": DiaSemana.LUNES,
        "hora_inicio": _t(16, 0),
        "hora_fin": _t(18, 50),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
    },
    {
        "dia": DiaSemana.MIERCOLES,
        "hora_inicio": _t(12, 30),
        "hora_fin": _t(15, 20),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
    },
    {
        "dia": DiaSemana.MIERCOLES,
        "hora_inicio": _t(16, 0),
        "hora_fin": _t(18, 50),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
    },
    {
        "dia": DiaSemana.VIERNES,
        "hora_inicio": _t(9, 0),
        "hora_fin": _t(11, 50),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
    },
    {
        "dia": DiaSemana.VIERNES,
        "hora_inicio": _t(12, 30),
        "hora_fin": _t(15, 20),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
    },
    {
        "dia": DiaSemana.VIERNES,
        "hora_inicio": _t(16, 0),
        "hora_fin": _t(18, 50),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
    },
    # Adultos sábado (solo Regular)
    {
        "dia": DiaSemana.SABADO,
        "hora_inicio": _t(9, 0),
        "hora_fin": _t(12, 50),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR,
    },
    {
        "dia": DiaSemana.SABADO,
        "hora_inicio": _t(14, 0),
        "hora_fin": _t(17, 0),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR,
    },
    # Niños (solo Regular)
    {
        "dia": DiaSemana.MARTES,
        "hora_inicio": _t(15, 50),
        "hora_fin": _t(17, 50),
        "tipo_alumno": TipoAlumno.NINO,
        "modalidades": _MOD_REGULAR,
    },
    {
        "dia": DiaSemana.JUEVES,
        "hora_inicio": _t(15, 50),
        "hora_fin": _t(17, 50),
        "tipo_alumno": TipoAlumno.NINO,
        "modalidades": _MOD_REGULAR,
    },
    {
        "dia": DiaSemana.SABADO,
        "hora_inicio": _t(11, 0),
        "hora_fin": _t(12, 50),
        "tipo_alumno": TipoAlumno.NINO,
        "modalidades": _MOD_REGULAR,
    },
    {
        "dia": DiaSemana.SABADO,
        "hora_inicio": _t(14, 0),
        "hora_fin": _t(15, 50),
        "tipo_alumno": TipoAlumno.NINO,
        "modalidades": _MOD_REGULAR,
    },
)
