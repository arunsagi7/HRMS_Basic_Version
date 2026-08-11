from django.urls import path
from . import views

urlpatterns = [
    path("login/", views.login_view, name="auth-login"),
    path("logout/", views.logout_view, name="auth-logout"),
    path("me/", views.me_view, name="auth-me"),

    # ── Team Access (employee credential management) ─────────────────────
    path("employees/", views.get_all_employee_credentials, name="employee-credentials-list"),
    path("employees/departments/", views.get_employee_departments, name="employee-departments"),
    path("employees/create/", views.create_employee_credential, name="employee-credentials-create"),
    path("employees/<int:pk>/edit/", views.edit_employee_credential, name="employee-credentials-edit"),
    path("employees/<int:pk>/delete/", views.delete_employee_credential, name="employee-credentials-delete"),
]