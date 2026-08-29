from apps.accounts.decorators import staff_operativo_required
from apps.scheduling.models import Horario
from apps.scheduling.services import CapacityService
from django.shortcuts import render


@staff_operativo_required
def horarios_list(request):
    filas = []
    for h in Horario.objects.select_related("salon", "profesor").order_by(
        "dia", "hora_inicio"
    ):
        filas.append(
            {
                "horario": h,
                "cupo": CapacityService.cupo_disponible(h),
                "regulares": CapacityService.count_regulares_activos(h),
                "flexi": CapacityService.count_reservas_flexi_vigentes(h),
            }
        )
    return render(request, "scheduling/horarios_list.html", {"filas": filas})
