# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
# pyright: reportPrivateUsage=false
from unittest.mock import patch

import pytest
from aws_credentials_http import ContainerCredentialsResolver, EcsContainerProvider
from smithy_aws_core.identity import AWSCredentialsIdentity
from smithy_aws_core.identity.chain import Standard, StandardProvider
from smithy_aws_core.identity.chain.provider import ChainSetup
from smithy_core.interfaces.identity import Identity
from smithy_http.aio.interfaces import HTTPClient
from smithy_http.testing import MockHTTPClient

_RELATIVE_URI = "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"
_FULL_URI = "AWS_CONTAINER_CREDENTIALS_FULL_URI"


class OtherIdentity(Identity):
    """A non-AWS identity type used to verify providers ignore unknown types."""


async def _setup_provider(
    provider: EcsContainerProvider,
    *,
    identity_type: type[Identity] = AWSCredentialsIdentity,
    http_client: HTTPClient | None = None,
) -> ChainSetup:
    setup = ChainSetup(http_client=http_client)
    setup.set_current_provider(provider)
    await provider.setup(identity_type, setup)
    return setup


def _clear_uri_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(_RELATIVE_URI, raising=False)
    monkeypatch.delenv(_FULL_URI, raising=False)


def test_provider_metadata() -> None:
    provider = EcsContainerProvider()

    assert provider.name == "EcsContainer"
    assert provider.ordering == Standard(slot=StandardProvider.ECS_CONTAINER)


async def test_ignores_non_aws_identity_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_uri_environment(monkeypatch)
    monkeypatch.setenv(_RELATIVE_URI, "/credentials")

    setup = await _setup_provider(EcsContainerProvider(), identity_type=OtherIdentity)

    assert setup.resolvers == ()
    assert not setup.terminal


@pytest.mark.parametrize(
    ("relative_uri", "full_uri"),
    [
        (None, None),
        ("", None),
        (None, ""),
        ("", ""),
    ],
)
async def test_requires_configured_endpoint(
    relative_uri: str | None,
    full_uri: str | None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_uri_environment(monkeypatch)
    if relative_uri is not None:
        monkeypatch.setenv(_RELATIVE_URI, relative_uri)
    if full_uri is not None:
        monkeypatch.setenv(_FULL_URI, full_uri)

    setup = await _setup_provider(EcsContainerProvider())

    assert setup.resolvers == ()
    assert not setup.terminal


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (_RELATIVE_URI, "/credentials"),
        (_FULL_URI, "http://169.254.170.23/credentials"),
    ],
)
async def test_registers_terminal_resolver_with_shared_http_client(
    name: str,
    value: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_uri_environment(monkeypatch)
    monkeypatch.setenv(name, value)
    http_client = MockHTTPClient()

    setup = await _setup_provider(EcsContainerProvider(), http_client=http_client)

    assert setup.terminal
    assert len(setup.resolvers) == 1
    assert setup.resolvers[0].provider_name == "EcsContainer"
    resolver = setup.resolvers[0].resolver
    assert isinstance(resolver, ContainerCredentialsResolver)
    assert resolver._http_client is http_client


async def test_creates_default_http_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_uri_environment(monkeypatch)
    monkeypatch.setenv(_RELATIVE_URI, "/credentials")
    http_client = MockHTTPClient()

    with patch(
        "aws_credentials_http.providers.AIOHTTPClient", return_value=http_client
    ) as client_factory:
        setup = await _setup_provider(EcsContainerProvider())

    client_factory.assert_called_once_with()
    resolver = setup.resolvers[0].resolver
    assert isinstance(resolver, ContainerCredentialsResolver)
    assert resolver._http_client is http_client
