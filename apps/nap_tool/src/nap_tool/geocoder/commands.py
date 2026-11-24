# SPDX-FileCopyrightText: 2026 Chenyan Ye <https://github.com/yechenyan> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Jonathan Amme <https://github.com/nesnoj> © Reiner Lemoine Institut
# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""CLI shell for the place data and geocoding."""

from pathlib import Path

import typer

from nap_tool.data import data_dir

from .config import CONFIG_PATH, load_config
from .osm_data import OsmFetchResult
from .osm_data import fetch as fetch_osm
from .place_data import FetchResult, fetch, is_ignored
from .service import run

place_data_app = typer.Typer(help="Manage the offline place data (BKG GN250, OSM objects).")


def warn_if_not_ignored(root: Path) -> None:
    """Warn on stderr when git does not ignore the place data folder of the data repository.

    Args:
        root: Data repository root.
    """
    if is_ignored(root) is False:
        typer.echo(
            "Warning: place_data/ is not ignored in nap_data; add 'place_data/' to its .gitignore",
            err=True,
        )


def state_word(result: FetchResult | OsmFetchResult) -> str:
    """``repaired``, ``updated`` or ``unchanged`` for a fetch result.

    Args:
        result: Outcome of a place data or OSM fetch.

    Returns:
        The word printed after the version.
    """
    return "repaired" if result.repaired else ("updated" if result.changed else "unchanged")


@place_data_app.command(name="fetch")
def place_data_fetch(
    force: bool = typer.Option(False, "--force", help="Rebuild even if the download is unchanged"),
    config_path: Path = typer.Option(CONFIG_PATH, help="Geocoding YAML"),
) -> None:
    """Download BKG GN250 and build the offline place data."""
    try:
        root = data_dir()
        result = fetch(root, load_config(config_path).place_data, force=force)
    except (ValueError, RuntimeError, OSError) as error:
        typer.echo(f"Place data error: {error}", err=True)
        raise typer.Exit(1) from error
    warn_if_not_ignored(root)
    typer.echo(f"Place data {result.version} {state_word(result)}: {result.places} places")


@place_data_app.command(name="osm-fetch")
def osm_fetch(
    from_file: Path | None = typer.Option(
        None, "--from-file", help="Import a saved Overpass export instead of querying the server"
    ),
    force: bool = typer.Option(False, "--force", help="Rebuild even if the export is unchanged"),
    config_path: Path = typer.Option(CONFIG_PATH, help="Geocoding YAML"),
) -> None:
    """Fetch OSM substations and plants (Overpass) and store them as place data."""
    try:
        root = data_dir()
        content = from_file.read_bytes() if from_file else None
        result = fetch_osm(root, load_config(config_path).osm, force=force, content=content)
    except (ValueError, RuntimeError, OSError) as error:
        typer.echo(f"OSM data error: {error}", err=True)
        raise typer.Exit(1) from error
    warn_if_not_ignored(root)
    typer.echo(
        f"OSM data {result.version} {state_word(result)}: {result.objects} objects "
        f"({result.unnamed} unnamed skipped)"
    )


def geocode_command(
    scheme_id: int = typer.Option(..., min=1, help="Harmonization scheme to geocode"),
    set_id: int | None = typer.Option(
        None, min=1, help="Set to geocode (defaults to the scheme's initial set)"
    ),
    config_path: Path = typer.Option(CONFIG_PATH, help="Geocoding YAML"),
) -> None:
    """Geocode the current classification output of a set."""
    try:
        root = data_dir()
        result = run(root, scheme_id, config_path, set_id=set_id)
    except (ValueError, RuntimeError, OSError) as error:
        typer.echo(f"Geocoding error: {error}", err=True)
        raise typer.Exit(1) from error
    report = result.report
    typer.echo(
        f"Resolved: {report['resolved']} of {report['locations']} ({report['resolved_share']:.1%})"
    )
    for status, count in report["by_status"].items():
        typer.echo(f"{status}: {count}")
    typer.echo(f"Output: {root / 'geocoded'}")
