# Spirit Academia — Etapa 19 (portabilidad)

## Setup limpio desde cero

Requisitos: **Python 3.11+**, pip.

```bash
cd spirit_academia
python -m venv .venv

# Windows
.venv\Scripts\activate
# Linux / macOS
# source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env          # Windows: copy .env.example .env
python manage.py migrate
python manage.py seed_params
```

SQLite por defecto (`DJANGO_USE_SQLITE=1` en `.env`). Postgres: `DJANGO_USE_SQLITE=0` + vars `POSTGRES_*`.

### Crear usuarios operativos

Login UI en `/login/` requiere grupo `recepcion` o `direccion` (grupos se crean en `migrate`).

```bash
python manage.py shell
```

```python
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from apps.accounts.roles import ROLE_RECEPCION, ROLE_DIRECCION, ensure_roles

ensure_roles()
User = get_user_model()

u, _ = User.objects.get_or_create(username="recepcion")
u.set_password("recepcion123")
u.save()
u.groups.set([Group.objects.get(name=ROLE_RECEPCION)])

u, _ = User.objects.get_or_create(username="direccion")
u.set_password("direccion123")
u.save()
u.groups.set([Group.objects.get(name=ROLE_DIRECCION)])
```

Opcional admin: `python manage.py createsuperuser` (superuser también pasa los checks de rol).

### Ejecutar

```bash
python manage.py runserver
```

Abrir http://127.0.0.1:8000/login/

## Roles

- **Recepción**: operación diaria (alumnos, horarios, pagos, Regular, Flexi, asistencias, compensaciones reposición, solicitudes de excepción).
- **Dirección**: además autoriza excepciones y reembolsos.

## Pantallas

| Ruta | Módulo |
|------|--------|
| `/alumnos/` | Alumnos |
| `/horarios/` | Horarios / cupos |
| `/pagos/` | Pagos |
| `/regular/` | Regular |
| `/flexi/` | Flexi / reservas |
| `/asistencias/` | Asistencias |
| `/asistencias/compensaciones/` | Compensaciones |
| `/excepciones/` | Excepciones |

Las vistas delegan a services existentes (sin duplicar reglas).

## Cobranza / vencimiento Flexi

```bash
python manage.py run_cobranza_diaria
python manage.py run_vencimiento_flexi
```

TZ: `America/Mexico_City`.

## Tests

```bash
python manage.py test apps.accounts apps.params apps.catalog apps.scheduling apps.people apps.enrollment apps.regular apps.billing apps.flexi apps.attendance apps.exceptions_ops apps.core
```

E2E integral MVP: `apps.core.tests_e2e` (flujos 1–8).

## Archivos que NO van al repo

| Archivo / carpeta | Motivo |
|-------------------|--------|
| `.env` | secretos y credenciales |
| `db.sqlite3`, `*.sqlite3` | datos locales de desarrollo |
| `.venv/` | entorno virtual |
| `staticfiles/`, `media/`, `local/`, `data/`, `backups/` | artefactos generados |

Solo se versiona `.env.example` (plantilla sin secretos reales).

## Migración futura a PostgreSQL

El proyecto ya soporta Postgres vía variables de entorno; no requiere cambios de código.

1. Instalar y levantar PostgreSQL (local o servidor).
2. Crear base y usuario:
   ```sql
   CREATE USER spirit WITH PASSWORD 'spirit';
   CREATE DATABASE spirit_academia OWNER spirit;
   ```
3. En `.env`:
   ```
   DJANGO_USE_SQLITE=0
   POSTGRES_DB=spirit_academia
   POSTGRES_USER=spirit
   POSTGRES_PASSWORD=<tu-password>
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   ```
4. Aplicar esquema: `python manage.py migrate`
5. Cargar datos iniciales: `python manage.py seed_params`
6. Recrear usuarios operativos (ver arriba) o `createsuperuser`.

**Migrar datos existentes desde SQLite** (opcional, cuando haya datos reales):

```bash
# Con SQLite activo, exportar
python manage.py dumpdata --natural-foreign --natural-primary -e contenttypes -e auth.Permission -o backup.json

# Cambiar .env a Postgres, migrate, luego importar
python manage.py loaddata backup.json
```

Verificar: `python manage.py check` y suite de tests completa.

## Checklist: mover a otra computadora

- [ ] Clonar / copiar repo (sin `.env`, `db.sqlite3`, `.venv`)
- [ ] Instalar Python 3.11+
- [ ] `python -m venv .venv` y activar
- [ ] `pip install -r requirements.txt`
- [ ] `copy .env.example .env` (Windows) o `cp .env.example .env`
- [ ] Editar `.env`: `DJANGO_SECRET_KEY` único, `DJANGO_DEBUG=1` en dev
- [ ] `python manage.py migrate`
- [ ] `python manage.py seed_params`
- [ ] Crear usuarios recepción / dirección (shell arriba)
- [ ] `python manage.py runserver` → probar `/login/`
- [ ] `python manage.py test apps.accounts apps.params apps.catalog apps.scheduling apps.people apps.enrollment apps.regular apps.billing apps.flexi apps.attendance apps.exceptions_ops apps.core`
- [ ] (Prod) `DJANGO_USE_SQLITE=0`, Postgres configurado, `DJANGO_DEBUG=0`, `ALLOWED_HOSTS` correcto

## requirements.txt

| Paquete | Uso |
|---------|-----|
| `Django>=5.0,<6` | framework web |
| `psycopg2-binary>=2.9` | driver PostgreSQL (listo para migración) |
| `python-dotenv>=1.0` | carga de `.env` |
