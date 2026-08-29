from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import staff_operativo_required
from apps.core.ui import mensaje_error_operacion, periodos_pendientes_con_montos
from apps.billing.models import Pago
from apps.billing.services import lineas_pendientes, monto_pendiente, registrar_pago_periodo
from apps.regular.models import PeriodoCobroRegular


@staff_operativo_required
def pagos_list(request):
    pagos = Pago.objects.select_related("alumno", "metodo").order_by(
        "-fecha_pago", "-id"
    )[:100]
    return render(
        request,
        "billing/pagos_list.html",
        {"pagos": pagos, "pendientes": periodos_pendientes_con_montos(limit=50)},
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
    return render(
        request,
        "billing/pago_periodo.html",
        {
            "periodo": periodo,
            "monto": monto_pendiente(periodo),
            "lineas": lineas_pendientes(periodo),
        },
    )
