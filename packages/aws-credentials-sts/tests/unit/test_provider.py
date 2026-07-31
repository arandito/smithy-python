#  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#  SPDX-License-Identifier: Apache-2.0

from collections.abc import Callable, Mapping

import pytest
from aws_credentials_sts.providers import ProfileAssumeRoleProvider
from aws_credentials_sts.resolvers import ProfileAssumeRoleCredentialsResolver
from smithy_aws_core.config.file_parser import Section, StandardizedOutput
from smithy_aws_core.config.merged_config import MergedConfig
from smithy_aws_core.identity import AWSCredentialsIdentity
from smithy_aws_core.identity.chain import ChainSetup, StandardProvider
from smithy_core.interfaces.identity import Identity

ROLE_ARN = "arn:aws:iam::123456789012:role/MyRole"


class OtherIdentity(Identity):
    """A non-AWS identity type used to verify providers ignore unknown types."""


@pytest.fixture
def merged_config() -> Callable[..., MergedConfig]:
    def _build(profiles: Mapping[str, Mapping[str, str]]) -> MergedConfig:
        sections = {
            name: Section(properties=dict(properties))
            for name, properties in profiles.items()
        }
        return MergedConfig(StandardizedOutput(profiles=sections), StandardizedOutput())

    return _build


def _setup(
    profile_file: MergedConfig | None = None,
    profile_name: str | None = None,
) -> ChainSetup:
    setup = ChainSetup(config_file=profile_file, profile_name=profile_name)
    setup.set_current_provider(ProfileAssumeRoleProvider())
    return setup


def test_provider_name_and_ordering() -> None:
    provider = ProfileAssumeRoleProvider()
    assert provider.name == StandardProvider.PROFILE_ASSUME_ROLE.canonical_name
    assert provider.ordering.slot is StandardProvider.PROFILE_ASSUME_ROLE


async def test_ignores_non_aws_identity_type(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config({"default": {"role_arn": ROLE_ARN}})
    setup = _setup(profile_file=profile_file, profile_name="default")

    await ProfileAssumeRoleProvider().setup(OtherIdentity, setup)

    assert setup.resolvers == ()
    assert not setup.terminal


async def test_no_profile_name_skips() -> None:
    setup = _setup(profile_file=None, profile_name=None)

    await ProfileAssumeRoleProvider().setup(AWSCredentialsIdentity, setup)

    assert setup.resolvers == ()
    assert not setup.terminal


async def test_profile_without_role_arn_skips(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config({"default": {"region": "us-east-1"}})
    setup = _setup(profile_file=profile_file, profile_name="default")

    await ProfileAssumeRoleProvider().setup(AWSCredentialsIdentity, setup)

    assert setup.resolvers == ()
    assert not setup.terminal


async def test_registers_terminal_resolver_for_role_arn(
    merged_config: Callable[..., MergedConfig],
) -> None:
    profile_file = merged_config(
        {
            "default": {"role_arn": ROLE_ARN, "source_profile": "base"},
            "base": {
                "aws_access_key_id": "akid",
                "aws_secret_access_key": "secret",
            },
        }
    )
    setup = _setup(profile_file=profile_file, profile_name="default")

    await ProfileAssumeRoleProvider().setup(AWSCredentialsIdentity, setup)

    assert setup.terminal
    assert len(setup.resolvers) == 1
    assert isinstance(setup.resolvers[0].resolver, ProfileAssumeRoleCredentialsResolver)
