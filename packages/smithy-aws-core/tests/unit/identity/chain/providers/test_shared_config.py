#  Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
#  SPDX-License-Identifier: Apache-2.0
from collections.abc import Awaitable, Callable
from unittest.mock import AsyncMock

import pytest
from smithy_aws_core.config.merged_config import MergedConfig
from smithy_aws_core.identity.chain.ordering import StandardProvider
from smithy_aws_core.identity.chain.provider import ChainSetup
from smithy_aws_core.identity.chain.providers import (
    shared_config as shared_config_module,
)
from smithy_aws_core.identity.chain.providers.shared_config import SharedConfigProvider

from .conftest import OtherIdentity


async def test_ignores_non_aws_identity_type(
    setup_provider: Callable[..., Awaitable[ChainSetup]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    load_config = AsyncMock()
    monkeypatch.setattr(shared_config_module, "load_config", load_config)

    setup = await setup_provider(SharedConfigProvider(), identity_type=OtherIdentity)

    assert setup.resolvers == ()
    assert not setup.terminal
    load_config.assert_not_awaited()


# Profile selection precedence: profile_name wins over the AWS_PROFILE
# env var (environment_profile), which wins over the "default" fallback.
@pytest.mark.parametrize(
    "profile_name, environment_profile, expected",
    [
        ("override", "environment", "override"),
        (None, "environment", "environment"),
        (None, None, "default"),
    ],
)
async def test_selects_profile_without_reloading(
    profile_name: str | None,
    environment_profile: str | None,
    expected: str,
    setup_provider: Callable[..., Awaitable[ChainSetup]],
    merged_config: Callable[..., MergedConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_file = merged_config()
    if environment_profile is None:
        monkeypatch.delenv("AWS_PROFILE", raising=False)
    else:
        monkeypatch.setenv("AWS_PROFILE", environment_profile)
    load_config = AsyncMock()
    monkeypatch.setattr(shared_config_module, "load_config", load_config)

    setup = await setup_provider(
        SharedConfigProvider(),
        config_file=config_file,
        profile_name=profile_name,
    )

    assert setup.config_file is config_file
    assert setup.profile_name == expected
    assert setup.resolvers == ()
    load_config.assert_not_awaited()


async def test_loads_when_not_preloaded(
    setup_provider: Callable[..., Awaitable[ChainSetup]],
    merged_config: Callable[..., MergedConfig],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loaded = merged_config({"default": {"name": "loaded"}})
    load_config = AsyncMock(return_value=loaded)
    monkeypatch.setattr(shared_config_module, "load_config", load_config)
    monkeypatch.delenv("AWS_PROFILE", raising=False)

    setup = await setup_provider(SharedConfigProvider())

    assert setup.config_file is loaded
    assert setup.profile_name == "default"
    assert setup.resolvers == ()
    load_config.assert_awaited_once_with()


@pytest.mark.parametrize("source_property", ["source_profile", "credential_source"])
async def test_marks_profile_assume_role_as_detected(
    source_property: str,
    setup_provider: Callable[..., Awaitable[ChainSetup]],
    merged_config: Callable[..., MergedConfig],
) -> None:
    setup = await setup_provider(
        SharedConfigProvider(),
        config_file=merged_config(
            {
                "default": {
                    "role_arn": "arn:aws:iam::123456789012:role/test",
                    source_property: "source",
                }
            }
        ),
    )

    assert setup.is_detected(StandardProvider.PROFILE_ASSUME_ROLE)


@pytest.mark.parametrize(
    "profile",
    [
        {"role_arn": "arn:aws:iam::123456789012:role/test"},
        {"source_profile": "source"},
        {"credential_source": "Environment"},
    ],
)
async def test_does_not_mark_incomplete_profile_assume_role(
    profile: dict[str, str],
    setup_provider: Callable[..., Awaitable[ChainSetup]],
    merged_config: Callable[..., MergedConfig],
) -> None:
    setup = await setup_provider(
        SharedConfigProvider(),
        config_file=merged_config({"default": profile}),
    )

    assert not setup.is_detected(StandardProvider.PROFILE_ASSUME_ROLE)
