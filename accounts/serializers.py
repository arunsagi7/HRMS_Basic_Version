# accounts/serializers.py

from rest_framework import serializers
from .models import Admin, Employee


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, style={"input_type": "password"})

    def validate(self, attrs):
        email = attrs["email"]
        password = attrs["password"]

        # Check Admin table first, then Employee table.
        admin = Admin.objects.filter(email=email).first()
        if admin and admin.check_password(password):
            attrs["principal"] = admin
            attrs["role"] = "admin"
            return attrs

        employee = Employee.objects.filter(email=email).first()
        if employee and employee.check_password(password):
            attrs["principal"] = employee
            attrs["role"] = "employee"
            return attrs

        raise serializers.ValidationError("Invalid email or password")


class AdminSerializer(serializers.ModelSerializer):
    class Meta:
        model = Admin
        fields = ["id", "name", "email"]


class EmployeeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Employee
        fields = ["id", "name", "email", "department", "role"]