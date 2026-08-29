from datetime import date

from django.utils import timezone



from django.contrib import messages

from django.core.exceptions import PermissionDenied, ValidationError

from django.shortcuts import get_object_or_404, redirect, render

from django.views.decorators.http import require_http_methods



from apps.accounts.decorators import staff_operativo_required

from apps.accounts.roles import user_is_direccion

from apps.attendance.models import Asistencia, Compensacion, EstadoCompensacion

from apps.attendance.services import (

    autorizar_reembolso,

    cancelar_por_spirit,

    marcar_asistio,

    marcar_ausente_alumno,

    programar_asistencia_flexi,

    programar_asistencia_regular,

    registrar_reposicion_sin_costo,

)

from apps.core.ui import (

    asignaciones_regular_activas,

    alumno_id_preseleccionado,

    mensaje_error_operacion,

    reservas_flexi_programables,

)

from apps.flexi.models import ReservaFlexi

from apps.regular.models import AsignacionRegular

from decimal import Decimal, InvalidOperation





@staff_operativo_required

def asistencias_list(request):

    qs = Asistencia.objects.select_related(

        "alumno", "horario"

    ).order_by("-fecha", "-id")[:100]

    return render(request, "attendance/asistencias_list.html", {"asistencias": qs})





@staff_operativo_required

@require_http_methods(["GET", "POST"])

def asistencia_programar(request):

    asignaciones = asignaciones_regular_activas()

    reservas = reservas_flexi_programables()

    alumno_pre = alumno_id_preseleccionado(request)

    if alumno_pre:

        asignaciones = asignaciones.filter(regular__alumno_id=alumno_pre)

        reservas = reservas.filter(paquete__alumno_id=alumno_pre)

    modalidad_preseleccionada = None

    if alumno_pre:

        tiene_reg = asignaciones.exists()

        tiene_flex = reservas.exists()

        if tiene_flex and not tiene_reg:

            modalidad_preseleccionada = "flexi"

        elif tiene_reg:

            modalidad_preseleccionada = "regular"

    if request.method == "POST":

        try:

            modalidad = request.POST.get("modalidad")

            if modalidad == "regular":

                asig_id = (request.POST.get("asignacion_id") or "").strip()

                if not asig_id:

                    raise ValidationError("Seleccione una asignación Regular.")

                asig = asignaciones.get(pk=asig_id)

                fecha_raw = (request.POST.get("fecha") or "").strip()

                if not fecha_raw:

                    raise ValidationError("Indique la fecha de la clase.")

                fecha = date.fromisoformat(fecha_raw)

                a = programar_asistencia_regular(asignacion=asig, fecha=fecha)

            elif modalidad == "flexi":

                reserva_id = (request.POST.get("reserva_id") or "").strip()

                if not reserva_id:

                    raise ValidationError("Seleccione una reserva Flexi.")

                res = reservas.get(pk=reserva_id)

                a = programar_asistencia_flexi(reserva=res)

            else:

                raise ValidationError("Seleccione modalidad Regular o Flexi.")

            messages.success(request, f"Asistencia programada: {a}")

            return redirect("asistencias_list")

        except (

            AsignacionRegular.DoesNotExist,

            ReservaFlexi.DoesNotExist,

            ValidationError,

            ValueError,

        ) as e:

            messages.error(request, mensaje_error_operacion(e))

    return render(

        request,

        "attendance/asistencia_programar.html",

        {

            "asignaciones": asignaciones,

            "reservas": reservas,

            "alumno_preseleccionado": alumno_pre,

            "modalidad_preseleccionada": modalidad_preseleccionada,

            "hoy": timezone.localdate().isoformat(),

        },

    )





@staff_operativo_required

@require_http_methods(["POST"])

def asistencia_accion(request, pk):

    asist = get_object_or_404(Asistencia, pk=pk)

    accion = request.POST.get("accion")

    try:

        if accion == "asistio":

            marcar_asistio(asist, usuario=request.user)

            messages.success(request, "Marcada como asistió.")

        elif accion == "ausente":

            marcar_ausente_alumno(asist, usuario=request.user)

            messages.success(request, "Marcada ausente (alumno).")

        elif accion == "spirit":

            cancelar_por_spirit(asist, usuario=request.user)

            messages.success(request, "Cancelada por Spirit; compensación pendiente.")

        else:

            messages.error(request, "Acción desconocida.")

    except ValidationError as e:

        messages.error(request, mensaje_error_operacion(e))

    return redirect("asistencias_list")





@staff_operativo_required

def compensaciones_list(request):

    qs = Compensacion.objects.select_related(

        "asistencia__alumno", "asistencia__horario"

    ).order_by("-id")[:100]

    return render(

        request,

        "attendance/compensaciones_list.html",

        {

            "compensaciones": qs,

            "es_direccion": user_is_direccion(request.user),

        },

    )





@staff_operativo_required

@require_http_methods(["POST"])

def compensacion_accion(request, pk):

    comp = get_object_or_404(Compensacion, pk=pk)

    if comp.estado != EstadoCompensacion.PENDIENTE:

        messages.error(request, "La compensación ya no está pendiente.")

        return redirect("compensaciones_list")

    accion = request.POST.get("accion")

    notas = request.POST.get("notas", "")

    try:

        if accion == "reposicion":

            registrar_reposicion_sin_costo(

                comp, usuario=request.user, notas=notas

            )

            messages.success(request, "Reposición sin costo registrada.")

        elif accion == "reembolso":

            monto = None

            raw = (request.POST.get("monto") or "").strip()

            if raw:

                monto = Decimal(raw)

            autorizar_reembolso(

                comp, usuario=request.user, monto=monto, notas=notas

            )

            messages.success(request, "Reembolso autorizado.")

        else:

            messages.error(request, "Acción desconocida.")

    except (PermissionDenied, ValidationError, InvalidOperation) as e:

        messages.error(request, mensaje_error_operacion(e))

    return redirect("compensaciones_list")


