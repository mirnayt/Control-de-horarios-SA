from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import Alumno, EstadoAlumno

ESTADOS_REACTIVABLES = frozenset(
    {
        EstadoAlumno.INACTIVO,
        EstadoAlumno.BAJA_ADMINISTRATIVA,
        EstadoAlumno.BAJA_VOLUNTARIA,
    }
)


@transaction.atomic
def marcar_baja(alumno: Alumno, *, voluntaria: bool = True) -> Alumno:
    """
    Marca baja voluntaria o administrativa (el historial del alumno se conserva).
    Si hay Regular activo, desactiva asignaciones para liberar cupo.
    """
    from apps.regular.models import EstadoRegular, Regular

    alumno.estado = (
        EstadoAlumno.BAJA_VOLUNTARIA if voluntaria else EstadoAlumno.BAJA_ADMINISTRATIVA
    )
    alumno.save(update_fields=["estado", "updated_at"])

    fecha = timezone.localdate()
    estado_reg = (
        EstadoRegular.BAJA_VOLUNTARIA if voluntaria else EstadoRegular.LIBERADO
    )
    for reg in Regular.objects.filter(alumno=alumno, estado=EstadoRegular.ACTIVO):
        for asig in reg.asignaciones.filter(activa=True):
            asig.activa = False
            asig.fecha_fin = fecha
            asig.save(update_fields=["activa", "fecha_fin", "updated_at"])
        reg.estado = estado_reg
        reg.save(update_fields=["estado", "updated_at"])
    return alumno


def cambiar_estado(alumno: Alumno, nuevo_estado: str) -> Alumno:
    if nuevo_estado not in EstadoAlumno.values:
        raise ValidationError(f"Estado inválido: {nuevo_estado}")
    alumno.estado = nuevo_estado
    alumno.full_clean()
    alumno.save(update_fields=["estado", "updated_at"])
    return alumno
