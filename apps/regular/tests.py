from datetime import date, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.catalog.models import Profesor, Salon
from apps.enrollment.services import alta_alumno
from apps.params.models import BloqueTarifaAdulto, ParametroVersion
from apps.params.services import seed_parametros_iniciales
from apps.people.models import EstadoAlumno, TipoAlumno
from apps.scheduling.models import DiaSemana, Horario, Modalidad, TipoAlumno as TipoHorario
from apps.scheduling.services import CapacityService, SinCupoError
from apps.regular.models import (
    AsignacionRegular,
    EstadoPeriodoCobro,
    EstadoRegular,
    PeriodoCobroRegular,
)
from apps.regular.services import (
    alta_regular,
    generar_periodo_cobro,
    liberar_lugar_logico,
    monto_periodo_desde_snapshot,
)


class RegularBaseTestCase(TestCase):
    def setUp(self):
        self.params = seed_parametros_iniciales()
        self.salon = Salon.objects.create(nombre="Salón R")
        self.profesor = Profesor.objects.create(nombre="Profe R")

    def _horario(self, dia, *, duracion=180, capacidad=8, tipo=TipoHorario.ADULTO, hora=9):
        inicio = time(hora, 0)
        fin_h = hora + duracion // 60
        fin_m = duracion % 60
        return Horario.objects.create(
            dia=dia,
            hora_inicio=inicio,
            hora_fin=time(fin_h, fin_m),
            duracion_minutos=duracion,
            capacidad=capacidad,
            tipo_alumno=tipo,
            modalidades=[Modalidad.REGULAR, Modalidad.FLEXI]
            if tipo != TipoHorario.NINO
            else [Modalidad.REGULAR],
            activo=True,
            salon=self.salon,
            profesor=self.profesor,
        )


class AltaYCalculoRegularTests(RegularBaseTestCase):
    """1 / 2 / 3 días adulto; niño; 5ª semana; sábado; alta post-7; cupo."""

    def test_adulto_1_dia_semana(self):
        # Ago 2026: 4 martes × 3 h = 12 h → $1,440
        alumno = alta_alumno(nombre_completo="A1", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES, duracion=180)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        self.assertEqual(periodo.horas_total, Decimal("12.00"))
        self.assertEqual(periodo.monto, Decimal("1440.00"))
        self.assertFalse(periodo.alta_parcial)
        self.assertEqual(periodo.estado, EstadoPeriodoCobro.PENDIENTE)

    def test_adulto_2_dias_semana(self):
        alumno = alta_alumno(nombre_completo="A2", tipo=TipoAlumno.ADULTO)
        h1 = self._horario(DiaSemana.MARTES, duracion=180, hora=9)
        h2 = self._horario(DiaSemana.MIERCOLES, duracion=180, hora=10)
        reg = alta_regular(
            alumno=alumno, horarios=[h1, h2], fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        self.assertEqual(periodo.horas_total, Decimal("24.00"))
        self.assertEqual(periodo.monto, Decimal("2760.00"))

    def test_adulto_3_dias_semana(self):
        alumno = alta_alumno(nombre_completo="A3", tipo=TipoAlumno.ADULTO)
        horarios = [
            self._horario(DiaSemana.MARTES, duracion=180, hora=9),
            self._horario(DiaSemana.MIERCOLES, duracion=180, hora=10),
            self._horario(DiaSemana.JUEVES, duracion=180, hora=11),
        ]
        reg = alta_regular(
            alumno=alumno, horarios=horarios, fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        self.assertEqual(periodo.horas_total, Decimal("36.00"))
        self.assertEqual(periodo.monto, Decimal("3960.00"))
        self.assertEqual(reg.asignaciones.filter(activa=True).count(), 3)

    def test_nino_regular(self):
        # 4 martes × 2 h = 8 h × $110 = $880
        alumno = alta_alumno(nombre_completo="N1", tipo=TipoAlumno.NINO)
        h = self._horario(
            DiaSemana.MARTES, duracion=120, tipo=TipoHorario.NINO, hora=16
        )
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        self.assertEqual(periodo.horas_total, Decimal("8.00"))
        self.assertEqual(periodo.monto, Decimal("880.00"))

    def test_mes_con_cinco_ocurrencias(self):
        # Ago 2026: 5 lunes × 3 h = 15 h → 12×120 + 3×110 = 1770
        alumno = alta_alumno(nombre_completo="A5", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.LUNES, duracion=180)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        self.assertEqual(periodo.horas_total, Decimal("15.00"))
        self.assertEqual(len(periodo.detalle_calculo["horarios"][0]["fechas"]), 5)
        self.assertEqual(periodo.monto, Decimal("1770.00"))

    def test_sabado_adulto_tarifa_base(self):
        # 5 sábados × 2 h = 10 h × $120 = $1,200 (sin bloques)
        alumno = alta_alumno(nombre_completo="Sab", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.SABADO, duracion=120, hora=10)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        self.assertEqual(periodo.horas_sabado, Decimal("10.00"))
        self.assertEqual(periodo.horas_semana, Decimal("0.00"))
        self.assertEqual(periodo.monto, Decimal("1200.00"))

    def test_alta_post_dia_7_proporcional(self):
        # Alta 10 ago en sábado → quedan 15,22,29 = 3×2h = 6h ×120 flat
        alumno = alta_alumno(nombre_completo="Parcial", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.SABADO, duracion=120, hora=10)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 10)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        self.assertTrue(periodo.alta_parcial)
        self.assertEqual(periodo.horas_total, Decimal("6.00"))
        self.assertEqual(periodo.monto, Decimal("720.00"))
        self.assertEqual(
            periodo.detalle_calculo["horarios"][0]["fechas"],
            ["2026-08-15", "2026-08-22", "2026-08-29"],
        )

    def test_rechazo_cupo_lleno(self):
        h = self._horario(DiaSemana.VIERNES, capacidad=1, hora=18)
        a1 = alta_alumno(nombre_completo="Cupo1", tipo=TipoAlumno.ADULTO)
        a2 = alta_alumno(nombre_completo="Cupo2", tipo=TipoAlumno.ADULTO)
        alta_regular(alumno=a1, horarios=[h], fecha_inicio=date(2026, 8, 1))
        self.assertEqual(CapacityService.cupo_disponible(h), 0)
        with self.assertRaises(SinCupoError):
            alta_regular(alumno=a2, horarios=[h], fecha_inicio=date(2026, 8, 1))

    def test_max_tres_horarios(self):
        alumno = alta_alumno(nombre_completo="Max", tipo=TipoAlumno.ADULTO)
        hs = [
            self._horario(DiaSemana.LUNES, hora=9),
            self._horario(DiaSemana.MARTES, hora=10),
            self._horario(DiaSemana.MIERCOLES, hora=11),
            self._horario(DiaSemana.JUEVES, hora=12),
        ]
        with self.assertRaises(ValidationError):
            alta_regular(alumno=alumno, horarios=hs, fecha_inicio=date(2026, 8, 1))


class SnapshotYLiberacionTests(RegularBaseTestCase):
    def test_calculo_reproducible_tras_cambio_tarifas(self):
        alumno = alta_alumno(nombre_completo="Snap", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES, duracion=180)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        periodo = reg.periodos_cobro.get(anio=2026, mes=8)
        monto_original = periodo.monto
        version_id = periodo.parametro_version_id
        detalle_original = periodo.detalle_calculo.copy()

        # Nueva versión con tarifas distintas (no debe alterar el periodo ya calculado).
        nueva = ParametroVersion.objects.create(
            vigente_desde=timezone.now() + timedelta(seconds=1),
            notas="tarifas nuevas",
            tarifa_hora_adulto=Decimal("999.00"),
            tarifa_hora_nino=Decimal("999.00"),
        )
        for orden, horas, tarifa in (
            (1, 12, Decimal("999.00")),
            (2, 12, Decimal("888.00")),
            (3, 12, Decimal("777.00")),
        ):
            BloqueTarifaAdulto.objects.create(
                parametro_version=nueva,
                orden=orden,
                horas_max=horas,
                tarifa_hora=tarifa,
            )

        periodo.refresh_from_db()
        self.assertEqual(monto_periodo_desde_snapshot(periodo), monto_original)
        self.assertEqual(periodo.parametro_version_id, version_id)
        self.assertEqual(periodo.monto, Decimal("1440.00"))
        self.assertEqual(periodo.detalle_calculo["monto"], detalle_original["monto"])

        # Recalcular forzando la versión original → mismo monto.
        recalc = generar_periodo_cobro(
            reg,
            2026,
            8,
            version=periodo.parametro_version,
            recalcular=True,
        )
        self.assertEqual(recalc.monto, monto_original)

    def test_liberacion_logica_prepara_etapa_6(self):
        alumno = alta_alumno(nombre_completo="Lib", tipo=TipoAlumno.ADULTO)
        h = self._horario(DiaSemana.MARTES, capacidad=2, duracion=180)
        reg = alta_regular(
            alumno=alumno, horarios=[h], fecha_inicio=date(2026, 8, 1)
        )
        self.assertEqual(CapacityService.cupo_disponible(h), 1)

        liberar_lugar_logico(reg, fecha=date(2026, 8, 11))
        reg.refresh_from_db()
        alumno.refresh_from_db()

        self.assertEqual(reg.estado, EstadoRegular.LIBERADO)
        self.assertFalse(AsignacionRegular.objects.filter(regular=reg, activa=True).exists())
        self.assertEqual(CapacityService.cupo_disponible(h), 2)
        periodo = PeriodoCobroRegular.objects.get(regular=reg, anio=2026, mes=8)
        self.assertEqual(periodo.estado, EstadoPeriodoCobro.LIBERADO)
        self.assertEqual(alumno.estado, EstadoAlumno.BAJA_ADMINISTRATIVA)
        self.assertIn("liberacion", periodo.detalle_calculo)
