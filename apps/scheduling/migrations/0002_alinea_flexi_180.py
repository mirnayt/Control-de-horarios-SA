from datetime import datetime, time

from django.db import migrations


def _duracion(hora_inicio, hora_fin) -> int:
    delta = datetime.combine(datetime.min, hora_fin) - datetime.combine(
        datetime.min, hora_inicio
    )
    return int(delta.total_seconds() // 60)


# dia weekday, hora_inicio, tipo_alumno, hora_fin
_AJUSTES = (
    (0, time(16, 0), "adulto", time(19, 0)),  # lunes
    (2, time(12, 30), "adulto", time(15, 30)),  # miércoles
    (2, time(16, 0), "adulto", time(19, 0)),
    (4, time(9, 0), "adulto", time(12, 0)),  # viernes
    (4, time(12, 30), "adulto", time(15, 30)),
    (4, time(16, 0), "adulto", time(19, 0)),
    (5, time(14, 0), "adulto", time(17, 0)),  # sábado
)

_MODS_FLEXI = ["regular", "flexi", "suelta"]


def alinea_flexi_180(apps, schema_editor):
    Horario = apps.get_model("scheduling", "Horario")
    for dia, hora_inicio, tipo, hora_fin in _AJUSTES:
        qs = Horario.objects.filter(
            dia=dia, hora_inicio=hora_inicio, tipo_alumno=tipo
        ).order_by("id")
        horario = qs.first()
        if horario is None:
            continue
        horario.hora_fin = hora_fin
        horario.duracion_minutos = _duracion(hora_inicio, hora_fin)
        actuales = list(horario.modalidades or [])
        for m in _MODS_FLEXI:
            if m not in actuales:
                actuales.append(m)
        horario.modalidades = actuales
        horario.save()
        qs.exclude(pk=horario.pk).delete()


def noop_reverse(apps, schema_editor):
    pass


class Migration(migrations.Migration):
    dependencies = [
        ("scheduling", "0001_initial"),
    ]

    operations = [
        migrations.RunPython(alinea_flexi_180, noop_reverse),
    ]
