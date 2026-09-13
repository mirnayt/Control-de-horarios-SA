from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import staff_operativo_required
from apps.core.ui import (
    alumnos_flexi_compra,
    alumno_id_preseleccionado,
    desglose_paquete_flexi,
    horarios_flexi_elegibles,
    mensaje_error_operacion,
    METODOS_PAGO_UI,
    paquetes_flexi_reservables,
)
from apps.flexi.models import EstadoReservaFlexi, PaqueteFlexi, ReservaFlexi
from apps.flexi.services import (
    cancelar_reserva_flexi,
    comprar_paquete_flexi,
    reservar_flexi,
)
from apps.people.models import Alumno
from apps.scheduling.models import Horario


@staff_operativo_required
def flexi_list(request):
    paquetes_qs = PaqueteFlexi.objects.select_related("alumno").order_by(
        "-fecha_compra", "-id"
    )[:50]
    paquetes = [desglose_paquete_flexi(p) for p in paquetes_qs]
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
        "metodos": METODOS_PAGO_UI,
    })


@staff_operativo_required
@require_http_methods(["GET", "POST"])
def flexi_reservar(request):
    paquetes = paquetes_flexi_reservables()
    alumno_pre = alumno_id_preseleccionado(request)
    if alumno_pre:
        paquetes = paquetes.filter(alumno_id=alumno_pre)

    fecha_raw = (
        request.POST.get("fecha_clase")
        or request.GET.get("fecha_clase")
        or ""
    ).strip()
    fecha = None
    if fecha_raw:
        try:
            fecha = date.fromisoformat(fecha_raw)
        except ValueError:
            fecha = None

    paquete_sel_id = (
        request.POST.get("paquete_id") or request.GET.get("paquete_id") or ""
    ).strip()
    alumno_para_cupo = None
    if paquete_sel_id.isdigit():
        pkg_sel = paquetes.filter(pk=int(paquete_sel_id)).first()
        if pkg_sel:
            alumno_para_cupo = pkg_sel.alumno

    horarios_filas = []
    if fecha is not None:
        horarios_filas = horarios_flexi_elegibles(
            fecha_clase=fecha, alumno=alumno_para_cupo
        )

    if request.method == "POST":
        try:
            pkg = paquetes.get(pk=request.POST.get("paquete_id"))
            horario = Horario.objects.get(
                pk=request.POST.get("horario_id"), activo=True
            )
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
            if fecha is not None:
                horarios_filas = horarios_flexi_elegibles(
                    fecha_clase=fecha, alumno=alumno_para_cupo
                )

    return render(
        request,
        "flexi/flexi_reservar.html",
        {
            "paquetes": paquetes,
            "horarios_filas": horarios_filas,
            "fecha_clase": fecha_raw,
            "paquete_sel_id": int(paquete_sel_id) if paquete_sel_id.isdigit() else None,
            "alumno_preseleccionado": alumno_pre,
        },
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
