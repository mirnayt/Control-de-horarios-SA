from django.core.management.base import BaseCommand

from apps.scheduling.operacion_seed import seed_operacion_spirit


class Command(BaseCommand):
    help = (
        "Carga configuración operativa Spirit: salones, horarios, parámetros. "
        "Valores provisionales (capacidad, salón default, profesor demo) en "
        "apps/scheduling/operacion_config.py."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Actualiza horarios existentes y recrea versión de parámetros.",
        )

    def handle(self, *args, **options):
        result = seed_operacion_spirit(force=options["force"])
        self.stdout.write(
            self.style.SUCCESS(
                f"Operación Spirit: salones={result.salones} "
                f"horarios={result.horarios} "
                f"(+{result.horarios_creados} nuevos, "
                f"{result.horarios_actualizados} actualizados) "
                f"params_id={result.parametros_version_id}"
            )
        )
