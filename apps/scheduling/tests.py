from datetime import date, time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from apps.catalog.models import Profesor, Salon
from apps.scheduling.models import DiaSemana, Horario, Modalidad, TipoAlumno
from apps.scheduling.services import CalendarService, CapacityService, SinCupoError


class HorarioModelTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(nombre="Salón 1")
        self.profesor = Profesor.objects.create(nombre="Profe Test")

    def _horario(self, **overrides):
        data = {
            "dia": DiaSemana.LUNES,
            "hora_inicio": time(9, 0),
            "hora_fin": time(10, 0),
            "duracion_minutos": 60,
            "capacidad": 8,
            "tipo_alumno": TipoAlumno.ADULTO,
            "modalidades": [Modalidad.REGULAR, Modalidad.FLEXI],
            "activo": True,
            "salon": self.salon,
            "profesor": self.profesor,
        }
        data.update(overrides)
        return Horario(**data)

    def test_capacidad_minima_invalida(self):
        h = self._horario(capacidad=0)
        with self.assertRaises(ValidationError):
            h.full_clean()

    def test_capacidad_valida_persiste(self):
        h = self._horario(capacidad=5)
        h.save()
        self.assertEqual(Horario.objects.get(pk=h.pk).capacidad, 5)

    def test_duracion_debe_coincidir_con_intervalo(self):
        h = self._horario(duracion_minutos=45)
        with self.assertRaises(ValidationError):
            h.full_clean()


class CapacityServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(nombre="Salón Cupo")
        self.profesor = Profesor.objects.create(nombre="Profe Cupo")
        self.horario = Horario.objects.create(
            dia=DiaSemana.MARTES,
            hora_inicio=time(18, 0),
            hora_fin=time(19, 0),
            duracion_minutos=60,
            capacidad=4,
            tipo_alumno=TipoAlumno.ADULTO,
            modalidades=[Modalidad.REGULAR, Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )

    def test_cupo_sin_ocupacion_igual_capacidad(self):
        self.assertEqual(CapacityService.cupo_disponible(self.horario), 4)

    def test_cupo_correcto_resta_regular_y_flexi(self):
        cupo = CapacityService.cupo_disponible(
            self.horario,
            regulares_activos=2,
            reservas_flexi_vigentes=1,
        )
        self.assertEqual(cupo, 1)

    def test_inactivo_cupo_cero(self):
        self.horario.activo = False
        self.horario.save()
        self.assertEqual(CapacityService.cupo_disponible(self.horario), 0)

    def test_activo_permite_cupo(self):
        self.assertTrue(self.horario.activo)
        self.assertGreater(CapacityService.cupo_disponible(self.horario), 0)

    def test_rechazo_con_cupo_cero(self):
        with self.assertRaises(SinCupoError):
            CapacityService.assert_tiene_cupo(
                self.horario,
                regulares_activos=3,
                reservas_flexi_vigentes=1,
            )

    def test_assert_tiene_cupo_ok(self):
        restante = CapacityService.assert_tiene_cupo(
            self.horario,
            regulares_activos=1,
            reservas_flexi_vigentes=0,
        )
        self.assertEqual(restante, 3)


class CalendarServiceTests(TestCase):
    def setUp(self):
        self.salon = Salon.objects.create(nombre="Salón Cal")
        self.profesor = Profesor.objects.create(nombre="Profe Cal")
        # Agosto 2026 tiene 5 sábados: 1, 8, 15, 22, 29
        self.horario_sabado = Horario.objects.create(
            dia=DiaSemana.SABADO,
            hora_inicio=time(10, 0),
            hora_fin=time(12, 0),
            duracion_minutos=120,
            capacidad=10,
            tipo_alumno=TipoAlumno.ADULTO,
            modalidades=[Modalidad.REGULAR],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )

    def test_cinco_ocurrencias_reales_en_mes(self):
        fechas = CalendarService.ocurrencias_en_mes(
            self.horario_sabado, 2026, 8
        )
        self.assertEqual(len(fechas), 5)
        self.assertEqual(
            fechas,
            [
                date(2026, 8, 1),
                date(2026, 8, 8),
                date(2026, 8, 15),
                date(2026, 8, 22),
                date(2026, 8, 29),
            ],
        )
        self.assertEqual(
            CalendarService.contar_ocurrencias(self.horario_sabado, 2026, 8),
            5,
        )

    def test_horas_usa_duracion_configurable(self):
        # 5×120 min = 10 h
        self.assertEqual(
            CalendarService.horas_en_mes(self.horario_sabado, 2026, 8),
            Decimal("10"),
        )

    def test_filtro_desde_alta_parcial(self):
        # Alta el 10 → restantes: 15, 22, 29
        fechas = CalendarService.ocurrencias_en_mes(
            self.horario_sabado, 2026, 8, desde=date(2026, 8, 10)
        )
        self.assertEqual(len(fechas), 3)
        self.assertEqual(fechas[0], date(2026, 8, 15))
