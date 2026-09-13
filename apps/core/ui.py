"""Consultas y mensajes amigables para formularios operativos (Recepción)."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.models import Q, QuerySet, Sum
from django.http import HttpRequest
from django.utils import timezone

from apps.flexi.models import EstadoPaqueteFlexi, EstadoReservaFlexi, PaqueteFlexi, ReservaFlexi
from apps.people.models import Alumno, EstadoAlumno, TipoAlumno
from apps.regular.models import AsignacionRegular, PeriodoCobroRegular, Regular
from apps.scheduling.models import DiaSemana, Horario, Modalidad, TipoAlumno as TipoHorario
from apps.scheduling.services import CapacityService

ESTADOS_PERIODO_PAGADO = ("pagado_a_tiempo", "pagado_con_recargo")
FLEXI_DIAS_ALERTA_VENCIMIENTO = 14
METODOS_PAGO_UI = (
    ("efectivo", "Efectivo"),
    ("transferencia", "Transferencia"),
    ("link", "Link de pago"),
)


def proxima_fecha_dia(dia_semana: int, *, desde: date | None = None) -> date:
    """Próxima fecha (incl. hoy) que cae en dia_semana (0=lunes … 6=domingo)."""
    desde = desde or timezone.localdate()
    delta = (int(dia_semana) - desde.weekday()) % 7
    return desde + timedelta(days=delta)


def etiqueta_dia(dia_semana: int) -> str:
    return dict(DiaSemana.choices).get(int(dia_semana), str(dia_semana))


def buscar_alumnos(q: str, *, qs: QuerySet[Alumno] | None = None) -> QuerySet[Alumno]:
    """Búsqueda por nombre, ID o teléfono/WhatsApp (alumno o tutor)."""
    base = qs if qs is not None else Alumno.objects.all()
    q = (q or "").strip()
    if not q:
        return base.order_by("nombre_completo")
    filtros = Q(nombre_completo__icontains=q) | Q(telefono__icontains=q) | Q(
        whatsapp__icontains=q
    ) | Q(tutor__telefono__icontains=q)
    if q.isdigit():
        filtros |= Q(pk=int(q))
    return base.filter(filtros).distinct().order_by("nombre_completo")


def sesiones_reservadas_paquete(paquete: PaqueteFlexi) -> int:
    total = (
        ReservaFlexi.objects.filter(
            paquete=paquete, estado=EstadoReservaFlexi.RESERVADA
        ).aggregate(n=Sum("sesiones_usadas"))["n"]
        or 0
    )
    return int(total)


def desglose_paquete_flexi(paquete: PaqueteFlexi) -> dict:
    reservadas = sesiones_reservadas_paquete(paquete)
    usadas = max(0, int(paquete.sesiones_consumidas) - reservadas)
    return {
        "paquete": paquete,
        "compradas": paquete.sesiones_compradas,
        "usadas": usadas,
        "reservadas": reservadas,
        "disponibles": paquete.sesiones_disponibles,
        "fecha_inicio": paquete.fecha_compra,
        "fecha_fin": paquete.fecha_fin,
    }


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
    if horario.tipo_alumno == TipoHorario.AMBOS:
        return True
    if horario.tipo_alumno == TipoHorario.NINO:
        return alumno.tipo == TipoAlumno.NINO
    if horario.tipo_alumno == TipoHorario.ADULTO:
        return alumno.tipo == TipoAlumno.ADULTO
    return True


def horarios_con_cupo(
    modalidad: str,
    *,
    alumno: Alumno | None = None,
    fecha_clase: date | None = None,
    duracion_minutos: int | None = None,
) -> list[Horario]:
    """Horarios activos, de la modalidad indicada, con cupo y compatibles con el alumno."""
    qs = Horario.objects.filter(activo=True).select_related("salon", "profesor")
    resultado: list[Horario] = []
    for h in qs:
        if modalidad not in (h.modalidades or []):
            continue
        if not _horario_compatible_alumno(h, alumno):
            continue
        if fecha_clase is not None and int(h.dia) != fecha_clase.weekday():
            continue
        if duracion_minutos is not None and int(h.duracion_minutos) != duracion_minutos:
            continue
        if CapacityService.cupo_disponible(h, fecha_clase=fecha_clase) <= 0:
            continue
        resultado.append(h)
    return resultado


def horarios_flexi_elegibles(
    *,
    fecha_clase: date,
    alumno: Alumno | None = None,
) -> list[dict]:
    """Horarios Flexi de 180 min para la fecha, con cupo de esa sesión."""
    from apps.flexi.services import DURACION_SESION_FLEXI_MINUTOS

    filas: list[dict] = []
    for h in horarios_con_cupo(
        Modalidad.FLEXI,
        alumno=alumno,
        fecha_clase=fecha_clase,
        duracion_minutos=DURACION_SESION_FLEXI_MINUTOS,
    ):
        filas.append(
            {
                "horario": h,
                "cupo": CapacityService.cupo_disponible(h, fecha_clase=fecha_clase),
            }
        )
    return filas


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


def _fila_ocupacion(horario: Horario, *, fecha_clase=None) -> dict:
    """Ocupación/cupo vía CapacityService (Flexi solo con fecha_clase)."""
    regulares = CapacityService.count_regulares_activos(horario)
    flexi = CapacityService.count_reservas_flexi_vigentes(
        horario, fecha_clase=fecha_clase
    )
    cupo = CapacityService.cupo_disponible(
        horario,
        fecha_clase=fecha_clase,
        regulares_activos=regulares,
        reservas_flexi_vigentes=flexi,
    )
    return {
        "horario": horario,
        "fecha_clase": fecha_clase,
        "regulares": regulares,
        "flexi": flexi,
        "ocupados": regulares + flexi,
        "cupo": cupo,
    }


def clases_hoy() -> list[dict]:
    """Horarios activos del día civil actual con cupo de esa fecha."""
    hoy = timezone.localdate()
    filas: list[dict] = []
    for h in (
        Horario.objects.filter(activo=True, dia=hoy.weekday())
        .select_related("salon", "profesor")
        .order_by("hora_inicio")
    ):
        filas.append(_fila_ocupacion(h, fecha_clase=hoy))
    return filas


def filas_horarios(*, dia: int | None = None, fecha_clase=None) -> list[dict]:
    """Listado de horarios con ocupación; Flexi solo si hay fecha_clase."""
    qs = Horario.objects.select_related("salon", "profesor").order_by(
        "dia", "hora_inicio"
    )
    if dia is not None:
        qs = qs.filter(dia=dia)
    return [_fila_ocupacion(h, fecha_clase=fecha_clase) for h in qs]


def contexto_roster_horario(horario: Horario, *, fecha_clase=None) -> dict:
    """Alumnos Regular del slot + reservas Flexi de la fecha (si hay)."""
    asignaciones = (
        AsignacionRegular.objects.filter(horario=horario, activa=True)
        .select_related("regular__alumno")
        .order_by("regular__alumno__nombre_completo")
    )
    if fecha_clase is not None:
        reservas = (
            ReservaFlexi.objects.filter(
                horario=horario,
                estado=EstadoReservaFlexi.RESERVADA,
                fecha_clase=fecha_clase,
            )
            .select_related("paquete__alumno")
            .order_by("paquete__alumno__nombre_completo")
        )
    else:
        reservas = ReservaFlexi.objects.none()
    fila = _fila_ocupacion(horario, fecha_clase=fecha_clase)
    return {
        **fila,
        "asignaciones": asignaciones,
        "reservas": reservas,
    }


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
    from apps.billing.services import linea_inscripcion_pendiente, monto_pendiente

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
        "inscripcion_pendiente": linea_inscripcion_pendiente(alumno),
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


def inscripciones_pendientes(limit: int = 15):
    """Líneas de inscripción pendientes para dashboard / CTA."""
    from apps.billing.models import ConceptoLinea, EstadoLineaCobro, LineaCobro

    return (
        LineaCobro.objects.filter(
            concepto=ConceptoLinea.INSCRIPCION,
            estado=EstadoLineaCobro.PENDIENTE,
        )
        .select_related("alumno")
        .order_by("-id")[:limit]
    )
