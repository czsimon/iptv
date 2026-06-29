#!/usr/bin/env python3
"""Refresh stream IPs in playlist2.m3u from the playlist in PLAYLIST_URL."""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Iterator
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from urllib.request import urlopen

ENV_FILE = ".env"
PLAYLIST_FILE = "playlist2.m3u"
LOGO_RE = re.compile(r'\btvg-logo="([^"]*)"')


def load_env_value(path: Path, key: str) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Missing env file: {path}")

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        name, value = line.split("=", 1)
        if name.strip() != key:
            continue

        value = value.strip()
        if (value.startswith('"') and value.endswith('"')) or (
            value.startswith("'") and value.endswith("'")
        ):
            value = value[1:-1]

        if not value:
            raise ValueError(f"{key} is empty in {path}")
        return value

    raise KeyError(f"{key} was not found in {path}")


def download_text(url: str) -> str:
    with urlopen(url, timeout=60) as response:
        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


def get_logo(line: str) -> str | None:
    match = LOGO_RE.search(line)
    return match.group(1).strip() if match else None


def get_logo_path(logo_url: str) -> str:
    parsed = urlsplit(logo_url)
    return parsed.path or logo_url


def stream_ip(stream_url: str) -> str | None:
    parsed = urlsplit(stream_url.strip())
    return parsed.hostname


def replace_stream_ip(stream_url: str, new_ip: str) -> str:
    stripped = stream_url.strip()
    parsed = urlsplit(stripped)
    if not parsed.hostname:
        return stream_url

    netloc = parsed.netloc
    old_host = parsed.hostname
    if parsed.port:
        replacement = f"{new_ip}:{parsed.port}"
    else:
        replacement = new_ip

    if parsed.username or parsed.password:
        credentials = parsed.username or ""
        if parsed.password is not None:
            credentials += f":{parsed.password}"
        replacement = f"{credentials}@{replacement}"

    # Replace from the right so credentials containing the hostname are left alone.
    netloc = netloc.rsplit(old_host, 1)[0] + replacement
    updated = urlunsplit((parsed.scheme, netloc, parsed.path, parsed.query, parsed.fragment))

    newline = "\n" if stream_url.endswith("\n") else ""
    return f"{updated}{newline}"


def iter_entries(lines: list[str]) -> Iterator[tuple[str, str]]:
    for index, line in enumerate(lines[:-1]):
        if line.startswith("#EXTINF"):
            yield line, lines[index + 1]


def build_logo_ip_index(downloaded_playlist: str) -> dict[str, str]:
    lines = downloaded_playlist.splitlines(keepends=True)
    logo_to_ip: dict[str, str] = {}

    for extinf, stream in iter_entries(lines):
        logo = get_logo(extinf)
        ip = stream_ip(stream)
        if not logo or not ip:
            continue

        logo_to_ip.setdefault(logo, ip)
        logo_to_ip.setdefault(get_logo_path(logo), ip)

    return logo_to_ip


def update_playlist(lines: list[str], logo_to_ip: dict[str, str]) -> tuple[list[str], int, int]:
    updated_lines = lines[:]
    matched = 0
    changed = 0

    for index, line in enumerate(lines[:-1]):
        if not line.startswith("#EXTINF"):
            continue

        logo = get_logo(line)
        if not logo:
            continue

        new_ip = logo_to_ip.get(logo) or logo_to_ip.get(get_logo_path(logo))
        if not new_ip:
            continue

        matched += 1
        old_stream = lines[index + 1]
        new_stream = replace_stream_ip(old_stream, new_ip)
        if new_stream != old_stream:
            updated_lines[index + 1] = new_stream
            changed += 1

    return updated_lines, matched, changed


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Update stream IPs in playlist2.m3u using PLAYLIST_URL from .env."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="show how many entries would change without writing playlist2.m3u",
    )
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    playlist_path = root / PLAYLIST_FILE

    playlist_url = load_env_value(root / ENV_FILE, "PLAYLIST_URL")
    downloaded_playlist = download_text(playlist_url)
    logo_to_ip = build_logo_ip_index(downloaded_playlist)

    if not playlist_path.exists():
        raise FileNotFoundError(f"Missing playlist file: {playlist_path}")

    original_lines = playlist_path.read_text(encoding="utf-8").splitlines(keepends=True)
    updated_lines, matched, changed = update_playlist(original_lines, logo_to_ip)

    if not args.dry_run and changed:
        playlist_path.write_text("".join(updated_lines), encoding="utf-8")

    action = "Would update" if args.dry_run else "Updated"
    print(f"{action} {changed} stream IP(s); matched {matched} playlist entrie(s).")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1) from None
