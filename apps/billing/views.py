from decimal import Decimal

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import staff_operativo_required
from apps.billing.models import EstadoLineaCobro, LineaCobro, Pago
from apps.billing.services import (
    linea_inscripcion_pendiente,
    lineas_pendientes,
    monto_pendiente,
    registrar_pago_inscripcion,
    registrar_pago_periodo,
)
from apps.core.ui import (
    METODOS_PAGO_UI,
    buscar_alumnos,
    mensaje_error_operacion,
    periodos_pendientes_con_montos,
)
from apps.people.models import Alumno
from apps.regular.models import PeriodoCobroRegular


def _cargos_alumno(alumno: Alumno) -> dict:
    insc = linea_inscripcion_pendiente(alumno)
    periodos = []
    for periodo in PeriodoCobroRegular.objects.filter(
        regular__alumno=alumno
    ).exclude(estado__in=("pagado_a_tiempo", "pagado_con_recargo")).select_related(
        "regular"
    ).order_by("-anio", "-mes"):
        lineas = lineas_pendientes(periodo)
        esperado = sum((ln.monto for ln in lineas), Decimal("0.00"))
        pagado = (
            LineaCobro.objects.filter(
                periodo=periodo, estado=EstadoLineaCobro.PAGADA
            ).aggregate(t=Sum("monto"))["t"]
            or Decimal("0.00")
        )
        periodos.append(
            {
                "periodo": periodo,
                "lineas": lineas,
                "esperado": esperado + pagado,
                "pagado": pagado,
                "saldo": monto_pendiente(periodo),
            }
        )
    otras = LineaCobro.objects.filter(
        alumno=alumno,
        estado=EstadoLineaCobro.PENDIENTE,
        periodo__isnull=True,
    ).exclude(concepto="inscripcion")
    return {
        "inscripcion": insc,
        "periodos": periodos,
        "otras": list(otras),
    }


@staff_operativo_required
def pagos_list(request):
    pagos = Pago.objects.select_related("alumno", "metodo").order_by(
        "-fecha_pago", "-id"
    )[:100]
    q = (request.GET.get("q") or "").strip()
    alumno_id = (request.GET.get("alumno_id") or "").strip()
    alumno = None
    resultados = None
    cargos = None

    if alumno_id.isdigit():
        alumno = Alumno.objects.filter(pk=int(alumno_id)).first()
    elif q:
        resultados = list(buscar_alumnos(q)[:20])
        if len(resultados) == 1:
            alumno = resultados[0]
            resultados = None

    if alumno is not None:
        cargos = _cargos_alumno(alumno)

    return render(
        request,
        "billing/pagos_list.html",
        {
            "pagos": pagos,
            "pendientes": periodos_pendientes_con_montos(limit=50),
            "q": q,
            "alumno": alumno,
            "resultados": resultados,
            "cargos": cargos,
            "metodos": METODOS_PAGO_UI,
        },
    )


@staff_operativo_required
@require_http_methods(["GET", "POST"])
def pago_periodo(request, periodo_id):
    periodo = get_object_or_404(
        PeriodoCobroRegular.objects.select_related("regular__alumno"),
        pk=periodo_id,
    )
    if request.method == "POST":
        try:
            pago = registrar_pago_periodo(
                periodo=periodo,
                metodo_codigo=request.POST.get("metodo_codigo", ""),
                referencia=request.POST.get("referencia", ""),
                notas=request.POST.get("notas", ""),
            )
            messages.success(request, f"Pago registrado: ${pago.monto_total}")
            return redirect("pagos_list")
        except ValidationError as e:
            messages.error(request, mensaje_error_operacion(e))
    lineas = lineas_pendientes(periodo)
    saldo = monto_pendiente(periodo)
    pagado = (
        LineaCobro.objects.filter(
            periodo=periodo, estado=EstadoLineaCobro.PAGADA
        ).aggregate(t=Sum("monto"))["t"]
        or Decimal("0.00")
    )
    return render(
        request,
        "billing/pago_periodo.html",
        {
            "periodo": periodo,
            "monto": saldo,
            "lineas": lineas,
            "esperado": saldo + pagado,
            "pagado": pagado,
            "saldo": saldo,
            "metodos": METODOS_PAGO_UI,
        },
    )


@staff_operativo_required
@require_http_methods(["GET", "POST"])
def pago_inscripcion(request, alumno_id):
    alumno = get_object_or_404(Alumno, pk=alumno_id)
    linea = linea_inscripcion_pendiente(alumno)
    if linea is None:
        messages.error(request, "No hay inscripción pendiente para este alumno.")
        return redirect(f"{reverse('pagos_list')}?alumno_id={alumno.pk}")
    if request.method == "POST":
        try:
            pago = registrar_pago_inscripcion(
                alumno=alumno,
                metodo_codigo=request.POST.get("metodo_codigo", ""),
                referencia=request.POST.get("referencia", ""),
                notas=request.POST.get("notas", ""),
            )
            messages.success(request, f"Inscripción pagada: ${pago.monto_total}")
            return redirect(f"{reverse('pagos_list')}?alumno_id={alumno.pk}")
        except ValidationError as e:
            messages.error(request, mensaje_error_operacion(e))
    return render(
        request,
        "billing/pago_inscripcion.html",
        {
            "alumno": alumno,
            "linea": linea,
            "metodos": METODOS_PAGO_UI,
        },
    )
