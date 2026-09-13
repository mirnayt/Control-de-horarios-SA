# Spirit Academia — Etapa 19 (portabilidad) + Railway

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
python manage.py seed_operacion
python manage.py create_ops_users
```

SQLite por defecto (`DJANGO_USE_SQLITE=1` en `.env`). Postgres: `DJANGO_USE_SQLITE=0` + `DATABASE_URL` o vars `POSTGRES_*`.

### Crear usuarios operativos

Login UI en `/login/` requiere grupo `recepcion` o `direccion` (grupos se crean en `migrate`).

```bash
python manage.py create_ops_users
# o con contraseñas explícitas:
# python manage.py create_ops_users --recepcion-password '...' --direccion-password '...' --reset-passwords
```

Por defecto crea `recepcion` / `direccion` (contraseñas `recepcion123` / `direccion123` si no defines `OPS_*_PASSWORD`).

Opcional admin: `python manage.py createsuperuser` (superuser también pasa los checks de rol).

### Ejecutar

```bash
python manage.py runserver
```

Abrir http://127.0.0.1:8000/login/

## Despliegue Railway + PostgreSQL

1. Crear servicio Web desde este repo (root: carpeta `spirit_academia` si el monorepo lo requiere).
2. Añadir plugin **PostgreSQL** y vincularlo (inyecta `DATABASE_URL`).
3. Variables de entorno del servicio:

| Variable | Valor |
|----------|--------|
| `DJANGO_SECRET_KEY` | secreto fuerte |
| `DJANGO_DEBUG` | `0` |
| `DJANGO_USE_SQLITE` | `0` |
| `DJANGO_ALLOWED_HOSTS` | `<servicio>.up.railway.app` (+ dominio custom) |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | `https://<servicio>.up.railway.app` |
| `OPS_RECEPCION_PASSWORD` | contraseña beta recepción |
| `OPS_DIRECCION_PASSWORD` | contraseña beta dirección |

`DATABASE_URL` viene del plugin. Si usas Postgres local sin SSL: `POSTGRES_SSL_REQUIRE=0`.

4. Arranque y release (ya en `Procfile` / `railway.toml`):

```bash
# release
python manage.py migrate --noinput
python manage.py seed_operacion
python manage.py create_ops_users
python manage.py collectstatic --noinput

# start
gunicorn config.wsgi:application --bind 0.0.0.0:$PORT
```

Local sigue con SQLite + `runserver`; no subas `.env` ni `db.sqlite3`.

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

## Migración a PostgreSQL (local o servidor)

1. Instalar y levantar PostgreSQL.
2. Crear base y usuario:
   ```sql
   CREATE USER spirit WITH PASSWORD 'spirit';
   CREATE DATABASE spirit_academia OWNER spirit;
   ```
3. En `.env`:
   ```
   DJANGO_USE_SQLITE=0
   POSTGRES_SSL_REQUIRE=0
   POSTGRES_DB=spirit_academia
   POSTGRES_USER=spirit
   POSTGRES_PASSWORD=<tu-password>
   POSTGRES_HOST=localhost
   POSTGRES_PORT=5432
   ```
   O bien: `DATABASE_URL=postgres://spirit:<password>@localhost:5432/spirit_academia`
4. Aplicar esquema: `python manage.py migrate`
5. Cargar operación: `python manage.py seed_operacion`
6. Usuarios: `python manage.py create_ops_users` o `createsuperuser`.

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
- [ ] `python manage.py seed_operacion`
- [ ] `python manage.py create_ops_users`
- [ ] `python manage.py runserver` → probar `/login/`
- [ ] `python manage.py test apps.accounts apps.params apps.catalog apps.scheduling apps.people apps.enrollment apps.regular apps.billing apps.flexi apps.attendance apps.exceptions_ops apps.core`
- [ ] (Prod / Railway) `DJANGO_USE_SQLITE=0`, `DATABASE_URL`, `DJANGO_DEBUG=0`, `ALLOWED_HOSTS` + `CSRF_TRUSTED_ORIGINS`

## requirements.txt

| Paquete | Uso |
|---------|-----|
| `Django>=5.0,<6` | framework web |
| `psycopg2-binary>=2.9` | driver PostgreSQL |
| `python-dotenv>=1.0` | carga de `.env` |
| `gunicorn>=22.0` | servidor WSGI (Railway) |
| `whitenoise>=6.6` | estáticos en producción |
| `dj-database-url>=2.2` | parsea `DATABASE_URL` (Railway) |
