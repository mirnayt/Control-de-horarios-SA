from datetime import date, datetime, time
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Profesor, Salon
from apps.enrollment.services import alta_alumno
from apps.flexi.models import (
    EstadoPaqueteFlexi,
    EstadoReservaFlexi,
)
from apps.flexi.services import (
    DURACION_SESION_FLEXI_MINUTOS,
    assert_horario_reservable_flexi,
    comprar_paquete_flexi,
    cancelar_reserva_flexi,
    conserva_sesion_al_cancelar,
    ejecutar_vencimiento_flexi,
    fecha_fin_vigencia,
    marcar_no_show,
    meses_vigencia_para,
    paquete_reservable,
    puede_comprar_flexi,
    puede_reservar_flexi,
    reservar_flexi,
)
from apps.params.services import seed_parametros_iniciales
from apps.people.models import TipoAlumno
from apps.regular.services import alta_regular
from apps.scheduling.models import DiaSemana, Horario, Modalidad, TipoAlumno as TipoHorario
from apps.scheduling.services import CapacityService, SinCupoError

TZ = ZoneInfo("America/Mexico_City")


class FlexiBaseTestCase(TestCase):
    def setUp(self):
        self.params = seed_parametros_iniciales()
        self.salon = Salon.objects.create(nombre="Salón F")
        self.profesor = Profesor.objects.create(nombre="Profe F")
        self.alumno = alta_alumno(nombre_completo="Flexi A", tipo=TipoAlumno.ADULTO)

    def _horario(
        self,
        dia=DiaSemana.MARTES,
        *,
        duracion=DURACION_SESION_FLEXI_MINUTOS,
        capacidad=2,
        hora=10,
    ):
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


class CompraYVigenciaTests(FlexiBaseTestCase):
    def test_compra_5_10_30(self):
        for n, meses, monto in (
            (5, 1, Decimal("600.00")),
            (10, 2, Decimal("1200.00")),
            (30, 6, Decimal("3600.00")),
        ):
            alumno = alta_alumno(nombre_completo=f"C{n}", tipo=TipoAlumno.ADULTO)
            pkg = comprar_paquete_flexi(
                alumno=alumno,
                sesiones=n,
                metodo_codigo="efectivo",
                fecha_compra=date(2026, 8, 1),
            )
            self.assertEqual(pkg.sesiones_compradas, n)
            self.assertEqual(pkg.sesiones_disponibles, n)
            self.assertEqual(pkg.meses_vigencia, meses)
            self.assertEqual(pkg.monto, monto)
            self.assertEqual(pkg.estado, EstadoPaqueteFlexi.ACTIVO)
            self.assertIsNotNone(pkg.pago)
            self.assertEqual(pkg.pago.monto_total, monto)
            self.assertEqual(pkg.fecha_fin, fecha_fin_vigencia(date(2026, 8, 1), meses))

    def test_vigencias_tabla(self):
        casos = [
            (5, 1),
            (6, 2),
            (10, 2),
            (11, 3),
            (15, 3),
            (16, 4),
            (20, 4),
            (21, 5),
            (25, 5),
            (26, 6),
            (30, 6),
        ]
        for sesiones, meses in casos:
            self.assertEqual(
                meses_vigencia_para(sesiones, version=self.params),
                meses,
            )

    def test_compra_sin_reserva(self):
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="transferencia",
            fecha_compra=date(2026, 8, 3),
        )
        self.assertEqual(pkg.reservas.count(), 0)
        self.assertEqual(pkg.sesiones_disponibles, 5)


class ReservaCupoTests(FlexiBaseTestCase):
    def test_reserva_con_cupo(self):
        h = self._horario(capacidad=2)
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        ahora = self._aware(date(2026, 8, 1), time(9, 0))
        # 2026-08-04 = martes
        r = reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=ahora,
        )
        pkg.refresh_from_db()
        self.assertEqual(r.estado, EstadoReservaFlexi.RESERVADA)
        self.assertEqual(pkg.sesiones_disponibles, 2)  # 5 − 3 h
        self.assertEqual(CapacityService.cupo_disponible(h), 2)
        self.assertEqual(
            CapacityService.cupo_disponible(h, fecha_clase=date(2026, 8, 4)),
            1,
        )

    def test_reserva_misma_fecha_llena_otra_fecha_libre(self):
        h = self._horario(capacidad=1)
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        ahora = self._aware(date(2026, 8, 1), time(9, 0))
        reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=ahora,
        )
        self.assertEqual(
            CapacityService.cupo_disponible(h, fecha_clase=date(2026, 8, 4)),
            0,
        )
        self.assertEqual(
            CapacityService.cupo_disponible(h, fecha_clase=date(2026, 8, 11)),
            1,
        )
        otro = alta_alumno(nombre_completo="Otro Fecha", tipo=TipoAlumno.ADULTO)
        pkg2 = comprar_paquete_flexi(
            alumno=otro,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        with self.assertRaises(SinCupoError):
            reservar_flexi(
                paquete=pkg2,
                horario=h,
                fecha_clase=date(2026, 8, 4),
                ahora=ahora,
            )
        r2 = reservar_flexi(
            paquete=pkg2,
            horario=h,
            fecha_clase=date(2026, 8, 11),
            ahora=ahora,
        )
        self.assertEqual(r2.estado, EstadoReservaFlexi.RESERVADA)

    def test_rechazo_sin_cupo(self):
        h = self._horario(capacidad=1)
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        ahora = self._aware(date(2026, 8, 1), time(9, 0))
        reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=ahora,
        )
        otro = alta_alumno(nombre_completo="Otro", tipo=TipoAlumno.ADULTO)
        pkg2 = comprar_paquete_flexi(
            alumno=otro,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        with self.assertRaises(SinCupoError):
            reservar_flexi(
                paquete=pkg2,
                horario=h,
                fecha_clase=date(2026, 8, 4),
                ahora=ahora,
            )


class CancelacionNoShowTests(FlexiBaseTestCase):
    def test_cancel_ge_24h_conserva(self):
        h = self._horario(capacidad=2, hora=10)
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        r = reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 1), time(9, 0)),
        )
        # Clase 10:00; cancelación 48h antes
        ahora = self._aware(date(2026, 8, 2), time(10, 0))
        cancelar_reserva_flexi(r, ahora=ahora)
        r.refresh_from_db()
        pkg.refresh_from_db()
        self.assertEqual(r.estado, EstadoReservaFlexi.CANCELADA)
        self.assertEqual(pkg.sesiones_disponibles, 5)
        self.assertEqual(CapacityService.cupo_disponible(h), 2)

    def test_cancel_lt_24h_consume(self):
        h = self._horario(capacidad=2, hora=10)
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        r = reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 1), time(9, 0)),
        )
        ahora = self._aware(date(2026, 8, 3), time(12, 0))  # <22h
        cancelar_reserva_flexi(r, ahora=ahora)
        r.refresh_from_db()
        pkg.refresh_from_db()
        self.assertEqual(r.estado, EstadoReservaFlexi.CANCELADA_TARDE)
        self.assertEqual(pkg.sesiones_disponibles, 2)
        self.assertEqual(CapacityService.cupo_disponible(h), 2)

    def test_no_show_consume(self):
        h = self._horario(capacidad=2)
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        r = reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 1), time(9, 0)),
        )
        marcar_no_show(r)
        r.refresh_from_db()
        pkg.refresh_from_db()
        self.assertEqual(r.estado, EstadoReservaFlexi.NO_SHOW)
        self.assertEqual(pkg.sesiones_disponibles, 2)
        self.assertEqual(CapacityService.cupo_disponible(h), 2)


class VencimientoTests(FlexiBaseTestCase):
    def test_vencimiento_con_saldo(self):
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        self.assertEqual(pkg.fecha_fin, date(2026, 8, 31))
        h = self._horario()
        reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 1), time(9, 0)),
        )
        pkg.refresh_from_db()
        self.assertEqual(pkg.sesiones_disponibles, 2)

        run = ejecutar_vencimiento_flexi(fecha=date(2026, 9, 1))
        pkg.refresh_from_db()
        self.assertEqual(pkg.estado, EstadoPaqueteFlexi.VENCIDO)
        self.assertEqual(pkg.sesiones_disponibles, 0)
        self.assertEqual(pkg.sesiones_vencidas, 2)
        self.assertEqual(pkg.sesiones_consumidas, 3)
        self.assertEqual(len(run.detalle["vencidos"]), 1)

    def test_idempotencia_vencimiento(self):
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        run1 = ejecutar_vencimiento_flexi(fecha=date(2026, 9, 1))
        pkg.refresh_from_db()
        self.assertEqual(pkg.sesiones_vencidas, 5)
        run2 = ejecutar_vencimiento_flexi(fecha=date(2026, 9, 1))
        self.assertEqual(run1.pk, run2.pk)
        # Con forzar: no duplica vencidas
        ejecutar_vencimiento_flexi(fecha=date(2026, 9, 1), forzar=True)
        pkg.refresh_from_db()
        self.assertEqual(pkg.sesiones_vencidas, 5)
        self.assertEqual(pkg.estado, EstadoPaqueteFlexi.VENCIDO)


class RegularMasFlexiTests(FlexiBaseTestCase):
    def test_regular_y_flexi_mismo_alumno(self):
        h_reg = self._horario(DiaSemana.LUNES, capacidad=4, hora=9)
        h_flex = self._horario(DiaSemana.MARTES, capacidad=4, hora=11)
        reg = alta_regular(
            alumno=self.alumno,
            horarios=[h_reg],
            fecha_inicio=date(2026, 8, 1),
        )
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 2),
        )
        r = reservar_flexi(
            paquete=pkg,
            horario=h_flex,
            fecha_clase=date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 2), time(9, 0)),
        )
        self.assertEqual(reg.estado, "activo")
        self.assertEqual(pkg.estado, EstadoPaqueteFlexi.ACTIVO)
        self.assertEqual(r.estado, EstadoReservaFlexi.RESERVADA)
        self.assertEqual(CapacityService.count_regulares_activos(h_reg), 1)
        self.assertEqual(
            CapacityService.count_reservas_flexi_vigentes(h_flex),
            0,
        )
        self.assertEqual(
            CapacityService.count_reservas_flexi_vigentes(
                h_flex, fecha_clase=date(2026, 8, 4)
            ),
            1,
        )


class RenovacionTests(FlexiBaseTestCase):
    def test_no_renueva_con_activo(self):
        comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        ok, _ = puede_comprar_flexi(self.alumno, fecha=date(2026, 8, 5))
        self.assertFalse(ok)

    def test_renueva_tras_vencido_en_1_7(self):
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        ejecutar_vencimiento_flexi(fecha=date(2026, 9, 1))
        pkg.refresh_from_db()
        self.assertEqual(pkg.estado, EstadoPaqueteFlexi.VENCIDO)

        ok, _ = puede_comprar_flexi(self.alumno, fecha=date(2026, 9, 3))
        self.assertTrue(ok)
        nuevo = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=10,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 9, 3),
        )
        self.assertTrue(nuevo.es_renovacion)
        self.assertEqual(nuevo.sesiones_compradas, 10)

    def test_rechaza_renovacion_fuera_1_7(self):
        comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        ejecutar_vencimiento_flexi(fecha=date(2026, 9, 1))
        ok, motivo = puede_comprar_flexi(self.alumno, fecha=date(2026, 9, 10))
        self.assertFalse(ok)
        self.assertIn("1–", motivo)


class ReglasFlexiCentralizadasTests(FlexiBaseTestCase):
    def test_rechaza_nino_en_compra(self):
        nino = alta_alumno(nombre_completo="Nino F", tipo=TipoAlumno.NINO)
        ok, motivo = puede_comprar_flexi(nino, fecha=date(2026, 8, 1))
        self.assertFalse(ok)
        self.assertIn("adultos", motivo)

    def test_rechaza_duracion_distinta_de_180(self):
        h = self._horario(duracion=120, hora=10)
        with self.assertRaises(ValidationError):
            assert_horario_reservable_flexi(h, alumno=self.alumno)

    def test_sabado_180_ok_sabado_corto_no(self):
        h_ok = self._horario(DiaSemana.SABADO, duracion=180, hora=9)
        assert_horario_reservable_flexi(h_ok, alumno=self.alumno)
        h_bad = self._horario(DiaSemana.SABADO, duracion=120, hora=14)
        with self.assertRaises(ValidationError):
            assert_horario_reservable_flexi(h_bad, alumno=self.alumno)

    def test_paquete_reservable_y_puede_reservar(self):
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        self.assertTrue(paquete_reservable(pkg, hoy=date(2026, 8, 2)))
        h = self._horario(capacidad=2)
        ok, _ = puede_reservar_flexi(
            pkg,
            h,
            date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 2), time(9, 0)),
        )
        self.assertTrue(ok)

    def test_conserva_sesion_24h(self):
        h = self._horario(capacidad=2, hora=10)
        pkg = comprar_paquete_flexi(
            alumno=self.alumno,
            sesiones=5,
            metodo_codigo="efectivo",
            fecha_compra=date(2026, 8, 1),
        )
        r = reservar_flexi(
            paquete=pkg,
            horario=h,
            fecha_clase=date(2026, 8, 4),
            ahora=self._aware(date(2026, 8, 1), time(9, 0)),
        )
        self.assertTrue(
            conserva_sesion_al_cancelar(
                r, ahora=self._aware(date(2026, 8, 2), time(10, 0))
            )
        )
        self.assertFalse(
            conserva_sesion_al_cancelar(
                r, ahora=self._aware(date(2026, 8, 3), time(12, 0))
            )
        )
