#!/usr/bin/env python3
"""Which published Craft Conductor release the website's demo shows.

The policy is .github/demo-release-policy.json:
  "channel": "beta-and-stable"  the newest published release, beta or stable (for now)
  "channel": "stable"           the newest stable release only: a beta never replaces it
A release is a beta when GitHub marks it as a pre-release OR its title says "(beta)" (release.yml
names every release "Craft Conductor vX.Y.Z (beta)" while Craft Conductor is in beta). Draft
releases never count.

    python tools/select_website_release.py                       # asks GitHub (GH_TOKEN, if set, is used)
    python tools/select_website_release.py --releases-file x.json --github-output "$GITHUB_OUTPUT"

It prints the chosen release as JSON (tag, version, channel, url, published) and fails, so nothing is
published, when no release fits the policy or a tag looks wrong.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / ".github" / "demo-release-policy.json"
ENDPOINT = "https://api.github.com/repos/silverWRX03/craft-conductor/releases?per_page=100"
CHANNELS = ("beta-and-stable", "stable")
TAG = re.compile(r"v\d+\.\d+\.\d+(?:(?:a|b|rc)\d+)?")  # (the tags release.yml makes: v0.28.0, v0.29.0b1, v1.0.0rc1)


class PolicyError(ValueError):
    pass


def channel_of(release: dict) -> str:
    """"beta" or "stable", as the website shows it."""
    return "beta" if release.get("prerelease") or "(beta)" in str(release.get("name") or "").lower() else "stable"


def load_policy(path: Path = POLICY) -> str:
    policy = json.loads(path.read_text(encoding="utf-8"))
    channel = policy.get("channel")
    if channel not in CHANNELS:
        raise PolicyError(f"{path.name}: \"channel\" must be one of {', '.join(CHANNELS)} (it is {channel!r})")
    return channel


def choose(releases: list[dict], channel: str) -> dict:
    if channel not in CHANNELS:
        raise PolicyError(f"unknown demo release channel {channel!r}")
    allowed = [r for r in releases if not r.get("draft") and r.get("published_at")
               and (channel == "beta-and-stable" or channel_of(r) == "stable")]
    if not allowed:
        raise PolicyError("no published release fits the website's policy "
                          + ("(stable only, and every release so far is a beta)" if channel == "stable" else ""))
    newest = max(allowed, key=lambda r: (r["published_at"], r.get("id", 0)))
    tag = str(newest.get("tag_name", ""))
    if not TAG.fullmatch(tag):
        raise PolicyError(f"the newest release's tag doesn't look like Craft Conductor's: {tag!r}")
    url = str(newest.get("html_url") or "")
    if url and not url.startswith("https://github.com/silverWRX03/craft-conductor/releases/"):
        raise PolicyError(f"the release's page isn't on GitHub: {url!r}")
    return {"tag": tag, "version": tag[1:], "channel": channel_of(newest), "url": url, "published": newest["published_at"]}


def fetch() -> list[dict]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "craft-conductor-website", "X-GitHub-Api-Version": "2022-11-28"}
    if os.environ.get("GH_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GH_TOKEN"]
    with urlopen(Request(ENDPOINT, headers=headers), timeout=30) as r:
        return json.load(r)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    p.add_argument("--releases-file", type=Path, help="GitHub's list of releases, saved (instead of asking GitHub)")
    p.add_argument("--github-output", type=Path, help="also write tag=, version=, channel=, url= lines here (GitHub Actions)")
    p.add_argument("--policy", type=Path, default=POLICY)
    a = p.parse_args()
    try:
        releases = json.loads(a.releases_file.read_text(encoding="utf-8")) if a.releases_file else fetch()
        chosen = choose(releases, load_policy(a.policy))
    except PolicyError as e:
        sys.exit(f"select_website_release: {e}")
    if a.github_output:
        with a.github_output.open("a", encoding="utf-8") as out:
            for key in ("tag", "version", "channel", "url"):
                out.write(f"{key}={chosen[key]}\n")
    print(json.dumps(chosen, sort_keys=True))


if __name__ == "__main__":
    main()
