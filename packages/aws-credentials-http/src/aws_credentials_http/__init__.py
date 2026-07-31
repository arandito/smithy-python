# Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
# SPDX-License-Identifier: Apache-2.0
from .client import (
    ContainerMetadataClient,
    ContainerMetadataConfig,
)
from .providers import EcsContainerProvider
from .resolvers import ContainerCredentialsResolver

__version__ = "0.1.0"

__all__ = (
    "ContainerCredentialsResolver",
    "ContainerMetadataClient",
    "ContainerMetadataConfig",
    "EcsContainerProvider",
)
