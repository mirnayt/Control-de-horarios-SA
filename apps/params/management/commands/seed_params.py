from django.core.management.base import BaseCommand

from apps.params.services import seed_parametros_iniciales


class Command(BaseCommand):
    help = "Crea parámetros iniciales MVP si no existen."

    def add_arguments(self, parser):
        parser.add_argument(
            "--force",
            action="store_true",
            help="Crea una nueva versión aunque ya existan parámetros.",
        )

    def handle(self, *args, **options):
        version = seed_parametros_iniciales(force=options["force"])
        self.stdout.write(self.style.SUCCESS(f"ParametroVersion id={version.pk}"))
