from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import staff_operativo_required
from apps.core.ui import (
    alumnos_activos,
    alumno_id_preseleccionado,
    buscar_alumnos,
    horarios_con_cupo,
    mensaje_error_operacion,
)
from apps.people.models import Alumno
from apps.regular.models import AsignacionRegular, Regular
from apps.regular.services import alta_regular
from apps.scheduling.models import Horario, Modalidad
from apps.scheduling.services import CapacityService


@staff_operativo_required
def regular_list(request):
    qs = Regular.objects.select_related("alumno").prefetch_related(
        "asignaciones__horario"
    )
    return render(request, "regular/regular_list.html", {"regulares": qs})


@staff_operativo_required
@require_http_methods(["GET", "POST"])
def regular_alta(request):
    q = (request.GET.get("q") or request.POST.get("q") or "").strip()
    alumno_id = (
        request.POST.get("alumno_id") or request.GET.get("alumno_id") or ""
    ).strip()
    alumno_pre = alumno_id_preseleccionado(request)
    if not alumno_id and alumno_pre:
        alumno_id = str(alumno_pre)

    alumno = None
    resultados = None
    if alumno_id.isdigit():
        alumno = alumnos_activos().filter(pk=int(alumno_id)).first()
    elif q:
        resultados = list(buscar_alumnos(q, qs=alumnos_activos())[:20])
        if len(resultados) == 1:
            alumno = resultados[0]
            resultados = None

    horarios = horarios_con_cupo(Modalidad.REGULAR, alumno=alumno)
    asignaciones_actuales = []
    if alumno is not None:
        asignaciones_actuales = list(
            AsignacionRegular.objects.filter(
                regular__alumno=alumno, activa=True
            ).select_related("horario", "regular")
        )

    if request.method == "POST":
        try:
            if alumno is None:
                raise ValidationError("Seleccione un alumno activo.")
            ids = request.POST.getlist("horario_ids")
            if not ids:
                raise ValidationError(
                    "Seleccione al menos un horario Regular con cupo."
                )
            hs = list(Horario.objects.filter(pk__in=ids, activo=True))
            if len(hs) != len(ids):
                raise ValidationError(
                    "Uno o más horarios no están activos o no son válidos."
                )
            reg = alta_regular(
                alumno=alumno,
                horarios=hs,
                es_tarifa_fundadora=request.POST.get("es_tarifa_fundadora") == "1",
            )
            messages.success(request, f"Alta Regular: {reg}")
            return redirect("regular_list")
        except (Alumno.DoesNotExist, ValidationError) as e:
            messages.error(request, mensaje_error_operacion(e))

    return render(
        request,
        "regular/regular_alta.html",
        {
            "q": q,
            "alumno": alumno,
            "resultados": resultados,
            "asignaciones_actuales": asignaciones_actuales,
            "horarios": [
                {"horario": h, "cupo": CapacityService.cupo_disponible(h)}
                for h in horarios
            ],
            "regular_alta_url": reverse("regular_alta"),
            "es_tarifa_fundadora": request.POST.get("es_tarifa_fundadora") == "1",
        },
    )
