# Not endpoints — internal helpers reused everywhere. These should be imported by every other file, so they belong in a shared module.

def _is_admin(request):
    # request.user is a SimplePrincipal wrapping either Admin or Employee
    # (see accounts/authentication.py) — .role is "admin" or "employee".
    return getattr(request.user, "role", None) == "admin"


def _current_employee(request):
    """Returns the logged-in Employee, or None if the caller isn't an employee."""
    if getattr(request.user, "role", None) != "employee":
        return None
    return request.user.instance

def _is_tl(request):
    employee = _current_employee(request)
    return employee is not None and employee.role == "TL"

def _can_manage_tasks(request):
    """Who's allowed to create tasks at all: Admin or a TL."""
    return _is_admin(request) or _is_tl(request)

def _owns_task_for_management(request, task):
    """Who's allowed to assign/reassign/hold/cancel THIS specific task.
    Admin: any task. TL: only tasks they personally created."""
    if _is_admin(request):
        return True
    employee = _current_employee(request)
    return employee is not None and employee.role == "TL" and task.assigned_by_employee_id == employee.id

def _can_review_task(request, task):
    """
    Who's allowed to review THIS task: Admin always. A TL only if they
    created it AND it isn't assigned to themselves — self-assigned TL
    tasks must go to admin for review, so a TL can't approve their own work.
    """
    if _is_admin(request):
        return True
    employee = _current_employee(request)
    if employee is None or employee.role != "TL":
        return False
    if task.assigned_by_employee_id != employee.id:
        return False
    if task.assigned_to_id == employee.id:
        return False  # self-assigned — admin reviews this one instead
    return True


def timezone_now():
    from django.utils import timezone
    return timezone.now()
