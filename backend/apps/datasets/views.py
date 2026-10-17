from drf_spectacular.utils import extend_schema, extend_schema_view
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.core.schema import errors
from apps.workspaces.matrix import Action
from apps.workspaces.scoping import WorkspaceScopedViewSetMixin

from .models import Dataset
from .serializers import DatasetSerializer, DatasetUploadSerializer, MappingSerializer
from .services import start_validation, update_mapping


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
    http_method_names = ["get", "post", "put", "patch", "head", "options"]
    required_actions = {"mapping": Action.EDIT, "validate": Action.EDIT}

    def get_serializer_class(self):
        if self.action == "create":
            return DatasetUploadSerializer
        if self.action == "mapping":
            return MappingSerializer
        return DatasetSerializer

    @extend_schema(
        methods=["PUT", "PATCH"],
        summary="Set the dataset's column mapping (Owner/Analyst only)",
        description=(
            "PUT replaces the mapping; PATCH merges the given fields into the stored one. "
            "Validates the date, target and regressor columns against the file. Resets the "
            "dataset to 'uploaded' and clears derived results."
        ),
        request=MappingSerializer,
        responses={200: DatasetSerializer, **errors(400, 403, 404, 409)},
    )
    @action(detail=True, methods=["put", "patch"], url_path="mapping")
    def mapping(self, request, *args, **kwargs):
        partial = request.method == "PATCH"
        serializer = MappingSerializer(data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        dataset = update_mapping(
            dataset=self.get_object(),
            actor=request.user,
            data=serializer.validated_data,
            partial=partial,
        )
        return Response(DatasetSerializer(dataset).data)

    @extend_schema(
        summary="Start a data-quality validation (Owner/Analyst only)",
        description=(
            "Queues a background task that builds the quality report and returns 202 with "
            "status 'validating'. Poll the dataset until status is 'validated' or 'failed'. "
            "409 'no_mapping' without a saved mapping, 409 'already_validating' while a "
            "run is in progress."
        ),
        request=None,
        responses={202: DatasetSerializer, **errors(403, 404, 409)},
    )
    @action(detail=True, methods=["post"], url_path="validate")
    def validate(self, request, *args, **kwargs):
        dataset = start_validation(dataset=self.get_object(), actor=request.user)
        return Response(DatasetSerializer(dataset).data, status=status.HTTP_202_ACCEPTED)

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        body = DatasetSerializer(serializer.instance).data
        return Response(body, status=status.HTTP_201_CREATED)
