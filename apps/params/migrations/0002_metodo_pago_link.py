from django.db import migrations


def ensure_metodo_link(apps, schema_editor):
    MetodoPagoCatalogo = apps.get_model("params", "MetodoPagoCatalogo")
    MetodoPagoCatalogo.objects.get_or_create(
        codigo="link",
        defaults={"nombre": "Link de pago", "activo": True},
    )


def noop_reverse(apps, schema_editor):
    """No elimina el método: puede haber pagos asociados."""


class Migration(migrations.Migration):
    dependencies = [
        ("params", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(ensure_metodo_link, noop_reverse),
    ]
