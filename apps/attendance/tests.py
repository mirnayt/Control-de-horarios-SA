from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.accounts.roles import ROLE_DIRECCION, ROLE_RECEPCION, ensure_roles
from apps.attendance.models import (
    Compensacion,
    EstadoAsistencia,
    EstadoCompensacion,
    TipoCompensacion,
)
from apps.attendance.services import (
    autorizar_reembolso,
    cancelar_por_spirit,
    marcar_asistio,
    marcar_ausente_alumno,
    programar_asistencia_flexi,
    programar_asistencia_regular,
    registrar_reposicion_sin_costo,
)
from apps.catalog.models import Profesor, Salon
from apps.enrollment.services import alta_alumno
from apps.flexi.models import EstadoReservaFlexi
from apps.flexi.services import comprar_paquete_flexi, reservar_flexi
from apps.params.services import seed_parametros_iniciales
from apps.people.models import TipoAlumno
from apps.regular.services import alta_regular
from apps.scheduling.models import DiaSemana, Horario, Modalidad, TipoAlumno as TipoHorario

TZ = ZoneInfo("America/Mexico_City")
User = get_user_model()


class AttendanceBaseTestCase(TestCase):
    def setUp(self):
        ensure_roles()
        self.params = seed_parametros_iniciales()
        self.salon = Salon.objects.create(nombre="Salón A")
        self.profesor = Profesor.objects.create(nombre="Profe A")
        self.recepcion = User.objects.create_user("recep", password="x")
        self.direccion = User.objects.create_user("dir", password="x")
        self.recepcion.groups.add(Group.objects.get(name=ROLE_RECEPCION))
        self.direccion.groups.add(Group.objects.get(name=ROLE_DIRECCION))
        self.otro = User.objects.create_user("otro", password="x")

    def _horario(self, dia=DiaSemana.MARTES, *, duracion=60, capacidad=4, hora=10):
        inicio = time(hora, 0)
        fin_h = hora + duracion // 60
        fin_m = duracion % 60
        return Horario.objects.create(
            dia=dia,
            hora_inicio=inicio,
            hora_fin=time(fin_h, fin_m),
            duracion_minutos=duracion,
            capacidad=capacidad,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.REGULAR, Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )

    def _aware(self, d: date, t: time) -> datetime:
        return timezone.make_aware(datetime.combine(d, t), TZ)


class RegularAsistenciaTests(AttendanceBaseTestCase):
    def test_asistencia_regular(self):
        alumno = alta_alumno(nombre_completo="R1", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        asig = reg.asignaciones.get(activa=True)
        # Martes 4 ago 2026
        asist = programar_asistencia_regular(
            asignacion=asig, fecha=date(2026, 8, 4)
        )
        self.assertEqual(asist.estado, EstadoAsistencia.PROGRAMADA)
        marcar_asistio(asist, usuario=self.recepcion)
        asist.refresh_from_db()
        self.assertEqual(asist.estado, EstadoAsistencia.ASISTIO)

    def test_ausencia_regular_clase_perdida(self):
        alumno = alta_alumno(nombre_completo="R2", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        asig = reg.asignaciones.get(activa=True)
        asist = programar_asistencia_regular(
            asignacion=asig, fecha=date(2026, 8, 4)
        )
        marcar_ausente_alumno(asist, usuario=self.recepcion)
        asist.refresh_from_db()
        self.assertEqual(asist.estado, EstadoAsistencia.AUSENTE_ALUMNO)
        self.assertTrue(asist.detalle.get("clase_perdida"))
        self.assertFalse(
            Compensacion.objects.filter(asistencia=asist).exists()
        )


class CancelacionSpiritTests(AttendanceBaseTestCase):
    def test_cancelacion_spirit_genera_compensacion(self):
        alumno = alta_alumno(nombre_completo="R3", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        asig = reg.asignaciones.get(activa=True)
        asist = programar_asistencia_regular(
            asignacion=asig, fecha=date(2026, 8, 4)
        )
        asist, comp = cancelar_por_spirit(asist, usuario=self.recepcion)
        asist.refresh_from_db()
        comp.refresh_from_db()
        self.assertEqual(asist.estado, EstadoAsistencia.PENDIENTE_COMPENSACION)
        self.assertEqual(comp.estado, EstadoCompensacion.PENDIENTE)
        self.assertEqual(len(comp.historial), 1)
        self.assertEqual(comp.historial[0]["evento"], "creada")


class CompensacionTests(AttendanceBaseTestCase):
    def _pendiente(self):
        alumno = alta_alumno(nombre_completo="C1", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        asig = reg.asignaciones.get(activa=True)
        asist = programar_asistencia_regular(
            asignacion=asig, fecha=date(2026, 8, 4)
        )
        return cancelar_por_spirit(asist, usuario=self.recepcion)

    def test_compensacion_reembolso(self):
        asist, comp = self._pendiente()
        autorizar_reembolso(
            comp,
            usuario=self.direccion,
            monto=Decimal("120.00"),
            notas="Reembolso Spirit",
        )
        comp.refresh_from_db()
        asist.refresh_from_db()
        self.assertEqual(comp.estado, EstadoCompensacion.RESUELTA)
        self.assertEqual(comp.tipo, TipoCompensacion.REEMBOLSO)
        self.assertEqual(comp.monto, Decimal("120.00"))
        self.assertEqual(asist.estado, EstadoAsistencia.CANCELADA_POR_SPIRIT)
        self.assertEqual(len(comp.historial), 2)

    def test_compensacion_reposicion(self):
        asist, comp = self._pendiente()
        registrar_reposicion_sin_costo(
            comp, usuario=self.recepcion, notas="Reposición"
        )
        comp.refresh_from_db()
        asist.refresh_from_db()
        self.assertEqual(comp.estado, EstadoCompensacion.RESUELTA)
        self.assertEqual(comp.tipo, TipoCompensacion.REPOSICION_SIN_COSTO)
        self.assertEqual(asist.estado, EstadoAsistencia.CANCELADA_POR_SPIRIT)
        self.assertEqual(len(comp.historial), 2)


class PermisosCompensacionTests(AttendanceBaseTestCase):
    def _pendiente(self):
        alumno = alta_alumno(nombre_completo="P1", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        asig = reg.asignaciones.get(activa=True)
        asist = programar_asistencia_regular(
            asignacion=asig, fecha=date(2026, 8, 4)
        )
        return cancelar_por_spirit(asist)[1]

    def test_recepcion_no_autoriza_reembolso(self):
        comp = self._pendiente()
        with self.assertRaises(PermissionDenied):
            autorizar_reembolso(comp, usuario=self.recepcion, monto=Decimal("50"))

    def test_direccion_autoriza_reembolso(self):
        comp = self._pendiente()
        autorizar_reembolso(comp, usuario=self.direccion, monto=Decimal("50"))
        comp.refresh_from_db()
        self.assertEqual(comp.estado, EstadoCompensacion.RESUELTA)

    def test_recepcion_registra_reposicion(self):
        comp = self._pendiente()
        registrar_reposicion_sin_costo(comp, usuario=self.recepcion)
        comp.refresh_from_db()
        self.assertEqual(comp.tipo, TipoCompensacion.REPOSICION_SIN_COSTO)

    def test_sin_rol_no_reposicion(self):
        comp = self._pendiente()
        with self.assertRaises(PermissionDenied):
            registrar_reposicion_sin_costo(comp, usuario=self.otro)


class FlexiSinDobleConsumoTests(AttendanceBaseTestCase):
    def test_asistio_flexi_no_doble_consumo(self):
        alumno = alta_alumno(nombre_completo="F1", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES, duracion=60)
        pkg = comprar_paquete_flexi(
            alumno=alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        self.assertEqual(pkg.sesiones_disponibles, 5)
        reserva = reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 1), time(9, 0)),
        )
        pkg.refresh_from_db()
        self.assertEqual(pkg.sesiones_disponibles, 4)
        self.assertEqual(pkg.sesiones_consumidas, 1)

        asist = programar_asistencia_flexi(reserva=reserva)
        marcar_asistio(asist, usuario=self.recepcion)
        pkg.refresh_from_db()
        reserva.refresh_from_db()
        # Sin segundo descuento
        self.assertEqual(pkg.sesiones_disponibles, 4)
        self.assertEqual(pkg.sesiones_consumidas, 1)
        self.assertEqual(reserva.estado, EstadoReservaFlexi.CONSUMIDA)

    def test_ausencia_flexi_no_doble_consumo(self):
        alumno = alta_alumno(nombre_completo="F2", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES, duracion=60)
        pkg = comprar_paquete_flexi(
            alumno=alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        reserva = reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 1), time(9, 0)),
        )
        pkg.refresh_from_db()
        disp_antes = pkg.sesiones_disponibles
        cons_antes = pkg.sesiones_consumidas

        asist = programar_asistencia_flexi(reserva=reserva)
        marcar_ausente_alumno(asist, usuario=self.recepcion)
        pkg.refresh_from_db()
        reserva.refresh_from_db()
        self.assertEqual(pkg.sesiones_disponibles, disp_antes)
        self.assertEqual(pkg.sesiones_consumidas, cons_antes)
        self.assertEqual(reserva.estado, EstadoReservaFlexi.NO_SHOW)

    def test_spirit_cancela_flexi_devuelve_sesion(self):
        alumno = alta_alumno(nombre_completo="F3", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES, duracion=60)
        pkg = comprar_paquete_flexi(
            alumno=alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        reserva = reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 1), time(9, 0)),
        )
        pkg.refresh_from_db()
        self.assertEqual(pkg.sesiones_disponibles, 4)

        asist = programar_asistencia_flexi(reserva=reserva)
        cancelar_por_spirit(asist, usuario=self.recepcion)
        pkg.refresh_from_db()
        reserva.refresh_from_db()
        asist.refresh_from_db()
        self.assertEqual(pkg.sesiones_disponibles, 5)
        self.assertEqual(pkg.sesiones_consumidas, 0)
        self.assertEqual(reserva.estado, EstadoReservaFlexi.CANCELADA)
        self.assertEqual(asist.estado, EstadoAsistencia.PENDIENTE_COMPENSACION)
