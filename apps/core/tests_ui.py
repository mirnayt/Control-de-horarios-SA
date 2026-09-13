"""Tests mínimos UI: acceso por rol y flujos principales."""

from datetime import date, time, timedelta
from decimal import Decimal
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from apps.accounts.roles import ROLE_DIRECCION, ROLE_RECEPCION, ensure_roles
from apps.attendance.models import EstadoAsistencia, EstadoCompensacion
from apps.attendance.services import cancelar_por_spirit, programar_asistencia_regular
from apps.catalog.models import Profesor, Salon
from apps.enrollment.services import alta_alumno
from apps.exceptions_ops.models import EstadoExcepcion, TipoExcepcion
from apps.flexi.models import EstadoPaqueteFlexi, EstadoReservaFlexi
from apps.flexi.services import comprar_paquete_flexi, reservar_flexi
from apps.params.services import seed_parametros_iniciales
from apps.people.models import EstadoAlumno, TipoAlumno
from apps.regular.services import alta_regular
from apps.scheduling.models import DiaSemana, Horario, Modalidad, TipoAlumno as TipoHorario

User = get_user_model()

OPS_URLS = [
    "home",
    "alumnos_list",
    "horarios_list",
    "pagos_list",
    "regular_list",
    "flexi_list",
    "asistencias_list",
    "compensaciones_list",
    "excepciones_list",
]


class UIAccessTests(TestCase):
    def setUp(self):
        ensure_roles()
        seed_parametros_iniciales()
        self.recepcion = User.objects.create_user("recep", password="x")
        self.direccion = User.objects.create_user("dir", password="x")
        self.otro = User.objects.create_user("otro", password="x")
        self.recepcion.groups.add(Group.objects.get(name=ROLE_RECEPCION))
        self.direccion.groups.add(Group.objects.get(name=ROLE_DIRECCION))

    def test_anonimo_redirige_login(self):
        c = Client()
        for name in OPS_URLS:
            r = c.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn("/login/", r.url)

    def test_sin_rol_prohibido(self):
        c = Client()
        c.login(username="otro", password="x")
        for name in OPS_URLS:
            r = c.get(reverse(name))
            self.assertEqual(r.status_code, 403, name)

    def test_recepcion_accede_operacion(self):
        c = Client()
        c.login(username="recep", password="x")
        for name in OPS_URLS:
            r = c.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)

    def test_direccion_accede_operacion(self):
        c = Client()
        c.login(username="dir", password="x")
        for name in OPS_URLS:
            r = c.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)


class UIFlowTests(TestCase):
    def setUp(self):
        ensure_roles()
        seed_parametros_iniciales()
        self.salon = Salon.objects.create(nombre="S1")
        self.profesor = Profesor.objects.create(nombre="P1")
        self.recepcion = User.objects.create_user("recep", password="x")
        self.direccion = User.objects.create_user("dir", password="x")
        self.recepcion.groups.add(Group.objects.get(name=ROLE_RECEPCION))
        self.direccion.groups.add(Group.objects.get(name=ROLE_DIRECCION))
        self.c = Client()
        self.c.login(username="recep", password="x")

    def _horario(self):
        return Horario.objects.create(
            dia=DiaSemana.MARTES,
            hora_inicio=time(10, 0),
            hora_fin=time(11, 0),
            duracion_minutos=60,
            capacidad=4,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.REGULAR, Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )

    def test_alta_alumno(self):
        r = self.c.post(
            reverse("alumno_alta"),
            {"nombre_completo": "Ana UI", "tipo": TipoAlumno.ADULTO, "notas": ""},
        )
        self.assertEqual(r.status_code, 302)
        from apps.people.models import Alumno

        self.assertTrue(Alumno.objects.filter(nombre_completo="Ana UI").exists())

    def test_alta_regular_y_pago(self):
        alumno = alta_alumno(nombre_completo="Reg UI", tipo=TipoAlumno.ADULTO)
        h = self._horario()
        r = self.c.post(
            reverse("regular_alta"),
            {"alumno_id": alumno.pk, "horario_ids": [h.pk]},
        )
        self.assertEqual(r.status_code, 302)
        from apps.regular.models import PeriodoCobroRegular, Regular

        reg = Regular.objects.get(alumno=alumno)
        periodo = PeriodoCobroRegular.objects.get(regular=reg)
        r2 = self.c.post(
            reverse("pago_periodo", args=[periodo.pk]),
            {"metodo_codigo": "efectivo", "referencia": "t1", "notas": ""},
        )
        self.assertEqual(r2.status_code, 302)
        periodo.refresh_from_db()
        self.assertIn(periodo.estado, ("pagado_a_tiempo", "pagado_con_recargo"))

    def test_flexi_compra(self):
        alumno = alta_alumno(nombre_completo="Flex UI", tipo=TipoAlumno.ADULTO)
        r = self.c.post(
            reverse("flexi_comprar"),
            {
                "alumno_id": alumno.pk,
                "sesiones": "10",
                "metodo_codigo": "efectivo",
                "referencia": "",
            },
        )
        self.assertEqual(r.status_code, 302)
        from apps.flexi.models import PaqueteFlexi

        self.assertTrue(PaqueteFlexi.objects.filter(alumno=alumno).exists())

    def test_excepcion_recepcion_solicita_direccion_autoriza(self):
        alumno = alta_alumno(nombre_completo="Exc UI", tipo=TipoAlumno.ADULTO)
        r = self.c.post(
            reverse("excepcion_nueva"),
            {
                "alumno_id": alumno.pk,
                "tipo": TipoExcepcion.OTRO,
                "motivo": "Viaje",
                "fecha_inicio": "2026-08-01",
                "fecha_fin": "",
                "notas": "",
            },
        )
        self.assertEqual(r.status_code, 302)
        from apps.exceptions_ops.models import ExcepcionAutorizada

        exc = ExcepcionAutorizada.objects.get(alumno=alumno)
        self.assertEqual(exc.estado, EstadoExcepcion.SOLICITADA)

        # Recepción no puede autorizar (servicio niega; queda solicitada)
        r_deny = self.c.post(
            reverse("excepcion_accion", args=[exc.pk]),
            {"accion": "autorizar", "notas": ""},
        )
        self.assertEqual(r_deny.status_code, 302)
        exc.refresh_from_db()
        self.assertEqual(exc.estado, EstadoExcepcion.SOLICITADA)

        cd = Client()
        cd.login(username="dir", password="x")
        r_ok = cd.post(
            reverse("excepcion_accion", args=[exc.pk]),
            {"accion": "autorizar", "notas": "OK"},
        )
        self.assertEqual(r_ok.status_code, 302)
        exc.refresh_from_db()
        self.assertEqual(exc.estado, EstadoExcepcion.AUTORIZADA)

    def test_compensacion_reembolso_solo_direccion(self):
        alumno = alta_alumno(nombre_completo="Comp UI", tipo=TipoAlumno.ADULTO)
        h = self._horario()
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        asig = reg.asignaciones.get(activa=True)
        asist = programar_asistencia_regular(
            asignacion=asig, fecha=date(2026, 8, 4)
        )
        _, comp = cancelar_por_spirit(asist, usuario=self.recepcion)

        r = self.c.post(
            reverse("compensacion_accion", args=[comp.pk]),
            {"accion": "reembolso", "monto": "100", "notas": ""},
        )
        self.assertEqual(r.status_code, 302)
        comp.refresh_from_db()
        self.assertEqual(comp.estado, EstadoCompensacion.PENDIENTE)

        cd = Client()
        cd.login(username="dir", password="x")
        r2 = cd.post(
            reverse("compensacion_accion", args=[comp.pk]),
            {"accion": "reembolso", "monto": "100", "notas": "ok"},
        )
        self.assertEqual(r2.status_code, 302)
        comp.refresh_from_db()
        self.assertEqual(comp.estado, EstadoCompensacion.RESUELTA)
        asist.refresh_from_db()
        self.assertEqual(asist.estado, EstadoAsistencia.CANCELADA_POR_SPIRIT)
        self.assertEqual(comp.monto, Decimal("100"))


class UIHardeningTests(TestCase):
    """Etapa 13: selects vacíos, modalidad, filtros y mensajes claros."""

    def setUp(self):
        ensure_roles()
        seed_parametros_iniciales()
        self.salon = Salon.objects.create(nombre="S1")
        self.profesor = Profesor.objects.create(nombre="P1")
        self.recepcion = User.objects.create_user("recep_h", password="x")
        self.recepcion.groups.add(Group.objects.get(name=ROLE_RECEPCION))
        self.c = Client()
        self.c.login(username="recep_h", password="x")

    def _horario(self, *, modalidades=None, activo=True, capacidad=4):
        return Horario.objects.create(
            dia=DiaSemana.MARTES,
            hora_inicio=time(10, 0),
            hora_fin=time(11, 0),
            duracion_minutos=60,
            capacidad=capacidad,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=modalidades or [Modalidad.REGULAR, Modalidad.FLEXI],
            activo=activo,
            salon=self.salon,
            profesor=self.profesor,
        )

    def test_flexi_reservar_sin_paquetes_muestra_mensaje(self):
        r = self.c.get(reverse("flexi_reservar"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Sin paquetes disponibles")
        self.assertContains(r, "Comprar Flexi")

    def test_flexi_reservar_excluye_paquete_sin_saldo_o_vencido(self):
        alumno = alta_alumno(nombre_completo="Pkg UI", tipo=TipoAlumno.ADULTO)
        h = self._horario()
        pkg = comprar_paquete_flexi(
            alumno=alumno, sesiones=10, metodo_codigo="efectivo"
        )
        pkg.sesiones_disponibles = 0
        pkg.estado = EstadoPaqueteFlexi.AGOTADO
        pkg.save()
        alumno2 = alta_alumno(nombre_completo="Pkg UI2", tipo=TipoAlumno.ADULTO)
        pkg2 = comprar_paquete_flexi(
            alumno=alumno2, sesiones=5, metodo_codigo="efectivo"
        )
        pkg2.fecha_fin = timezone.localdate() - timedelta(days=1)
        pkg2.save()
        alumno3 = alta_alumno(nombre_completo="Pkg UI3", tipo=TipoAlumno.ADULTO)
        pkg3 = comprar_paquete_flexi(
            alumno=alumno3, sesiones=5, metodo_codigo="efectivo"
        )
        r = self.c.get(reverse("flexi_reservar"))
        content = r.content.decode()
        bloque = re.search(
            r'name="paquete_id".*?</select>', content, re.S
        ).group(0)
        self.assertIn(f'<option value="{pkg3.pk}">', bloque)
        for excluido in (pkg, pkg2):
            self.assertNotIn(f'<option value="{excluido.pk}">', bloque)

    def test_flexi_reservar_solo_horarios_flexi_con_cupo(self):
        alumno = alta_alumno(nombre_completo="Hor UI", tipo=TipoAlumno.ADULTO)
        pkg = comprar_paquete_flexi(alumno=alumno, sesiones=10, metodo_codigo="efectivo")
        hoy = timezone.localdate()
        h_flexi = Horario.objects.create(
            dia=hoy.weekday(),
            hora_inicio=time(10, 0),
            hora_fin=time(13, 0),
            duracion_minutos=180,
            capacidad=4,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )
        h_regular = self._horario(modalidades=[Modalidad.REGULAR])
        h_lleno = Horario.objects.create(
            dia=hoy.weekday(),
            hora_inicio=time(14, 0),
            hora_fin=time(17, 0),
            duracion_minutos=180,
            capacidad=1,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.REGULAR, Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )
        alta_regular(
            alumno=alta_alumno(nombre_completo="Llena", tipo=TipoAlumno.ADULTO),
            horarios=[h_lleno],
            fecha_inicio=date(2026, 8, 1),
        )
        r = self.c.get(
            reverse("flexi_reservar"),
            {"paquete_id": pkg.pk, "fecha_clase": hoy.isoformat()},
        )
        content = r.content.decode()
        self.assertIn(f'<option value="{h_flexi.pk}">', content)
        self.assertNotIn(f'<option value="{h_regular.pk}">', content)
        self.assertNotIn(f'<option value="{h_lleno.pk}">', content)

    def test_asistencia_programar_campos_por_modalidad(self):
        r = self.c.get(reverse("asistencia_programar"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'id="bloque-regular"')
        self.assertContains(r, 'id="bloque-flexi" hidden')
        self.assertContains(r, "Sin asignaciones activas")
        self.assertContains(r, "Sin reservas Flexi vigentes")

    def test_asistencia_flexi_reserva_invalida_mensaje_claro(self):
        r = self.c.post(
            reverse("asistencia_programar"),
            {"modalidad": "flexi", "reserva_id": "99999"},
            follow=True,
        )
        self.assertContains(r, "Seleccione una reserva Flexi vigente")
        self.assertNotContains(r, "matching query does not exist")

    def test_asistencia_flexi_sin_reserva_mensaje_claro(self):
        r = self.c.post(
            reverse("asistencia_programar"),
            {"modalidad": "flexi", "reserva_id": ""},
            follow=True,
        )
        self.assertContains(r, "Seleccione una reserva Flexi.")

    def test_regular_alta_sin_horarios_mensaje(self):
        alumno = alta_alumno(nombre_completo="SinHor", tipo=TipoAlumno.ADULTO)
        self._horario(modalidades=[Modalidad.FLEXI])
        r = self.c.get(reverse("regular_alta"), {"alumno_id": alumno.pk})
        self.assertContains(r, "No hay horarios Regular activos con cupo")
        self.assertContains(r, "Revisar horarios y cupos")

    def test_regular_alta_nino_solo_ve_horarios_nino(self):
        nino = alta_alumno(nombre_completo="Nino UI", tipo=TipoAlumno.NINO)
        adulto = alta_alumno(nombre_completo="Adulto UI", tipo=TipoAlumno.ADULTO)
        h_nino = Horario.objects.create(
            dia=DiaSemana.MARTES,
            hora_inicio=time(15, 50),
            hora_fin=time(17, 50),
            duracion_minutos=120,
            capacidad=4,
            tipo_alumno=TipoHorario.NINO,
            modalidades=[Modalidad.REGULAR],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )
        h_adulto = Horario.objects.create(
            dia=DiaSemana.LUNES,
            hora_inicio=time(16, 0),
            hora_fin=time(19, 0),
            duracion_minutos=180,
            capacidad=4,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.REGULAR],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )
        h_ambos = Horario.objects.create(
            dia=DiaSemana.MIERCOLES,
            hora_inicio=time(10, 0),
            hora_fin=time(11, 0),
            duracion_minutos=60,
            capacidad=4,
            tipo_alumno=TipoHorario.AMBOS,
            modalidades=[Modalidad.REGULAR],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )
        r_nino = self.c.get(reverse("regular_alta"), {"alumno_id": nino.pk})
        content_nino = r_nino.content.decode()
        self.assertIn(f'value="{h_nino.pk}"', content_nino)
        self.assertIn(f'value="{h_ambos.pk}"', content_nino)
        self.assertNotIn(f'value="{h_adulto.pk}"', content_nino)

        r_adulto = self.c.get(reverse("regular_alta"), {"alumno_id": adulto.pk})
        content_adulto = r_adulto.content.decode()
        self.assertIn(f'value="{h_adulto.pk}"', content_adulto)
        self.assertIn(f'value="{h_ambos.pk}"', content_adulto)
        self.assertNotIn(f'value="{h_nino.pk}"', content_adulto)

    def test_excepcion_solo_alumnos_activos(self):
        activo = alta_alumno(nombre_completo="Activo", tipo=TipoAlumno.ADULTO)
        baja = alta_alumno(nombre_completo="Baja", tipo=TipoAlumno.ADULTO)
        baja.estado = EstadoAlumno.BAJA_VOLUNTARIA
        baja.save()
        r = self.c.get(reverse("excepcion_nueva"))
        self.assertContains(r, activo.nombre_completo)
        self.assertNotContains(r, baja.nombre_completo)

    def test_programar_flexi_con_reserva_valida(self):
        alumno = alta_alumno(nombre_completo="Res UI", tipo=TipoAlumno.ADULTO)
        h = Horario.objects.create(
            dia=timezone.localdate().weekday(),
            hora_inicio=time(10, 0),
            hora_fin=time(13, 0),
            duracion_minutos=180,
            capacidad=4,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )
        pkg = comprar_paquete_flexi(
            alumno=alumno, sesiones=10, metodo_codigo="efectivo"
        )
        reserva = reservar_flexi(
            paquete=pkg, horario=h, fecha_clase=timezone.localdate()
        )
        r = self.c.post(
            reverse("asistencia_programar"),
            {"modalidad": "flexi", "reserva_id": reserva.pk},
        )
        self.assertEqual(r.status_code, 302)
        self.assertEqual(reserva.estado, EstadoReservaFlexi.RESERVADA)


class UIDashboardTests(TestCase):
    """Etapa 15: dashboard de recepción y ficha de alumno."""

    def setUp(self):
        ensure_roles()
        seed_parametros_iniciales()
        self.salon = Salon.objects.create(nombre="S1")
        self.profesor = Profesor.objects.create(nombre="P1")
        self.recepcion = User.objects.create_user("recep_d", password="x")
        self.recepcion.groups.add(Group.objects.get(name=ROLE_RECEPCION))
        self.c = Client()
        self.c.login(username="recep_d", password="x")

    def _horario(self, *, dia=None):
        if dia is None:
            dia = timezone.localdate().weekday()
        return Horario.objects.create(
            dia=dia,
            hora_inicio=time(10, 0),
            hora_fin=time(11, 0),
            duracion_minutos=60,
            capacidad=4,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.REGULAR, Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )

    def test_home_dashboard_secciones(self):
        r = self.c.get(reverse("home"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Acciones rápidas")
        self.assertContains(r, "Clases de hoy")
        self.assertContains(r, "Pagos pendientes")
        self.assertContains(r, "Flexi por vencer")
        self.assertContains(r, reverse("alumno_alta"))
        self.assertContains(r, reverse("asistencia_programar"))

    def test_home_muestra_clase_hoy_y_pago_pendiente(self):
        h = self._horario()
        alumno = alta_alumno(nombre_completo="Dash UI", tipo=TipoAlumno.ADULTO)
        alta_regular(alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1))
        r = self.c.get(reverse("home"))
        self.assertContains(r, str(h))
        self.assertContains(r, "Dash UI")
        self.assertContains(r, "Cobrar")

    def test_home_flexi_por_vencer(self):
        alumno = alta_alumno(nombre_completo="Vence UI", tipo=TipoAlumno.ADULTO)
        pkg = comprar_paquete_flexi(
            alumno=alumno, sesiones=10, metodo_codigo="efectivo"
        )
        pkg.fecha_fin = timezone.localdate() + timedelta(days=5)
        pkg.save()
        r = self.c.get(reverse("home"))
        self.assertContains(r, "Vence UI")
        self.assertContains(r, "Flexi por vencer")

    def test_alumno_detail_secciones_y_acciones(self):
        alumno = alta_alumno(nombre_completo="Ficha UI", tipo=TipoAlumno.ADULTO)
        h = self._horario()
        alta_regular(alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1))
        comprar_paquete_flexi(alumno=alumno, sesiones=10, metodo_codigo="efectivo")
        r = self.c.get(reverse("alumno_detail", args=[alumno.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Plan Regular")
        self.assertContains(r, "Pagos pendientes")
        self.assertContains(r, "Flexi")
        self.assertContains(r, "Asistencias recientes")
        self.assertContains(r, f"alumno_id={alumno.pk}")

    def test_formularios_preseleccionan_alumno(self):
        alumno = alta_alumno(nombre_completo="Pre UI", tipo=TipoAlumno.ADULTO)
        q = f"?alumno_id={alumno.pk}"
        for name in ("flexi_comprar", "excepcion_nueva"):
            r = self.c.get(reverse(name) + q)
            self.assertContains(
                r,
                f'<option value="{alumno.pk}" selected>',
                msg_prefix=name,
            )
        r = self.c.get(reverse("regular_alta") + q)
        self.assertContains(r, alumno.nombre_completo)
        self.assertContains(r, f'name="alumno_id" value="{alumno.pk}"')
        r = self.c.get(reverse("flexi_reservar") + q)
        self.assertEqual(r.status_code, 200)
        r2 = self.c.get(reverse("asistencia_programar") + q)
        self.assertEqual(r2.status_code, 200)


class UIUXPolishTests(TestCase):
    """Etapa 18: pulido UX operativo."""

    def setUp(self):
        ensure_roles()
        seed_parametros_iniciales()
        self.salon = Salon.objects.create(nombre="S1")
        self.profesor = Profesor.objects.create(nombre="P1")
        self.recepcion = User.objects.create_user("recep_u", password="x")
        self.direccion = User.objects.create_user("dir_u", password="x")
        self.recepcion.groups.add(Group.objects.get(name=ROLE_RECEPCION))
        self.direccion.groups.add(Group.objects.get(name=ROLE_DIRECCION))
        self.c = Client()
        self.c.login(username="recep_u", password="x")

    def _horario(self, dia=None):
        if dia is None:
            dia = DiaSemana.MARTES
        return Horario.objects.create(
            dia=dia,
            hora_inicio=time(10, 0),
            hora_fin=time(11, 0),
            duracion_minutos=60,
            capacidad=4,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.REGULAR, Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )

    def test_listas_enlazan_ficha_alumno(self):
        alumno = alta_alumno(nombre_completo="Link UI", tipo=TipoAlumno.ADULTO)
        h = self._horario()
        reg = alta_regular(alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1))
        comprar_paquete_flexi(alumno=alumno, sesiones=10, metodo_codigo="efectivo")
        asig = reg.asignaciones.get(activa=True)
        asist = programar_asistencia_regular(asignacion=asig, fecha=date(2026, 8, 4))
        cancelar_por_spirit(asist, usuario=self.recepcion)
        self.c.post(
            reverse("excepcion_nueva"),
            {
                "alumno_id": alumno.pk,
                "tipo": TipoExcepcion.OTRO,
                "motivo": "Viaje",
                "fecha_inicio": "2026-08-01",
                "fecha_fin": "",
                "notas": "",
            },
        )
        url_ficha = reverse("alumno_detail", args=[alumno.pk])
        for name in (
            "pagos_list",
            "flexi_list",
            "asistencias_list",
            "compensaciones_list",
            "excepciones_list",
            "regular_list",
        ):
            r = self.c.get(reverse(name))
            self.assertContains(r, url_ficha, msg_prefix=name)

    def test_home_kpis_clicables_y_total_pendiente(self):
        alumno = alta_alumno(nombre_completo="KPI UI", tipo=TipoAlumno.ADULTO)
        h = self._horario(dia=timezone.localdate().weekday())
        alta_regular(alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1))
        r = self.c.get(reverse("home"))
        self.assertContains(r, reverse("horarios_list"))
        self.assertContains(r, reverse("pagos_list"))
        self.assertContains(r, reverse("flexi_list"))
        self.assertContains(r, "stat-card-link")
        self.assertContains(r, "$")

    def test_alumnos_busqueda_por_nombre(self):
        alta_alumno(nombre_completo="Ana Busca", tipo=TipoAlumno.ADULTO)
        alta_alumno(nombre_completo="Pedro Otro", tipo=TipoAlumno.ADULTO)
        r = self.c.get(reverse("alumnos_list"), {"q": "Ana"})
        self.assertContains(r, "Ana Busca")
        self.assertNotContains(r, "Pedro Otro")

    def test_pagos_muestra_desglose_y_formato_moneda(self):
        alumno = alta_alumno(nombre_completo="Pago UI", tipo=TipoAlumno.ADULTO)
        h = self._horario()
        alta_regular(alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1))
        r = self.c.get(reverse("pagos_list"))
        self.assertContains(r, "Mensualidad")
        self.assertContains(r, "$")

    def test_regular_alta_cupo_y_contador(self):
        alumno = alta_alumno(nombre_completo="Cupo UI", tipo=TipoAlumno.ADULTO)
        self._horario()
        r = self.c.get(reverse("regular_alta"), {"alumno_id": alumno.pk})
        self.assertContains(r, "cupo")
        self.assertContains(r, "0/3")

    def test_asistencia_programar_fecha_hoy_y_lista_horario(self):
        from apps.core.ui import proxima_fecha_dia

        alumno = alta_alumno(nombre_completo="Asis UI", tipo=TipoAlumno.ADULTO)
        h = self._horario()
        reg = alta_regular(alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1))
        programar_asistencia_regular(
            asignacion=reg.asignaciones.get(activa=True),
            fecha=date(2026, 8, 4),
        )
        r = self.c.get(reverse("asistencia_programar"))
        sugerida = proxima_fecha_dia(h.dia).isoformat()
        self.assertContains(r, f'data-fecha="{sugerida}"')
        self.assertContains(r, f'value="{sugerida}"')
        r2 = self.c.get(reverse("asistencias_list"))
        self.assertContains(r2, str(h))

    def test_excepciones_muestra_fechas_y_pendiente_direccion(self):
        alumno = alta_alumno(nombre_completo="Exc UX", tipo=TipoAlumno.ADULTO)
        self.c.post(
            reverse("excepcion_nueva"),
            {
                "alumno_id": alumno.pk,
                "tipo": TipoExcepcion.OTRO,
                "motivo": "Viaje",
                "fecha_inicio": "2026-08-01",
                "fecha_fin": "2026-08-15",
                "notas": "",
            },
        )
        r = self.c.get(reverse("excepciones_list"))
        self.assertContains(r, "2026")
        self.assertContains(r, "Pendiente de Dirección")
        self.assertContains(r, "Espera decisión de Dirección")
        cd = Client()
        cd.login(username="dir_u", password="x")
        r_dir = cd.get(reverse("excepciones_list"))
        self.assertContains(r_dir, "Autorizar")
        self.assertContains(r_dir, "Rechazar")

    def test_ficha_separa_bajas(self):
        alumno = alta_alumno(nombre_completo="Baja UI", tipo=TipoAlumno.ADULTO)
        r = self.c.get(reverse("alumno_detail", args=[alumno.pk]))
        self.assertContains(r, "panel-danger")
        self.assertContains(r, "Baja / reactivación")

    def test_nav_activo_subpantallas(self):
        alumno = alta_alumno(nombre_completo="Nav UI", tipo=TipoAlumno.ADULTO)
        from apps.regular.models import PeriodoCobroRegular

        h = self._horario()
        alta_regular(alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1))
        periodo = PeriodoCobroRegular.objects.first()
        checks = [
            (reverse("pago_periodo", args=[periodo.pk]), reverse("pagos_list")),
            (reverse("regular_alta"), reverse("regular_list")),
            (reverse("flexi_comprar"), reverse("flexi_list")),
            (reverse("compensaciones_list"), reverse("compensaciones_list")),
            (reverse("excepcion_nueva"), reverse("excepciones_list")),
        ]
        for page_url, nav_href in checks:
            r = self.c.get(page_url)
            self.assertRegex(
                r.content.decode(),
                rf'class="nav-link active" href="{re.escape(nav_href)}"',
                msg=page_url,
            )

    def test_brand_por_rol(self):
        r_rec = self.c.get(reverse("home"))
        self.assertContains(r_rec, "Recepción")
        cd = Client()
        cd.login(username="dir_u", password="x")
        r_dir = cd.get(reverse("home"))
        self.assertContains(r_dir, "Dirección")


class UIRecepcionDiaTests(TestCase):
    """Inicio + horarios + roster para operar el día."""

    def setUp(self):
        ensure_roles()
        seed_parametros_iniciales()
        self.salon = Salon.objects.create(nombre="S1")
        self.profesor = Profesor.objects.create(nombre="P1")
        self.recepcion = User.objects.create_user("recep_dia", password="x")
        self.recepcion.groups.add(Group.objects.get(name=ROLE_RECEPCION))
        self.c = Client()
        self.c.login(username="recep_dia", password="x")
        self.hoy = timezone.localdate()

    def _horario(self, dia=None, *, flexi=False):
        if dia is None:
            dia = self.hoy.weekday()
        if flexi:
            return Horario.objects.create(
                dia=dia,
                hora_inicio=time(10, 0),
                hora_fin=time(13, 0),
                duracion_minutos=180,
                capacidad=4,
                tipo_alumno=TipoHorario.ADULTO,
                modalidades=[Modalidad.REGULAR, Modalidad.FLEXI],
                activo=True,
                salon=self.salon,
                profesor=self.profesor,
            )
        return Horario.objects.create(
            dia=dia,
            hora_inicio=time(10, 0),
            hora_fin=time(11, 0),
            duracion_minutos=60,
            capacidad=4,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.REGULAR, Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )

    def test_home_clases_hoy_ver_grupo_y_buscar(self):
        h = self._horario()
        alumno = alta_alumno(nombre_completo="Grupo UI", tipo=TipoAlumno.ADULTO)
        alta_regular(alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1))
        r = self.c.get(reverse("home"))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Buscar alumno")
        self.assertContains(r, "P1")
        self.assertContains(r, "1/4")
        self.assertContains(r, reverse("horario_roster", args=[h.pk]))
        self.assertContains(r, "Ver grupo")
        self.assertContains(r, reverse("alumnos_list"))

    def test_horarios_filtro_hoy_cuenta_flexi_con_fecha(self):
        h = self._horario(flexi=True)
        alumno = alta_alumno(nombre_completo="Flex Hoy", tipo=TipoAlumno.ADULTO)
        pkg = comprar_paquete_flexi(
            alumno=alumno, sesiones=10, metodo_codigo="efectivo"
        )
        reservar_flexi(paquete=pkg, horario=h, fecha_clase=self.hoy)
        r = self.c.get(reverse("horarios_list"), {"dia": self.hoy.weekday()})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Regular + Flexi")
        fila = r.context["filas"][0]
        self.assertEqual(fila["regulares"], 0)
        self.assertEqual(fila["flexi"], 1)
        self.assertEqual(fila["ocupados"], 1)
        self.assertEqual(r.context["fecha_clase"], self.hoy)
        self.assertContains(r, reverse("horario_roster", args=[h.pk]))

    def test_horarios_sin_fecha_solo_regular(self):
        otro = (self.hoy.weekday() + 1) % 7
        h = self._horario(dia=otro, flexi=True)
        alumno = alta_alumno(nombre_completo="Solo Reg", tipo=TipoAlumno.ADULTO)
        alta_regular(alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1))
        pkg = comprar_paquete_flexi(
            alumno=alumno, sesiones=10, metodo_codigo="efectivo"
        )
        delta = (otro - self.hoy.weekday()) % 7
        if delta == 0:
            delta = 7
        fecha_res = self.hoy + timedelta(days=delta)
        reservar_flexi(paquete=pkg, horario=h, fecha_clase=fecha_res)

        r = self.c.get(reverse("horarios_list"), {"dia": otro})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "solo ocupación Regular")
        self.assertIsNone(r.context["fecha_clase"])
        fila = r.context["filas"][0]
        self.assertEqual(fila["regulares"], 1)
        self.assertEqual(fila["flexi"], 0)
        self.assertEqual(fila["ocupados"], 1)
        self.assertContains(r, "—")

    def test_roster_con_fecha_lista_regular_y_flexi(self):
        h = self._horario(flexi=True)
        reg_al = alta_alumno(nombre_completo="Reg Roster", tipo=TipoAlumno.ADULTO)
        flex_al = alta_alumno(nombre_completo="Flex Roster", tipo=TipoAlumno.ADULTO)
        alta_regular(alumno=reg_al, horarios=[h], fecha_inicio=date(2026, 8, 1))
        pkg = comprar_paquete_flexi(
            alumno=flex_al, sesiones=10, metodo_codigo="efectivo"
        )
        reservar_flexi(paquete=pkg, horario=h, fecha_clase=self.hoy)
        url = reverse("horario_roster", args=[h.pk])
        r = self.c.get(url, {"fecha": self.hoy.isoformat()})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Reg Roster")
        self.assertContains(r, "Flex Roster")
        self.assertContains(r, reverse("alumno_detail", args=[reg_al.pk]))
        self.assertContains(r, reverse("asistencia_programar"))

    def test_roster_sin_fecha_no_lista_flexi(self):
        otro = (self.hoy.weekday() + 2) % 7
        h = self._horario(dia=otro, flexi=True)
        flex_al = alta_alumno(nombre_completo="Flex Oculto", tipo=TipoAlumno.ADULTO)
        pkg = comprar_paquete_flexi(
            alumno=flex_al, sesiones=10, metodo_codigo="efectivo"
        )
        delta = (otro - self.hoy.weekday()) % 7
        if delta == 0:
            delta = 7
        reservar_flexi(
            paquete=pkg, horario=h, fecha_clase=self.hoy + timedelta(days=delta)
        )
        r = self.c.get(reverse("horario_roster", args=[h.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, "Elige una fecha")
        self.assertNotContains(r, "Flex Oculto")
