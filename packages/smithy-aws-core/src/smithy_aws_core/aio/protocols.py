from typing import Any, Final

from smithy_core.codecs import Codec
from smithy_core.exceptions import DiscriminatorError
from smithy_core.schemas import APIOperation
from smithy_core.shapes import ShapeID, ShapeType
from smithy_http.aio.interfaces import HTTPErrorIdentifier, HTTPResponse
from smithy_http.aio.protocols import HttpBindingClientProtocol
from smithy_json import JSONCodec, JSONDocument

from ..traits import RestJson1Trait
from ..utils import parse_document_discriminator, parse_error_code


class AWSErrorIdentifier(HTTPErrorIdentifier):
    _HEADER_KEY: Final = "x-amzn-errortype"

    def identify(
        self,
        *,
        operation: APIOperation[Any, Any],
        response: HTTPResponse,
    ) -> ShapeID | None:
        if self._HEADER_KEY not in response.fields:
            return None

        error_field = response.fields[self._HEADER_KEY]
        code = error_field.values[0] if len(error_field.values) > 0 else None
        if code is not None:
            return parse_error_code(code, operation.schema.id.namespace)
        return None


class AWSJSONDocument(JSONDocument):
    @property
    def discriminator(self) -> ShapeID:
        if self.shape_type is ShapeType.STRUCTURE:
            return self._schema.id
        parsed = parse_document_discriminator(self, self._settings.default_namespace)
        if parsed is None:
            raise DiscriminatorError(
                f"Unable to parse discriminator for {self.shape_type} document."
            )
        return parsed


class RestJsonClientProtocol(HttpBindingClientProtocol):
    """An implementation of the aws.protocols#restJson1 protocol."""

    _id: Final = RestJson1Trait.id
    _codec: Final = JSONCodec(document_class=AWSJSONDocument)
    _contentType: Final = "application/json"
    _error_identifier: Final = AWSErrorIdentifier()

    @property
    def id(self) -> ShapeID:
        return self._id

    @property
    def payload_codec(self) -> Codec:
        return self._codec

    @property
    def content_type(self) -> str:
        return self._contentType

    @property
    def error_identifier(self) -> HTTPErrorIdentifier:
        return self._error_identifier
