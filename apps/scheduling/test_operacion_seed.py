from datetime import time
from decimal import Decimal

from django.test import TestCase

from apps.catalog.models import Profesor, Salon
from apps.params.models import ParametroVersion
from apps.scheduling.models import DiaSemana, Horario, Modalidad, TipoAlumno
from apps.scheduling.operacion_config import (
    CAPACIDAD_PLACEHOLDER,
    HORARIOS_OPERACION,
    PROFESOR_DEMO,
    SALON_DEFAULT,
    SALONES,
)
from apps.scheduling.operacion_seed import seed_operacion_spirit


class OperacionSeedTests(TestCase):
    def test_seed_crea_catalogo_y_horarios(self):
        result = seed_operacion_spirit()
        self.assertEqual(result.salones, len(SALONES))
        self.assertEqual(result.horarios_creados, len(HORARIOS_OPERACION))
        self.assertEqual(Horario.objects.count(), len(HORARIOS_OPERACION))
        self.assertTrue(Salon.objects.filter(nombre=SALON_DEFAULT).exists())
        self.assertTrue(Profesor.objects.filter(nombre=PROFESOR_DEMO).exists())
        self.assertIsNotNone(ParametroVersion.vigente())

    def test_seed_idempotente_sin_force(self):
        seed_operacion_spirit()
        result = seed_operacion_spirit()
        self.assertEqual(result.horarios_creados, 0)
        self.assertEqual(result.horarios_actualizados, 0)
        self.assertEqual(Horario.objects.count(), len(HORARIOS_OPERACION))

    def test_placeholders_provisionales(self):
        seed_operacion_spirit()
        for h in Horario.objects.all():
            self.assertEqual(h.capacidad, CAPACIDAD_PLACEHOLDER)
            self.assertEqual(h.salon.nombre, SALON_DEFAULT)
            self.assertEqual(h.profesor.nombre, PROFESOR_DEMO)

    def test_modalidades_confirmadas(self):
        seed_operacion_spirit()
        adulto_sem = Horario.objects.get(
            dia=DiaSemana.LUNES,
            hora_inicio=time(16, 0),
            tipo_alumno=TipoAlumno.ADULTO,
        )
        self.assertEqual(
            set(adulto_sem.modalidades),
            {Modalidad.REGULAR, Modalidad.FLEXI, Modalidad.SUELTA},
        )
        adulto_sab = Horario.objects.get(
            dia=DiaSemana.SABADO,
            hora_inicio=time(9, 0),
            tipo_alumno=TipoAlumno.ADULTO,
        )
        self.assertEqual(adulto_sab.modalidades, [Modalidad.REGULAR])
        nino = Horario.objects.get(
            dia=DiaSemana.MARTES,
            hora_inicio=time(15, 50),
            tipo_alumno=TipoAlumno.NINO,
        )
        self.assertEqual(nino.modalidades, [Modalidad.REGULAR])

    def test_duraciones_calculadas(self):
        seed_operacion_spirit()
        h170 = Horario.objects.get(
            dia=DiaSemana.LUNES,
            hora_inicio=time(16, 0),
            tipo_alumno=TipoAlumno.ADULTO,
        )
        self.assertEqual(h170.duracion_minutos, 170)
        h230 = Horario.objects.get(
            dia=DiaSemana.SABADO,
            hora_inicio=time(9, 0),
            tipo_alumno=TipoAlumno.ADULTO,
        )
        self.assertEqual(h230.duracion_minutos, 230)
        h110 = Horario.objects.get(
            dia=DiaSemana.SABADO,
            hora_inicio=time(11, 0),
            tipo_alumno=TipoAlumno.NINO,
        )
        self.assertEqual(h110.duracion_minutos, 110)

    def test_parametros_tarifas_spirit(self):
        seed_operacion_spirit()
        v = ParametroVersion.vigente()
        self.assertEqual(v.tarifa_hora_adulto, Decimal("120.00"))
        self.assertEqual(v.tarifa_hora_nino, Decimal("110.00"))
        self.assertEqual(v.flexi_tarifa_hora, Decimal("120.00"))
        self.assertEqual(v.precio_clase_suelta, Decimal("500.00"))
        self.assertEqual(v.cuota_inscripcion, Decimal("500.00"))
        self.assertEqual(v.monto_recargo, Decimal("100.00"))
        self.assertTrue(v.sabado_adulto_sin_descuento_progresivo)
        self.assertEqual(v.bloques_adulto.count(), 3)
        self.assertEqual(v.vigencias_flexi.count(), 6)

    def test_force_actualiza_horarios(self):
        seed_operacion_spirit()
        h = Horario.objects.first()
        h.capacidad = 1
        h.save(update_fields=["capacidad"])
        result = seed_operacion_spirit(force=True)
        self.assertGreater(result.horarios_actualizados, 0)
        h.refresh_from_db()
        self.assertEqual(h.capacidad, CAPACIDAD_PLACEHOLDER)
