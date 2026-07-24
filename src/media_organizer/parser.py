from __future__ import annotations

import re
from pathlib import Path

from media_organizer.models import Episode, Movie

EPISODE_RE = re.compile(
    r"(?i)(?P<season>\d{1,2})[x](?P<first>\d{1,3})"
    r"|[Ss](?P<sseason>\d{1,2})[ ._-]*[Ee](?P<sfirst>\d{1,3})(?P<extra>(?:[ ._-]*E\d{1,3})*)"
)
YEAR_RE = re.compile(r"(?<!\d)(?P<year>19\d{2}|20\d{2})(?!\d)")
NOISE_RE = re.compile(r"(?i)^(?:torrent|www|com|org|net|[a-f0-9]{8,}|rarbg|yts|eztv)$")

TECHNICAL_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    # Resolution
    (re.compile(r"(?i)(?<!\w)720p(?!\w)"), "720p"),
    (re.compile(r"(?i)(?<!\w)1080p(?!\w)"), "1080p"),
    (re.compile(r"(?i)(?<!\w)2160p(?!\w)"), "2160p"),
    (re.compile(r"(?i)(?<!\w)4k(?!\w)"), "4K"),
    # HDR
    (re.compile(r"(?i)(?<!\w)hdr(?![\w+])"), "HDR"),
    (re.compile(r"(?i)(?<!\w)hdr10(?![\w+])"), "HDR10"),
    (re.compile(r"(?i)(?<!\w)hdr10\+(?!\w)"), "HDR10+"),
    (
        re.compile(r"(?i)(?:dolby[ ._-]*vision|(?<!\w)dovi(?!\w)|(?<!\w)dv(?!\w))"),
        "Dolby Vision",
    ),
    (re.compile(r"(?i)(?<!\w)sdr(?!\w)"), "SDR"),
    # Codec
    (re.compile(r"(?i)(?<!\w)x264(?!\w)"), "x264"),
    (re.compile(r"(?i)(?<!\w)x265(?!\w)"), "x265"),
    (re.compile(r"(?i)(?<!\w)h264(?!\w)"), "H.264"),
    (re.compile(r"(?i)(?<!\w)h265(?!\w)"), "H265"),
    (re.compile(r"(?i)(?<!\w)hevc(?!\w)"), "HEVC"),
    (re.compile(r"(?i)(?<!\w)avc(?!\w)"), "AVC"),
    (re.compile(r"(?i)(?<!\w)av1(?!\w)"), "AV1"),
    # Source
    (re.compile(r"(?i)(?<!\w)uhd[ ._-]*blu[ ._-]*ray(?!\w)"), "UHD BluRay"),
    (re.compile(r"(?i)(?<!uhd[ ._-])blu[ ._-]*ray(?!\w)"), "BluRay"),
    (re.compile(r"(?i)(?<!\w)web[ ._-]*dl(?!\w)"), "WEB-DL"),
    (re.compile(r"(?i)(?<!\w)web[ ._-]*rip(?!\w)"), "WEBRip"),
    (re.compile(r"(?i)(?<!\w)hdtv(?!\w)"), "HDTV"),
    (re.compile(r"(?i)(?<!\w)dvd(?!\w)"), "DVD"),
    (re.compile(r"(?i)(?<!\w)remux(?!\w)"), "REMUX"),
    # Audio
    (re.compile(r"(?i)(?<!\w)atmos(?!\w)"), "Atmos"),
    (re.compile(r"(?i)(?<!\w)true[ ._-]*hd(?!\w)"), "TrueHD"),
    (re.compile(r"(?i)(?<!\w)dts[ ._-]*hd[ ._-]*ma(?!\w)"), "DTS-HD MA"),
    (re.compile(r"(?i)(?<!\w)dts[ ._-]*hd(?![ ._-]*ma)(?!\w)"), "DTS-HD"),
    (re.compile(r"(?i)(?<!\w)dts(?![ ._-]*hd)(?!\w)"), "DTS"),
    (re.compile(r"(?i)(?<!\w)aac(?!\w)"), "AAC"),
    (re.compile(r"(?i)(?<!\w)flac(?!\w)"), "FLAC"),
    # Edition
    (re.compile(r"(?i)director(?:'s|s)?[ ._-]*cut"), "Director's Cut"),
    (re.compile(r"(?i)final[ ._-]*cut"), "Final Cut"),
    (re.compile(r"(?i)(?<!\w)extended(?!\w)"), "Extended"),
    (re.compile(r"(?i)(?<!\w)theatrical(?!\w)"), "Theatrical"),
    (re.compile(r"(?i)(?<!\w)imax[ ._-]*enhanced(?!\w)"), "IMAX Enhanced"),
    (re.compile(r"(?i)(?<!\w)imax(?![ ._-]*enhanced)(?!\w)"), "IMAX"),
)


def clean_title(raw: str) -> str:
    words = re.sub(r"[._]+", " ", raw)
    words = re.sub(r"(?<!\w)-|-(?!\w)", " ", words)
    words = re.sub(r"\s+", " ", words).strip(" ._-")
    return words


def parse_episode(path: Path) -> Episode | None:
    stem = path.stem
    match = EPISODE_RE.search(stem)
    if not match:
        return None
    if match.group("season") is not None:
        season = int(match.group("season"))
        episodes = (int(match.group("first")),)
    else:
        season = int(match.group("sseason"))
        episodes = (int(match.group("sfirst")),)
        extra = match.group("extra") or ""
        episodes += tuple(int(number) for number in re.findall(r"(?i)E(\d{1,3})", extra))
    series = clean_title(stem[: match.start()])
    if not series or season < 0 or any(number < 1 for number in episodes):
        return None
    return Episode(series=series, season=season, episodes=episodes, extension=path.suffix.lower())


def parse_movie(path: Path) -> Movie | None:
    stem = path.stem
    year_match = YEAR_RE.search(stem)
    if not year_match:
        return None
    title = clean_title(stem[: year_match.start()])
    if not title or NOISE_RE.match(title):
        return None
    remainder = stem[year_match.end() :]
    tags: list[str] = []
    for pattern, normalized in TECHNICAL_PATTERNS:
        if pattern.search(remainder) and normalized not in tags:
            tags.append(normalized)
    return Movie(
        title=title,
        year=int(year_match.group("year")),
        technical_tags=tuple(tags),
        extension=path.suffix.lower(),
    )
