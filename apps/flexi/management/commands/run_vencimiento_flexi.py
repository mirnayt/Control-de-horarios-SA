from django.core.management.base import BaseCommand
from django.utils.dateparse import parse_date

from apps.flexi.services import job_vencimiento_flexi


class Command(BaseCommand):
    help = "Vence paquetes Flexi con saldo sobrante (idempotente por fecha local)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--fecha",
            type=str,
            default=None,
            help="Fecha YYYY-MM-DD (default: hoy America/Mexico_City).",
        )
        parser.add_argument(
            "--forzar",
            action="store_true",
            help="Reprocesa aunque ya exista EjecucionVencimientoFlexi del día.",
        )

    def handle(self, *args, **options):
        fecha = None
        if options["fecha"]:
            fecha = parse_date(options["fecha"])
            if fecha is None:
                raise SystemExit("fecha inválida; use YYYY-MM-DD")
        run = job_vencimiento_flexi(fecha=fecha, forzar=options["forzar"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Vencimiento Flexi {run.fecha}: "
                f"{len(run.detalle.get('vencidos', []))} paquete(s)"
            )
        )
