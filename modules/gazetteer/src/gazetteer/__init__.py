# SPDX-FileCopyrightText: 2026 Hendrik Huyskens <https://github.com/henhuy> © Reiner Lemoine Institut
#
# SPDX-License-Identifier: Apache-2.0

"""Fuzzy-match place and station names against the gazetteer of one DSO."""

import argparse
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from rapidfuzz import fuzz

# Leading words that only say "this is a station", with any separator after them.
STATION_PREFIX = re.compile(
    r"^(?:uw|umspannwerk|umspannstation|umspannanlage|ons|ortsnetzstation|netzstation"
    r"|trafostation|schaltwerk|schaltstation|station)\b[\s.:-]*"
)


def gazetteer_path() -> Path:
    """Return the gazetteer file inside NAP_DATA_DIR.

    Returns:
        Absolute path of `gazetteer/gazetteer.sqlite`.

    Raises:
        SystemExit: If NAP_DATA_DIR is unset.
    """
    value = os.environ.get("NAP_DATA_DIR")
    if not value:
        raise SystemExit("error: NAP_DATA_DIR is required; set it to the nap_data directory")
    return Path(value).expanduser().resolve() / "gazetteer" / "gazetteer.sqlite"


def normalize(name: str) -> str:
    """Casefold (which maps ß to ss), collapse whitespace and strip station prefixes.

    Args:
        name: A queried or stored name.

    Returns:
        The comparable form; never empty for a non-blank name.
    """
    normalized = " ".join(name.casefold().split())
    return STATION_PREFIX.sub("", normalized) or normalized


def check_area(connection: sqlite3.Connection, dso: str, level: str | None) -> None:
    """Fail unless the gazetteer has an area for the DSO (and level, if given).

    Args:
        connection: Open gazetteer.
        dso: DSO MaStR number.
        level: Grid level or None.

    Raises:
        SystemExit: For an unknown DSO MaStR number or a level the DSO has no area for.
    """
    levels = [
        row[0]
        for row in connection.execute(
            "SELECT grid_level FROM dso_area WHERE dso_mastr_nr = ? ORDER BY grid_level", (dso,)
        )
    ]
    if not levels:
        raise SystemExit(f"error: unknown DSO MaStR number {dso}; it has no DSO area")
    if level is not None and level not in levels:
        raise SystemExit(
            f"error: DSO {dso} has no area for grid level {level}; known: {', '.join(levels)}"
        )


def load_entries(
    connection: sqlite3.Connection, dso: str, level: str | None, kind: str | None
) -> list[tuple[dict, set[str]]]:
    """Load the gazetteer entries inside one DSO's area.

    Args:
        connection: Open gazetteer.
        dso: DSO MaStR number.
        level: Grid level; None covers the union of all of the DSO's levels.
        kind: "place" or "station"; None covers both.

    Returns:
        Per entry its candidate fields (without score) and its normalized names.
    """
    rows = connection.execute(
        """
        SELECT DISTINCT entry_area.kind, entry_area.entry_id,
            coalesce(place.name, station.name), coalesce(place.osm, station.osm),
            coalesce(station.alt_names, '[]'), place.place_type, station.voltage, station.operator
        FROM entry_area
        LEFT JOIN place ON entry_area.kind = 'place' AND place.id = entry_area.entry_id
        LEFT JOIN station ON entry_area.kind = 'station' AND station.id = entry_area.entry_id
        WHERE dso_mastr_nr = :dso
            AND (:level IS NULL OR grid_level = :level)
            AND (:kind IS NULL OR entry_area.kind = :kind)
        """,
        {"dso": dso, "level": level, "kind": kind},
    )
    entries = []
    for kind, _, name, osm, alt_names, place_type, voltage, operator in rows:
        details = (
            {"place_type": place_type}
            if kind == "place"
            else {"voltage": voltage, "operator": operator}
        )
        entries.append(
            (
                {"name": name, "kind": kind, "osm": osm, **details},
                {normalize(each) for each in [name, *json.loads(alt_names)]},
            )
        )
    return entries


def match(entries: list[tuple[dict, set[str]]], query: str, limit: int) -> list[dict]:
    """Rank the entries for one query by their best-matching name.

    Args:
        entries: Entries from `load_entries`.
        query: Queried name.
        limit: Maximum number of candidates.

    Returns:
        Up to `limit` candidates, best first; entries scoring 0 are no match.
    """
    query = normalize(query)
    candidates = []
    # ponytail: linear scan over one DSO's entries; use rapidfuzz.process.cdist if DSOs get huge.
    for candidate, names in entries:
        score = round(max(fuzz.WRatio(query, name) for name in names), 1)
        if score > 0:
            candidates.append(
                {"name": candidate["name"], "kind": candidate["kind"], "score": score, **candidate}
            )
    candidates.sort(key=lambda candidate: (-candidate["score"], candidate["name"]))
    return candidates[:limit]


def positive_int(value: str) -> int:
    """Parse a count of at least 1 for argparse.

    Args:
        value: Command-line value.

    Returns:
        The count.

    Raises:
        argparse.ArgumentTypeError: If the value is not a positive integer.
    """
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError(f"must be a positive integer: {value}")
    return int(value)


def main(argv: list[str] | None = None) -> None:
    """Run `gazetteer`.

    Args:
        argv: Command-line arguments; defaults to `sys.argv`.

    Raises:
        SystemExit: For a missing gazetteer, an unknown DSO or level, or invalid arguments.
    """
    parser = argparse.ArgumentParser(prog="gazetteer")
    commands = parser.add_subparsers(required=True)
    match_parser = commands.add_parser(
        "match", help="Print one JSON line of ranked candidates per queried name."
    )
    match_parser.add_argument("--dso", required=True, help="MaStR number of the DSO")
    match_parser.add_argument("--kind", choices=["place", "station"], help="default: both")
    match_parser.add_argument(
        "--level", help="grid level of the DSO area, e.g. HV; default: all levels"
    )
    match_parser.add_argument(
        "-n", type=positive_int, default=5, help="candidates per name (default: 5)"
    )
    match_parser.add_argument("names", nargs="+", metavar="NAME")
    args = parser.parse_args(argv)
    path = gazetteer_path()
    if not path.is_file():
        raise SystemExit(
            f"error: gazetteer not found at {path}; build it with `gazetteer-build` "
            "(modules/gazetteer_build) and check NAP_DATA_DIR"
        )
    with closing(sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)) as connection:
        check_area(connection, args.dso, args.level)
        entries = load_entries(connection, args.dso, args.level, args.kind)
    for query in args.names:
        print(
            json.dumps(
                {"q": query, "candidates": match(entries, query, args.n)}, ensure_ascii=False
            )
        )
