from datetime import date

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import staff_operativo_required
from apps.accounts.roles import user_is_direccion
from apps.attendance.models import Asistencia, Compensacion, EstadoAsistencia, EstadoCompensacion
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
    etiqueta_dia,
    mensaje_error_operacion,
    proxima_fecha_dia,
    reservas_flexi_programables,
)
from apps.flexi.models import ReservaFlexi
from apps.people.models import Alumno
from apps.regular.models import AsignacionRegular
from apps.scheduling.models import Horario

from decimal import Decimal, InvalidOperation


def _asignaciones_con_fecha(asignaciones):
    hoy = timezone.localdate()
    filas = []
    for a in asignaciones:
        proxima = proxima_fecha_dia(a.horario.dia, desde=hoy)
        filas.append(
            {
                "asignacion": a,
                "dia_label": etiqueta_dia(a.horario.dia),
                "proxima_fecha": proxima.isoformat(),
            }
        )
    return filas


@staff_operativo_required
def asistencias_list(request):
    qs = Asistencia.objects.select_related(
        "alumno", "horario", "horario__profesor"
    ).order_by("-fecha", "-id")

    fecha_raw = (request.GET.get("fecha") or "").strip()
    if fecha_raw:
        try:
            qs = qs.filter(fecha=date.fromisoformat(fecha_raw))
        except ValueError:
            pass

    alumno_q = (request.GET.get("alumno") or "").strip()
    if alumno_q:
        if alumno_q.isdigit():
            qs = qs.filter(alumno_id=int(alumno_q))
        else:
            qs = qs.filter(alumno__nombre_completo__icontains=alumno_q)

    horario_id = (request.GET.get("horario_id") or "").strip()
    if horario_id.isdigit():
        qs = qs.filter(horario_id=int(horario_id))

    profesor_id = (request.GET.get("profesor_id") or "").strip()
    if profesor_id.isdigit():
        qs = qs.filter(horario__profesor_id=int(profesor_id))

    estado = (request.GET.get("estado") or "").strip()
    if estado and estado in EstadoAsistencia.values:
        qs = qs.filter(estado=estado)

    from apps.catalog.models import Profesor

    return render(
        request,
        "attendance/asistencias_list.html",
        {
            "asistencias": qs[:200],
            "estados": EstadoAsistencia.choices,
            "horarios": Horario.objects.filter(activo=True).order_by(
                "dia", "hora_inicio"
            ),
            "profesores": Profesor.objects.filter(activo=True).order_by("nombre"),
            "filtros": {
                "fecha": fecha_raw,
                "alumno": alumno_q,
                "horario_id": horario_id,
                "profesor_id": profesor_id,
                "estado": estado,
            },
        },
    )


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

    filas_asig = _asignaciones_con_fecha(asignaciones)
    fecha_sugerida = filas_asig[0]["proxima_fecha"] if filas_asig else timezone.localdate().isoformat()

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
            "filas_asignaciones": filas_asig,
            "reservas": reservas,
            "alumno_preseleccionado": alumno_pre,
            "modalidad_preseleccionada": modalidad_preseleccionada,
            "fecha_sugerida": fecha_sugerida,
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
