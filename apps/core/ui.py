"""Consultas y mensajes amigables para formularios operativos (Recepción)."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import QuerySet
from django.http import HttpRequest
from django.utils import timezone

from apps.flexi.models import EstadoPaqueteFlexi, EstadoReservaFlexi, PaqueteFlexi, ReservaFlexi
from apps.people.models import Alumno, EstadoAlumno, TipoAlumno
from apps.regular.models import AsignacionRegular, PeriodoCobroRegular, Regular
from apps.scheduling.models import Horario, Modalidad, TipoAlumno as TipoHorario
from apps.scheduling.services import CapacityService

ESTADOS_PERIODO_PAGADO = ("pagado_a_tiempo", "pagado_con_recargo")
FLEXI_DIAS_ALERTA_VENCIMIENTO = 14


def mensaje_error_operacion(exc: Exception) -> str:
    """Traduce excepciones técnicas a mensajes claros para Recepción."""
    if isinstance(exc, ValidationError):
        if hasattr(exc, "message_dict"):
            partes = []
            for campo, msgs in exc.message_dict.items():
                for m in msgs:
                    partes.append(f"{campo}: {m}" if campo != "__all__" else str(m))
            return " ".join(partes) if partes else str(exc)
        if getattr(exc, "messages", None):
            return " ".join(str(m) for m in exc.messages)
        return str(exc)

    modelos = (
        (Alumno, "Seleccione un alumno activo válido."),
        (PaqueteFlexi, "Seleccione un paquete Flexi activo con saldo y vigencia."),
        (Horario, "Seleccione un horario activo con cupo disponible."),
        (AsignacionRegular, "Seleccione una asignación Regular activa."),
        (ReservaFlexi, "Seleccione una reserva Flexi vigente (estado reservada)."),
    )
    for model, msg in modelos:
        if isinstance(exc, model.DoesNotExist):
            return msg

    if isinstance(exc, ValueError):
        return "Revise los datos del formulario (fechas y números válidos)."

    return str(exc) or "No se pudo completar la operación."


def alumnos_activos() -> QuerySet[Alumno]:
    return Alumno.objects.filter(estado=EstadoAlumno.ACTIVO).order_by("nombre_completo")


def alumnos_flexi_compra() -> QuerySet[Alumno]:
    return alumnos_activos().filter(tipo=TipoAlumno.ADULTO)


def paquetes_flexi_reservables() -> QuerySet[PaqueteFlexi]:
    hoy = timezone.localdate()
    return (
        PaqueteFlexi.objects.filter(
            estado=EstadoPaqueteFlexi.ACTIVO,
            sesiones_disponibles__gt=0,
            fecha_fin__gte=hoy,
        )
        .select_related("alumno")
        .order_by("-fecha_compra", "-id")
    )


def _horario_compatible_alumno(horario: Horario, alumno: Alumno | None) -> bool:
    if alumno is None:
        return True
    if horario.tipo_alumno == TipoHorario.NINO:
        return False
    if horario.tipo_alumno == TipoHorario.ADULTO:
        return alumno.tipo == TipoAlumno.ADULTO
    return True


def horarios_con_cupo(
    modalidad: str,
    *,
    alumno: Alumno | None = None,
) -> list[Horario]:
    """Horarios activos, de la modalidad indicada, con cupo y compatibles con el alumno."""
    qs = Horario.objects.filter(activo=True).select_related("salon", "profesor")
    resultado: list[Horario] = []
    for h in qs:
        if modalidad not in (h.modalidades or []):
            continue
        if not _horario_compatible_alumno(h, alumno):
            continue
        if CapacityService.cupo_disponible(h) <= 0:
            continue
        resultado.append(h)
    return resultado


def asignaciones_regular_activas() -> QuerySet[AsignacionRegular]:
    return (
        AsignacionRegular.objects.filter(activa=True)
        .select_related("regular__alumno", "horario")
        .order_by("regular__alumno__nombre_completo", "horario__dia", "horario__hora_inicio")
    )


def reservas_flexi_programables() -> QuerySet[ReservaFlexi]:
    return (
        ReservaFlexi.objects.filter(estado=EstadoReservaFlexi.RESERVADA)
        .select_related("paquete__alumno", "horario")
        .order_by("fecha_clase", "hora_inicio")
    )


def alumno_id_preseleccionado(request: HttpRequest) -> int | None:
    raw = (request.GET.get("alumno_id") or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def clases_hoy() -> list[dict]:
    """Horarios activos del día civil actual con cupo derivado."""
    dia = timezone.localdate().weekday()
    filas: list[dict] = []
    for h in (
        Horario.objects.filter(activo=True, dia=dia)
        .select_related("salon", "profesor")
        .order_by("hora_inicio")
    ):
        filas.append(
            {
                "horario": h,
                "cupo": CapacityService.cupo_disponible(h),
                "regulares": CapacityService.count_regulares_activos(h),
                "flexi": CapacityService.count_reservas_flexi_vigentes(h),
            }
        )
    return filas


def periodos_pendientes(limit: int = 20) -> QuerySet[PeriodoCobroRegular]:
    return (
        PeriodoCobroRegular.objects.exclude(estado__in=ESTADOS_PERIODO_PAGADO)
        .select_related("regular__alumno")
        .order_by("-anio", "-mes")[:limit]
    )


def total_monto_pendiente(periodos: QuerySet[PeriodoCobroRegular] | list) -> Decimal:
    """Suma de montos pendientes para dashboard / KPIs."""
    from apps.billing.services import monto_pendiente

    return sum((monto_pendiente(p) for p in periodos), Decimal("0.00"))


def periodos_pendientes_con_montos(limit: int = 50) -> list[dict]:
    """Periodos impagos con monto total y líneas para listados UI."""
    from apps.billing.services import lineas_pendientes, monto_pendiente

    resultado: list[dict] = []
    for periodo in periodos_pendientes(limit=limit):
        resultado.append(
            {
                "periodo": periodo,
                "monto": monto_pendiente(periodo),
                "lineas": lineas_pendientes(periodo),
            }
        )
    return resultado


def flexi_proximos_vencer(
    *,
    dias: int = FLEXI_DIAS_ALERTA_VENCIMIENTO,
    limit: int = 20,
) -> QuerySet[PaqueteFlexi]:
    hoy = timezone.localdate()
    return (
        PaqueteFlexi.objects.filter(
            estado=EstadoPaqueteFlexi.ACTIVO,
            sesiones_disponibles__gt=0,
            fecha_fin__gte=hoy,
            fecha_fin__lte=hoy + timedelta(days=dias),
        )
        .select_related("alumno")
        .order_by("fecha_fin")[:limit]
    )


def contexto_ficha_alumno(alumno: Alumno) -> dict:
    """Datos agregados para la ficha operativa del alumno."""
    from apps.attendance.models import Asistencia
    from apps.billing.models import Pago
    from apps.billing.services import monto_pendiente

    periodos_qs = (
        PeriodoCobroRegular.objects.filter(regular__alumno=alumno)
        .exclude(estado__in=ESTADOS_PERIODO_PAGADO)
        .select_related("regular")
        .order_by("-anio", "-mes")
    )
    return {
        "regulares": Regular.objects.filter(alumno=alumno).prefetch_related(
            "asignaciones__horario"
        ),
        "periodos_pendientes": [
            {"periodo": p, "monto": monto_pendiente(p)} for p in periodos_qs
        ],
        "paquetes_flexi": PaqueteFlexi.objects.filter(alumno=alumno).order_by(
            "-fecha_compra", "-id"
        )[:10],
        "reservas_flexi": ReservaFlexi.objects.filter(
            paquete__alumno=alumno,
            estado=EstadoReservaFlexi.RESERVADA,
        )
        .select_related("horario", "paquete")
        .order_by("fecha_clase")[:10],
        "asistencias": Asistencia.objects.filter(alumno=alumno)
        .select_related("horario")
        .order_by("-fecha", "-id")[:15],
        "pagos": Pago.objects.filter(alumno=alumno)
        .select_related("metodo")
        .order_by("-fecha_pago", "-id")[:10],
    }
