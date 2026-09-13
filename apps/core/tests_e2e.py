"""Etapa 11: pruebas integrales MVP de extremo a extremo (flujos 1–8)."""

from datetime import date, datetime, time
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.test import TestCase
from django.utils import timezone

from apps.accounts.roles import ROLE_DIRECCION, ROLE_RECEPCION, ensure_roles
from apps.attendance.models import EstadoAsistencia, EstadoCompensacion, TipoCompensacion
from apps.attendance.services import (
    cancelar_por_spirit,
    marcar_asistio,
    programar_asistencia_flexi,
    programar_asistencia_regular,
    registrar_reposicion_sin_costo,
)
from apps.billing.models import ConceptoLinea, EstadoLineaCobro, LineaCobro
from apps.billing.services import (
    ejecutar_cobranza_diaria,
    registrar_pago_inscripcion,
    registrar_pago_periodo,
)
from apps.catalog.models import Profesor, Salon
from apps.enrollment.models import Inscripcion
from apps.enrollment.services import alta_alumno, reactivar_alumno
from apps.exceptions_ops.models import EstadoExcepcion, TipoExcepcion
from apps.exceptions_ops.services import autorizar, crear_solicitud
from apps.flexi.models import EstadoPaqueteFlexi, EstadoReservaFlexi
from apps.flexi.services import (
    cancelar_reserva_flexi,
    comprar_paquete_flexi,
    reservar_flexi,
)
from apps.params.services import PricingService, seed_parametros_iniciales
from apps.people.models import EstadoAlumno, TipoAlumno
from apps.people.services import marcar_baja
from apps.regular.models import EstadoPeriodoCobro, EstadoRegular
from apps.regular.services import alta_regular, calcular_monto_regular
from apps.scheduling.models import DiaSemana, Horario, Modalidad, TipoAlumno as TipoHorario
from apps.scheduling.services import CalendarService, CapacityService, SinCupoError

User = get_user_model()


class E2EBase(TestCase):
    def setUp(self):
        ensure_roles()
        self.params = seed_parametros_iniciales()
        self.salon = Salon.objects.create(nombre="S-E2E")
        self.profesor = Profesor.objects.create(nombre="P-E2E")
        self.recepcion = User.objects.create_user("recep_e2e", password="x")
        self.direccion = User.objects.create_user("dir_e2e", password="x")
        self.recepcion.groups.add(Group.objects.get(name=ROLE_RECEPCION))
        self.direccion.groups.add(Group.objects.get(name=ROLE_DIRECCION))

    def _horario(
        self,
        dia,
        *,
        duracion=60,
        capacidad=4,
        hora=10,
        modalidades=None,
        tipo=TipoHorario.ADULTO,
    ):
        return Horario.objects.create(
            dia=dia,
            hora_inicio=time(hora, 0),
            hora_fin=time(hora + duracion // 60, duracion % 60),
            duracion_minutos=duracion,
            capacidad=capacidad,
            tipo_alumno=tipo,
            modalidades=modalidades
            or [Modalidad.REGULAR, Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )

    def _aware(self, d: date, t: time = time(9, 0)):
        naive = datetime.combine(d, t)
        return timezone.make_aware(naive, timezone.get_current_timezone())


class Flujo1RegularPagoAsistencia(E2EBase):
    def test_alta_inscripcion_regular_pago_asistencia(self):
        alumno = alta_alumno(nombre_completo="E2E Reg", tipo=TipoAlumno.ADULTO)
        self.assertEqual(alumno.estado, EstadoAlumno.ACTIVO)
        self.assertEqual(Inscripcion.objects.filter(alumno=alumno).count(), 1)
        self.assertEqual(alumno.inscripcion.monto, self.params.cuota_inscripcion)

        linea = LineaCobro.objects.get(
            alumno=alumno, concepto=ConceptoLinea.INSCRIPCION
        )
        self.assertEqual(linea.estado, EstadoLineaCobro.PENDIENTE)
        self.assertEqual(linea.monto, self.params.cuota_inscripcion)
        self.assertEqual(
            linea.reglas_aplicadas.get("inscripcion_id"), alumno.inscripcion.pk
        )

        registrar_pago_inscripcion(
            alumno=alumno,
            metodo_codigo="efectivo",
            fecha_pago=date(2026, 8, 1),
        )
        linea.refresh_from_db()
        self.assertEqual(linea.estado, EstadoLineaCobro.PAGADA)

        h = self._horario(DiaSemana.MARTES, duracion=180, capacidad=4)
        # Ago 2026: martes 4,11,18,25 = 4 occ × 3h = 12h → $1440
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        self.assertEqual(periodo.monto, Decimal("1440.00"))
        self.assertEqual(periodo.estado, EstadoPeriodoCobro.PENDIENTE)

        pago = registrar_pago_periodo(
            periodo=periodo,
            metodo_codigo="efectivo",
            fecha_pago=date(2026, 8, 5),
        )
        periodo.refresh_from_db()
        self.assertEqual(periodo.estado, EstadoPeriodoCobro.PAGADO_A_TIEMPO)
        self.assertEqual(pago.monto_total, Decimal("1440.00"))

        asig = reg.asignaciones.get(activa=True)
        asist = programar_asistencia_regular(
            asignacion=asig, fecha=date(2026, 8, 4)
        )
        marcar_asistio(asist, usuario=self.recepcion)
        asist.refresh_from_db()
        self.assertEqual(asist.estado, EstadoAsistencia.ASISTIO)


class Flujo2FlexiReservaAsistenciaCancel(E2EBase):
    def test_alta_flexi_pago_reserva_asistencia_y_cancelacion(self):
        alumno = alta_alumno(nombre_completo="E2E Flex", tipo=TipoAlumno.ADULTO)
        pkg = comprar_paquete_flexi(
            alumno=alumno,
            sesiones=10,
            metodo_codigo="transferencia",
            fecha_compra=date(2026, 8, 1),
        )
        self.assertEqual(pkg.estado, EstadoPaqueteFlexi.ACTIVO)
        self.assertEqual(pkg.monto, PricingService.monto_flexi(10))
        self.assertEqual(pkg.pago.monto_total, pkg.monto)
        self.assertEqual(pkg.sesiones_disponibles, 10)

        h = self._horario(DiaSemana.MARTES, duracion=180, capacidad=4)
        reserva = reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 2), time(9, 0)),
        )
        pkg.refresh_from_db()
        self.assertEqual(reserva.estado, EstadoReservaFlexi.RESERVADA)
        self.assertEqual(pkg.sesiones_disponibles, 7)

        asist = programar_asistencia_flexi(reserva=reserva)
        marcar_asistio(asist, usuario=self.recepcion)
        reserva.refresh_from_db()
        self.assertEqual(reserva.estado, EstadoReservaFlexi.CONSUMIDA)
        self.assertEqual(pkg.sesiones_disponibles, 7)  # sin doble consumo

        # Segunda reserva + cancel ≥24h conserva sesión
        pkg.refresh_from_db()
        r2 = reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 11),
            ahora=self._aware(date(2026, 8, 5), time(9, 0)),
        )
        pkg.refresh_from_db()
        disp_antes = pkg.sesiones_disponibles
        cancelar_reserva_flexi(
            r2,
            ahora=self._aware(date(2026, 8, 9), time(9, 0)),
        )
        pkg.refresh_from_db()
        r2.refresh_from_db()
        self.assertEqual(r2.estado, EstadoReservaFlexi.CANCELADA)
        self.assertEqual(pkg.sesiones_disponibles, disp_antes + 3)


class Flujo3PagoTardioRecargoLiberacion(E2EBase):
    def test_pago_tardio_recargo_y_dia_11_libera(self):
        alumno = alta_alumno(nombre_completo="E2E Tarde", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MIERCOLES, duracion=180, capacidad=2)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        cupo_antes = CapacityService.cupo_disponible(h)
        self.assertEqual(cupo_antes, 1)

        # Día 8: recargo vía cobranza
        run = ejecutar_cobranza_diaria(fecha=date(2026, 8, 8))
        periodo.refresh_from_db()
        self.assertEqual(periodo.estado, EstadoPeriodoCobro.VENCIDO)
        recargo = LineaCobro.objects.get(
            periodo=periodo, concepto=ConceptoLinea.RECARGO
        )
        self.assertEqual(recargo.monto, self.params.monto_recargo)
        self.assertTrue(any(x["periodo_id"] == periodo.pk for x in run.detalle["recargos_aplicados"]))

        # Día 9: pago con recargo
        pago = registrar_pago_periodo(
            periodo=periodo,
            metodo_codigo="efectivo",
            fecha_pago=date(2026, 8, 9),
        )
        periodo.refresh_from_db()
        self.assertEqual(periodo.estado, EstadoPeriodoCobro.PAGADO_CON_RECARGO)
        self.assertEqual(
            pago.monto_total, periodo.monto + self.params.monto_recargo
        )

        # Otro alumno: impago hasta día 11
        alumno2 = alta_alumno(nombre_completo="E2E Libera", tipo=TipoAlumno.ADULTO)
        h2 = self._horario(DiaSemana.JUEVES, duracion=60, capacidad=1, hora=11)
        reg2 = alta_regular(
            alumno=alumno2, horarios=[h2], fecha_inicio=date(2026, 8, 1)
        )
        periodo2 = reg2.periodos_cobro.get(anio=2026, mes=8)
        self.assertEqual(CapacityService.cupo_disponible(h2), 0)

        ejecutar_cobranza_diaria(fecha=date(2026, 8, 11))
        periodo2.refresh_from_db()
        reg2.refresh_from_db()
        alumno2.refresh_from_db()
        self.assertEqual(periodo2.estado, EstadoPeriodoCobro.LIBERADO)
        self.assertEqual(reg2.estado, EstadoRegular.LIBERADO)
        self.assertFalse(reg2.asignaciones.filter(activa=True).exists())
        self.assertEqual(alumno2.estado, EstadoAlumno.BAJA_ADMINISTRATIVA)
        self.assertEqual(CapacityService.cupo_disponible(h2), 1)


class Flujo4BajaReactivacion(E2EBase):
    def test_baja_y_reactivacion_sin_nueva_inscripcion(self):
        alumno = alta_alumno(nombre_completo="E2E Baja", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.LUNES, capacidad=1, hora=8)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        self.assertEqual(CapacityService.cupo_disponible(h), 0)
        insc_id = alumno.inscripcion.pk
        monto = alumno.inscripcion.monto

        marcar_baja(alumno, voluntaria=True)
        alumno.refresh_from_db()
        reg.refresh_from_db()
        self.assertEqual(alumno.estado, EstadoAlumno.BAJA_VOLUNTARIA)
        self.assertEqual(reg.estado, EstadoRegular.BAJA_VOLUNTARIA)
        self.assertFalse(reg.asignaciones.filter(activa=True).exists())
        self.assertEqual(CapacityService.cupo_disponible(h), 1)

        reactivar_alumno(alumno)
        alumno.refresh_from_db()
        self.assertEqual(alumno.estado, EstadoAlumno.ACTIVO)
        self.assertEqual(Inscripcion.objects.filter(alumno=alumno).count(), 1)
        self.assertEqual(alumno.inscripcion.pk, insc_id)
        self.assertEqual(alumno.inscripcion.monto, monto)
        # Regular no se reactiva solo; cupo sigue libre para nuevo alta
        reg.refresh_from_db()
        self.assertEqual(reg.estado, EstadoRegular.BAJA_VOLUNTARIA)
        self.assertEqual(CapacityService.cupo_disponible(h), 1)


class Flujo5CancelacionSpiritCompensacion(E2EBase):
    def test_cancelacion_spirit_compensacion_reposicion(self):
        alumno = alta_alumno(nombre_completo="E2E Spirit", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        asig = reg.asignaciones.get(activa=True)
        asist = programar_asistencia_regular(
            asignacion=asig, fecha=date(2026, 8, 4)
        )
        _, comp = cancelar_por_spirit(asist, usuario=self.recepcion)
        asist.refresh_from_db()
        self.assertEqual(asist.estado, EstadoAsistencia.PENDIENTE_COMPENSACION)
        self.assertEqual(comp.estado, EstadoCompensacion.PENDIENTE)

        registrar_reposicion_sin_costo(
            comp, usuario=self.recepcion, notas="reposición E2E"
        )
        comp.refresh_from_db()
        asist.refresh_from_db()
        self.assertEqual(comp.estado, EstadoCompensacion.RESUELTA)
        self.assertEqual(comp.tipo, TipoCompensacion.REPOSICION_SIN_COSTO)
        self.assertEqual(asist.estado, EstadoAsistencia.CANCELADA_POR_SPIRIT)


class Flujo6ExcepcionDireccion(E2EBase):
    def test_excepcion_autorizada_por_direccion(self):
        alumno = alta_alumno(nombre_completo="E2E Exc", tipo=TipoAlumno.ADULTO)
        exc = crear_solicitud(
            alumno=alumno,
            tipo=TipoExcepcion.OTRO,
            motivo="Viaje médico",
            fecha_inicio=date(2026, 8, 10),
            usuario=self.recepcion,
        )
        self.assertEqual(exc.estado, EstadoExcepcion.SOLICITADA)
        autorizar(exc, usuario=self.direccion, notas="OK Dir")
        exc.refresh_from_db()
        self.assertEqual(exc.estado, EstadoExcepcion.AUTORIZADA)
        self.assertEqual(exc.autorizador_id, self.direccion.pk)


class Flujo7CuposConflictoRegularFlexi(E2EBase):
    def test_cupo_lleno_bloquea_regular_y_flexi(self):
        h = self._horario(DiaSemana.VIERNES, duracion=180, capacidad=1, hora=16)
        a1 = alta_alumno(nombre_completo="E2E Cupo1", tipo=TipoAlumno.ADULTO)
        a2 = alta_alumno(nombre_completo="E2E Cupo2", tipo=TipoAlumno.ADULTO)

        alta_regular(alumno=a1, horarios=[h], fecha_inicio=date(2026, 8, 1))
        self.assertEqual(CapacityService.cupo_disponible(h), 0)

        with self.assertRaises(SinCupoError):
            alta_regular(alumno=a2, horarios=[h], fecha_inicio=date(2026, 8, 1))

        pkg = comprar_paquete_flexi(
            alumno=a2,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 2),
        )
        with self.assertRaises(SinCupoError):
            reservar_flexi(
                paquete=pkg,
                horario=h,
                fecha_clase=date(2026, 8, 7),  # viernes
                ahora=self._aware(date(2026, 8, 3), time(9, 0)),
            )

    def test_flexi_reserva_ocupa_cupo_de_esa_fecha_no_bloquea_regular(self):
        """Flexi resta cupo solo en fecha_clase; Regular mira cupo recurrente."""
        h = self._horario(DiaSemana.VIERNES, duracion=180, capacidad=1, hora=14)
        a_flex = alta_alumno(nombre_completo="E2E FlexCupo", tipo=TipoAlumno.ADULTO)
        a_reg = alta_alumno(nombre_completo="E2E RegCupo", tipo=TipoAlumno.ADULTO)
        pkg = comprar_paquete_flexi(
            alumno=a_flex,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        fecha = date(2026, 8, 7)
        reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=fecha,
            ahora=self._aware(date(2026, 8, 2), time(9, 0)),
        )
        self.assertEqual(CapacityService.cupo_disponible(h), 1)
        self.assertEqual(
            CapacityService.cupo_disponible(h, fecha_clase=fecha),
            0,
        )
        alta_regular(
            alumno=a_reg, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        self.assertEqual(CapacityService.cupo_disponible(h), 0)


class Flujo8QuintaSemanaCobro(E2EBase):
    def test_quinta_semana_cobra_ocurrencias_reales(self):
        # Ago 2026 lunes: 3,10,17,24,31 = 5
        h = self._horario(DiaSemana.LUNES, duracion=60, capacidad=4, hora=9)
        fechas = CalendarService.ocurrencias_en_mes(h, 2026, 8)
        self.assertEqual(len(fechas), 5)
        self.assertEqual(fechas[-1], date(2026, 8, 31))

        alumno = alta_alumno(nombre_completo="E2E 5ta", tipo=TipoAlumno.ADULTO)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        self.assertEqual(periodo.horas_total, Decimal("5.00"))
        # 5h en bloque 1 a $120
        self.assertEqual(periodo.monto, Decimal("600.00"))

        calc = calcular_monto_regular(reg, 2026, 8)
        self.assertEqual(calc["monto"], periodo.monto)
        self.assertEqual(
            calc["detalle_calculo"]["horarios"][0]["ocurrencias"], 5
        )
