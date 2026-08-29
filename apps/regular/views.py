from django.contrib import messages

from django.core.exceptions import ValidationError

from django.shortcuts import redirect, render

from django.views.decorators.http import require_http_methods



from apps.accounts.decorators import staff_operativo_required

from apps.core.ui import (

    alumnos_activos,

    alumno_id_preseleccionado,

    horarios_con_cupo,

    mensaje_error_operacion,

)

from apps.people.models import Alumno

from apps.regular.models import Regular

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

    alumnos = alumnos_activos()

    horarios = horarios_con_cupo(Modalidad.REGULAR)

    if request.method == "POST":

        try:

            alumno = alumnos.get(pk=request.POST.get("alumno_id"))

            ids = request.POST.getlist("horario_ids")

            if not ids:

                raise ValidationError(

                    "Seleccione al menos un horario Regular con cupo."

                )

            hs = list(

                Horario.objects.filter(pk__in=ids, activo=True)

            )

            if len(hs) != len(ids):

                raise ValidationError(

                    "Uno o más horarios no están activos o no son válidos."

                )

            reg = alta_regular(alumno=alumno, horarios=hs)

            messages.success(request, f"Alta Regular: {reg}")

            return redirect("regular_list")

        except (Alumno.DoesNotExist, ValidationError) as e:

            messages.error(request, mensaje_error_operacion(e))

    return render(

        request,

        "regular/regular_alta.html",

        {

            "alumnos": alumnos,

            "horarios": [
                {"horario": h, "cupo": CapacityService.cupo_disponible(h)}
                for h in horarios
            ],

            "alumno_preseleccionado": alumno_id_preseleccionado(request),

        },

    )


