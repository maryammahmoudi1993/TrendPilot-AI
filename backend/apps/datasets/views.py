from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.response import Response

from apps.core.schema import errors
from apps.workspaces.scoping import WorkspaceScopedViewSetMixin

from .models import Dataset
from .serializers import DatasetSerializer, DatasetUploadSerializer


@extend_schema_view(
    list=extend_schema(
        summary="List a workspace's datasets", responses={200: DatasetSerializer, **errors(404)}
    ),
    retrieve=extend_schema(
        summary="Get a dataset",
        responses={200: DatasetSerializer, **errors(404)},
    ),
    create=extend_schema(
        summary="Upload a CSV dataset (Owner/Analyst only)",
        request=DatasetUploadSerializer,
        responses={201: DatasetSerializer, **errors(400, 403, 404)},
    ),
)
class DatasetViewSet(
    WorkspaceScopedViewSetMixin,
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    viewsets.GenericViewSet,
):
    queryset = Dataset.objects.all()
    http_method_names = ["get", "post", "head", "options"]

    def get_serializer_class(self):
        return DatasetUploadSerializer if self.action == "create" else DatasetSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        body = DatasetSerializer(serializer.instance).data
        return Response(body, status=status.HTTP_201_CREATED)
