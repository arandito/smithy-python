#  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#  SPDX-License-Identifier: Apache-2.0

# pyright: reportPrivateUsage=false
from collections.abc import Callable, Mapping
from unittest.mock import AsyncMock

import pytest
from aws_credentials_sts.resolvers import (
    AssumeRoleConfigurationError,
    AssumeRoleCredentialsResolver,
    ProfileAssumeRoleCredentialsResolver,
    resolve_sts_region,
)
from smithy_aws_core.config.file_parser import Section, StandardizedOutput
from smithy_aws_core.config.merged_config import MergedConfig
from smithy_aws_core.identity import (
    AWSCredentialsIdentity,
    StaticCredentialsResolver,
)
from smithy_aws_core.identity.chain import ChainSetup, Standard, StandardProvider

ROLE_ARN = "arn:aws:iam::123456789012:role/MyRole"
SOURCE_ROLE_ARN = "arn:aws:iam::123456789012:role/SourceRole"


@pytest.fixture
def merged_config() -> Callable[..., MergedConfig]:
    def _build(profiles: Mapping[str, Mapping[str, str]]) -> MergedConfig:
        sections = {
            name: Section(properties=dict(properties))
            for name, properties in profiles.items()
        }
        return MergedConfig(StandardizedOutput(profiles=sections), StandardizedOutput())

    return _build


# ---------------------------------------------------------------------------
# resolve_sts_region
# ---------------------------------------------------------------------------


def test_resolve_sts_region_defaults_when_nothing_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)

    assert resolve_sts_region() == "us-east-1"


def test_resolve_sts_region_prefers_env(
    monkeypatch: pytest.MonkeyPatch,
    merged_config: Callable[..., MergedConfig],
) -> None:
    monkeypatch.setenv("AWS_REGION", "us-west-2")
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    profile_file = merged_config({"default": {"region": "eu-west-1"}})

    region = resolve_sts_region(profile_file=profile_file, profile_name="default")

    assert region == "us-west-2"


def test_resolve_sts_region_falls_back_to_default_region_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "ap-south-1")

    assert resolve_sts_region() == "ap-south-1"


def test_resolve_sts_region_reads_profile_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
    merged_config: Callable[..., MergedConfig],
) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    profile_file = merged_config({"default": {"region": "eu-west-1"}})

    region = resolve_sts_region(profile_file=profile_file, profile_name="default")

    assert region == "eu-west-1"


# ---------------------------------------------------------------------------
# ProfileAssumeRoleCredentialsResolver construction / validation
# ---------------------------------------------------------------------------


def test_missing_profile_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config({"default": {"region": "us-east-1"}})

    with pytest.raises(AssumeRoleConfigurationError, match="does not exist"):
        ProfileAssumeRoleCredentialsResolver(
            profile_name="missing", profile_file=profile_file
        )


def test_region_override_wins_over_profile(
    merged_config: Callable[..., MergedConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("AWS_REGION", raising=False)
    monkeypatch.delenv("AWS_DEFAULT_REGION", raising=False)
    profile_file = merged_config({"role": {"region": "eu-west-1"}})

    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role",
        profile_file=profile_file,
        region_override="us-west-2",
    )

    assert resolver._region == "us-west-2"


# ---------------------------------------------------------------------------
# source_profile chaining
# ---------------------------------------------------------------------------


async def test_source_profile_with_static_credentials(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {"role_arn": ROLE_ARN, "source_profile": "base"},
            "base": {
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
            },
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    delegate = await resolver._create_assume_role_resolver(
        profile_name="role", visited=("role",)
    )

    assert isinstance(delegate, AssumeRoleCredentialsResolver)
    assert delegate._role_arn == ROLE_ARN
    assert isinstance(delegate._source_resolver, StaticCredentialsResolver)
    identity = await delegate._source_resolver.get_identity(properties={})
    assert identity.access_key_id == "akid"
    assert identity.secret_access_key == "secret"


async def test_first_profile_credentials_ignored_in_favor_of_source(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {
                "role_arn": ROLE_ARN,
                "source_profile": "base",
                "aws_access_key_id": "ignored-akid",
                "aws_secret_access_key": "ignored-secret",
            },
            "base": {
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
            },
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    delegate = await resolver._create_assume_role_resolver(
        profile_name="role", visited=("role",)
    )

    assert isinstance(delegate._source_resolver, StaticCredentialsResolver)
    identity = await delegate._source_resolver.get_identity(properties={})
    assert identity.access_key_id == "akid"
    assert identity.secret_access_key == "secret"


async def test_external_id_and_duration_forwarded_to_delegate(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {
                "role_arn": ROLE_ARN,
                "source_profile": "base",
                "external_id": "my-external-id",
                "duration_seconds": "1800",
            },
            "base": {
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
            },
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    delegate = await resolver._create_assume_role_resolver(
        profile_name="role", visited=("role",)
    )

    assert delegate._external_id == "my-external-id"
    assert delegate._duration_seconds == 1800


async def test_external_id_and_duration_default_to_none(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {"role_arn": ROLE_ARN, "source_profile": "base"},
            "base": {
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
            },
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    delegate = await resolver._create_assume_role_resolver(
        profile_name="role", visited=("role",)
    )

    assert delegate._external_id is None
    assert delegate._duration_seconds is None


async def test_invalid_duration_seconds_is_ignored(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {
                "role_arn": ROLE_ARN,
                "source_profile": "base",
                "duration_seconds": "not-a-number",
            },
            "base": {
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
            },
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    delegate = await resolver._create_assume_role_resolver(
        profile_name="role", visited=("role",)
    )

    assert delegate._duration_seconds is None


async def test_nested_source_profile_role_chain(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {"role_arn": ROLE_ARN, "source_profile": "intermediate"},
            "intermediate": {
                "role_arn": SOURCE_ROLE_ARN,
                "source_profile": "base",
            },
            "base": {
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
            },
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    delegate = await resolver._create_assume_role_resolver(
        profile_name="role", visited=("role",)
    )

    # The outer role assumes via an inner AssumeRole resolver that itself
    # sources from the static base profile.
    assert isinstance(delegate, AssumeRoleCredentialsResolver)
    inner = delegate._source_resolver
    assert isinstance(inner, AssumeRoleCredentialsResolver)
    assert inner._role_arn == SOURCE_ROLE_ARN
    assert isinstance(inner._source_resolver, StaticCredentialsResolver)


async def test_chain_terminates_at_static_credentials(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {"role_arn": ROLE_ARN, "source_profile": "middle"},
            "middle": {
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
                "role_arn": SOURCE_ROLE_ARN,
                "source_profile": "base",
            },
            "base": {
                "aws_access_key_id": "unused-akid",
                "aws_secret_access_key": "unused-secret",
            },
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    delegate = await resolver._create_assume_role_resolver(
        profile_name="role", visited=("role",)
    )

    assert delegate._role_arn == ROLE_ARN
    assert isinstance(delegate._source_resolver, StaticCredentialsResolver)
    identity = await delegate._source_resolver.get_identity(properties={})
    assert identity.access_key_id == "akid"
    assert identity.secret_access_key == "secret"


async def test_circular_source_profile_with_static_credentials_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "a": {
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
                "role_arn": ROLE_ARN,
                "source_profile": "b",
            },
            "b": {"role_arn": SOURCE_ROLE_ARN, "source_profile": "a"},
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="a", profile_file=profile_file
    )

    with pytest.raises(AssumeRoleConfigurationError, match="Circular"):
        await resolver._create_assume_role_resolver(profile_name="a", visited=("a",))


async def test_missing_source_profile_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {"role": {"role_arn": ROLE_ARN, "source_profile": "ghost"}}
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    with pytest.raises(AssumeRoleConfigurationError, match="does not exist"):
        await resolver._create_assume_role_resolver(
            profile_name="role", visited=("role",)
        )


async def test_circular_source_profile_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "a": {"role_arn": ROLE_ARN, "source_profile": "b"},
            "b": {"role_arn": SOURCE_ROLE_ARN, "source_profile": "a"},
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="a", profile_file=profile_file
    )

    with pytest.raises(AssumeRoleConfigurationError, match="Circular"):
        await resolver._create_assume_role_resolver(profile_name="a", visited=("a",))


async def test_self_referencing_profile_requires_static_credentials(
    merged_config: Callable[..., MergedConfig],
) -> None:
    # A profile whose source_profile points at itself but has no static keys.
    profile_file = merged_config(
        {"role": {"role_arn": ROLE_ARN, "source_profile": "role"}}
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    with pytest.raises(
        AssumeRoleConfigurationError, match="complete static credentials"
    ):
        await resolver._create_assume_role_resolver(
            profile_name="role", visited=("role",)
        )


async def test_self_referencing_profile_with_static_credentials(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {
                "role_arn": ROLE_ARN,
                "source_profile": "role",
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
            }
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    delegate = await resolver._create_assume_role_resolver(
        profile_name="role", visited=("role",)
    )

    assert isinstance(delegate._source_resolver, StaticCredentialsResolver)


# ---------------------------------------------------------------------------
# configuration errors
# ---------------------------------------------------------------------------


async def test_missing_role_arn_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config({"role": {"source_profile": "base"}})
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    with pytest.raises(AssumeRoleConfigurationError, match="does not define role_arn"):
        await resolver._create_assume_role_resolver(
            profile_name="role", visited=("role",)
        )


async def test_both_source_and_credential_source_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {
                "role_arn": ROLE_ARN,
                "source_profile": "base",
                "credential_source": "Environment",
            }
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    with pytest.raises(AssumeRoleConfigurationError, match="cannot define both"):
        await resolver._create_assume_role_resolver(
            profile_name="role", visited=("role",)
        )


async def test_neither_source_nor_credential_source_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config({"role": {"role_arn": ROLE_ARN}})
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    with pytest.raises(AssumeRoleConfigurationError, match="must define either"):
        await resolver._create_assume_role_resolver(
            profile_name="role", visited=("role",)
        )


async def test_source_profile_without_credentials_or_role_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {"role_arn": ROLE_ARN, "source_profile": "base"},
            "base": {"region": "us-east-1"},
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    with pytest.raises(
        AssumeRoleConfigurationError, match="no supported credential source"
    ):
        await resolver._create_assume_role_resolver(
            profile_name="role", visited=("role",)
        )


async def test_partial_static_credentials_raise(
    merged_config: Callable[..., MergedConfig],
) -> None:
    # source profile has an access key but no secret key.
    profile_file = merged_config(
        {
            "role": {"role_arn": ROLE_ARN, "source_profile": "base"},
            "base": {"aws_access_key_id": "akid"},
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    with pytest.raises(AssumeRoleConfigurationError, match="partial credentials"):
        await resolver._create_assume_role_resolver(
            profile_name="role", visited=("role",)
        )


async def test_unsupported_credential_source_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {"role": {"role_arn": ROLE_ARN, "credential_source": "Bogus"}}
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    with pytest.raises(
        AssumeRoleConfigurationError, match="Unsupported credential_source"
    ):
        await resolver._create_assume_role_resolver(
            profile_name="role", visited=("role",)
        )


# ---------------------------------------------------------------------------
# credential_source
# ---------------------------------------------------------------------------


class _FakeProvider:
    """A chain provider that adds a single static resolver during setup."""

    def __init__(self, resolver: StaticCredentialsResolver) -> None:
        self._resolver = resolver

    @property
    def name(self) -> str:
        return StandardProvider.ENVIRONMENT.canonical_name

    @property
    def ordering(self) -> Standard:
        return Standard(slot=StandardProvider.ENVIRONMENT)

    async def setup(self, identity_type: object, setup: ChainSetup) -> None:
        setup.add_resolver(self._resolver)


@pytest.mark.parametrize(
    "credential_source",
    ["Environment", "EcsContainer", "Ec2InstanceMetadata"],
)
async def test_credential_source_builds_resolver_from_provider(
    merged_config: Callable[..., MergedConfig],
    credential_source: str,
) -> None:
    profile_file = merged_config(
        {"role": {"role_arn": ROLE_ARN, "credential_source": credential_source}}
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )
    static = StaticCredentialsResolver(
        AWSCredentialsIdentity(access_key_id="akid", secret_access_key="secret")
    )
    resolver._find_provider = lambda slot: _FakeProvider(static)  # type: ignore[assignment]

    delegate = await resolver._create_assume_role_resolver(
        profile_name="role", visited=("role",)
    )

    assert isinstance(delegate, AssumeRoleCredentialsResolver)
    identity = await delegate._source_resolver.get_identity(properties={})
    assert identity.access_key_id == "akid"


async def test_credential_source_no_installed_provider_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {"role": {"role_arn": ROLE_ARN, "credential_source": "Ec2InstanceMetadata"}}
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )
    resolver._find_provider = lambda slot: None  # type: ignore[assignment]

    with pytest.raises(AssumeRoleConfigurationError, match="No provider is installed"):
        await resolver._create_assume_role_resolver(
            profile_name="role", visited=("role",)
        )


async def test_credential_source_provider_registers_nothing_raises(
    merged_config: Callable[..., MergedConfig],
) -> None:
    class _EmptyProvider:
        async def setup(self, identity_type: object, setup: ChainSetup) -> None:
            return None

    profile_file = merged_config(
        {"role": {"role_arn": ROLE_ARN, "credential_source": "Environment"}}
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )
    resolver._find_provider = lambda slot: _EmptyProvider()  # type: ignore[assignment]

    with pytest.raises(AssumeRoleConfigurationError, match="is not configured"):
        await resolver._create_assume_role_resolver(
            profile_name="role", visited=("role",)
        )


# ---------------------------------------------------------------------------
# get_identity / invalidate delegation
# ---------------------------------------------------------------------------


async def test_get_identity_creates_and_reuses_delegate(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "role": {"role_arn": ROLE_ARN, "source_profile": "base"},
            "base": {
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
            },
        }
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )
    expected = AWSCredentialsIdentity(access_key_id="a", secret_access_key="s")
    delegate = AsyncMock()
    delegate.get_identity.return_value = expected

    async def _make_delegate(**kwargs: object) -> AsyncMock:
        return delegate

    resolver._create_assume_role_resolver = _make_delegate  # type: ignore[assignment]

    first = await resolver.get_identity(properties={})
    second = await resolver.get_identity(properties={})

    assert first is expected
    assert second is expected
    # The delegate is built once and reused across calls.
    assert resolver._delegate is delegate
    assert delegate.get_identity.await_count == 2


async def test_invalidate_before_setup_is_noop(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {"role": {"role_arn": ROLE_ARN, "source_profile": "base"}}
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )

    # No delegate has been created yet, so invalidate should not raise.
    await resolver.invalidate()
    assert resolver._delegate is None


async def test_invalidate_delegates_when_initialized(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {"role": {"role_arn": ROLE_ARN, "source_profile": "base"}}
    )
    resolver = ProfileAssumeRoleCredentialsResolver(
        profile_name="role", profile_file=profile_file
    )
    delegate = AsyncMock()
    resolver._delegate = delegate

    await resolver.invalidate()

    delegate.invalidate.assert_awaited_once()
