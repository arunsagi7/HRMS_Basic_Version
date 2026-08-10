# tasks/urls.py

from django.urls import path
from . import views

urlpatterns = [
    path("get_all_tasks/", views.get_all_tasks, name="task-list"),
    path("create_task/", views.create_task, name="task-create"),
    path("assign_task/<int:pk>/", views.assign_task, name="task-assign"),
    path("get_all_departments/", views.get_all_departments, name="task-departments"),
    path("get_all_employees/", views.get_all_employees, name="task-employees"),
    path("get_priority_choices/", views.get_priority_choices, name="task-priorities"),

    # ── Timer flow ─────────────────────────────────────────────────────────
    path("my_active_session/", views.get_active_session, name="task-active-session"),
    path("<int:pk>/start/", views.start_task, name="task-start"),
    path("<int:pk>/pause/", views.pause_task, name="task-pause"),
    path("<int:pk>/resume/", views.resume_task, name="task-resume"),
    path("<int:pk>/submit/", views.submit_task, name="task-submit"),
    path("<int:pk>/sessions/", views.get_task_sessions, name="task-sessions"),

    # ── Admin review queue ─────────────────────────────────────────────────
    path("review_tasks/", views.get_review_tasks, name="task-review-tasks"),
    path("<int:pk>/review/start/", views.start_review, name="task-review-start"),
    path("<int:pk>/review/approve/", views.approve_task, name="task-review-approve"),
    path("<int:pk>/review/rework/", views.request_rework, name="task-review-rework"),

    # ── Time corrections ─── NOTE: these use "sessions/" and "corrections/",
    # NOT "tasks/" — make sure whatever include() maps this urls.py doesn't
    # prefix everything with /api/tasks/, or these paths won't match
    # /api/sessions/... and /api/corrections/... at all.
    path("sessions/<int:session_id>/correction-request/", views.request_correction, name="correction-request"),
    path("corrections/pending/", views.get_pending_corrections, name="correction-pending"),
    path("corrections/<int:pk>/decision/", views.decide_correction, name="correction-decision"),

    # ── Hold / Cancel / Archive ──────────────────────────────────────────
    path("<int:pk>/hold/", views.hold_task, name="task-hold"),
    path("<int:pk>/release_hold/", views.release_hold, name="task-release-hold"),
    path("<int:pk>/cancel/", views.cancel_task, name="task-cancel"),
    path("<int:pk>/archive/", views.archive_task, name="task-archive"),
    
    
    # tasks/urls.py — add these

    path("corrections/approved/", views.get_approved_corrections, name="correction-approved"),
    path("corrections/rejected/", views.get_rejected_corrections, name="correction-rejected"),
    path("activity/", views.get_all_activity, name="activity-all"),
    path("my_activity/", views.get_my_activity, name="activity-employee"),
    path("reports/admin/", views.get_admin_reports, name="reports-admin"),
    path("reports/employee/", views.get_my_reports, name="reports-employee"),
    
    # Delete task
    path("<int:pk>/delete/", views.delete_task, name="task-delete"),
    
    path("tl_tasks/", views.get_tl_tasks, name="tl-tasks"),
]