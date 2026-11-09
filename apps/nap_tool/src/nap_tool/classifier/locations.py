"""Location names from measure names and descriptions (deterministic, no geocoding).

Word lists and station keywords come from the ``locations`` section of the classification
YAML; the structural patterns (route separators, station-name shape, street names) are
defined here. A location is returned as written in the source, with a kind that tells how
to geocode it: a station type (``substation``, ``switching_station``, ``local_substation``),
``search_area``, ``street_address``, ``code`` or ``place``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .config import ClassifyConfig

# Voltages ("110 kV", "110/10-kV", "0,4 kV"); kVA/kvar do not match because of \b.
KV_RE = re.compile(
    r"(?<![\d.,])(\d{1,3}(?:[.,]\d{1,2})?(?:\s*-?\s*/\s*\d{1,3}(?:[.,]\d{1,2})?)*)\s*-?\s*kv\b",
    re.I,
)
SEP_RE = re.compile(
    r"\s+[-–—]+\s+|\s*(?:<->|<-->|->|-->|=>|→|↔|>)\s*|\s+nach\s+|\s+bis\s+(?:zum\s+|zur\s+)?|"
    r"(?<=\w)[-–]\s+(?=[A-ZÄÖÜ])|\s+[-–](?=[A-ZÄÖÜ])"
)
BETWEEN_RE = re.compile(r"zwischen\s+(?:den\s+\w+\s+|dem\s+\w+\s+)?(.+?)\s+und\s+(.+)", re.I)
FROM_TO_RE = re.compile(
    r"\bvon\s+(?:der\s+|dem\s+)?(.+?)\s+(?:nach|bis(?:\s+zu[mr])?)\s+(.+)", re.I
)
HYPHEN_PAIR_RE = re.compile(
    r"^([A-ZÄÖÜ][\w.äöüß/]+(?:\s[A-ZÄÖÜ][\w.äöüß/]+)?)[-–]"
    r"([A-ZÄÖÜ][\w.äöüß/]+(?:\s[A-ZÄÖÜ][\w.äöüß/]+)?)$"
)
COMPASS = {"nord", "süd", "ost", "west", "mitte", "nordost", "nordwest", "südost", "südwest"}
ID_TOKEN = re.compile(
    r"^(?:[A-Z]{1,3}\d{1,4}[a-z]?|\d+[_/]\w+|\w*_\w*|t\+\d+|\d+x|\d+-syst\.?)$", re.I
)
NOISE_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*mm²?|\b\d+\s*x\s*\d*|\bT\s*\+\s*\d+|"
    r"\b(?:19|20)\d{2}(?:\s*[-/]\s*(?:19|20)?\d{2})?\b|\d{1,2}\.\d{1,2}\.\d{2,4}|"
    r"\b\d+(?:[.,]\d+)?\s*(?:mvar|mva|km|m|kva)\b|\d+\s*-?\s*°\s*-?\s*c|\(.*?\)|\[.*?\]",
    re.I,
)
STREET_RE = re.compile(
    r"(?:str\.?|straße|strasse|weg|platz|allee|gasse|ring|damm|ufer|steig|pfad|chaussee)$", re.I
)
STREET_PREFIX_RE = re.compile(
    r"^(?:Am|An der|An den|Im|In der|In den|Zum|Zur|Auf der|Auf dem|Hinter der|Unter den|"
    r"Vor dem)\s+[A-ZÄÖÜ]"
)
NAME_TAIL = (
    r"(?P<name>(?:[A-ZÄÖÜ0-9\"„][\w.\-/\"“äöüßÄÖÜ]*)(?:\s+(?:[A-ZÄÖÜ0-9][\w.\-/äöüßÄÖÜ]*|am|"
    r"an der|im|ob der|bei|a\.d\.|i\.))*?)(?=\s*$|\s*[,;:()]|\s+[-–>]|"
    r"\s+(?:nach|bis|und|zum|zur|in)\b|\s+[a-zäöü])"
)

Place = tuple[str, str]


@dataclass
class Locations:
    """Locations found in one text."""

    places: list[Place] = field(default_factory=list)
    how: str = ""


class LocationFinder:
    """Find location names in measure texts with the configured word lists.

    Args:
        config: Classification configuration with a ``locations`` section.
    """

    def __init__(self, config: ClassifyConfig) -> None:
        settings = config.locations
        self.kinds = [
            (kind, re.compile(rf"(?:{'|'.join(keywords)})", re.I))
            for kind, keywords in settings["types"].items()
        ]
        keywords = "|".join(k for words in settings["types"].values() for k in words)
        self.station_name = re.compile(rf"(?i:\b(?P<kw>{keywords})\b)\.?:?\s+{NAME_TAIL}")
        self.strip = [re.compile(pattern, re.I) for pattern in settings["strip_patterns"]]
        self.stop_words = {word.lower() for word in settings["stop_words"]}
        self.stop_suffix = re.compile(rf"({'|'.join(settings['stop_suffixes'])})$")
        self.connectors = {word.lower() for word in settings["connectors"]}

    def keyword_kind(self, keyword: str) -> str:
        """Location kind for a station keyword such as ``UW`` or ``Suchraum``."""
        return next((kind for kind, rx in self.kinds if rx.fullmatch(keyword)), "place")

    def is_stop(self, token: str, suffixes: bool = True) -> bool:
        """Tell whether a token is a measure, asset or technical word rather than a name.

        Args:
            token: One word of the text.
            suffixes: Apply the stop suffixes ("-ung", "-trasse"); off for the words right
                after a station keyword, where "UW Breitungen" names a place.

        Returns:
            True when the token is not part of a name.
        """
        word = token.lower().strip(".,:;!?\"„“'()")
        if not word:
            return True
        if word in self.stop_words or KV_RE.fullmatch(word) or re.fullmatch(r"[\d.,/\-+]+", word):
            return True
        if STREET_RE.search(word):  # 'Bergstrasse' is a street, not a 'Trasse'
            return False
        match = self.stop_suffix.search(word) if suffixes else None
        if match and len(word) >= len(match.group(1)) + 2:
            return True
        if "-" in word or "/" in word:  # compounds such as 'HS-Kabel', 'Ausbau/ENB'
            parts = [part for part in re.split(r"[-/]", word) if part]
            return all(len(part) == 1 or self.is_stop(part, suffixes) for part in parts)
        return False

    def clean(self, text: str, suffixes: bool = True) -> str | None:
        """Keep runs of capitalised name tokens; drop measure words, voltages, IDs and years.

        A dropped word breaks the run; connectors ('am', 'in der') are kept only inside a
        run; house numbers are kept directly after a street name.

        Args:
            text: Text fragment.
            suffixes: Apply the stop suffixes (see ``is_stop``) also to the first word.

        Returns:
            The location name, or None.
        """
        text = KV_RE.sub(" ", text)
        text = NOISE_RE.sub(" ", text).replace("_", " ")
        runs: list[list[str]] = [[]]

        def split_run() -> None:
            if runs[-1]:
                runs.append([])

        for token in [item for item in re.split(r"\s+|:", text) if item]:
            core = token.strip(",;:()\"„“'&+")
            # Only the first word after a station keyword is exempt ("UW Breitungen").
            check = suffixes or any(runs)
            if core == "St" and token.endswith("."):  # 'St. Peter' = Sankt
                runs[-1].append("St.")
                continue
            if (
                runs[-1]
                and re.fullmatch(r"\d{1,4}[a-z]?(?:-\d{1,4}[a-z]?)?", core)
                and STREET_RE.search(runs[-1][-1])
            ):
                runs[-1].append(core)
                continue
            if (
                not core
                or core.endswith("-")
                or self.is_stop(core, check)
                or ID_TOKEN.fullmatch(core)
            ):
                split_run()
                continue
            if "-" in core:  # 'UW-Klausdorf' -> 'Klausdorf'
                parts = core.split("-")
                while parts and (not parts[0] or self.is_stop(parts[0], check)):
                    parts.pop(0)
                while parts and (not parts[-1] or self.is_stop(parts[-1], check)):
                    parts.pop()
                core = "-".join(parts)
                if not core:
                    split_run()
                    continue
            if core[0].islower() and core.lower() not in self.connectors:
                split_run()
                continue
            runs[-1].append(core)
        names = []
        for run in runs:
            while run and run[0][0].islower():
                run.pop(0)
            while run and run[-1].lower() in self.connectors and run[-1][0].islower():
                run.pop()
            if run and re.search(r"[A-Za-zÄÖÜäöüß]{2}", " ".join(run)):
                names.append(" ".join(run))
        location = " ".join(names).strip(" -–,;:/")
        return location or None

    def station_names(self, text: str) -> list[Place]:
        """Station names after a station keyword, with the keyword's kind."""
        places: list[Place] = []
        for match in self.station_name.finditer(text):
            name = self.clean(match.group("name"), suffixes=False)
            if name and name not in [place[0] for place in places]:
                places.append((name, self.keyword_kind(match.group("kw"))))
        return places

    def place(self, fragment: str, text: str) -> Place | None:
        """A station name in the fragment, else its cleaned words with a geocoding kind."""
        names = self.station_names(fragment)
        if names:
            return names[0]
        name = self.clean(fragment)
        return (name, geocoding_kind(name, text)) if name else None

    def find(self, text: str, line_like: bool, strict: bool) -> Locations:
        """Find locations in a measure name or description.

        Args:
            text: Measure name or description.
            line_like: Whether the asset is a line, so routes are split into endpoints.
            strict: Accept only station names and explicit endpoints (descriptions).

        Returns:
            Locations in source order and how they were found: ``endpoints``,
            ``endpoints_hyphen``, ``endpoints_route``, ``station_name``, ``plain`` or "".
        """
        if not text or not text.strip():
            return Locations()
        text = re.sub(r"\s+", " ", text).strip()
        for pattern in self.strip:
            text = pattern.sub(" ", text)
        original = text
        parens = re.findall(r"\((.*?)\)", text)
        text = re.sub(r"\(.*?\)", " ", text).strip()
        # Underscore chains: a route for lines, an address hierarchy otherwise.
        underscore = bool(re.search(r"[A-Za-zÄÖÜäöüß.]_[A-Za-zÄÖÜäöüß]", text))
        plain_segments = [part.strip() for part in re.split(r"[;,]", text) if part.strip()]
        segments = (
            [part.strip() for part in re.split(r"[;,_]", text) if part.strip()]
            if underscore
            else plain_segments
        )
        for index in range(len(segments) - 1, 0, -1):
            if re.fullmatch(r"(?i)str\.?|straße|strasse|weg", segments[index]):
                segments[index - 1] = f"{segments[index - 1]} {segments.pop(index)}"
        if line_like:
            for segment in plain_segments + (segments if underscore else []):
                route = self.route(segment, original)
                if route:
                    return Locations(route, "endpoints")
        names = [place for segment in segments for place in self.station_names(segment)]
        names = list(dict.fromkeys(names))
        if names:
            if line_like and len(names) >= 2:
                return Locations(names, "endpoints")
            return Locations(names, "station_name")
        if strict:
            return self.in_parentheses(parens)
        places: list[Place] = []
        for segment in segments:
            for part in SEP_RE.split(segment) if not line_like else [segment]:
                name = self.clean(part)
                if name and name not in [place[0] for place in places]:
                    if not (underscore and is_code(name)):
                        places.append((name, geocoding_kind(name, original)))
        if (
            line_like
            and underscore
            and len(places) >= 2
            and not any(
                STREET_RE.search(name.split()[-1].rstrip(".0123456789")) for name, _ in places
            )
            and not any(STREET_PREFIX_RE.match(name) for name, _ in places)
        ):
            last = places[-1]
            match = HYPHEN_PAIR_RE.match(last[0])
            if match and match.group(2).lower() not in COMPASS:  # 'Stromhütte-Heide' -> 'Heide'
                last = (match.group(2), last[1])
            return Locations([*places[:-1], last], "endpoints_route")
        if line_like and len(places) == 1:
            match = HYPHEN_PAIR_RE.match(places[0][0])
            if (
                match
                and match.group(2).lower() not in COMPASS
                and match.group(1).split()[-1].lower() not in COMPASS
            ):
                kind = places[0][1]
                return Locations(
                    [(match.group(1), kind), (match.group(2), kind)], "endpoints_hyphen"
                )
        if line_like and len(places) > 1:
            return Locations([(", ".join(name for name, _ in places[:3]), places[0][1])], "plain")
        if places:
            return Locations(places, "plain")
        return self.in_parentheses(parens)

    def route(self, segment: str, text: str) -> list[Place] | None:
        """Endpoints of 'zwischen A und B', 'von A nach B' or 'A - B - C' (with via points)."""
        for pattern in (BETWEEN_RE, FROM_TO_RE):
            match = pattern.search(segment)
            if match:
                parts = [match.group(1), match.group(2)]
                break
        else:
            parts = SEP_RE.split(segment)
            if len(parts) < 2:
                return None
        places = [self.place(part, text) for part in parts]
        if not places[0] or not places[-1]:
            return None
        return [place for place in places if place]

    def in_parentheses(self, parens: list[str]) -> Locations:
        """Station names or search areas in parentheses ('Neubau UW (Suchraum X)')."""
        names = list(dict.fromkeys(place for text in parens for place in self.station_names(text)))
        return Locations(names, "station_name") if names else Locations()


def is_code(name: str) -> bool:
    """Code-like underscore chain element ('ONS', '10K', 'DigiONS')."""
    return all(
        len(word) <= 2 or not re.search(r"[a-zäöüß]", word) or re.search(r"[A-ZÄÖÜ]{3}", word)
        for word in name.split()
    )


def geocoding_kind(name: str, text: str) -> str:
    """Kind of a location without station keyword: search area, street, code or place."""
    if re.search(r"suchraum", text, re.I):
        return "search_area"
    first = name.split(",")[0].strip()
    words = [word for word in re.split(r"[,\s]+", name) if word]
    if (
        any(
            STREET_RE.search(word.rstrip(".0123456789")) or STREET_RE.search(word) for word in words
        )
        or STREET_PREFIX_RE.match(first)
        or re.search(r"[A-Za-zäöüß.]\s?\d{1,4}[a-z]?(?:-\d{1,4}[a-z]?)?$", first)
    ):
        return "street_address"
    # Short all-caps or alphanumeric codes ('AB', 'UW93'); long all-caps words are names.
    if not re.search(r"[a-zäöüß]", first) and (len(first) <= 5 or re.search(r"\d", first)):
        return "code"
    return "place"
