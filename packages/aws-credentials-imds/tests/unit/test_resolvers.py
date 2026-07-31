# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

# pyright: reportPrivateUsage=false
import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from aws_credentials_imds.client import IMDSConfig
from aws_credentials_imds.resolvers import IMDSCredentialsResolver
from smithy_core.exceptions import SmithyIdentityError

_CREDS = {
    "AccessKeyId": "test-access-key",
    "SecretAccessKey": "test-secret-key",
    "Token": "test-session-token",
    "AccountId": "test-account",
    "Expiration": "2025-03-13T07:28:47Z",
}


async def test_imds_credentials_resolver() -> None:
    # Test IMDSCredentialsResolver retrieving credentials
    http_client = AsyncMock()
    config = IMDSConfig()
    ec2_metadata = AsyncMock()
    resolver = IMDSCredentialsResolver(http_client, config)
    resolver._ec2_metadata_client = ec2_metadata

    # Mock IMDSClient get responses
    ec2_metadata.get.side_effect = ["test-profile", json.dumps(_CREDS)]

    credentials = await resolver.get_identity(properties={})
    assert credentials.access_key_id == "test-access-key"
    assert credentials.secret_access_key == "test-secret-key"
    assert credentials.session_token == "test-session-token"
    assert credentials.account_id == "test-account"
    assert credentials.expiration == datetime(2025, 3, 13, 7, 28, 47, tzinfo=UTC)
    ec2_metadata.get.assert_awaited()


async def test_resolver_uses_configured_profile_name() -> None:
    # When a profile name is configured, the resolver skips the profile lookup
    # and requests credentials for that profile directly.
    http_client = AsyncMock()
    config = IMDSConfig(ec2_instance_profile_name="configured-profile")
    ec2_metadata = AsyncMock()
    resolver = IMDSCredentialsResolver(http_client, config)
    resolver._ec2_metadata_client = ec2_metadata

    ec2_metadata.get.return_value = json.dumps(_CREDS)

    await resolver.get_identity(properties={})

    ec2_metadata.get.assert_awaited_once_with(
        path="/latest/meta-data/iam/security-credentials/configured-profile"
    )


async def test_resolver_caches_unexpired_credentials() -> None:
    # A second resolution returns cached credentials without querying IMDS again.
    http_client = AsyncMock()
    config = IMDSConfig()
    ec2_metadata = AsyncMock()
    resolver = IMDSCredentialsResolver(http_client, config)
    resolver._ec2_metadata_client = ec2_metadata

    future = datetime(9999, 1, 1, tzinfo=UTC).isoformat()
    ec2_metadata.get.side_effect = [
        "test-profile",
        json.dumps({**_CREDS, "Expiration": future}),
    ]

    first = await resolver.get_identity(properties={})
    second = await resolver.get_identity(properties={})

    assert first is second
    assert ec2_metadata.get.await_count == 2


async def test_resolver_invalidate_forces_refresh() -> None:
    http_client = AsyncMock()
    config = IMDSConfig()
    ec2_metadata = AsyncMock()
    resolver = IMDSCredentialsResolver(http_client, config)
    resolver._ec2_metadata_client = ec2_metadata

    future = datetime(9999, 1, 1, tzinfo=UTC).isoformat()
    ec2_metadata.get.side_effect = [
        "test-profile",
        json.dumps({**_CREDS, "Expiration": future}),
        "test-profile",
        json.dumps({**_CREDS, "Expiration": future}),
    ]

    await resolver.get_identity(properties={})
    await resolver.invalidate()
    await resolver.get_identity(properties={})

    # Both the profile lookup and the credential fetch run again after invalidate.
    assert ec2_metadata.get.await_count == 4


async def test_resolver_requires_access_key_and_secret() -> None:
    http_client = AsyncMock()
    config = IMDSConfig()
    ec2_metadata = AsyncMock()
    resolver = IMDSCredentialsResolver(http_client, config)
    resolver._ec2_metadata_client = ec2_metadata

    ec2_metadata.get.side_effect = [
        "test-profile",
        json.dumps({"AccessKeyId": "test-access-key"}),
    ]

    with pytest.raises(SmithyIdentityError):
        await resolver.get_identity(properties={})
