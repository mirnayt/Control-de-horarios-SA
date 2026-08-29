from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase

from apps.accounts.roles import (
    ROLE_DIRECCION,
    ROLE_RECEPCION,
    ensure_roles,
    user_is_direccion,
    user_is_recepcion,
)


class RolesTests(TestCase):
    def setUp(self):
        ensure_roles()
        User = get_user_model()
        self.user = User.objects.create_user("recep", password="x")
        self.jefe = User.objects.create_user("dir", password="x")

    def test_groups_exist(self):
        self.assertTrue(Group.objects.filter(name=ROLE_RECEPCION).exists())
        self.assertTrue(Group.objects.filter(name=ROLE_DIRECCION).exists())

    def test_role_helpers(self):
        self.user.groups.add(Group.objects.get(name=ROLE_RECEPCION))
        self.jefe.groups.add(Group.objects.get(name=ROLE_DIRECCION))
        self.assertTrue(user_is_recepcion(self.user))
        self.assertFalse(user_is_direccion(self.user))
        self.assertTrue(user_is_direccion(self.jefe))
