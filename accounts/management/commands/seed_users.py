# accounts/management/commands/seed_users.py
#
# Run once to create Divya (Admin table) and the employees (Employee table).
#   python manage.py seed_users
#
# Edit the lists below to match your real people before running.

from django.core.management.base import BaseCommand
from accounts.models import Admin, Employee

TEMP_PASSWORD = "ChangeMe@123"

ADMIN = {"name": "Divya", "email": "divya@billiontags.com"}

EMPLOYEES = [
    {"name": "Revathi", "email": "revathi@billiontags.com", "department": "Sales", "role": "Executive"},
    {"name": "Timo", "email": "timo@billiontags.com", "department": "Design", "role": "Designer"},
    {"name": "Yuvan", "email": "yuvan@billiontags.com", "department": "HR", "role": "Executive"},
    {"name": "Nagarajan K C", "email": "nagarajan.kc@billiontags.com", "department": "SEO", "role": "Specialist"},
    {"name": "Ramesh", "email": "ramesh@billiontags.com", "department": "Operations", "role": "Executive"},
    {"name": "Vinoth", "email": "vinoth@billiontags.com", "department": "Video/Content", "role": "Creator"},
    {"name": "JaiKumar", "email": "jaikumar@billiontags.com", "department": "Social Media", "role": "Executive"},
    {"name": "Jayeshlin", "email": "jayeshlin@billiontags.com", "department": "HR", "role": "Executive"},
    {"name": "Lakshana", "email": "lakshana@billiontags.com", "department": "Partnerships", "role": "Executive"},
    {"name": "Pradeep", "email": "pradeep@billiontags.com", "department": "Ad Operations", "role": "Executive"},
]


class Command(BaseCommand):
    help = "Seeds the Admin (Divya) and Employee accounts"

    def handle(self, *args, **options):
        admin, created = Admin.objects.get_or_create(
            email=ADMIN["email"],
            defaults={"name": ADMIN["name"]},
        )
        if created:
            admin.set_password(TEMP_PASSWORD)
            admin.save()
            self.stdout.write(self.style.SUCCESS(f"Created admin: {admin.email}"))
        else:
            self.stdout.write(f"Admin already exists: {admin.email}")

        for emp in EMPLOYEES:
            employee, created = Employee.objects.get_or_create(
                email=emp["email"],
                defaults={
                    "name": emp["name"],
                    "department": emp["department"],
                    "role": emp["role"],
                },
            )
            if created:
                employee.set_password(TEMP_PASSWORD)
                employee.save()
                self.stdout.write(self.style.SUCCESS(f"Created employee: {employee.email}"))
            else:
                self.stdout.write(f"Employee already exists: {employee.email}")

        self.stdout.write(self.style.WARNING(f"Temporary password for all seeded accounts: {TEMP_PASSWORD}"))