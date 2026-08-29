from datetime import date

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied
from django.test import TestCase

from apps.accounts.roles import ROLE_DIRECCION, ROLE_RECEPCION, ensure_roles
from apps.enrollment.services import alta_alumno
from apps.exceptions_ops.models import EstadoExcepcion, TipoExcepcion
from apps.exceptions_ops.services import autorizar, crear_solicitud, rechazar
from apps.params.services import seed_parametros_iniciales
from apps.people.models import TipoAlumno

User = get_user_model()


class ExcepcionesBaseTestCase(TestCase):
    def setUp(self):
        ensure_roles()
        seed_parametros_iniciales()
        self.recepcion = User.objects.create_user("recep", password="x")
        self.direccion = User.objects.create_user("dir", password="x")
        self.recepcion.groups.add(Group.objects.get(name=ROLE_RECEPCION))
        self.direccion.groups.add(Group.objects.get(name=ROLE_DIRECCION))
        self.alumno = alta_alumno(nombre_completo="E1", tipo=TipoAlumno.ADULTO)


class CrearSolicitudTests(ExcepcionesBaseTestCase):
    def test_recepcion_crea_solicitud(self):
        exc = crear_solicitud(
            alumno=self.alumno,
            tipo=TipoExcepcion.MEDICO_PROLONGADO,
            motivo="Tratamiento prolongado",
            fecha_inicio=date(2026, 8, 1),
            fecha_fin=date(2026, 9, 30),
            usuario=self.recepcion,
        )
        self.assertEqual(exc.estado, EstadoExcepcion.SOLICITADA)
        self.assertIsNone(exc.autorizador)
        self.assertEqual(len(exc.historial), 1)
        self.assertEqual(exc.historial[0]["evento"], "solicitada")


class DecisionDireccionTests(ExcepcionesBaseTestCase):
    def _solicitud(self):
        return crear_solicitud(
            alumno=self.alumno,
            tipo=TipoExcepcion.MEDICO_PROLONGADO,
            motivo="Caso médico",
            fecha_inicio=date(2026, 8, 1),
            usuario=self.recepcion,
        )

    def test_direccion_autoriza(self):
        exc = self._solicitud()
        autorizar(exc, usuario=self.direccion, notas="OK")
        exc.refresh_from_db()
        self.assertEqual(exc.estado, EstadoExcepcion.AUTORIZADA)
        self.assertEqual(exc.autorizador, self.direccion)
        self.assertEqual(len(exc.historial), 2)
        self.assertEqual(exc.historial[1]["evento"], "autorizada")

    def test_direccion_rechaza(self):
        exc = self._solicitud()
        rechazar(exc, usuario=self.direccion, notas="Insuficiente")
        exc.refresh_from_db()
        self.assertEqual(exc.estado, EstadoExcepcion.RECHAZADA)
        self.assertEqual(exc.autorizador, self.direccion)
        self.assertEqual(len(exc.historial), 2)
        self.assertEqual(exc.historial[1]["evento"], "rechazada")


class PermisosExcepcionTests(ExcepcionesBaseTestCase):
    def test_recepcion_no_autoriza(self):
        exc = crear_solicitud(
            alumno=self.alumno,
            tipo=TipoExcepcion.OTRO,
            motivo="Solicitud",
            fecha_inicio=date(2026, 8, 1),
            usuario=self.recepcion,
        )
        with self.assertRaises(PermissionDenied):
            autorizar(exc, usuario=self.recepcion)
        with self.assertRaises(PermissionDenied):
            rechazar(exc, usuario=self.recepcion)
        exc.refresh_from_db()
        self.assertEqual(exc.estado, EstadoExcepcion.SOLICITADA)
