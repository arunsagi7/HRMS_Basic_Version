# accounts/authentication.py
#
# Custom DRF authentication class, since we're not using AUTH_USER_MODEL /
# DRF's built-in TokenAuthentication (those expect one User table).
# This reads "Authorization: Token <key>" and looks it up in our AuthToken table.

from rest_framework.authentication import BaseAuthentication
from rest_framework.exceptions import AuthenticationFailed
from .models import AuthToken


class SimplePrincipal:
    """
    Wraps an Admin or Employee instance so request.user behaves the way
    DRF permission classes (like IsAuthenticated) expect.
    """
    def __init__(self, instance, role):
        self.instance = instance
        self.role = role
        self.is_authenticated = True
        self.is_anonymous = False

    def __getattr__(self, item):
        # Fall through to the underlying Admin/Employee fields (name, email, etc.)
        return getattr(self.instance, item)


class AdminEmployeeTokenAuthentication(BaseAuthentication):
    keyword = "Token"

    def authenticate(self, request):
        auth_header = request.META.get("HTTP_AUTHORIZATION", "")
        if not auth_header.startswith(self.keyword + " "):
            return None  # let other authenticators / AllowAny handle it

        key = auth_header[len(self.keyword) + 1:].strip()
        try:
            token = AuthToken.objects.select_related("admin", "employee").get(key=key)
        except AuthToken.DoesNotExist:
            raise AuthenticationFailed("Invalid or expired token")

        principal = SimplePrincipal(token.owner, token.role)
        return (principal, token)