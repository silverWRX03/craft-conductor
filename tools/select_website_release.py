#!/usr/bin/env python3
"""Find the latest PUBLISHED Craft Conductor release for the public demo.

Policy is in .github/demo-release-policy.json; 'both' is temporary until
the project owner explicitly changes it to 'stable'. Stable-only means
never silently switching the public demo back to a beta.
"""
from __future__ import annotations
from datetime import datetime
import argparse
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / ".github" / "demo-release-policy.json"
ENDPOINT = "https://api.github.com/repos/silverWRX03/craft-conductor/releases?per_page=100"

def choose(releases: list[dict], channel: str) -> dict:
    if channel not in ("both", "stable"):
        raise ValueError("Invalid website demo release policy")
    allowed = [r for r in releases
               if not r.get("draft") and r.get("published_at")
               and (channel == "both" or not r.get("prerelease"))]
    if not allowed:
        raise ValueError("No published releases matching the website demo channel.")
    allowed.sort(key=lambda r: (r["published_at"],r.get("id",0)), reverse=True)
    result=allowed[0]
    tag=result.get("tag_name","")
    if not tag.startswith("v") or any(x in tag for x in ("..","/","\\"," ","\n","\r")):
        raise ValueError("Unexpected release tag: "+repr(tag))
    return {"tag":tag,"version":tag.lstrip("v"),"channel":"beta" if result.get("prerelease") else "stable","url":result.get("html_url","")}

def main() -> None:
    ap=argparse.ArgumentParser()
    ap.add_argument("--github-output", type=Path)
    ap.add_argument("--releases-file", type=Path, help="Offline fixture for tests")
    a=ap.parse_args()
    policy=json.loads(POLICY.read_text(encoding="utf8"))
    channel=policy.get("channel")
    if a.releases_file:
        data=json.loads(a.releases_file.read_text(encoding="utf8"))
    else:
        token=os.environ.get("GH_TOKEN","")
        headers={"Accept":"application/vnd.github+json","User-Agent":"craft-conductor-website-build","X-GitHub-Api-Version":"2022-11-28"}
        if token:headers["Authorization"]="Bearer "+token
        req=Request(ENDPOINT,headers=headers)
        with urlopen(req,timeout=25) as res:
            data=json.load(res)
    item=choose(data,channel)
    if a.github_output:
        with a.github_output.open("a",encoding="utf8") as out:
            for k,v in item.items():
                out.write(k+"="+str(v)+"\n")
    print(json.dumps(item,sort_keys=True))

if __name__=="__main__":
    main()
