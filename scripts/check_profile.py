"""Check the organization profile against a reviewed public catalog and live links."""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CATALOG = "https://raw.githubusercontent.com/probityai/agent-evidence-atlas/35bd66c8d800f89bbd8ca2e596b35fef083cd78c/docs/catalog.json"
CATALOG_SHA256 = "b911ab35428e90bc61a030d21e63dd0e5e518b5fbc1315e624d9c4132c2ffbaa"
LINK = re.compile(r"\[([^\]]+)\]\(([^\s)]+)\)")
ROW = re.compile(r"^\| ([^|]+) \| \[([^\]]+)\]\(([^\s)]+)\) \|$", re.MULTILINE)
HOSTS = {"github.com", "raw.githubusercontent.com", "probityai.github.io"}


def fetch(url: str) -> bytes:
    parts = urlsplit(url)
    if parts.scheme != "https" or parts.hostname not in HOSTS or parts.username or parts.password:
        raise ValueError(f"Unapproved public link: {url}")
    request = Request(url, headers={"User-Agent": "Probity-profile-check"})
    with urlopen(request, timeout=30) as response:
        if response.status != 200:
            raise ValueError(f"Link did not return HTTP 200: {url}")
        data = response.read(1_048_577)
    if not data or len(data) > 1_048_576:
        raise ValueError(f"Empty or oversized public document: {url}")
    return data


def validate_profile(text: str, catalog: dict) -> list[str]:
    if not isinstance(catalog, dict):
        raise ValueError("The reviewed catalog must be an object")
    components = catalog.get("components")
    if not isinstance(components, list) or not components:
        raise ValueError("The reviewed catalog must contain a nonempty component list")
    expected = set()
    identities = set()
    for item in components:
        if not isinstance(item, dict) or any(
            not isinstance(item.get(field), str) or not item[field].strip()
            for field in ("id", "task", "display_name", "docs_url")
        ):
            raise ValueError("Every reviewed component needs an identity, task, name and source")
        pair = (item["task"], item["display_name"], item["docs_url"])
        if item["id"] in identities or pair in expected:
            raise ValueError("Reviewed component identities and task/source pairs must be unique")
        identities.add(item["id"])
        expected.add(pair)
    rows = ROW.findall(text)
    if len(rows) != len(components) or len(set(rows)) != len(rows) or set(rows) != expected:
        raise ValueError("The profile must contain every reviewed task/source pair exactly once")
    links = [url for _, url in LINK.findall(text)]
    for url in links:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in HOSTS or parts.username or parts.password:
            raise ValueError(f"Unapproved public link: {url}")
    for surface in ("start.html", "start.md", "llms.txt", "lab.html"):
        if f"https://probityai.github.io/agent-evidence-atlas/{surface}" not in links:
            raise ValueError(f"The public discovery link is missing: {surface}")
    return sorted(set(links))


def readback_target(url: str) -> str:
    """Read the pinned README bytes instead of GitHub's presentation HTML."""
    match = re.fullmatch(r"https://github.com/(probityai/[^/]+)/blob/([0-9a-f]{40})/(README\.md)", url)
    if match:
        repository, commit, path = match.groups()
        return f"https://raw.githubusercontent.com/{repository}/{commit}/{path}"
    return url


def main() -> None:
    raw = fetch(CATALOG)
    if hashlib.sha256(raw).hexdigest() != CATALOG_SHA256:
        raise ValueError("The reviewed catalog bytes changed")
    text = (Path(__file__).resolve().parents[1] / "profile/README.md").read_text()
    catalog = json.loads(raw)
    links = validate_profile(text, catalog)
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, map(readback_target, links)))
    print(f"Profile matches all {len(catalog['components'])} reviewed task/source pairs; {len(results)} public links read back.")


if __name__ == "__main__":
    main()
