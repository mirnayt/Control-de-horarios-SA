from datetime import datetime

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import TimeStampedModel


class TipoAlumno(models.TextChoices):
    ADULTO = "adulto", "Adulto"
    NINO = "nino", "Niño"
    AMBOS = "ambos", "Adulto y niño"


class Modalidad(models.TextChoices):
    REGULAR = "regular", "Regular"
    FLEXI = "flexi", "Flexi"
    SUELTA = "suelta", "Clase suelta"


class DiaSemana(models.IntegerChoices):
    LUNES = 0, "Lunes"
    MARTES = 1, "Martes"
    MIERCOLES = 2, "Miércoles"
    JUEVES = 3, "Jueves"
    VIERNES = 4, "Viernes"
    SABADO = 5, "Sábado"
    DOMINGO = 6, "Domingo"


class Horario(TimeStampedModel):
    """Slot semanal configurable (capacidad y cupo derivado vía CapacityService)."""

    dia = models.PositiveSmallIntegerField(choices=DiaSemana.choices)
    hora_inicio = models.TimeField()
    hora_fin = models.TimeField()
    duracion_minutos = models.PositiveSmallIntegerField(
        help_text="Duración de la clase en minutos.",
    )
    capacidad = models.PositiveSmallIntegerField()
    tipo_alumno = models.CharField(max_length=16, choices=TipoAlumno.choices)
    modalidades = models.JSONField(
        default=list,
        help_text='Lista de modalidades: "regular", "flexi", "suelta".',
    )
    activo = models.BooleanField(default=True)
    salon = models.ForeignKey(
        "catalog.Salon",
        on_delete=models.PROTECT,
        related_name="horarios",
    )
    profesor = models.ForeignKey(
        "catalog.Profesor",
        on_delete=models.PROTECT,
        related_name="horarios",
    )

    class Meta:
        ordering = ["dia", "hora_inicio"]
        verbose_name = "Horario"
        verbose_name_plural = "Horarios"

    def __str__(self):
        dia = self.get_dia_display()
        return f"{dia} {self.hora_inicio:%H:%M}-{self.hora_fin:%H:%M} ({self.salon})"

    def clean(self):
        errors = {}
        if self.capacidad is not None and self.capacidad < 1:
            errors["capacidad"] = "La capacidad debe ser al menos 1."
        if self.hora_inicio and self.hora_fin and self.hora_fin <= self.hora_inicio:
            errors["hora_fin"] = "hora_fin debe ser posterior a hora_inicio."
        if self.hora_inicio and self.hora_fin and self.duracion_minutos:
            delta = datetime.combine(datetime.min, self.hora_fin) - datetime.combine(
                datetime.min, self.hora_inicio
            )
            expected = int(delta.total_seconds() // 60)
            if expected != self.duracion_minutos:
                errors["duracion_minutos"] = (
                    f"Debe coincidir con el intervalo inicio–fin ({expected} min)."
                )
        modalidades = self.modalidades or []
        if not isinstance(modalidades, list) or not modalidades:
            errors["modalidades"] = "Indica al menos una modalidad."
        else:
            valid = {c.value for c in Modalidad}
            invalid = [m for m in modalidades if m not in valid]
            if invalid:
                errors["modalidades"] = f"Modalidades inválidas: {invalid}."
            if Modalidad.FLEXI in modalidades and self.tipo_alumno == TipoAlumno.NINO:
                errors["modalidades"] = "Flexi no aplica a horarios solo niño."
            if Modalidad.SUELTA in modalidades and self.tipo_alumno == TipoAlumno.NINO:
                errors["modalidades"] = "Clase suelta no aplica a horarios solo niño."
        if errors:
            raise ValidationError(errors)

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)
