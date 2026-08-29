from django.contrib import admin
from django.urls import include, path

from apps.accounts import views as accounts_views

urlpatterns = [
    path("admin/", admin.site.urls),
    path("login/", accounts_views.login_view, name="login"),
    path("logout/", accounts_views.logout_view, name="logout"),
    path("", accounts_views.home, name="home"),
    path("alumnos/", include("apps.people.urls")),
    path("horarios/", include("apps.scheduling.urls")),
    path("pagos/", include("apps.billing.urls")),
    path("regular/", include("apps.regular.urls")),
    path("flexi/", include("apps.flexi.urls")),
    path("asistencias/", include("apps.attendance.urls")),
    path("excepciones/", include("apps.exceptions_ops.urls")),
]
