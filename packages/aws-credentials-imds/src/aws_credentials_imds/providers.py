# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
import os
from typing import Literal
from urllib.parse import urlsplit

from smithy_aws_core.identity import AWSCredentialsIdentity
from smithy_aws_core.identity.chain import Standard, StandardProvider
from smithy_aws_core.identity.chain.provider import ChainSetup
from smithy_core import URI
from smithy_core.interfaces.identity import Identity
from smithy_http.aio.aiohttp import AIOHTTPClient

from .client import IMDSConfig
from .resolvers import IMDSCredentialsResolver

_DISABLED_ENV = "AWS_EC2_METADATA_DISABLED"
_DISABLED_PROFILE = "disable_ec2_metadata"
_ENDPOINT_ENV = "AWS_EC2_METADATA_SERVICE_ENDPOINT"
_ENDPOINT_PROFILE = "ec2_metadata_service_endpoint"
_ENDPOINT_MODE_ENV = "AWS_EC2_METADATA_SERVICE_ENDPOINT_MODE"
_ENDPOINT_MODE_PROFILE = "ec2_metadata_service_endpoint_mode"
_PROFILE_NAME_ENV = "AWS_EC2_INSTANCE_PROFILE_NAME"
_PROFILE_NAME_PROFILE = "ec2_instance_profile_name"


def _profile_value(setup: ChainSetup, key: str) -> str | None:
    config_file = setup.config_file
    profile_name = setup.profile_name
    if config_file is None or profile_name is None:
        return None
    return config_file.get(profile_name, key)


def _resolve_value(
    setup: ChainSetup,
    env_name: str,
    profile_key: str,
) -> str | None:
    env_value = os.environ.get(env_name)
    if env_value:
        return env_value
    return _profile_value(setup, profile_key)


def _parse_endpoint(value: str | None) -> URI | None:
    if value is None:
        return None

    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError as error:
        raise ValueError(f"Invalid IMDS endpoint URI: {value}") from error

    if not parsed.scheme or parsed.hostname is None:
        raise ValueError(f"Invalid IMDS endpoint URI: {value}")

    return URI(
        scheme=parsed.scheme,
        username=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=port,
        path=parsed.path or None,
        query=parsed.query or None,
        fragment=parsed.fragment or None,
    )


def _parse_endpoint_mode(value: str | None) -> Literal["IPv4", "IPv6"]:
    if value is None:
        return "IPv4"

    normalized = value.casefold()
    if normalized == "ipv4":
        return "IPv4"
    if normalized == "ipv6":
        return "IPv6"
    raise ValueError(
        f"Invalid IMDS endpoint mode {value!r}; expected 'IPv4' or 'IPv6'."
    )


def _validate_profile_name(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("The configured EC2 instance profile name must not be blank.")
    return value


class Ec2InstanceMetadataProvider:
    """Adds the EC2 instance metadata resolver to the credential chain."""

    @property
    def name(self) -> str:
        """Return the canonical provider name."""
        return StandardProvider.EC2_INSTANCE_METADATA.canonical_name

    @property
    def ordering(self) -> Standard:
        """Return the provider's standard chain position."""
        return Standard(slot=StandardProvider.EC2_INSTANCE_METADATA)

    async def setup(
        self,
        identity_type: type[Identity],
        setup: ChainSetup,
    ) -> None:
        """Add IMDS as a non-terminal resolver."""
        if identity_type is not AWSCredentialsIdentity:
            return

        disabled = _resolve_value(setup, _DISABLED_ENV, _DISABLED_PROFILE)
        if disabled is not None and disabled.casefold() == "true":
            return

        endpoint = _resolve_value(setup, _ENDPOINT_ENV, _ENDPOINT_PROFILE)
        endpoint_mode = _resolve_value(
            setup, _ENDPOINT_MODE_ENV, _ENDPOINT_MODE_PROFILE
        )
        profile_name = _resolve_value(setup, _PROFILE_NAME_ENV, _PROFILE_NAME_PROFILE)
        config = IMDSConfig(
            endpoint_uri=_parse_endpoint(endpoint),
            endpoint_mode=_parse_endpoint_mode(endpoint_mode),
            ec2_instance_profile_name=_validate_profile_name(profile_name),
        )
        setup.add_resolver(
            IMDSCredentialsResolver(
                http_client=setup.http_client or AIOHTTPClient(),
                config=config,
            )
        )
