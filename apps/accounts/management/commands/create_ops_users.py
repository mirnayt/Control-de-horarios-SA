"""Crea usuarios operativos recepción / dirección (idempotente)."""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.roles import ROLE_DIRECCION, ROLE_RECEPCION, ensure_roles


class Command(BaseCommand):
    help = (
        "Crea o actualiza usuarios operativos recepción y dirección. "
        "Contraseñas: --recepcion-password / --direccion-password o "
        "OPS_RECEPCION_PASSWORD / OPS_DIRECCION_PASSWORD."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--recepcion-username",
            default=os.getenv("OPS_RECEPCION_USERNAME", "recepcion"),
        )
        parser.add_argument(
            "--direccion-username",
            default=os.getenv("OPS_DIRECCION_USERNAME", "direccion"),
        )
        parser.add_argument(
            "--recepcion-password",
            default=os.getenv("OPS_RECEPCION_PASSWORD", ""),
        )
        parser.add_argument(
            "--direccion-password",
            default=os.getenv("OPS_DIRECCION_PASSWORD", ""),
        )
        parser.add_argument(
            "--reset-passwords",
            action="store_true",
            help="Actualiza la contraseña aunque el usuario ya exista.",
        )

    def handle(self, *args, **options):
        ensure_roles()
        User = get_user_model()

        recepcion_password = options["recepcion_password"] or "recepcion123"
        direccion_password = options["direccion_password"] or "direccion123"

        if not options["recepcion_password"] and not options["direccion_password"]:
            self.stdout.write(
                self.style.WARNING(
                    "Usando contraseñas por defecto (recepcion123 / direccion123). "
                    "En producción define OPS_RECEPCION_PASSWORD y OPS_DIRECCION_PASSWORD."
                )
            )

        created = []
        for username, password, role in (
            (options["recepcion_username"], recepcion_password, ROLE_RECEPCION),
            (options["direccion_username"], direccion_password, ROLE_DIRECCION),
        ):
            if not username:
                raise CommandError("Username operativo vacío.")
            user, was_created = User.objects.get_or_create(username=username)
            if was_created or options["reset_passwords"]:
                user.set_password(password)
                user.save()
            user.groups.set([Group.objects.get(name=role)])
            created.append(
                f"{username} ({'creado' if was_created else 'actualizado'}; rol={role})"
            )

        self.stdout.write(self.style.SUCCESS("; ".join(created)))
