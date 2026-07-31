#  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#  SPDX-License-Identifier: Apache-2.0

# pyright: reportPrivateUsage=false
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock

import pytest
from aws_credentials_sts.resolvers import (
    AssumeRoleCredentialsResolver,
    _account_id_from_arn,
)
from aws_sdk_sts.models import (
    AssumedRoleUser,
    AssumeRoleOutput,
    Credentials,
)
from smithy_core.exceptions import SmithyIdentityError

ROLE_ARN = "arn:aws:iam::123456789012:role/MyRole"
ASSUMED_ROLE_ARN = "arn:aws:sts::123456789012:assumed-role/MyRole/session"
ACCESS_KEY_ID = "test-access-key"
SECRET_ACCESS_KEY = "test-secret-key"
SESSION_TOKEN = "test-session-token"


def _future_expiry() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


def _past_expiry() -> datetime:
    return datetime.now(UTC) - timedelta(hours=1)


def _valid_output(
    *, access_key_id: str = ACCESS_KEY_ID, expiration: datetime | None = None
) -> AssumeRoleOutput:
    """An AssumeRole response with valid credentials and assumed-role user."""
    return AssumeRoleOutput(
        credentials=Credentials(
            access_key_id=access_key_id,
            secret_access_key=SECRET_ACCESS_KEY,
            session_token=SESSION_TOKEN,
            expiration=expiration or _future_expiry(),
        ),
        assumed_role_user=AssumedRoleUser(assumed_role_id="id", arn=ASSUMED_ROLE_ARN),
    )


def _mock_sts_client(
    resolver: AssumeRoleCredentialsResolver, *responses: AssumeRoleOutput
) -> AsyncMock:
    """Attach a mock STS client returning one response per AssumeRole call."""
    client = AsyncMock()
    client.assume_role.side_effect = list(responses)
    resolver._client = client
    return client


@pytest.mark.parametrize(
    "arn,expected",
    [
        (ASSUMED_ROLE_ARN, "123456789012"),
        ("arn:aws:sts:::assumed-role/MyRole/session", None),  # empty account field
        ("not-an-arn", None),  # too few segments
        (None, None),
    ],
)
def test_account_id_from_arn(arn: str | None, expected: str | None) -> None:
    assert _account_id_from_arn(arn) == expected


async def test_resolves_identity_from_assume_role() -> None:
    expiration = _future_expiry()
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=AsyncMock(), role_arn=ROLE_ARN
    )
    _mock_sts_client(resolver, _valid_output(expiration=expiration))

    identity = await resolver.get_identity(properties={})

    assert identity.access_key_id == ACCESS_KEY_ID
    assert identity.secret_access_key == SECRET_ACCESS_KEY
    assert identity.session_token == SESSION_TOKEN
    assert identity.expiration == expiration
    assert identity.account_id == "123456789012"


async def test_missing_credentials_raises() -> None:
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=AsyncMock(), role_arn=ROLE_ARN
    )
    _mock_sts_client(resolver, AssumeRoleOutput(credentials=None))

    with pytest.raises(SmithyIdentityError, match="did not contain credentials"):
        await resolver.get_identity(properties={})


async def test_valid_credentials_reused() -> None:
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=AsyncMock(), role_arn=ROLE_ARN
    )
    sts_client = _mock_sts_client(
        resolver,
        _valid_output(access_key_id="test-access-key-1"),
        _valid_output(access_key_id="test-access-key-2"),
    )

    identity_one = await resolver.get_identity(properties={})
    identity_two = await resolver.get_identity(properties={})

    # The cached identity is returned without a second STS call.
    assert identity_one is identity_two
    assert sts_client.assume_role.call_count == 1


async def test_expired_credentials_refreshed() -> None:
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=AsyncMock(), role_arn=ROLE_ARN
    )
    sts_client = _mock_sts_client(
        resolver,
        _valid_output(access_key_id="test-access-key-1", expiration=_past_expiry()),
        _valid_output(access_key_id="test-access-key-2"),
    )

    identity_one = await resolver.get_identity(properties={})
    identity_two = await resolver.get_identity(properties={})

    # The cached identity is refreshed with a second STS call.
    assert identity_one is not identity_two
    assert identity_one.access_key_id == "test-access-key-1"
    assert identity_two.access_key_id == "test-access-key-2"
    assert sts_client.assume_role.call_count == 2


async def test_assume_role_request_uses_role_arn() -> None:
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=AsyncMock(),
        role_arn=ROLE_ARN,
        role_session_name="test-session-name",
    )
    sts_client = _mock_sts_client(resolver, _valid_output())

    await resolver.get_identity(properties={})

    request = sts_client.assume_role.call_args.args[0]
    assert request.role_arn == ROLE_ARN
    assert request.role_session_name == "test-session-name"


async def test_assume_role_request_forwards_external_id_and_duration() -> None:
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=AsyncMock(),
        role_arn=ROLE_ARN,
        external_id="my-external-id",
        duration_seconds=1800,
    )
    sts_client = _mock_sts_client(resolver, _valid_output())

    await resolver.get_identity(properties={})

    request = sts_client.assume_role.call_args.args[0]
    assert request.external_id == "my-external-id"
    assert request.duration_seconds == 1800


async def test_assume_role_request_omits_optional_fields_by_default() -> None:
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=AsyncMock(), role_arn=ROLE_ARN
    )
    sts_client = _mock_sts_client(resolver, _valid_output())

    await resolver.get_identity(properties={})

    request = sts_client.assume_role.call_args.args[0]
    assert request.external_id is None
    assert request.duration_seconds is None


async def test_role_session_name_generated_when_unset() -> None:
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=AsyncMock(), role_arn=ROLE_ARN
    )
    sts_client = _mock_sts_client(resolver, _valid_output())

    await resolver.get_identity(properties={})

    request = sts_client.assume_role.call_args.args[0]
    assert request.role_session_name.startswith("aws-sdk-python-")


async def test_role_session_name_stable_across_refreshes() -> None:
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=AsyncMock(), role_arn=ROLE_ARN
    )
    sts_client = _mock_sts_client(
        resolver,
        _valid_output(expiration=_past_expiry()),
        _valid_output(),
    )

    await resolver.get_identity(properties={})
    await resolver.get_identity(properties={})

    first, second = sts_client.assume_role.call_args_list
    assert first.args[0].role_session_name == second.args[0].role_session_name


async def test_invalidate_clears_cache_and_source() -> None:
    source_resolver = AsyncMock()
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=source_resolver, role_arn=ROLE_ARN
    )
    sts_client = _mock_sts_client(
        resolver,
        _valid_output(access_key_id="test-access-key-1"),
        _valid_output(access_key_id="test-access-key-2"),
    )

    identity_one = await resolver.get_identity(properties={})
    await resolver.invalidate()
    identity_two = await resolver.get_identity(properties={})

    # invalidate() drops the cache so a fresh STS call is made, and it
    # propagates to the source resolver.
    assert identity_one.access_key_id == "test-access-key-1"
    assert identity_two.access_key_id == "test-access-key-2"
    assert sts_client.assume_role.call_count == 2
    source_resolver.invalidate.assert_awaited_once()


async def test_credentials_without_expiration_are_cached() -> None:
    # AWSCredentialsIdentity.is_expired is False when expiration is None, so a
    # credential with no expiration is treated as non-expiring and reused.
    resolver = AssumeRoleCredentialsResolver(
        source_resolver=AsyncMock(), role_arn=ROLE_ARN
    )
    output = AssumeRoleOutput(
        credentials=Credentials(
            access_key_id=ACCESS_KEY_ID,
            secret_access_key=SECRET_ACCESS_KEY,
            session_token=SESSION_TOKEN,
            expiration=None,  # type: ignore[arg-type]
        ),
        assumed_role_user=AssumedRoleUser(assumed_role_id="id", arn=ASSUMED_ROLE_ARN),
    )
    sts_client = _mock_sts_client(resolver, output, _valid_output())

    await resolver.get_identity(properties={})
    await resolver.get_identity(properties={})

    assert sts_client.assume_role.call_count == 1
