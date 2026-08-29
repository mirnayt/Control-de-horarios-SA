from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from apps.params.models import ParametroVersion, VigenciaFlexi
from apps.params.services import PricingService, seed_parametros_iniciales


class ParamsTests(TestCase):
    def test_seed_crea_version_bloques_y_vigencias(self):
        version = seed_parametros_iniciales()
        self.assertEqual(version.bloques_adulto.count(), 3)
        self.assertEqual(version.vigencias_flexi.count(), 6)
        self.assertTrue(version.sabado_adulto_sin_descuento_progresivo)
        self.assertEqual(version.tarifa_hora_adulto, Decimal("120.00"))

    def test_vigente_devuelve_ultima_por_fecha(self):
        antigua = ParametroVersion.objects.create(
            vigente_desde=timezone.now() - timedelta(days=30),
            notas="antigua",
        )
        nueva = ParametroVersion.objects.create(
            vigente_desde=timezone.now() - timedelta(days=1),
            notas="nueva",
        )
        self.assertEqual(ParametroVersion.vigente().pk, nueva.pk)
        self.assertNotEqual(ParametroVersion.vigente().pk, antigua.pk)

    def test_clean_dias_cobranza_invalidos(self):
        v = ParametroVersion(
            vigente_desde=timezone.now(),
            dia_pago_normal_fin=10,
            dia_recargo_inicio=8,
            dia_recargo_fin=10,
            dia_liberacion=11,
        )
        with self.assertRaises(ValidationError):
            v.full_clean()

    def test_vigencia_flexi_rango_invalido(self):
        version = seed_parametros_iniciales()
        bad = VigenciaFlexi(
            parametro_version=version,
            sesiones_min=10,
            sesiones_max=5,
            meses_vigencia=1,
        )
        with self.assertRaises(ValidationError):
            bad.full_clean()


class PricingServiceTests(TestCase):
    def setUp(self):
        self.version = seed_parametros_iniciales()

    def test_adulto_12h_igual_1440(self):
        self.assertEqual(
            PricingService.monto_regular_adulto(12, version=self.version),
            Decimal("1440.00"),
        )

    def test_adulto_24h_igual_2760(self):
        self.assertEqual(
            PricingService.monto_regular_adulto(24, version=self.version),
            Decimal("2760.00"),
        )

    def test_adulto_36h_igual_3960(self):
        self.assertEqual(
            PricingService.monto_regular_adulto(36, version=self.version),
            Decimal("3960.00"),
        )

    def test_nino_8h_igual_880(self):
        self.assertEqual(
            PricingService.monto_regular_nino(8, version=self.version),
            Decimal("880.00"),
        )

    def test_alta_parcial_adulto_sin_descuentos(self):
        # 24h con bloques = 2760; parcial = 24×120 = 2880
        self.assertEqual(
            PricingService.monto_regular_adulto(
                24, version=self.version, alta_parcial=True
            ),
            Decimal("2880.00"),
        )
        self.assertNotEqual(
            PricingService.monto_regular_adulto(24, version=self.version),
            PricingService.monto_regular_adulto(
                24, version=self.version, alta_parcial=True
            ),
        )

    def test_sabado_adulto_sin_descuento_progresivo(self):
        # 24h sábado = 24×120 = 2880 (no 2760 de bloques)
        self.assertEqual(
            PricingService.monto_regular_adulto(
                24, version=self.version, es_sabado=True
            ),
            Decimal("2880.00"),
        )

    def test_duracion_configurable_a_horas(self):
        horas = PricingService.horas_desde_duracion(90, 4)
        self.assertEqual(horas, Decimal("6"))
        self.assertEqual(
            PricingService.monto_regular_adulto(horas, version=self.version),
            Decimal("720.00"),
        )

    def test_flexi_y_suelta(self):
        self.assertEqual(
            PricingService.monto_flexi(10, version=self.version),
            Decimal("1200.00"),
        )
        self.assertEqual(
            PricingService.monto_clase_suelta(version=self.version),
            Decimal("500.00"),
        )
