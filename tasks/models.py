# tasks/models.py

from django.db import models
from django.utils import timezone
from accounts.models import Admin, Employee


class Task(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", "Low"
        MEDIUM = "medium", "Medium"
        HIGH = "high", "High"
        URGENT = "urgent", "Urgent"

    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Assigned / Not Started"
        IN_PROGRESS = "in_progress", "In Progress"
        PAUSED = "paused", "Paused"
        SUBMITTED = "submitted", "Submitted"
        UNDER_REVIEW = "under_review", "Under Review"
        REWORK_NEEDED = "rework_needed", "Rework Needed"
        RESUBMITTED = "resubmitted", "Resubmitted"
        COMPLETED = "completed", "Completed"
        ON_HOLD = "on_hold", "On Hold"
        CANCELLED = "cancelled", "Cancelled"
        ARCHIVED = "archived", "Archived"

    class Quality(models.TextChoices):
        EXCELLENT = "excellent", "Excellent"
        GOOD = "good", "Good"
        NEEDS_IMPROVEMENT = "needs_improvement", "Needs Improvement"
        REWORK_NEEDED = "rework_needed", "Rework Needed"
        REJECTED = "rejected", "Rejected"

    # ── System-generated identifier, e.g. "TASK-001" ──────────────────────
    task_id = models.CharField(max_length=20, unique=True, editable=False, blank=True)

    # ── Admin fields (set when creating/editing the task) ─────────────────
    task_name = models.CharField(max_length=255)
    task_details = models.TextField(blank=True)
    assigned_to = models.ForeignKey(
        Employee, on_delete=models.PROTECT, related_name="assigned_tasks",
        null=True, blank=True,
    )
    assigned_by = models.ForeignKey(
        Admin, on_delete=models.PROTECT, related_name="tasks_assigned"
    )
    priority = models.CharField(max_length=10, choices=Priority.choices, default=Priority.MEDIUM)
    assigned_date = models.DateField(auto_now_add=True)
    due_date = models.DateField(null=True, blank=True)
    allotted_time = models.DecimalField(
        max_digits=6, decimal_places=2, null=True, blank=True,
        help_text="Allotted time in hours",
    )

    # ── System-tracked status & timer totals ───────────────────────────────
    task_status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.NOT_STARTED
    )
    total_time_taken = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="Sum of all closed TimerSession durations, in hours",
    )
    remaining_or_over_time = models.DecimalField(
        max_digits=6, decimal_places=2, default=0,
        help_text="allotted_time - total_time_taken. Negative = over time.",
    )

    # ── Submission fields (filled by employee at Stop/Submit) ─────────────
    task_sheet_link = models.TextField(blank=True, help_text="Stored as-is, no URL validation")
    employee_remarks = models.TextField(blank=True)
    submitted_date = models.DateTimeField(null=True, blank=True)

    # ── Review fields (filled by admin) ────────────────────────────────────
    quality_of_task = models.CharField(
        max_length=25, choices=Quality.choices, blank=True
    )
    rating = models.PositiveSmallIntegerField(null=True, blank=True)  # 1–5
    admin_remarks = models.TextField(blank=True)
    reviewed_date = models.DateTimeField(null=True, blank=True)
    rework_count = models.PositiveIntegerField(default=0)

    # ── Bookkeeping ─────────────────────────────────────────────────────────
    last_activity = models.DateTimeField(auto_now=True)
    
    status_before_hold = models.CharField(max_length=20, blank=True) # Add this

    class Meta:
        ordering = ["-assigned_date", "-id"]

    def __str__(self):
        return f"{self.task_id} — {self.task_name}"

    def save(self, *args, **kwargs):
        is_new = self._state.adding
        super().save(*args, **kwargs)
        if is_new and not self.task_id:
            self.task_id = f"TASK-{self.pk:03d}"
            super().save(update_fields=["task_id"])

    def recalc_total_time(self):
        """
        Total time = sum of every CLOSED session's duration, in hours.
        Called after any session is closed (Pause or Stop/Submit).
        """
        from decimal import Decimal, ROUND_HALF_UP

        total_seconds = (
            self.sessions.filter(end_time__isnull=False)
            .aggregate(total=models.Sum("duration_seconds"))
            .get("total") or 0
        )
        # Keep this as Decimal arithmetic throughout — allotted_time is a
        # DecimalField, and Decimal - float raises TypeError in Python.
        hours = (Decimal(total_seconds) / Decimal(3600)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
        self.total_time_taken = hours
        if self.allotted_time is not None:
            self.remaining_or_over_time = self.allotted_time - hours
        self.save(update_fields=["total_time_taken", "remaining_or_over_time"])

class TimerSession(models.Model):
    """
    One row per Start->Pause (or Start->Submit) interval. Never overwritten —
    rework creates a NEW session on top of old ones, per the flowchart's
    "Old and new sessions preserved" rule.
    """
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="sessions")
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="timer_sessions")
    start_time = models.DateTimeField(auto_now_add=True)
    end_time = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(null=True, blank=True)
    is_rework_session = models.BooleanField(
        default=False, help_text="True if this session was opened after a Rework Needed decision."
    )

    class Meta:
        ordering = ["-start_time"]

    def __str__(self):
        return f"{self.task.task_id} session started {self.start_time}"

    def close(self):
        """Ends this session now and stores its duration. Does NOT touch the Task —
        callers are responsible for calling task.recalc_total_time() afterward."""
        self.end_time = timezone.now()
        self.duration_seconds = int((self.end_time - self.start_time).total_seconds())
        self.save(update_fields=["end_time", "duration_seconds"])
        
#--------------------New-------------------------------
# tasks/models.py — add this model
class CorrectionRequest(models.Model):
    class Status(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        REJECTED = "rejected", "Rejected"

    session = models.ForeignKey(TimerSession, on_delete=models.CASCADE, related_name="correction_requests")
    requested_by = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="correction_requests")
    reason = models.TextField()
    original_end_time = models.DateTimeField()   # snapshot for comparison, even if later approved/changed
    requested_end_time = models.DateTimeField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    admin_notes = models.TextField(blank=True)
    decided_by = models.ForeignKey(Admin, null=True, blank=True, on_delete=models.SET_NULL)
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]