# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0

from .providers import ProfileAssumeRoleProvider
from .resolvers import (
    AssumeRoleConfigurationError,
    AssumeRoleCredentialsResolver,
    ProfileAssumeRoleCredentialsResolver,
    resolve_sts_region,
)

__all__ = (
    "AssumeRoleConfigurationError",
    "AssumeRoleCredentialsResolver",
    "ProfileAssumeRoleCredentialsResolver",
    "ProfileAssumeRoleProvider",
    "resolve_sts_region",
)

__version__ = "0.1.0"
