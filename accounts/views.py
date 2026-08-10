# accounts/views.py

from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.permissions import AllowAny, IsAuthenticated

from .serializers import LoginSerializer, AdminSerializer, EmployeeSerializer
from .models import AuthToken


@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    """
    POST /api/auth/login/
    body: { "email": "...", "password": "..." }
    returns: { "token": "...", "role": "admin" | "employee", "name": "..." }
    """
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    principal = serializer.validated_data["principal"]
    role = serializer.validated_data["role"]

    token = AuthToken.objects.create(
        admin=principal if role == "admin" else None,
        employee=principal if role == "employee" else None,
    )

    return Response(
        {"token": token.key, "role": role, "name": principal.name},
        status=status.HTTP_200_OK,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def logout_view(request):
    # request.auth is the AuthToken row (see authentication.py)
    request.auth.delete()
    return Response(status=status.HTTP_204_NO_CONTENT)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me_view(request):
    principal = request.user
    if principal.role == "admin":
        data = AdminSerializer(principal.instance).data
        data["auth_role"] = "admin"
        data["is_tl"] = False
    else:
        data = EmployeeSerializer(principal.instance).data  # keeps job-title `role`, e.g. "TL"
        data["auth_role"] = "employee"
        data["is_tl"] = principal.instance.role == "TL"
    return Response(data)