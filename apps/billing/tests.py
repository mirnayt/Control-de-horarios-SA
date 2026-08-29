from datetime import date, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.billing.models import (
    ConceptoLinea,
    EstadoLineaCobro,
    EstadoPago,
    EjecucionCobranza,
    LineaCobro,
    Pago,
)
from apps.billing.services import (
    aplicar_recargo_si_corresponde,
    asegurar_linea_mensualidad,
    ejecutar_cobranza_diaria,
    registrar_pago_periodo,
)
from apps.catalog.models import Profesor, Salon
from apps.enrollment.services import alta_alumno
from apps.params.models import BloqueTarifaAdulto, ParametroVersion
from apps.params.services import seed_parametros_iniciales
from apps.people.models import EstadoAlumno, TipoAlumno
from apps.regular.models import (
    AsignacionRegular,
    EstadoPeriodoCobro,
    EstadoRegular,
)
from apps.regular.services import alta_regular
from apps.scheduling.models import DiaSemana, Horario, Modalidad, TipoAlumno as TipoHorario
from apps.scheduling.services import CapacityService


class BillingBaseTestCase(TestCase):
    def setUp(self):
        self.params = seed_parametros_iniciales()
        self.salon = Salon.objects.create(nombre="Salon B")
        self.profesor = Profesor.objects.create(nombre="Profe B")

    def _horario(self, dia, *, duracion=180, capacidad=8, hora=9):
        return Horario.objects.create(
            dia=dia,
            hora_inicio=time(hora, 0),
            hora_fin=time(hora + duracion // 60, duracion % 60),
            duracion_minutos=duracion,
            capacidad=capacidad,
            tipo_alumno=TipoHorario.ADULTO,
            modalidades=[Modalidad.REGULAR, Modalidad.FLEXI],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )

    def _alta(self, *, capacidad=8, nombre="Alumno B"):
        alumno = alta_alumno(nombre_completo=nombre, tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES, capacidad=capacidad)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        return alumno, h, reg, periodo


class PagoVentanaTests(BillingBaseTestCase):
    def test_pago_dias_1_a_7_sin_recargo(self):
        _, _, reg, periodo = self._alta()
        monto = periodo.monto

        pago = registrar_pago_periodo(
            periodo=periodo,
            metodo_codigo="efectivo",
            fecha_pago=date(2026, 8, 5),
        )

        periodo.refresh_from_db()
        self.assertEqual(pago.estado, EstadoPago.CONFIRMADO)
        self.assertEqual(pago.monto_total, monto)
        self.assertEqual(periodo.estado, EstadoPeriodoCobro.PAGADO_A_TIEMPO)
        self.assertFalse(
            LineaCobro.objects.filter(
                periodo=periodo, concepto=ConceptoLinea.RECARGO
            ).exists()
        )
        self.assertEqual(
            LineaCobro.objects.filter(
                periodo=periodo, estado=EstadoLineaCobro.PAGADA
            ).count(),
            1,
        )

    def test_pago_dias_8_a_10_con_recargo(self):
        _, _, _, periodo = self._alta()
        monto = periodo.monto

        pago = registrar_pago_periodo(
            periodo=periodo,
            metodo_codigo="transferencia",
            fecha_pago=date(2026, 8, 9),
        )

        periodo.refresh_from_db()
        self.assertEqual(pago.monto_total, monto + Decimal("100.00"))
        self.assertEqual(periodo.estado, EstadoPeriodoCobro.PAGADO_CON_RECARGO)
        recargo = LineaCobro.objects.get(
            periodo=periodo, concepto=ConceptoLinea.RECARGO
        )
        self.assertEqual(recargo.monto, Decimal("100.00"))
        self.assertEqual(recargo.estado, EstadoLineaCobro.PAGADA)


class LiberacionYReactivacionTests(BillingBaseTestCase):
    def test_impago_libera_dia_11(self):
        alumno, h, reg, periodo = self._alta(capacidad=2)
        self.assertEqual(CapacityService.cupo_disponible(h), 1)

        ejecucion = ejecutar_cobranza_diaria(fecha=date(2026, 8, 11))
        periodo.refresh_from_db()
        reg.refresh_from_db()
        alumno.refresh_from_db()

        self.assertEqual(periodo.estado, EstadoPeriodoCobro.LIBERADO)
        self.assertEqual(reg.estado, EstadoRegular.LIBERADO)
        self.assertFalse(
            AsignacionRegular.objects.filter(regular=reg, activa=True).exists()
        )
        self.assertEqual(CapacityService.cupo_disponible(h), 2)
        self.assertEqual(alumno.estado, EstadoAlumno.BAJA_ADMINISTRATIVA)
        self.assertEqual(ejecucion.fecha, date(2026, 8, 11))
        self.assertTrue(
            LineaCobro.objects.filter(
                periodo=periodo, concepto=ConceptoLinea.RECARGO
            ).exists()
        )

    def test_pago_post_liberacion_sin_cupo_no_reactiva(self):
        alumno_a, h, reg_a, periodo_a = self._alta(capacidad=1, nombre="A")
        ejecutar_cobranza_diaria(fecha=date(2026, 8, 11))
        reg_a.refresh_from_db()
        self.assertEqual(CapacityService.cupo_disponible(h), 1)

        alumno_b = alta_alumno(nombre_completo="B", tipo=TipoAlumno.ADULTO)
        alta_regular(
            alumno=alumno_b, horarios=[h], fecha_inicio=date(2026, 8, 12)
        )
        self.assertEqual(CapacityService.cupo_disponible(h), 0)

        periodo_a.refresh_from_db()
        pago = registrar_pago_periodo(
            periodo=periodo_a,
            metodo_codigo="efectivo",
            fecha_pago=date(2026, 8, 12),
        )
        reg_a.refresh_from_db()
        alumno_a.refresh_from_db()
        periodo_a.refresh_from_db()

        self.assertEqual(pago.estado, EstadoPago.CONFIRMADO)
        self.assertTrue(pago.reglas_aplicadas.get("sin_cupo_para_reactivar"))
        self.assertFalse(pago.reglas_aplicadas.get("reactivado"))
        self.assertEqual(reg_a.estado, EstadoRegular.LIBERADO)
        self.assertEqual(alumno_a.estado, EstadoAlumno.BAJA_ADMINISTRATIVA)
        self.assertEqual(periodo_a.estado, EstadoPeriodoCobro.PAGADO_CON_RECARGO)

    def test_pago_post_liberacion_con_cupo_reactiva(self):
        alumno, h, reg, periodo = self._alta(capacidad=1, nombre="R")
        ejecutar_cobranza_diaria(fecha=date(2026, 8, 11))
        reg.refresh_from_db()
        self.assertEqual(reg.estado, EstadoRegular.LIBERADO)
        self.assertEqual(CapacityService.cupo_disponible(h), 1)

        periodo.refresh_from_db()
        pago = registrar_pago_periodo(
            periodo=periodo,
            metodo_codigo="transferencia",
            fecha_pago=date(2026, 8, 12),
        )
        reg.refresh_from_db()
        alumno.refresh_from_db()

        self.assertTrue(pago.reglas_aplicadas.get("reactivado"))
        self.assertFalse(pago.reglas_aplicadas.get("sin_cupo_para_reactivar"))
        self.assertEqual(reg.estado, EstadoRegular.ACTIVO)
        self.assertEqual(alumno.estado, EstadoAlumno.ACTIVO)
        self.assertTrue(
            AsignacionRegular.objects.filter(regular=reg, activa=True).exists()
        )
        self.assertEqual(CapacityService.cupo_disponible(h), 0)


class SnapshotEIdempotenciaTests(BillingBaseTestCase):
    def test_snapshot_no_cambia_si_cambian_tarifas(self):
        _, _, _, periodo = self._alta()
        linea = asegurar_linea_mensualidad(periodo)
        monto = linea.monto
        reglas = dict(linea.reglas_aplicadas)

        ParametroVersion.objects.create(
            vigente_desde=timezone.now() + timedelta(seconds=1),
            notas="tarifas nuevas",
            tarifa_hora_adulto=Decimal("999.00"),
            tarifa_hora_nino=Decimal("999.00"),
            monto_recargo=Decimal("500.00"),
        )
        for orden, horas, tarifa in (
            (1, 12, Decimal("999.00")),
            (2, 12, Decimal("888.00")),
            (3, 12, Decimal("777.00")),
        ):
            BloqueTarifaAdulto.objects.create(
                parametro_version=ParametroVersion.objects.latest("id"),
                orden=orden,
                horas_max=horas,
                tarifa_hora=tarifa,
            )

        linea.refresh_from_db()
        self.assertEqual(linea.monto, monto)
        self.assertEqual(linea.reglas_aplicadas["monto_periodo"], reglas["monto_periodo"])
        self.assertEqual(linea.monto, Decimal("1440.00"))

        # Recargo ya snapshotteado tampoco muda.
        aplicar_recargo_si_corresponde(periodo, fecha=date(2026, 8, 8))
        recargo = LineaCobro.objects.get(
            periodo=periodo, concepto=ConceptoLinea.RECARGO
        )
        self.assertEqual(recargo.monto, Decimal("100.00"))

        with self.assertRaises(ValidationError):
            recargo.monto = Decimal("500.00")
            recargo.save()

    def test_no_duplica_recargo_ni_job_al_ejecutar_dos_veces(self):
        _, _, _, periodo = self._alta()

        e1 = ejecutar_cobranza_diaria(fecha=date(2026, 8, 8))
        e2 = ejecutar_cobranza_diaria(fecha=date(2026, 8, 8))
        self.assertEqual(e1.pk, e2.pk)
        self.assertEqual(EjecucionCobranza.objects.filter(fecha=date(2026, 8, 8)).count(), 1)
        self.assertEqual(
            LineaCobro.objects.filter(
                periodo=periodo, concepto=ConceptoLinea.RECARGO
            ).count(),
            1,
        )

        aplicar_recargo_si_corresponde(periodo, fecha=date(2026, 8, 9))
        aplicar_recargo_si_corresponde(periodo, fecha=date(2026, 8, 10))
        self.assertEqual(
            LineaCobro.objects.filter(
                periodo=periodo, concepto=ConceptoLinea.RECARGO
            ).count(),
            1,
        )

        # Dia 11 dos veces: una sola liberacion.
        ejecutar_cobranza_diaria(fecha=date(2026, 8, 11))
        ejecutar_cobranza_diaria(fecha=date(2026, 8, 11))
        periodo.refresh_from_db()
        self.assertEqual(periodo.estado, EstadoPeriodoCobro.LIBERADO)
        self.assertEqual(
            LineaCobro.objects.filter(
                periodo=periodo, concepto=ConceptoLinea.RECARGO
            ).count(),
            1,
        )
