# tasks/serializers.py

from rest_framework import serializers
from .models import Task, TimerSession


class TaskListSerializer(serializers.ModelSerializer):
    """
    Used for the task table. assigned_to_name / department_name / assigned_by_name
    are derived — department isn't its own table, it's just Employee.department,
    so we read it off whichever employee the task is currently assigned to.
    Uses SerializerMethodField (not a dotted `source=`) so unassigned tasks
    (assigned_to = None) don't blow up with an AttributeError.
    """
    assigned_to_name = serializers.SerializerMethodField()
    created_by_role = serializers.SerializerMethodField()   # "admin" | "tl" — lets the UI badge TL-created tasks
    department_name = serializers.SerializerMethodField()
    assigned_by_name = serializers.SerializerMethodField()
    has_active_session = serializers.SerializerMethodField()

    class Meta:
        model = Task
        fields = [
            "id", "task_id", "task_name", "task_details",
            "assigned_to", "assigned_to_name", "department_name",
            "assigned_by_name",
            "priority", "assigned_date", "due_date", "allotted_time",
            "task_status", "total_time_taken", "remaining_or_over_time",
            "task_sheet_link", "employee_remarks", "submitted_date",
            "quality_of_task", "rating", "admin_remarks", "reviewed_date",
            "rework_count", "has_active_session", "created_by_role",
        ]

    def get_assigned_to_name(self, obj):
        return obj.assigned_to.name if obj.assigned_to_id else None

    def get_department_name(self, obj):
        return obj.assigned_to.department if obj.assigned_to_id else None

    def get_assigned_by_name(self, obj):
        return obj.assigned_by_name
    
    def get_created_by_role(self, obj):
        return obj.created_by_role

    def get_has_active_session(self, obj):
        # Lets the frontend show "Timer running" without a second request.
        return obj.sessions.filter(end_time__isnull=True).exists()


class TaskCreateSerializer(serializers.ModelSerializer):
    """
    Step 1 of the two-step flow: just the name and details. assigned_by is
    set in the view from the logged-in admin, never from the request body.
    """
    class Meta:
        model = Task
        fields = ["task_name", "task_details"]

    def validate_task_name(self, value):
        if not value.strip():
            raise serializers.ValidationError("Task name cannot be blank.")
        return value


class TaskAssignSerializer(serializers.ModelSerializer):
    """
    Step 2: assign / reassign. No `department` field here on purpose —
    department is derived from whichever Employee is chosen as assigned_to.
    """
    class Meta:
        model = Task
        fields = ["assigned_to", "priority", "due_date", "allotted_time"]
        extra_kwargs = {
            "assigned_to": {"required": True},
            "priority": {"required": True},
            "due_date": {"required": True},
            "allotted_time": {"required": True},
        }


class TimerSessionSerializer(serializers.ModelSerializer):
    """Read-only — used to show an employee's session history for a task."""
    class Meta:
        model = TimerSession
        fields = ["id", "start_time", "end_time", "duration_seconds", "is_rework_session"]


class TaskSubmitSerializer(serializers.Serializer):
    """
    Body for POST /api/tasks/<id>/submit/. task_sheet_link is stored as
    entered, no URL validation, per the flowchart's confirmed constraints.
    """
    task_sheet_link = serializers.CharField(required=True, allow_blank=False)
    employee_remarks = serializers.CharField(required=False, allow_blank=True, default="")
    
    
# ── Add to tasks/serializers.py ───────────────────────────  ───────────────────

class ReviewApproveSerializer(serializers.Serializer):
    quality_of_task = serializers.ChoiceField(choices=Task.Quality.choices)
    rating = serializers.IntegerField(min_value=1, max_value=5)
    admin_remarks = serializers.CharField(required=False, allow_blank=True, default="")


class ReviewReworkSerializer(serializers.Serializer):
    admin_remarks = serializers.CharField(required=True, allow_blank=False)
    
# tasks/serializers.py — add this import and serializer

from .models import Task, TimerSession, CorrectionRequest  # add CorrectionRequest to the existing import

class CorrectionListSerializer(serializers.ModelSerializer):
    """Used by the pending/approved/rejected correction list screens."""
    task_id = serializers.CharField(source="session.task.task_id", read_only=True)
    task_name = serializers.CharField(source="session.task.task_name", read_only=True)
    employee_name = serializers.CharField(source="requested_by.name", read_only=True)
    decided_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CorrectionRequest
        fields = [
            "id", "task_id", "task_name", "employee_name", "reason",
            "original_end_time", "requested_end_time", "status",
            "admin_notes", "decided_by_name", "decided_at", "created_at",
        ]

    def get_decided_by_name(self, obj):
        return obj.decided_by.name if obj.decided_by_id else None