# Reports

from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from ..models import Task
from ..serializers import ( TaskListSerializer )
from django.db import models as db_models  # aliased so it doesn't clash with the `models` you already reference via Task etc.
from tasks.views.utils import _is_admin, _current_employee

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
    
