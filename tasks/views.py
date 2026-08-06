# tasks/views.py

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

from accounts.models import Employee
from .models import Task, TimerSession
from .serializers import (
    TaskListSerializer, TaskCreateSerializer, TaskAssignSerializer,
    TimerSessionSerializer, TaskSubmitSerializer, ReviewApproveSerializer, ReviewReworkSerializer
)
from .activity import ActivityLog, log_activity

# tasks/views.py — add this import at the top

from django.db import models as db_models  # aliased so it doesn't clash with the `models` you already reference via Task etc.
from .serializers import CorrectionListSerializer
from .models import CorrectionRequest  # already imported lower down in your file — just make sure it's available at module level

def _is_admin(request):
    # request.user is a SimplePrincipal wrapping either Admin or Employee
    # (see accounts/authentication.py) — .role is "admin" or "employee".
    return getattr(request.user, "role", None) == "admin"


def _current_employee(request):
    """Returns the logged-in Employee, or None if the caller isn't an employee."""
    if getattr(request.user, "role", None) != "employee":
        return None
    return request.user.instance


# ── Task CRUD (unchanged from before) ────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_all_tasks(request):
    """
    GET /api/tasks/get_all_tasks/
    Everyone — admin and employee alike — sees every task now. Employees
    are no longer filtered to their own assigned tasks; the frontend
    renders read-only vs. editable based on whether assigned_to matches
    the caller. Actual edit permission is still enforced server-side in
    start_task/pause_task/resume_task/submit_task (assigned_to_id check),
    so this list-only change doesn't open up any write access.
    """
    tasks = Task.objects.all()
    if request.query_params.get("include_archived") != "true":
        tasks = tasks.exclude(task_status=Task.Status.ARCHIVED)

    return Response(TaskListSerializer(tasks, many=True).data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def create_task(request):
    """
    POST /api/tasks/create_task/
    body: { "task_name": "...", "task_details": "..." }
    Admin-only. Creates the task unassigned (assigned_to = null,
    task_status = Not Started).
    """
    if not _is_admin(request):
        return Response({"detail": "Only admins can create tasks."}, status=status.HTTP_403_FORBIDDEN)

    serializer = TaskCreateSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    task = serializer.save(assigned_by=request.user.instance)
    return Response(TaskListSerializer(task).data, status=status.HTTP_201_CREATED)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def assign_task(request, pk):
    """
    PATCH /api/tasks/assign_task/<id>/
    Admin-only. Same endpoint handles first assignment and reassignment.
    """
    if not _is_admin(request):
        return Response({"detail": "Only admins can assign tasks."}, status=status.HTTP_403_FORBIDDEN)

    task = get_object_or_404(Task, pk=pk)
    serializer = TaskAssignSerializer(task, data=request.data, partial=True)
    serializer.is_valid(raise_exception=True)
    task = serializer.save(task_status=Task.Status.NOT_STARTED)
    
    return Response(TaskListSerializer(task).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_all_departments(request):
    """GET /api/tasks/get_all_departments/"""
    departments = (
        Employee.objects.exclude(department="")
        .values_list("department", flat=True)
        .distinct()
        .order_by("department")
    )
    return Response([{"id": name, "name": name} for name in departments])


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_all_employees(request):
    """GET /api/tasks/get_all_employees/?department=Engineering"""
    employees = Employee.objects.all()
    department = request.query_params.get("department")
    if department:
        employees = employees.filter(department=department)
    data = [{"id": e.id, "name": e.name, "department": e.department} for e in employees]
    return Response(data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_priority_choices(request):
    """GET /api/tasks/get_priority_choices/"""
    return Response([{"value": value, "label": label} for value, label in Task.Priority.choices])


# ── Employee timer flow (Section 3 of the flowchart) ────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_active_session(request):
    employee = _current_employee(request)
    if employee is None:
        return Response({"detail": "Only employees have timer sessions."}, status=status.HTTP_403_FORBIDDEN)

    session = (
        TimerSession.objects.filter(employee=employee, end_time__isnull=True)
        .select_related("task")
        .first()
    )
    if not session:
        return Response({"active": False, "task": None, "task_name": None, "session": None})

    return Response({
        "active": True,
        "task": session.task_id,
        "task_name": session.task.task_name,
        "session": TimerSessionSerializer(session).data,
    })
    
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_task(request, pk):
    employee = _current_employee(request)
    if employee is None:
        return Response({"detail": "Only employees can start a timer."}, status=status.HTTP_403_FORBIDDEN)

    task = get_object_or_404(Task, pk=pk)
    if task.assigned_to_id != employee.id:
        return Response({"detail": "This task isn't assigned to you."}, status=status.HTTP_403_FORBIDDEN)

    if task.task_status != Task.Status.NOT_STARTED:
        return Response(
            {"detail": "This task has already been started. Use Resume instead."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        if TimerSession.objects.select_for_update().filter(employee=employee, end_time__isnull=True).exists():
            return Response(
                {"detail": "You already have an active timer running on another task. Pause or submit it first."},
                status=status.HTTP_409_CONFLICT,
            )

        TimerSession.objects.create(task=task, employee=employee)
        task.task_status = Task.Status.IN_PROGRESS
        task.save(update_fields=["task_status"])

        log_activity(
            task, request.user, ActivityLog.Action.STARTED,
            from_status="not_started", to_status="in_progress",
        )

    return Response(TaskListSerializer(task).data)

from django.db import transaction

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def pause_task(request, pk):
    """
    POST /api/tasks/<id>/pause/
    Closes the current open session, calculates its duration, recalculates
    the task's total time, and sets status = Paused.
    """
    employee = _current_employee(request)
    if employee is None:
        return Response({"detail": "Only employees can pause a timer."}, status=status.HTTP_403_FORBIDDEN)

    task = get_object_or_404(Task, pk=pk)
    if task.assigned_to_id != employee.id:
        return Response({"detail": "This task isn't assigned to you."}, status=status.HTTP_403_FORBIDDEN)

    session = TimerSession.objects.filter(task=task, employee=employee, end_time__isnull=True).first()
    if not session:
        return Response({"detail": "There's no active timer session to pause."}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        session.close()
        task.task_status = Task.Status.PAUSED
        task.save(update_fields=["task_status"])
        task.recalc_total_time()
        log_activity(
            task, request.user, ActivityLog.Action.PAUSED,
            from_status="in_progress", to_status="paused",
            details={"session_id": session.id, "duration_seconds": session.duration_seconds},
        )
    
    return Response(TaskListSerializer(task).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def resume_task(request, pk):
    employee = _current_employee(request)
    if employee is None:
        return Response({"detail": "Only employees can resume a timer."}, status=status.HTTP_403_FORBIDDEN)

    task = get_object_or_404(Task, pk=pk)
    if task.assigned_to_id != employee.id:
        return Response({"detail": "This task isn't assigned to you."}, status=status.HTTP_403_FORBIDDEN)

    if task.task_status not in (Task.Status.PAUSED, Task.Status.REWORK_NEEDED):
        return Response(
            {"detail": "This task isn't paused or awaiting rework, so it can't be resumed."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        if TimerSession.objects.select_for_update().filter(employee=employee, end_time__isnull=True).exists():
            return Response(
                {"detail": "You already have an active timer running on another task. Pause or submit it first."},
                status=status.HTTP_409_CONFLICT,
            )

        from_status = task.task_status
        session = TimerSession.objects.create(
            task=task, employee=employee,
            is_rework_session=(task.task_status == Task.Status.REWORK_NEEDED),
        )
        task.task_status = Task.Status.IN_PROGRESS
        task.save(update_fields=["task_status"])

        log_activity(
            task, request.user, ActivityLog.Action.RESUMED,
            from_status=from_status, to_status="in_progress",
            details={"session_id": session.id, "is_rework_session": session.is_rework_session},
        )

    return Response(TaskListSerializer(task).data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def submit_task(request, pk):
    employee = _current_employee(request)
    if employee is None:
        return Response({"detail": "Only employees can submit a task."}, status=status.HTTP_403_FORBIDDEN)

    task = get_object_or_404(Task, pk=pk)
    if task.assigned_to_id != employee.id:
        return Response({"detail": "This task isn't assigned to you."}, status=status.HTTP_403_FORBIDDEN)

    if task.task_status not in (Task.Status.IN_PROGRESS, Task.Status.PAUSED):
        return Response(
            {"detail": "This task must be in progress or paused to submit it."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = TaskSubmitSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    with transaction.atomic():
        open_session = TimerSession.objects.filter(task=task, employee=employee, end_time__isnull=True).first()
        if open_session:
            open_session.close()

        from_status = task.task_status
        task.task_sheet_link = serializer.validated_data["task_sheet_link"]
        task.employee_remarks = serializer.validated_data["employee_remarks"]
        task.submitted_date = timezone_now()
        task.task_status = Task.Status.RESUBMITTED if task.rework_count > 0 else Task.Status.SUBMITTED
        task.save(update_fields=["task_sheet_link", "employee_remarks", "submitted_date", "task_status"])

        if open_session:
            task.recalc_total_time()

        log_activity(
            task, request.user, ActivityLog.Action.SUBMITTED,
            from_status=from_status, to_status=task.task_status,
            details={"task_sheet_link": task.task_sheet_link},
        )

    return Response(TaskListSerializer(task).data)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_task_sessions(request, pk):
    """
    GET /api/tasks/<id>/sessions/
    Session history for a task — admin can see any task's sessions,
    employee can only see sessions for their own assigned task.
    """
    task = get_object_or_404(Task, pk=pk)
    if not _is_admin(request) and task.assigned_to_id != request.user.instance.id:
        return Response({"detail": "You can't view sessions for this task."}, status=status.HTTP_403_FORBIDDEN)

    sessions = task.sessions.all()
    return Response(TimerSessionSerializer(sessions, many=True).data)


def timezone_now():
    from django.utils import timezone
    return timezone.now()

# ── Add to tasks/views.py ─────────────────────────────────────────────────────
# (also add: from .serializers import ReviewApproveSerializer, ReviewReworkSerializer
#  to your existing serializer import line, and `from django.utils import timezone`
#  if it isn't already imported)

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_review_tasks(request):
    """
    GET /api/tasks/review_tasks/
    Admin-only. Shows every task waiting on a review decision —
    Submitted, Resubmitted, or already opened as Under Review.
    """
    if not _is_admin(request):
        return Response({"detail": "Only admins can view the review queue."}, status=status.HTTP_403_FORBIDDEN)

    tasks = Task.objects.filter(
        task_status__in=[Task.Status.SUBMITTED, Task.Status.RESUBMITTED, Task.Status.UNDER_REVIEW]
    )
    return Response(TaskListSerializer(tasks, many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def start_review(request, pk):
    """
    POST /api/tasks/<id>/review/start/
    Admin-only. Submitted/Resubmitted -> Under Review.
    """
    if not _is_admin(request):
        return Response({"detail": "Only admins can review tasks."}, status=status.HTTP_403_FORBIDDEN)

    task = get_object_or_404(Task, pk=pk)
    if task.task_status not in (Task.Status.SUBMITTED, Task.Status.RESUBMITTED):
        return Response(
            {"detail": "Only submitted or resubmitted tasks can enter review."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task.task_status = Task.Status.UNDER_REVIEW
    task.save(update_fields=["task_status"])
    return Response(TaskListSerializer(task).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def approve_task(request, pk):
    if not _is_admin(request):
        return Response({"detail": "Only admins can approve tasks."}, status=status.HTTP_403_FORBIDDEN)

    task = get_object_or_404(Task, pk=pk)
    if task.task_status != Task.Status.UNDER_REVIEW:
        return Response(
            {"detail": "This task must be Under Review before it can be approved."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = ReviewApproveSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    with transaction.atomic():
        task.quality_of_task = serializer.validated_data["quality_of_task"]
        task.rating = serializer.validated_data["rating"]
        task.admin_remarks = serializer.validated_data["admin_remarks"]
        task.reviewed_date = timezone.now()
        task.task_status = Task.Status.COMPLETED
        task.save(update_fields=[
            "quality_of_task", "rating", "admin_remarks", "reviewed_date", "task_status",
        ])

        log_activity(
            task, request.user, ActivityLog.Action.APPROVED,
            from_status="under_review", to_status="completed",
            details={"quality": task.quality_of_task, "rating": task.rating, "remarks": task.admin_remarks},
        )

    return Response(TaskListSerializer(task).data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def request_rework(request, pk):
    if not _is_admin(request):
        return Response({"detail": "Only admins can request rework."}, status=status.HTTP_403_FORBIDDEN)

    task = get_object_or_404(Task, pk=pk)
    if task.task_status != Task.Status.UNDER_REVIEW:
        return Response(
            {"detail": "This task must be Under Review before requesting rework."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    serializer = ReviewReworkSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    with transaction.atomic():
        task.admin_remarks = serializer.validated_data["admin_remarks"]
        task.reviewed_date = timezone.now()
        task.rework_count = task.rework_count + 1
        task.task_status = Task.Status.REWORK_NEEDED
        task.save(update_fields=["admin_remarks", "reviewed_date", "rework_count", "task_status"])

        log_activity(
            task, request.user, ActivityLog.Action.REWORK_REQUESTED,
            from_status="under_review", to_status="rework_needed",
            details={"admin_remarks": task.admin_remarks, "rework_count": task.rework_count},
        )

    return Response(TaskListSerializer(task).data)

#------------------------New------------------------------------
# tasks/views.py — add these
from django.db import transaction
from .activity import ActivityLog, log_activity
from .models import CorrectionRequest

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def request_correction(request, session_id):
    """
    POST /api/sessions/<session_id>/correction-request/
    body: { "reason": "...", "requested_end_time": "2026-08-01T14:30:00Z" }
    """
    employee = _current_employee(request)
    if employee is None:
        return Response({"detail": "Only employees can request corrections."}, status=status.HTTP_403_FORBIDDEN)

    session = get_object_or_404(TimerSession, pk=session_id)
    if session.employee_id != employee.id:
        return Response({"detail": "This session isn't yours."}, status=status.HTTP_403_FORBIDDEN)
    if session.end_time is None:
        return Response({"detail": "Only closed sessions can be corrected."}, status=status.HTTP_400_BAD_REQUEST)
    if session.correction_requests.filter(status=CorrectionRequest.Status.PENDING).exists():
        return Response({"detail": "A correction request is already pending for this session."}, status=status.HTTP_409_CONFLICT)

    reason = request.data.get("reason", "").strip()
    requested_end_time = request.data.get("requested_end_time")
    if not reason or not requested_end_time:
        return Response({"detail": "reason and requested_end_time are required."}, status=status.HTTP_400_BAD_REQUEST)

    correction = CorrectionRequest.objects.create(
        session=session, requested_by=employee, reason=reason,
        original_end_time=session.end_time, requested_end_time=requested_end_time,
    )
    log_activity(session.task, request.user, ActivityLog.Action.CORRECTION_REQUESTED,
                 details={"session_id": session.id, "requested_end_time": str(requested_end_time)})
    return Response({"id": correction.id, "status": correction.status}, status=status.HTTP_201_CREATED)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_pending_corrections(request):
    """GET /api/corrections/pending/ — admin-only queue for decisions."""
    if not _is_admin(request):
        return Response({"detail": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
    corrections = CorrectionRequest.objects.filter(
        status=CorrectionRequest.Status.PENDING
    ).select_related("session", "session__task", "requested_by").order_by("-created_at")
    return Response(CorrectionListSerializer(corrections, many=True).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def decide_correction(request, pk):
    """
    POST /api/corrections/<id>/decision/
    body: { "decision": "approve" | "reject", "admin_notes": "..." }
    """
    if not _is_admin(request):
        return Response({"detail": "Admin only."}, status=status.HTTP_403_FORBIDDEN)

    correction = get_object_or_404(CorrectionRequest, pk=pk, status=CorrectionRequest.Status.PENDING)
    decision = request.data.get("decision")
    if decision not in ("approve", "reject"):
        return Response({"detail": "decision must be 'approve' or 'reject'."}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        if decision == "approve":
            session = correction.session
            old_end, old_duration = session.end_time, session.duration_seconds
            session.end_time = correction.requested_end_time
            session.duration_seconds = int((session.end_time - session.start_time).total_seconds())
            session.save(update_fields=["end_time", "duration_seconds"])
            session.task.recalc_total_time()
            correction.status = CorrectionRequest.Status.APPROVED
            details = {
                "old_end_time": str(old_end), "new_end_time": str(session.end_time),
                "old_duration_seconds": old_duration, "new_duration_seconds": session.duration_seconds,
            }
        else:
            correction.status = CorrectionRequest.Status.REJECTED
            details = {"reason_rejected": request.data.get("admin_notes", "")}

        correction.admin_notes = request.data.get("admin_notes", "")
        correction.decided_by = request.user.instance
        correction.decided_at = timezone.now()
        correction.save(update_fields=["status", "admin_notes", "decided_by", "decided_at"])

        log_activity(correction.session.task, request.user, ActivityLog.Action.CORRECTION_DECIDED, details=details)

    return Response({"id": correction.id, "status": correction.status})

# tasks/views.py

def _close_open_session_if_any(task):
    """Shared by hold/cancel — closes any running session so no time is lost."""
    open_session = task.sessions.filter(end_time__isnull=True).first()
    if open_session:
        open_session.close()
        task.recalc_total_time()

NON_FINAL_STATUSES = [s for s in Task.Status.values if s not in
                      (Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED)]

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def hold_task(request, pk):
    if not _is_admin(request):
        return Response({"detail": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
    task = get_object_or_404(Task, pk=pk)
    if task.task_status not in NON_FINAL_STATUSES:
        return Response({"detail": "This task can't be put on hold from its current status."}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        _close_open_session_if_any(task)
        old_status = task.task_status
        task.status_before_hold = old_status
        task.task_status = Task.Status.ON_HOLD
        task.save(update_fields=["task_status", "status_before_hold"])
        log_activity(task, request.user, ActivityLog.Action.HOLD, from_status=old_status, to_status="on_hold")

    return Response(TaskListSerializer(task).data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def release_hold(request, pk):
    if not _is_admin(request):
        return Response({"detail": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
    task = get_object_or_404(Task, pk=pk)
    if task.task_status != Task.Status.ON_HOLD:
        return Response({"detail": "This task isn't on hold."}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        restored = task.status_before_hold or Task.Status.NOT_STARTED
        task.task_status = restored
        task.status_before_hold = ""
        task.save(update_fields=["task_status", "status_before_hold"])
        log_activity(task, request.user, ActivityLog.Action.RELEASED_HOLD, from_status="on_hold", to_status=restored)

    return Response(TaskListSerializer(task).data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def cancel_task(request, pk):
    if not _is_admin(request):
        return Response({"detail": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
    task = get_object_or_404(Task, pk=pk)
    if task.task_status not in NON_FINAL_STATUSES + [Task.Status.ON_HOLD]:
        return Response({"detail": "This task can't be cancelled from its current status."}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        _close_open_session_if_any(task)
        old_status = task.task_status
        task.task_status = Task.Status.CANCELLED
        task.save(update_fields=["task_status"])
        log_activity(task, request.user, ActivityLog.Action.CANCELLED, from_status=old_status, to_status="cancelled",
                     details={"reason": request.data.get("reason", "")})

    return Response(TaskListSerializer(task).data)

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def archive_task(request, pk):
    if not _is_admin(request):
        return Response({"detail": "Admin only."}, status=status.HTTP_403_FORBIDDEN)
    task = get_object_or_404(Task, pk=pk)
    if task.task_status not in (Task.Status.COMPLETED, Task.Status.CANCELLED):
        return Response({"detail": "Only completed or cancelled tasks can be archived."}, status=status.HTTP_400_BAD_REQUEST)

    with transaction.atomic():
        task.task_status = Task.Status.ARCHIVED
        task.save(update_fields=["task_status"])
        log_activity(task, request.user, ActivityLog.Action.ARCHIVED, to_status="archived")

    return Response(TaskListSerializer(task).data)


# ── Correction history (approved / rejected) — shared by admin + employee screens ──

def _corrections_queryset(request, status_value):
    qs = CorrectionRequest.objects.filter(status=status_value).select_related(
        "session", "session__task", "requested_by", "decided_by"
    ).order_by("-decided_at")
    if not _is_admin(request):
        employee = _current_employee(request)
        if employee is None:
            return CorrectionRequest.objects.none()
        qs = qs.filter(requested_by=employee)
    return qs

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_approved_corrections(request):
    """GET /api/corrections/approved/ — admin sees all, employee sees only their own."""
    corrections = _corrections_queryset(request, CorrectionRequest.Status.APPROVED)
    return Response(CorrectionListSerializer(corrections, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_rejected_corrections(request):
    """GET /api/corrections/rejected/ — admin sees all, employee sees only their own."""
    corrections = _corrections_queryset(request, CorrectionRequest.Status.REJECTED)
    return Response(CorrectionListSerializer(corrections, many=True).data)


# ── Audit history ────────────────────────────────────────────────────────────

def _activity_to_dict(log):
    return {
        "id": log.id,
        "task_id": log.task.task_id,
        "task_name": log.task.task_name,
        "actor_name": log.actor_name,
        "actor_role": "admin" if log.actor_admin_id else ("employee" if log.actor_employee_id else "system"),
        "action": log.action,
        "action_label": log.get_action_display(),
        "from_status": log.from_status,
        "to_status": log.to_status,
        "details": log.details,
        "created_at": log.created_at,
    }
    
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_all_activity(request):
    """
    GET /api/activity/?task_id=&action=&employee=
    Admin-only. Sitewide audit log, most recent first, capped at 500 rows.
    """
    if not _is_admin(request):
        return Response({"detail": "Admin only."}, status=status.HTTP_403_FORBIDDEN)

    from .activity import ActivityLog
    logs = ActivityLog.objects.select_related(
        "task", "actor_admin", "actor_employee"
    ).order_by("-created_at")

    task_id = request.query_params.get("task_id")
    if task_id:
        logs = logs.filter(task__task_id__icontains=task_id)
    action = request.query_params.get("action")
    if action:
        logs = logs.filter(action=action)
    employee_id = request.query_params.get("employee")
    if employee_id:
        logs = logs.filter(actor_employee_id=employee_id)

    return Response([_activity_to_dict(l) for l in logs[:500]])

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_my_activity(request):
    """
    GET /api/my_activity/
    Employee-only. Every activity entry on tasks assigned to them —
    including admin actions like approve/rework, so they can see their
    task's full history, not just their own clicks.
    """
    employee = _current_employee(request)
    if employee is None:
        return Response({"detail": "Employees only."}, status=status.HTTP_403_FORBIDDEN)

    from .activity import ActivityLog
    logs = ActivityLog.objects.filter(task__assigned_to=employee).select_related(
        "task", "actor_admin", "actor_employee"
    ).order_by("-created_at")

    return Response([_activity_to_dict(l) for l in logs[:500]])


# ── Reports ─────────────────────────────────────────────────────────────────

@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_admin_reports(request):
    """
    GET /api/reports/admin/?employee=&status=&priority=&date_from=&date_to=
    Admin-only. Summary KPIs + breakdowns + the filtered task list itself.
    """
    if not _is_admin(request):
        return Response({"detail": "Admin only."}, status=status.HTTP_403_FORBIDDEN)

    tasks = Task.objects.all()
    employee_id = request.query_params.get("employee")
    if employee_id:
        tasks = tasks.filter(assigned_to_id=employee_id)
    status_filter = request.query_params.get("status")
    if status_filter:
        tasks = tasks.filter(task_status=status_filter)
    priority = request.query_params.get("priority")
    if priority:
        tasks = tasks.filter(priority=priority)
    date_from = request.query_params.get("date_from")
    if date_from:
        tasks = tasks.filter(assigned_date__gte=date_from)
    date_to = request.query_params.get("date_to")
    if date_to:
        tasks = tasks.filter(assigned_date__lte=date_to)

    total = tasks.count()
    completed = tasks.filter(task_status=Task.Status.COMPLETED).count()
    overdue = tasks.filter(due_date__lt=timezone.now().date()).exclude(
        task_status__in=[Task.Status.COMPLETED, Task.Status.CANCELLED, Task.Status.ARCHIVED]
    ).count()
    total_hours = tasks.aggregate(total=db_models.Sum("total_time_taken"))["total"] or 0
    avg_rating = tasks.exclude(rating__isnull=True).aggregate(avg=db_models.Avg("rating"))["avg"]

    by_employee = list(
        tasks.exclude(assigned_to__isnull=True)
        .values("assigned_to__name")
        .annotate(count=db_models.Count("id"), hours=db_models.Sum("total_time_taken"))
        .order_by("-count")
    )
    by_status = list(tasks.values("task_status").annotate(count=db_models.Count("id")))

    return Response({
        "summary": {
            "total_tasks": total,
            "completed": completed,
            "completion_rate": round((completed / total) * 100, 1) if total else 0,
            "overdue": overdue,
            "total_hours": float(total_hours),
            "avg_rating": round(avg_rating, 2) if avg_rating else None,
        },
        "by_employee": by_employee,
        "by_status": by_status,
        "tasks": TaskListSerializer(tasks.order_by("-assigned_date"), many=True).data,
    })
    
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def get_my_reports(request):
    """GET /api/reports/mine/ — employee-only personal summary."""
    employee = _current_employee(request)
    if employee is None:
        return Response({"detail": "Employees only."}, status=status.HTTP_403_FORBIDDEN)

    tasks = Task.objects.filter(assigned_to=employee)
    total = tasks.count()
    completed = tasks.filter(task_status=Task.Status.COMPLETED).count()
    total_hours = tasks.aggregate(total=db_models.Sum("total_time_taken"))["total"] or 0
    avg_rating = tasks.exclude(rating__isnull=True).aggregate(avg=db_models.Avg("rating"))["avg"]
    by_quality = list(
        tasks.exclude(quality_of_task="").values("quality_of_task").annotate(count=db_models.Count("id"))
    )
    
    return Response({
        "summary": {
            "total_tasks": total,
            "completed": completed,
            "completion_rate": round((completed / total) * 100, 1) if total else 0,
            "total_hours": float(total_hours),
            "avg_rating": round(avg_rating, 2) if avg_rating else None,
        },
        "by_quality": by_quality,
        "tasks": TaskListSerializer(tasks.order_by("-assigned_date"), many=True).data,
    })
    

@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def delete_task(request, pk):
    """
    DELETE /api/tasks/<id>/delete/
    Admin-only. Permanently removes the task. Only allowed for tasks that
    are already Cancelled or Archived — deleting an active/in-progress
    task would silently destroy timer history, so that's blocked.
    """
    if not _is_admin(request):
        return Response({"detail": "Admin only."}, status=status.HTTP_403_FORBIDDEN)

    task = get_object_or_404(Task, pk=pk)
    if task.task_status not in (Task.Status.CANCELLED, Task.Status.ARCHIVED):
        return Response(
            {"detail": "Only cancelled or archived tasks can be deleted."},
            status=status.HTTP_400_BAD_REQUEST,
        )

    task_id_str = task.task_id
    task.delete()  # CASCADE removes sessions, correction_requests; ActivityLog rows are SET_NULL/CASCADE per their FK config
    return Response({"detail": f"{task_id_str} deleted."}, status=status.HTTP_200_OK)