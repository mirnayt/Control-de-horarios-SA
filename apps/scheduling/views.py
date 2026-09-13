from datetime import date

from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from apps.accounts.decorators import staff_operativo_required
from apps.core.ui import contexto_roster_horario, filas_horarios
from apps.scheduling.models import DiaSemana, Horario


def _parse_dia(raw: str | None, *, default_hoy: bool) -> int | None:
    """None = todos los días. Entero 0–6 = día de semana."""
    if raw is None:
        return timezone.localdate().weekday() if default_hoy else None
    raw = raw.strip().lower()
    if raw in ("", "all", "todos"):
        return None
    dia = int(raw)
    if dia not in {c.value for c in DiaSemana}:
        raise ValueError("día inválido")
    return dia


def _parse_fecha(raw: str | None) -> date | None:
    if not raw:
        return None
    return date.fromisoformat(raw.strip())


@staff_operativo_required
def horarios_list(request):
    hoy = timezone.localdate()
    dia_raw = request.GET.get("dia")
    try:
        dia = _parse_dia(dia_raw, default_hoy=True)
    except (TypeError, ValueError):
        dia = hoy.weekday()

    fecha_clase = _parse_fecha(request.GET.get("fecha"))
    if fecha_clase is None and dia is not None and dia == hoy.weekday():
        fecha_clase = hoy

    return render(
        request,
        "scheduling/horarios_list.html",
        {
            "filas": filas_horarios(dia=dia, fecha_clase=fecha_clase),
            "dia_filtro": dia,
            "fecha_clase": fecha_clase,
            "hoy": hoy,
            "dias": DiaSemana,
        },
    )


@staff_operativo_required
def horario_roster(request, pk: int):
    horario = get_object_or_404(
        Horario.objects.select_related("salon", "profesor"), pk=pk
    )
    hoy = timezone.localdate()
    fecha_clase = _parse_fecha(request.GET.get("fecha"))
    if fecha_clase is None and horario.dia == hoy.weekday():
        fecha_clase = hoy

    ctx = contexto_roster_horario(horario, fecha_clase=fecha_clase)
    ctx.update({"hoy": hoy})
    return render(request, "scheduling/horario_roster.html", ctx)
