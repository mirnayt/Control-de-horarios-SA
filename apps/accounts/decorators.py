"""Decoradores de acceso para UI interna (recepción / dirección)."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

from .roles import user_is_direccion, user_is_recepcion


def staff_operativo_required(view_func):
    """Recepción o Dirección (operación diaria)."""

    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not (user_is_recepcion(request.user) or user_is_direccion(request.user)):
            raise PermissionDenied("Se requiere rol Recepción o Dirección.")
        return view_func(request, *args, **kwargs)

    return _wrapped


def direccion_required(view_func):
    """Solo Dirección (excepciones / reembolsos)."""

    @login_required
    @wraps(view_func)
    def _wrapped(request, *args, **kwargs):
        if not user_is_direccion(request.user):
            raise PermissionDenied("Se requiere rol Dirección.")
        return view_func(request, *args, **kwargs)

    return _wrapped
