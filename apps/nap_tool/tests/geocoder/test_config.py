# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Geocoding configuration."""

from pathlib import Path

import pytest

from nap_tool.geocoder.config import load_config


def test_default_config_loads() -> None:
    config = load_config()
    assert config.place_data.url.endswith("/gn250/aktuell/gn250.utm32s.csv.zip")
    assert config.place_data.member == "gn250/GN250.csv"
    assert config.place_data.object_classes == ["AX_Gemeinde", "AX_Ortslage"]
    assert "nord" in config.matching.suffix_words
    assert config.matching.max_anchor_km == 100
    assert config.matching.min_anchor_points == 3


def test_invalid_yaml_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "geocode.yaml"
    path.write_text("place_data: [", encoding="utf-8")
    with pytest.raises(ValueError, match="Invalid geocoding YAML"):
        load_config(path)


def test_invalid_values_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "geocode.yaml"
    path.write_text(
        "place_data: {url: 'https://example.test/x.zip'}\nmatching: {max_anchor_km: 0}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError):
        load_config(path)


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    path = tmp_path / "geocode.yaml"
    path.write_text(
        "place_data: {url: 'https://example.test/x.zip'}\nmatching: {suffix_word: [nord]}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="suffix_word"):
        load_config(path)


def test_osm_defaults_load() -> None:
    osm = load_config().osm
    assert osm.classes == ["substation", "plant"]
    assert osm.kinds["substation"] == ["substation"]
    assert osm.kinds["place"] == ["plant"]
    assert set(osm.rescue_only_kinds) == {"place", "search_area"}
    assert "umspannwerk" in osm.strip_words
    assert osm.max_km == 15


def test_osm_kind_with_unknown_class_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "geocode.yaml"
    path.write_text(
        "place_data: {url: 'https://example.test/x.zip'}\n"
        "osm: {classes: [substation], kinds: {place: [plant]}}\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="plant"):
        load_config(path)
