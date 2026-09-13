"""Cupo derivado y ocurrencias reales de horario por mes."""

from calendar import monthrange
from datetime import date, timedelta

from django.apps import apps
from django.core.exceptions import ValidationError


class SinCupoError(ValidationError):
    """Sin plazas disponibles en el horario."""


class CalendarService:
    """
    Ocurrencias reales de un Horario en un mes civil (incluye 5ª semana).

    `horario.dia` usa el mismo esquema que date.weekday(): 0=lunes … 6=domingo.
    """

    @classmethod
    def ocurrencias_en_mes(
        cls,
        horario,
        year: int,
        month: int,
        *,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> list[date]:
        """
        Fechas del mes en que cae el día del horario.

        Opcional: filtrar por rango [desde, hasta] (p. ej. alta mid-month).
        """
        if not (1 <= month <= 12):
            raise ValidationError("month debe estar entre 1 y 12.")
        dia_semana = int(horario.dia)
        if not (0 <= dia_semana <= 6):
            raise ValidationError(f"día de horario inválido: {dia_semana}")

        _, last_day = monthrange(year, month)
        mes_inicio = date(year, month, 1)
        mes_fin = date(year, month, last_day)

        inicio = mes_inicio
        fin = mes_fin
        if desde is not None:
            inicio = max(inicio, desde)
        if hasta is not None:
            fin = min(fin, hasta)
        if inicio > fin:
            return []

        # Primer día del rango que coincide con dia_semana.
        delta = (dia_semana - inicio.weekday()) % 7
        cursor = inicio + timedelta(days=delta)
        fechas: list[date] = []
        while cursor <= fin:
            fechas.append(cursor)
            cursor += timedelta(days=7)
        return fechas

    @classmethod
    def contar_ocurrencias(
        cls,
        horario,
        year: int,
        month: int,
        *,
        desde: date | None = None,
        hasta: date | None = None,
    ) -> int:
        return len(
            cls.ocurrencias_en_mes(
                horario, year, month, desde=desde, hasta=hasta
            )
        )

    @classmethod
    def horas_en_mes(
        cls,
        horario,
        year: int,
        month: int,
        *,
        desde: date | None = None,
        hasta: date | None = None,
    ):
        """Horas = (duracion_minutos/60) × ocurrencias reales."""
        from decimal import Decimal

        n = cls.contar_ocurrencias(
            horario, year, month, desde=desde, hasta=hasta
        )
        return (Decimal(horario.duracion_minutos) * Decimal(n)) / Decimal(60)


class CapacityService:
    """
    Calcula cupo disponible por horario / sesión.

    Regular: cuenta AsignacionRegular activas (ocupan cupo recurrente).
    Flexi: solo con fecha_clase — reservas en estado reservada de ESA fecha.
    Sin fecha_clase: Flexi no resta (solo regulares).
    Overrides explícitos siguen siendo útiles en tests.
    """

    @staticmethod
    def count_regulares_activos(horario) -> int:
        try:
            Asignacion = apps.get_model("regular", "AsignacionRegular")
        except LookupError:
            return 0
        qs = Asignacion.objects.filter(horario=horario, activa=True)
        return qs.count()

    @staticmethod
    def count_reservas_flexi_vigentes(horario, fecha_clase: date | None = None) -> int:
        """
        Reservas Flexi que ocupan cupo.
        Sin fecha_clase → 0 (el cupo Flexi es por sesión/fecha).
        """
        if fecha_clase is None:
            return 0
        try:
            Reserva = apps.get_model("flexi", "ReservaFlexi")
        except LookupError:
            return 0
        return Reserva.objects.filter(
            horario=horario,
            estado="reservada",
            fecha_clase=fecha_clase,
        ).count()

    @classmethod
    def cupo_disponible(
        cls,
        horario,
        *,
        fecha_clase: date | None = None,
        regulares_activos: int | None = None,
        reservas_flexi_vigentes: int | None = None,
    ) -> int:
        """
        Con fecha_clase:
          cupo = capacidad − regulares − reservas Flexi de esa fecha.
        Sin fecha_clase:
          cupo = capacidad − regulares (Flexi no acumula).
        """
        if not horario.activo:
            return 0
        reg = (
            regulares_activos
            if regulares_activos is not None
            else cls.count_regulares_activos(horario)
        )
        flex = (
            reservas_flexi_vigentes
            if reservas_flexi_vigentes is not None
            else cls.count_reservas_flexi_vigentes(horario, fecha_clase=fecha_clase)
        )
        return max(0, horario.capacidad - reg - flex)

    @classmethod
    def assert_tiene_cupo(
        cls,
        horario,
        plazas: int = 1,
        *,
        fecha_clase: date | None = None,
        regulares_activos: int | None = None,
        reservas_flexi_vigentes: int | None = None,
    ) -> int:
        """Devuelve cupo si hay plazas; rechaza con SinCupoError si cupo=0 o insuficiente."""
        cupo = cls.cupo_disponible(
            horario,
            fecha_clase=fecha_clase,
            regulares_activos=regulares_activos,
            reservas_flexi_vigentes=reservas_flexi_vigentes,
        )
        if cupo < plazas:
            raise SinCupoError(
                f"Sin cupo disponible en el horario (cupo={cupo}, se requieren {plazas})."
            )
        return cupo
