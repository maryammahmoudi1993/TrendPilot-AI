from django.http import Http404
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.routers import SimpleRouter

from apps.core.schema import errors

from .matrix import Action
from .member_serializers import AddMemberSerializer, ChangeRoleSerializer, MemberSerializer
from .models import Membership
from .scoping import WorkspaceScopedViewSetMixin, workspace_prefix
from .services import add_member, change_role, remove_member


@extend_schema_view(
    list=extend_schema(
        summary="List the workspace's members (any member)", responses=MemberSerializer
    ),
    create=extend_schema(
        summary="Add an existing user by email (Owner only)",
        request=AddMemberSerializer,
        responses={201: MemberSerializer, **errors(400, 403, 404)},
    ),
    partial_update=extend_schema(
        summary="Change a member's role (Owner only)",
        request=ChangeRoleSerializer,
        responses={200: MemberSerializer, **errors(400, 403, 404, 409)},
    ),
    destroy=extend_schema(
        summary="Remove a member (Owner only)",
        responses={204: None, **errors(403, 404, 409)},
    ),
    leave=extend_schema(
        summary="Leave the workspace (any member except the last Owner)",
        request=None,
        responses={204: OpenApiResponse(description="Left."), **errors(404, 409)},
    ),
)
class MemberViewSet(
    WorkspaceScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Members of a workspace. Any member may list or leave; only Owners manage."""

    queryset = Membership.objects.select_related("user")
    serializer_class = MemberSerializer
    http_method_names = ["get", "post", "patch", "delete", "head", "options"]
    required_actions = {
        "create": Action.MANAGE_MEMBERS,
        "partial_update": Action.MANAGE_MEMBERS,
        "destroy": Action.MANAGE_MEMBERS,
        "leave": Action.VIEW,
    }

    def create(self, request, *args, **kwargs):
        serializer = AddMemberSerializer(data=request.data, context={"workspace": self.workspace})
        serializer.is_valid(raise_exception=True)
        membership = add_member(
            workspace=self.workspace,
            user=serializer.validated_data["email"],
            role=serializer.validated_data["role"],
            actor=request.user,
        )
        return Response(MemberSerializer(membership).data, status=status.HTTP_201_CREATED)

    def partial_update(self, request, *args, **kwargs):
        membership = self.get_object()
        serializer = ChangeRoleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            membership = change_role(
                membership=membership, role=serializer.validated_data["role"], actor=request.user
            )
        except Membership.DoesNotExist as exc:  # removed concurrently
            raise Http404 from exc
        return Response(MemberSerializer(membership).data)

    def destroy(self, request, *args, **kwargs):
        self._remove(self.get_object(), actor=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["post"])
    def leave(self, request, *args, **kwargs):
        self._remove(self.get_membership(), actor=request.user, voluntary=True)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @staticmethod
    def _remove(membership, **kwargs):
        try:
            remove_member(membership=membership, **kwargs)
        except Membership.DoesNotExist as exc:  # removed concurrently
            raise Http404 from exc


router = SimpleRouter()
router.register(workspace_prefix("members"), MemberViewSet, basename="member")
