from datetime import date

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import staff_operativo_required
from apps.catalog.models import Sucursal
from apps.core.ui import buscar_alumnos, contexto_ficha_alumno, mensaje_error_operacion, serializar_alumno
from apps.enrollment.services import alta_alumno, reactivar_alumno
from apps.people.models import Alumno, EstadoAlumno, TipoAlumno, Tutor
from apps.people.services import marcar_baja


@staff_operativo_required
def alumnos_list(request):
    qs = Alumno.objects.all().select_related("tutor", "sucursal")
    q = (request.GET.get("q") or "").strip()
    if q:
        qs = buscar_alumnos(q, qs=qs)
    tipo = (request.GET.get("tipo") or "").strip()
    if tipo in TipoAlumno.values:
        qs = qs.filter(tipo=tipo)
    estado = (request.GET.get("estado") or "").strip()
    if estado in EstadoAlumno.values:
        qs = qs.filter(estado=estado)
    return render(
        request,
        "people/alumnos_list.html",
        {
            "alumnos": qs,
            "q": q,
            "tipo": tipo,
            "estado": estado,
            "tipos": TipoAlumno.choices,
            "estados": EstadoAlumno.choices,
        },
    )


@staff_operativo_required
def alumnos_buscar(request):
    q = (request.GET.get("q") or "").strip()
    activos = (request.GET.get("activos") or "") == "1"
    adultos = (request.GET.get("adultos") or "") == "1"
    qs = Alumno.objects.select_related("sucursal", "tutor")
    if activos:
        qs = qs.filter(estado=EstadoAlumno.ACTIVO)
    if adultos:
        qs = qs.filter(tipo=TipoAlumno.ADULTO)
    if q:
        qs = buscar_alumnos(q, qs=qs)
    else:
        qs = qs.none()
    return JsonResponse({"results": [serializar_alumno(a) for a in qs[:15]]})


@staff_operativo_required
@require_http_methods(["GET", "POST"])
def alumno_alta(request):
    if request.method == "POST":
        try:
            tipo = request.POST.get("tipo", "")
            tutor = None
            if tipo == TipoAlumno.NINO:
                tutor_nombre = (request.POST.get("tutor_nombre") or "").strip()
                if not tutor_nombre:
                    raise ValidationError(
                        {"tutor_nombre": "Para menores indique el contacto del tutor."}
                    )
                tutor = Tutor.objects.create(
                    nombre_completo=tutor_nombre,
                    telefono=(request.POST.get("tutor_telefono") or "").strip(),
                    parentesco=(request.POST.get("tutor_parentesco") or "").strip(),
                )
            fn_raw = (request.POST.get("fecha_nacimiento") or "").strip()
            fecha_nacimiento = date.fromisoformat(fn_raw) if fn_raw else None
            sucursal_id = (request.POST.get("sucursal_id") or "").strip()
            sucursal = None
            if sucursal_id.isdigit():
                sucursal = Sucursal.objects.filter(pk=int(sucursal_id), activo=True).first()
            alumno = alta_alumno(
                nombre_completo=request.POST.get("nombre_completo", ""),
                tipo=tipo,
                notas=request.POST.get("notas", ""),
                fecha_nacimiento=fecha_nacimiento,
                telefono=request.POST.get("telefono", ""),
                whatsapp=request.POST.get("whatsapp", ""),
                tutor=tutor,
                sucursal=sucursal,
                requiere_factura=request.POST.get("requiere_factura") == "1",
                pack_intro=request.POST.get("pack_intro") == "1",
            )
            messages.success(request, f"Alumno creado: {alumno}")
            return redirect("alumno_detail", pk=alumno.pk)
        except (ValidationError, ValueError) as e:
            messages.error(request, mensaje_error_operacion(e))
    return render(
        request,
        "people/alumno_alta.html",
        {
            "tipos": TipoAlumno.choices,
            "sucursales": Sucursal.objects.filter(activo=True).order_by("nombre"),
        },
    )


@staff_operativo_required
@require_http_methods(["GET", "POST"])
def alumno_detail(request, pk):
    alumno = get_object_or_404(Alumno.objects.select_related("tutor"), pk=pk)
    if request.method == "POST":
        accion = request.POST.get("accion")
        try:
            if accion == "baja_voluntaria":
                marcar_baja(alumno, voluntaria=True)
                messages.success(request, "Baja voluntaria registrada.")
            elif accion == "baja_administrativa":
                marcar_baja(alumno, voluntaria=False)
                messages.success(request, "Baja administrativa registrada.")
            elif accion == "reactivar":
                reactivar_alumno(alumno)
                messages.success(request, "Alumno reactivado.")
            alumno.refresh_from_db()
        except ValidationError as e:
            messages.error(request, mensaje_error_operacion(e))
    ctx = {"alumno": alumno}
    ctx.update(contexto_ficha_alumno(alumno))
    return render(request, "people/alumno_detail.html", ctx)
