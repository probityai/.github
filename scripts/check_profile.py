"""Check the organization profile against a reviewed public catalog and live links."""

from __future__ import annotations

import hashlib
import json
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

CATALOG = "https://raw.githubusercontent.com/probityai/agent-evidence-vectors/f70e16b6b59b0f159cf0d56eb1064f0f80179030/site/docs/catalog.json"
CATALOG_SHA256 = "223bc7f454d04af42180eae2a237d2623daf1f23e6901177fbef1f4432f8ef60"
# Every `](target)`, so the outer link of a badge (`[![alt](image)](target)`) is read as well as its image.
LINK = re.compile(r"\]\(([^\s)]+)\)")
ROW = re.compile(r"^\| ([^|]+) \| \[([^\]]+)\]\(([^\s)]+)\) \|$", re.MULTILINE)
HOSTS = {"github.com", "raw.githubusercontent.com", "probityai.github.io", "img.shields.io", "pypi.org"}
# The page opens with one pinned install: the probityai command or the vectors corpus.
INSTALL = re.compile(r"^```(?:bash|sh)\n(?:pip install probityai|uvx agent-evidence-vectors)==\d+\.\d+\.\d+\n", re.MULTILINE)
# Every `name==X.Y.Z` pin in the page is held to the newest release on PyPI.
PIN = re.compile(r"\b([a-z][a-z0-9-]*)==(\d+\.\d+\.\d+)\b")


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
    links = LINK.findall(text)
    for url in links:
        parts = urlsplit(url)
        if parts.scheme != "https" or parts.hostname not in HOSTS or parts.username or parts.password:
            raise ValueError(f"Unapproved public link: {url}")
    if not INSTALL.search(text):
        raise ValueError("The profile must open with one pinned install of probityai or agent-evidence-vectors")
    for surface in ("start.html", "start.md", "llms.txt", "lab.html"):
        if f"https://probityai.github.io/agent-evidence-atlas/{surface}" not in links:
            raise ValueError(f"The public discovery link is missing: {surface}")
    return sorted(set(links))


def stale_pins(text: str, latest: dict[str, str]) -> list[str]:
    """Return every pinned package whose version is not the newest release."""
    return sorted({f"{name}=={version} (newest {latest[name]})"
                   for name, version in PIN.findall(text) if latest[name] != version})


def readback_target(url: str) -> str:
    """Read the pinned README bytes instead of GitHub's presentation HTML."""
    match = re.fullmatch(r"https://github.com/(probityai/[^/]+)/blob/([0-9a-f]{40})/((?:(?!\.{1,2}/)[A-Za-z0-9._-]+/)*README\.md)", url)
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
    names = sorted({name for name, _ in PIN.findall(text)})
    latest = {name: json.loads(fetch(f"https://pypi.org/pypi/{name}/json"))["info"]["version"] for name in names}
    stale = stale_pins(text, latest)
    if stale:
        raise ValueError("Pins behind PyPI: " + ", ".join(stale))
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(fetch, map(readback_target, links)))
    print(f"Profile matches all {len(catalog['components'])} reviewed task/source pairs; {len(results)} public links read back.")


if __name__ == "__main__":
    main()
