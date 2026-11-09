# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Loading and validating the provider registry (config/providers.yaml)."""

from enum import Enum
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SourceType(str, Enum):
    """How a provider's documents are obtained."""

    HUB = "hub"
    CUSTOM = "custom"
    MANUAL = "manual"
    VNBDIGITAL = "vnbdigital"


class HubConfig(BaseModel):
    """Shared hub page that lists documents for multiple providers."""

    url: str


class VnbDigitalConfig(BaseModel):
    """Configuration for VNBdigital, the shared German VNB document hub."""

    enabled: bool = True
    graphql_url: str = "https://www.vnbdigital.de/gateway/graphql"


class Provider(BaseModel):
    """One entry in the provider registry.

    Attributes:
        name: Human-readable provider name.
        slug: Filesystem-safe identifier; used as the folder name under
            data/raw/ and data/processed/.
        source_type: How this provider's documents are obtained.
        url: Direct download URL. Required when source_type is CUSTOM.
        hub_match: Link text/label used to find this provider on the hub
            page. Required when source_type is HUB.
        note: Free-text note, e.g. why a source is manual.
    """

    name: str
    slug: str
    source_type: SourceType
    url: str | None = None
    hub_match: str | None = None
    note: str | None = None


class ProvidersConfig(BaseModel):
    """Top-level shape of config/providers.yaml."""

    hub: HubConfig | None = None
    vnbdigital: VnbDigitalConfig = Field(default_factory=VnbDigitalConfig)
    providers: list[Provider] = Field(default_factory=list)


def load_providers(config_path: Path) -> ProvidersConfig:
    """Load and validate the provider registry.

    Args:
        config_path: Path to a providers.yaml file.

    Returns:
        Validated providers configuration.

    Raises:
        FileNotFoundError: If config_path does not exist.
        pydantic.ValidationError: If the YAML content doesn't match the schema.
    """
    with config_path.open(encoding="utf-8") as config_file:
        raw_config = yaml.safe_load(config_file)
    return ProvidersConfig.model_validate(raw_config)
