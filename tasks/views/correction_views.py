# Time Corrections
# Everything related to CorrectionRequest.
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from .utils import _is_admin, _current_employee
from rest_framework import status
from django.shortcuts import get_object_or_404
from ..models import TimerSession, CorrectionRequest
from django.db import transaction
from ..activity import ActivityLog, log_activity
from ..serializers import CorrectionListSerializer
from django.utils import timezone


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

