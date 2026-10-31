"""Check that server.json, app/__init__.py and (optionally) the git tag agree.

Usage: python scripts/check_release_metadata.py [--tag v0.1.0]
Exits non-zero on any mismatch. Used by .github/workflows/release.yml.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]


def package_version() -> str:
    text = (ROOT / "app/__init__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit("app/__init__.py has no __version__")
    return match.group(1)


def problems(tag: str | None = None) -> list[str]:
    manifest = json.loads((ROOT / "server.json").read_text(encoding="utf-8"))
    version = package_version()
    found: list[str] = []
    if manifest.get("version") != version:
        found.append(f"server.json version {manifest.get('version')} != app {version}")
    for package in manifest.get("packages", []):
        if package.get("registryType") == "oci":
            image = package.get("identifier", "")
            if image.rpartition(":")[2] != version:
                found.append(f"oci image {image} tag != {version}")
        elif "version" in package and package["version"] != version:
            found.append(f"{package.get('registryType')} package version {package['version']} != {version}")
    if tag and tag != f"v{version}":
        found.append(f"tag {tag} != v{version}")
    return found


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", default=os.environ.get("GITHUB_REF_NAME") or None)
    args = parser.parse_args(argv)
    found = problems(args.tag)
    for line in found:
        print(f"release metadata mismatch: {line}", file=sys.stderr)
    if not found:
        print(f"release metadata ok: {package_version()}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
