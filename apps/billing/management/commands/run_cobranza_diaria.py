from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import date

from apps.billing.services import ejecutar_cobranza_diaria


class Command(BaseCommand):
    help = (
        "Job diario de cobranza (America/Mexico_City): "
        "recargo dias 8-10 y liberacion dia 11+. Idempotente."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fecha",
            type=str,
            default=None,
            help="YYYY-MM-DD (default: hoy local Mexico City).",
        )
        parser.add_argument(
            "--forzar",
            action="store_true",
            help="Reprocesa aunque ya exista EjecucionCobranza del dia.",
        )

    def handle(self, *args, **options):
        fecha = None
        if options["fecha"]:
            fecha = date.fromisoformat(options["fecha"])
        ejecucion = ejecutar_cobranza_diaria(
            fecha=fecha, forzar=options["forzar"]
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"Cobranza {ejecucion.fecha} @ {ejecucion.ejecutado_en.isoformat()} "
                f"(TZ={timezone.get_current_timezone_name()})"
            )
        )
        det = ejecucion.detalle or {}
        self.stdout.write(
            f"recargos={len(det.get('recargos_aplicados', []))} "
            f"liberaciones={len(det.get('liberaciones', []))}"
        )
