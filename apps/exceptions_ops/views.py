from datetime import date



from django.contrib import messages

from django.core.exceptions import PermissionDenied, ValidationError

from django.shortcuts import get_object_or_404, redirect, render

from django.views.decorators.http import require_http_methods



from apps.accounts.decorators import staff_operativo_required

from apps.accounts.roles import user_is_direccion

from apps.core.ui import alumnos_activos, alumno_id_preseleccionado, mensaje_error_operacion

from apps.exceptions_ops.models import EstadoExcepcion, ExcepcionAutorizada, TipoExcepcion

from apps.exceptions_ops.services import autorizar, crear_solicitud, rechazar

from apps.people.models import Alumno





@staff_operativo_required

def excepciones_list(request):

    qs = ExcepcionAutorizada.objects.select_related("alumno", "autorizador").order_by(

        "-id"

    )[:100]

    return render(

        request,

        "exceptions_ops/excepciones_list.html",

        {

            "excepciones": qs,

            "es_direccion": user_is_direccion(request.user),

        },

    )





@staff_operativo_required

@require_http_methods(["GET", "POST"])

def excepcion_nueva(request):

    alumnos = alumnos_activos()

    if request.method == "POST":

        try:

            alumno = alumnos.get(pk=request.POST.get("alumno_id"))

            fin_raw = (request.POST.get("fecha_fin") or "").strip()

            exc = crear_solicitud(

                alumno=alumno,

                tipo=request.POST.get("tipo", ""),

                motivo=request.POST.get("motivo", ""),

                fecha_inicio=date.fromisoformat(request.POST.get("fecha_inicio", "")),

                fecha_fin=date.fromisoformat(fin_raw) if fin_raw else None,

                usuario=request.user,

                notas=request.POST.get("notas", ""),

            )

            messages.success(request, f"Solicitud creada: {exc}")

            return redirect("excepciones_list")

        except (Alumno.DoesNotExist, ValidationError, PermissionDenied, ValueError) as e:

            messages.error(request, mensaje_error_operacion(e))

    return render(

        request,

        "exceptions_ops/excepcion_nueva.html",

        {"alumnos": alumnos, "tipos": TipoExcepcion.choices, "alumno_preseleccionado": alumno_id_preseleccionado(request)},

    )





@staff_operativo_required

@require_http_methods(["POST"])

def excepcion_accion(request, pk):

    exc = get_object_or_404(ExcepcionAutorizada, pk=pk)

    if exc.estado != EstadoExcepcion.SOLICITADA:

        messages.error(request, "La excepción ya no está solicitada.")

        return redirect("excepciones_list")

    accion = request.POST.get("accion")

    notas = request.POST.get("notas", "")

    try:

        if accion == "autorizar":

            autorizar(exc, usuario=request.user, notas=notas)

            messages.success(request, "Excepción autorizada.")

        elif accion == "rechazar":

            rechazar(exc, usuario=request.user, notas=notas)

            messages.success(request, "Excepción rechazada.")

        else:

            messages.error(request, "Acción desconocida.")

    except (PermissionDenied, ValidationError) as e:

        messages.error(request, mensaje_error_operacion(e))

    return redirect("excepciones_list")


