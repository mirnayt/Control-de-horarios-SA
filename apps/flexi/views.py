from datetime import date



from django.contrib import messages

from django.core.exceptions import ValidationError

from django.shortcuts import get_object_or_404, redirect, render

from django.views.decorators.http import require_http_methods



from apps.accounts.decorators import staff_operativo_required

from apps.core.ui import (

    alumnos_flexi_compra,

    alumno_id_preseleccionado,

    horarios_con_cupo,

    mensaje_error_operacion,

    paquetes_flexi_reservables,

)

from apps.flexi.models import EstadoReservaFlexi, PaqueteFlexi, ReservaFlexi

from apps.flexi.services import (

    cancelar_reserva_flexi,

    comprar_paquete_flexi,

    reservar_flexi,

)

from apps.people.models import Alumno

from apps.scheduling.models import Horario, Modalidad





@staff_operativo_required

def flexi_list(request):

    paquetes = PaqueteFlexi.objects.select_related("alumno").order_by(

        "-fecha_compra", "-id"

    )[:50]

    reservas = (

        ReservaFlexi.objects.filter(estado=EstadoReservaFlexi.RESERVADA)

        .select_related("paquete__alumno", "horario")

        .order_by("fecha_clase")[:50]

    )

    return render(

        request,

        "flexi/flexi_list.html",

        {"paquetes": paquetes, "reservas": reservas},

    )





@staff_operativo_required

@require_http_methods(["GET", "POST"])

def flexi_comprar(request):

    alumnos = alumnos_flexi_compra()

    if request.method == "POST":

        try:

            alumno = alumnos.get(pk=request.POST.get("alumno_id"))

            pkg = comprar_paquete_flexi(

                alumno=alumno,

                sesiones=int(request.POST.get("sesiones") or 0),

                metodo_codigo=request.POST.get("metodo_codigo", ""),

                referencia=request.POST.get("referencia", ""),

            )

            messages.success(request, f"Paquete comprado: {pkg}")

            return redirect("flexi_list")

        except (Alumno.DoesNotExist, ValidationError, ValueError) as e:

            messages.error(request, mensaje_error_operacion(e))

    return render(request, "flexi/flexi_comprar.html", {

        "alumnos": alumnos,

        "alumno_preseleccionado": alumno_id_preseleccionado(request),

    })





@staff_operativo_required

@require_http_methods(["GET", "POST"])

def flexi_reservar(request):

    paquetes = paquetes_flexi_reservables()

    alumno_pre = alumno_id_preseleccionado(request)

    if alumno_pre:

        paquetes = paquetes.filter(alumno_id=alumno_pre)

    horarios = horarios_con_cupo(Modalidad.FLEXI)

    if request.method == "POST":

        try:

            pkg = paquetes.get(pk=request.POST.get("paquete_id"))

            horario = Horario.objects.get(

                pk=request.POST.get("horario_id"), activo=True

            )

            fecha_raw = (request.POST.get("fecha_clase") or "").strip()

            if not fecha_raw:

                raise ValidationError("Indique la fecha de la clase.")

            fecha = date.fromisoformat(fecha_raw)

            r = reservar_flexi(paquete=pkg, horario=horario, fecha_clase=fecha)

            messages.success(request, f"Reserva creada: {r}")

            return redirect("flexi_list")

        except (

            PaqueteFlexi.DoesNotExist,

            Horario.DoesNotExist,

            ValidationError,

            ValueError,

        ) as e:

            messages.error(request, mensaje_error_operacion(e))

    return render(

        request,

        "flexi/flexi_reservar.html",

        {"paquetes": paquetes, "horarios": horarios, "alumno_preseleccionado": alumno_pre},

    )





@staff_operativo_required

@require_http_methods(["POST"])

def flexi_cancelar(request, reserva_id):

    reserva = get_object_or_404(ReservaFlexi, pk=reserva_id)

    try:

        cancelar_reserva_flexi(reserva)

        messages.success(request, "Reserva cancelada.")

    except ValidationError as e:

        messages.error(request, mensaje_error_operacion(e))

    return redirect("flexi_list")


