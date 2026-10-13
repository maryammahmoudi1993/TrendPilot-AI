from django.db import transaction
from drf_spectacular.utils import (
    OpenApiResponse,
    extend_schema,
    extend_schema_view,
    inline_serializer,
)
from rest_framework import generics, serializers, status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from apps.audit.models import AuditAction
from apps.audit.services import record
from apps.core.schema import errors

from .serializers import (
    ChangePasswordSerializer,
    LogoutSerializer,
    RegisterSerializer,
    UserSerializer,
)
from .throttles import LoginRateThrottle, RegisterRateThrottle

TokenPairSerializer = inline_serializer(
    "TokenPair",
    {"access": serializers.CharField(), "refresh": serializers.CharField()},
)
RegisterResponseSerializer = inline_serializer(
    "RegisterResponse",
    {
        "user": UserSerializer(),
        "access": serializers.CharField(),
        "refresh": serializers.CharField(),
    },
)


def _tokens_for(user) -> dict:
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


@extend_schema(
    tags=["auth"],
    summary="Create an account",
    responses={201: RegisterResponseSerializer, **errors(400, 429)},
)
class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [RegisterRateThrottle]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        body = {"user": UserSerializer(user).data, **_tokens_for(user)}
        return Response(body, status=status.HTTP_201_CREATED)


@extend_schema(
    tags=["auth"],
    summary="Log in with email and password",
    responses={200: TokenPairSerializer, **errors(400, 401, 429)},
)
class LoginView(TokenObtainPairView):
    """Wrong email and wrong password give the same 401 so emails are not leaked."""

    permission_classes = [AllowAny]
    authentication_classes: list = []
    throttle_classes = [LoginRateThrottle]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        try:
            serializer.is_valid(raise_exception=True)
        except TokenError as exc:
            raise InvalidToken(exc.args[0]) from exc
        record(
            AuditAction.LOGIN,
            actor=serializer.user,
            target_type="user",
            target_id=serializer.user.pk,
        )
        return Response(serializer.validated_data, status=status.HTTP_200_OK)


@extend_schema(
    tags=["auth"],
    summary="Rotate the refresh token and get a new access token",
    responses={200: TokenPairSerializer, **errors(401)},
)
class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]
    authentication_classes: list = []


@extend_schema(
    tags=["auth"],
    summary="Blacklist the caller's refresh token",
    request=LogoutSerializer,
    responses={204: OpenApiResponse(description="Logged out."), **errors(400, 401)},
)
class LogoutView(APIView):
    def post(self, request):
        serializer = LogoutSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        with transaction.atomic():
            serializer.validated_data["refresh"].blacklist()
            record(
                AuditAction.LOGOUT,
                actor=request.user,
                target_type="user",
                target_id=request.user.pk,
            )
        return Response(status=status.HTTP_204_NO_CONTENT)


@extend_schema_view(
    get=extend_schema(
        tags=["auth"],
        summary="Get the current user",
        responses={200: UserSerializer, **errors(401)},
    ),
    patch=extend_schema(
        tags=["auth"],
        summary="Update the current user's profile",
        responses={200: UserSerializer, **errors(400, 401)},
    ),
)
class MeView(generics.RetrieveUpdateAPIView):
    serializer_class = UserSerializer
    http_method_names = ["get", "patch", "head", "options"]

    def get_object(self):
        return self.request.user


@extend_schema(
    tags=["auth"],
    summary="Change password; all other sessions are signed out",
    request=ChangePasswordSerializer,
    responses={200: TokenPairSerializer, **errors(400, 401)},
)
class ChangePasswordView(APIView):
    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = request.user
        user.set_password(serializer.validated_data["new_password"])
        with transaction.atomic():
            user.save(update_fields=["password"])
            # Sign out every other session: all outstanding refresh tokens are blacklisted.
            for outstanding in OutstandingToken.objects.filter(user=user):
                BlacklistedToken.objects.get_or_create(token=outstanding)
            record(AuditAction.PASSWORD_CHANGE, actor=user, target_type="user", target_id=user.pk)
        return Response(_tokens_for(user))
