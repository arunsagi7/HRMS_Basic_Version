# tasks/admin.py

from django.contrib import admin
from .models import Task


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = (
        "task_id", "task_name", "assigned_to", "assigned_by",
        "priority", "task_status", "total_time_taken", "due_date",
    )
    list_filter = ("task_status", "priority")
    search_fields = ("task_id", "task_name", "assigned_to__name")
    readonly_fields = ("task_id", "assigned_date", "total_time_taken", "last_activity")