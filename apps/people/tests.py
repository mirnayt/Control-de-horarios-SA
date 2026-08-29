from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.test import TestCase

from apps.enrollment.models import Inscripcion
from apps.enrollment.services import (
    alta_alumno,
    reactivar_alumno,
    requiere_pago_inscripcion,
)
from apps.params.services import seed_parametros_iniciales
from apps.people.models import Alumno, EstadoAlumno, TipoAlumno, Tutor
from apps.people.services import cambiar_estado, marcar_baja


class PeopleEnrollmentTests(TestCase):
    def setUp(self):
        self.params = seed_parametros_iniciales()

    def test_alta_adulto_y_nino(self):
        adulto = alta_alumno(nombre_completo="Ana Pérez", tipo=TipoAlumno.ADULTO)
        nino = alta_alumno(
            nombre_completo="Luis Pérez",
            tipo=TipoAlumno.NINO,
            tutor=Tutor.objects.create(nombre_completo="Ana Pérez", parentesco="madre"),
        )
        self.assertEqual(adulto.tipo, TipoAlumno.ADULTO)
        self.assertEqual(adulto.estado, EstadoAlumno.ACTIVO)
        self.assertEqual(nino.tipo, TipoAlumno.NINO)
        self.assertIsNotNone(nino.tutor)
        self.assertEqual(adulto.inscripcion.monto, Decimal("500.00"))
        self.assertEqual(nino.inscripcion.monto, self.params.cuota_inscripcion)

    def test_nombre_completo_obligatorio(self):
        with self.assertRaises(ValidationError):
            alta_alumno(nombre_completo="   ", tipo=TipoAlumno.ADULTO)
        alumno = Alumno(nombre_completo="", tipo=TipoAlumno.ADULTO)
        with self.assertRaises(ValidationError):
            alumno.full_clean()

    def test_inscripcion_unica_por_alumno(self):
        alumno = alta_alumno(nombre_completo="Único", tipo=TipoAlumno.ADULTO)
        self.assertEqual(Inscripcion.objects.filter(alumno=alumno).count(), 1)
        with self.assertRaises(IntegrityError):
            Inscripcion.objects.create(
                alumno=alumno,
                fecha_original=alumno.inscripcion.fecha_original,
                monto=Decimal("500.00"),
                pagada=True,
            )

    def test_regreso_sin_nuevo_cobro_inscripcion(self):
        alumno = alta_alumno(nombre_completo="Regresa", tipo=TipoAlumno.ADULTO)
        fecha_original = alumno.inscripcion.fecha_original
        monto_original = alumno.inscripcion.monto
        inscripcion_id = alumno.inscripcion.pk

        marcar_baja(alumno, voluntaria=True)
        self.assertEqual(alumno.estado, EstadoAlumno.BAJA_VOLUNTARIA)
        self.assertFalse(requiere_pago_inscripcion(alumno))

        reactivado = reactivar_alumno(alumno)
        self.assertEqual(reactivado.estado, EstadoAlumno.ACTIVO)
        self.assertEqual(Inscripcion.objects.filter(alumno=alumno).count(), 1)
        self.assertEqual(alumno.inscripcion.pk, inscripcion_id)
        self.assertEqual(alumno.inscripcion.fecha_original, fecha_original)
        self.assertEqual(alumno.inscripcion.monto, monto_original)
        self.assertFalse(requiere_pago_inscripcion(alumno))

    def test_baja_libera_cupo_regular(self):
        from datetime import date, time

        from apps.catalog.models import Profesor, Salon
        from apps.regular.models import EstadoRegular
        from apps.regular.services import alta_regular
        from apps.scheduling.models import (
            DiaSemana,
            Horario,
            Modalidad,
            TipoAlumno as TipoHorario,
        )
        from apps.scheduling.services import CapacityService

        salon = Salon.objects.create(nombre="S-baja")
        profe = Profesor.objects.create(nombre="P-baja")
        h = Horario.objects.create(
            dia=DiaSemana.LUNES,
            hora_inicio=time(9, 0),
            hora_fin=time(10, 0),
            duracion_minutos=60,
            capacidad=1,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.REGULAR],
            activo=True,
            salon=salon,
            profesor=profe,
        )
        alumno = alta_alumno(nombre_completo="Libera cupo", tipo=TipoAlumno.ADULTO)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        self.assertEqual(CapacityService.cupo_disponible(h), 0)

        marcar_baja(alumno, voluntaria=True)
        reg.refresh_from_db()
        self.assertEqual(reg.estado, EstadoRegular.BAJA_VOLUNTARIA)
        self.assertEqual(CapacityService.cupo_disponible(h), 1)

    def test_estados_basicos_alumno(self):
        alumno = alta_alumno(nombre_completo="Estados", tipo=TipoAlumno.ADULTO)
        for estado in EstadoAlumno.values:
            cambiar_estado(alumno, estado)
            alumno.refresh_from_db()
            self.assertEqual(alumno.estado, estado)

        marcar_baja(alumno, voluntaria=False)
        self.assertEqual(alumno.estado, EstadoAlumno.BAJA_ADMINISTRATIVA)
        cambiar_estado(alumno, EstadoAlumno.INACTIVO)
        reactivar_alumno(alumno)
        self.assertEqual(alumno.estado, EstadoAlumno.ACTIVO)
