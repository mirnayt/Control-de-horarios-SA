from django.contrib.auth import authenticate, login, logout
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from apps.accounts.decorators import staff_operativo_required
from apps.accounts.roles import user_is_direccion, user_is_recepcion
from apps.core.ui import (
    clases_hoy,
    flexi_proximos_vencer,
    inscripciones_pendientes,
    periodos_pendientes_con_montos,
    total_monto_pendiente,
)


@require_http_methods(["GET", "POST"])
def login_view(request):
    if request.user.is_authenticated:
        return redirect("home")
    error = ""
    if request.method == "POST":
        user = authenticate(
            request,
            username=request.POST.get("username", ""),
            password=request.POST.get("password", ""),
        )
        if user is not None:
            login(request, user)
            return redirect(request.GET.get("next") or "home")
        error = "Credenciales inválidas."
    return render(request, "accounts/login.html", {"error": error})


@staff_operativo_required
def logout_view(request):
    logout(request)
    return redirect("login")


@staff_operativo_required
def home(request):
    pendientes = periodos_pendientes_con_montos(limit=15)
    insc_pendientes = list(inscripciones_pendientes(limit=15))
    return render(
        request,
        "home.html",
        {
            "es_recepcion": user_is_recepcion(request.user),
            "es_direccion": user_is_direccion(request.user),
            "hoy": timezone.localdate(),
            "clases_hoy": clases_hoy(),
            "pagos_pendientes": pendientes,
            "inscripciones_pendientes": insc_pendientes,
            "total_pendiente": total_monto_pendiente(
                [item["periodo"] for item in pendientes]
            ),
            "flexi_por_vencer": flexi_proximos_vencer(limit=15),
        },
    )
