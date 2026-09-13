"""Contexto global para layout operativo (nav, brand)."""

from apps.accounts.roles import user_is_direccion, user_is_recepcion

_NAV_SECTIONS: dict[str, str] = {
    "home": "home",
    "alumnos_list": "alumnos",
    "alumno_alta": "alumnos",
    "alumno_detail": "alumnos",
    "horarios_list": "horarios",
    "horario_roster": "horarios",
    "pagos_list": "pagos",
    "pago_periodo": "pagos",
    "pago_inscripcion": "pagos",
    "regular_list": "regular",
    "regular_alta": "regular",
    "flexi_list": "flexi",
    "flexi_comprar": "flexi",
    "flexi_reservar": "flexi",
    "flexi_cancelar": "flexi",
    "asistencias_list": "asistencias",
    "asistencia_programar": "asistencias",
    "asistencia_accion": "asistencias",
    "compensaciones_list": "compensaciones",
    "compensacion_accion": "compensaciones",
    "excepciones_list": "excepciones",
    "excepcion_nueva": "excepciones",
    "excepcion_accion": "excepciones",
}


def operative_ui(request):
    if not request.user.is_authenticated:
        return {}
    match = getattr(request, "resolver_match", None)
    url_name = match.url_name if match else ""
    return {
        "es_direccion": user_is_direccion(request.user),
        "es_recepcion": user_is_recepcion(request.user),
        "nav_section": _NAV_SECTIONS.get(url_name, ""),
    }
