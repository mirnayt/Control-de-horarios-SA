"""Roles operativos MVP: recepcion / direccion (Django Groups)."""

ROLE_RECEPCION = "recepcion"
ROLE_DIRECCION = "direccion"

ALL_ROLES = (ROLE_RECEPCION, ROLE_DIRECCION)


def ensure_roles():
    """Crea los grupos de rol si no existen."""
    from django.contrib.auth.models import Group

    for name in ALL_ROLES:
        Group.objects.get_or_create(name=name)


def user_has_role(user, role_name: str) -> bool:
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return True
    return user.groups.filter(name=role_name).exists()


def user_is_recepcion(user) -> bool:
    return user_has_role(user, ROLE_RECEPCION)


def user_is_direccion(user) -> bool:
    return user_has_role(user, ROLE_DIRECCION)
