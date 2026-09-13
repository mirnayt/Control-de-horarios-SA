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
    fecha_nacimiento: date | None = None,
    telefono: str = "",
    whatsapp: str = "",
) -> Alumno:
    """
    Alta de alumno con inscripción única y cargo de cuota en billing.
    El pago de inscripción es operación separada (billing.registrar_pago_inscripcion).
    """
    if tipo not in TipoAlumno.values:
        raise ValidationError({"tipo": f"Tipo inválido: {tipo}"})

    alumno = Alumno(
        nombre_completo=(nombre_completo or "").strip(),
        tipo=tipo,
        estado=EstadoAlumno.ACTIVO,
        tutor=tutor,
        notas=notas,
        fecha_nacimiento=fecha_nacimiento,
        telefono=(telefono or "").strip(),
        whatsapp=(whatsapp or "").strip(),
    )
    alumno.full_clean()
    alumno.save()

    version = ParametroVersion.vigente()
    if version is None:
        raise ValidationError("No hay versión de parámetros vigente.")

    # pagada no es fuente de verdad; se deja False y no se usa en flujos nuevos.
    insc = Inscripcion.objects.create(
        alumno=alumno,
        fecha_original=fecha or timezone.localdate(),
        monto=version.cuota_inscripcion,
        pagada=False,
        parametro_version=version,
    )

    from apps.billing.services import asegurar_linea_inscripcion

    asegurar_linea_inscripcion(
        alumno=alumno,
        monto=insc.monto,
        inscripcion_id=insc.pk,
        version=version,
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
