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
SALON_DEFAULT = "Salón niños"
SALON_ADULTOS = "Salón adultos"
PROFESOR_DEMO = "Por asignar"

SALONES = (
    "Recepción / espacio pequeño",
    "Salón niños",
    "Salón adultos",
)

# Renombres idempotentes al reseedar (nombres previos → actuales).
SALON_RENAMES = (
    ("Sala multiusos", "Salón niños"),
    ("Sala grande de pintura", "Salón adultos"),
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
# Slots con Flexi: duración exacta 180 min (regla Flexi del service).
HORARIOS_OPERACION: tuple[HorarioOperacion, ...] = (
    # Adultos entre semana (Regular + Flexi + Suelta, 180 min)
    {
        "dia": DiaSemana.LUNES,
        "hora_inicio": _t(16, 0),
        "hora_fin": _t(19, 0),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
        "salon": SALON_ADULTOS,
    },
    {
        "dia": DiaSemana.MIERCOLES,
        "hora_inicio": _t(12, 30),
        "hora_fin": _t(15, 30),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
        "salon": SALON_ADULTOS,
    },
    {
        "dia": DiaSemana.MIERCOLES,
        "hora_inicio": _t(16, 0),
        "hora_fin": _t(19, 0),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
        "salon": SALON_ADULTOS,
    },
    {
        "dia": DiaSemana.VIERNES,
        "hora_inicio": _t(9, 0),
        "hora_fin": _t(12, 0),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
        "salon": SALON_ADULTOS,
    },
    {
        "dia": DiaSemana.VIERNES,
        "hora_inicio": _t(12, 30),
        "hora_fin": _t(15, 30),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
        "salon": SALON_ADULTOS,
    },
    {
        "dia": DiaSemana.VIERNES,
        "hora_inicio": _t(16, 0),
        "hora_fin": _t(19, 0),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
        "salon": SALON_ADULTOS,
    },
    # Adultos sábado mañana (solo Regular, duración distinta)
    {
        "dia": DiaSemana.SABADO,
        "hora_inicio": _t(9, 0),
        "hora_fin": _t(12, 50),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR,
        "salon": SALON_ADULTOS,
    },
    # Adultos sábado 14:00–17:00 (180 min): Regular + Flexi + Suelta
    {
        "dia": DiaSemana.SABADO,
        "hora_inicio": _t(14, 0),
        "hora_fin": _t(17, 0),
        "tipo_alumno": TipoAlumno.ADULTO,
        "modalidades": _MOD_REGULAR_FLEXI_SUELTA,
        "salon": SALON_ADULTOS,
    },
    # Niños (solo Regular) → Salón niños (default)
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
