from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.params.models import ParametroVersion
from apps.people.models import Alumno, EstadoAlumno, TipoAlumno, Tutor
from apps.people.services import ESTADOS_REACTIVABLES

from .models import Inscripcion


def cuota_inscripcion_vigente(*, en=None) -> Decimal:
    version = ParametroVersion.vigente(en=en)
    if version is None:
        raise ValidationError("No hay versión de parámetros vigente.")
    return version.cuota_inscripcion


def requiere_pago_inscripcion(alumno: Alumno) -> bool:
    """False si ya existe inscripción histórica (p. ej. regreso post-baja)."""
    return not Inscripcion.objects.filter(alumno=alumno).exists()


@transaction.atomic
def alta_alumno(
    *,
    nombre_completo: str,
    tipo: str,
    tutor: Tutor | None = None,
    fecha: date | None = None,
    notas: str = "",
) -> Alumno:
    """Alta de alumno con inscripción única y cuota vigente ($500 por defecto)."""
    if tipo not in TipoAlumno.values:
        raise ValidationError({"tipo": f"Tipo inválido: {tipo}"})

    alumno = Alumno(
        nombre_completo=(nombre_completo or "").strip(),
        tipo=tipo,
        estado=EstadoAlumno.ACTIVO,
        tutor=tutor,
        notas=notas,
    )
    alumno.full_clean()
    alumno.save()

    version = ParametroVersion.vigente()
    if version is None:
        raise ValidationError("No hay versión de parámetros vigente.")

    Inscripcion.objects.create(
        alumno=alumno,
        fecha_original=fecha or timezone.localdate(),
        monto=version.cuota_inscripcion,
        pagada=True,
        parametro_version=version,
    )
    return alumno


@transaction.atomic
def reactivar_alumno(alumno: Alumno) -> Alumno:
    """
    Regreso post-baja: vuelve a activo sin nueva inscripción ni nuevo cobro.
    """
    if alumno.estado not in ESTADOS_REACTIVABLES:
        raise ValidationError(
            f"No se puede reactivar desde estado '{alumno.estado}'."
        )
    if requiere_pago_inscripcion(alumno):
        raise ValidationError(
            "El alumno no tiene inscripción histórica; usar alta_alumno."
        )

    alumno.estado = EstadoAlumno.ACTIVO
    alumno.save(update_fields=["estado", "updated_at"])
    return alumno
