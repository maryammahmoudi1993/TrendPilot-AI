from rest_framework import status
from rest_framework.exceptions import APIException


class LastOwnerError(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "A workspace must always keep at least one Owner."
    default_code = "last_owner"
