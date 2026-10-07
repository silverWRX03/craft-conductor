"""Build the GitHub wiki: the user manual (src/craft_conductor/webui/manual.md, the same one the app shows)
split into one page per section, with the app's own screenshots (src/craft_conductor/webui/screenshots),
plus the hand-written pages in wiki/ (Home, the Power users pages) and a sidebar to find them all.

    python packaging/wiki.py OUT_DIR

The wiki workflow (.github/workflows/wiki.yml) runs this on every change to main and publishes
OUT_DIR to the repository's wiki, so the wiki always matches the manual.
"""

from __future__ import annotations

import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MANUAL = ROOT / "src" / "craft_conductor" / "webui" / "manual.md"
PAGES = ROOT / "wiki"          # hand-written pages (Home, Power users) and images/ (the icon)
SHOTS = ROOT / "src" / "craft_conductor" / "webui" / "screenshots"  # the pictures, as Help shows them too
START = "Craft-Conductor-Manual"   # the manual's first page (the wiki page the manual starts on)

# Manual sections that belong with the power users' pages, not the everyday manual.
POWER_SECTIONS = ("Where Craft Conductor keeps things", "Command line")
# The hand-written Power users pages, in the sidebar's order: (page, title).
POWER_PAGES = [
    ("Power-Users", "Power users: start here"),
    ("Configuration", "Configuration (craft-conductor.toml)"),
    ("Building-Servers-From-The-Command-Line", "Building servers from the command line"),
    ("Running-It-Forever", "Running it forever"),
    ("Linux-Servers-Without-A-Screen", "Linux servers without a screen"),
    ("Managing-Players-From-The-Command-Line", "Managing players from the command line"),
    ("Java-In-Detail", "Java in detail"),
    ("How-An-Upgrade-Works", "How an upgrade works"),
    ("Updating-Craft-Conductor", "Updating Craft Conductor"),
    ("Mods-That-Block-Downloads", "Mods that block third-party downloads"),
    ("Security", "Security"),
    ("Other-Ways-To-Install", "Other ways to install"),
    ("For-Maintainers", "For maintainers"),
]
# Shorter titles for some manual sections (for the page names and the sidebar).
TITLES = {"Friends: playing with friends": "Playing with friends",
          "For friends: joining a server": "Joining a friend's server",
          "What Craft Conductor can and can't do": "What it can and can't do"}
# Screenshots under each section or sub-section, after its first paragraph: (file in SHOTS, caption).
# The same as "See this screen" in the app's manual (MANUAL_PICTURES in app.js; test_wiki.py checks).
IMAGES = {
    "Getting started": [("sign-in.png", "Signing in the first time"), ("choose-password.png", "Choosing your own password")],
    "The guided setup": [("guided-setup.png", "The guided setup's checklist, in a corner of the page")],
    "Creating a server": [("new-server.png", "New server"), ("mod-browser.png", "The mod browser"),
                          ("map-preview.png", "World generation & map preview, with landmarks"),
                          ("manual-downloads.png", "Mods to download by hand: a link for each, and the box to drop them on")],
    "On another computer (Linux, over SSH)": [("ssh-install.png", "Install on a Linux computer or rented server (SSH)")],
    "Messages": [("question.png", "A question waits in the middle of the screen")],
    "Your servers": [("servers.png", "Your servers, and a modded single-player game")],
    "Dashboard": [("dashboard.png", "The Dashboard of a running server"),
                  ("dashboard-problem.png", "A server that didn't start: what went wrong, and the fix")],
    "Connected Players": [("connected-players.png", "Connected Players: a row's actions open, and the Whitelist panel")],
    "Performance": [("performance.png", "Performance, with the last hour's graph")],
    "Check my setup": [("check-my-setup.png", "Check my setup")],
    "Console": [("console.png", "The Console")],
    "Players": [("players.png", "The Players page"), ("player-activity.png", "Player activity")],
    "Mods": [("mods.png", "Installed mods")],
    "Updates": [("updates.png", "The Updates page, waiting for two mods"), ("update-readiness.png", "Show why: each mod, ready or not")],
    "Backups": [("backups.png", "Backups, each checked, with what changed since the one before")],
    "Java": [("java.png", "Java versions")],
    "Settings": [("settings.png", "A server's settings"), ("web-map.png", "World tools and the web map")],
    "Friends: playing with friends": [("friends.png", "Invite links on the Friends page"),
                                       ("discord-invite.png", "Posting Java and Bedrock invites to Discord")],
    "For friends: joining a server": [("invite-page.png", "The invite page your friend opens"),
                                      ("friend-setup.png", "Craft Conductor setting up Minecraft on your friend's computer")],
    "Remote access and phones": [("remote-access.png", "Remote access & phones"), ("phone.png", "On a phone")],
    "Craft Conductor settings": [("craft-conductor-settings.png", "Craft Conductor settings: Connections"),
                                 ("display.png", "Appearance: language, size, contrast and motion"),
                                 ("update-available.png", "A Craft Conductor update is available"),
                                 ("update-dots.png", "About & updates: the red dots, and the update waiting"),
                                 ("updating.png", "Updating Craft Conductor, with the step it's on"),
                                 ("update-restarting.png", "Restarting Craft Conductor while the control panel is away"),
                                 ("update-failed.png", "An update that didn't work"),
                                 ("update-launch.png", "Another browser is offered the new version")],
    "Troubleshooting": [("help.png", "Help, with its contents on the left")],
}


def page_name(title: str) -> str:
    """A wiki page name: words joined with hyphens (GitHub shows hyphens as spaces)."""
    title = TITLES.get(title, title)
    return re.sub(r"[^A-Za-z0-9]+", "-", title.replace("'", "")).strip("-")


def sections(text: str) -> tuple[str, list[tuple[str, str]]]:
    """The manual's introduction, and its "## " sections as (title, body)."""
    parts = re.split(r"^## (.+)$", text, flags=re.M)
    intro = re.sub(r"^# .+\n+", "", parts[0]).strip()
    return intro, [(parts[i].strip(), parts[i + 1].strip()) for i in range(1, len(parts), 2)]


def with_images(title: str, body: str) -> str:
    """The section's pictures after its first paragraph, and each sub-section's after its own."""
    def after_first(text: str, shots: list[tuple[str, str]]) -> str:
        first, sep, rest = text.partition("\n\n")
        pictures = "\n\n".join(f"![{caption}](images/{name})" for name, caption in shots)
        return f"{first}\n\n{pictures}{sep}{rest}"
    parts = re.split(r"^(### .+)$", body, flags=re.M)  # [text, heading, text, heading, text...]
    if title in IMAGES:
        parts[0] = after_first(parts[0], IMAGES[title])
    for i in range(1, len(parts), 2):
        sub = parts[i][4:].strip()
        if sub in IMAGES:
            parts[i + 1] = "\n\n" + after_first(parts[i + 1].lstrip("\n"), IMAGES[sub])
    return "".join(parts)


def build(out: Path) -> list[str]:
    """Write the wiki into ``out``; the page names written."""
    intro, secs = sections(MANUAL.read_text(encoding="utf-8"))
    out.mkdir(parents=True, exist_ok=True)
    everyday = [(t, b) for t, b in secs if t not in POWER_SECTIONS]
    power = [(t, b) for t, b in secs if t in POWER_SECTIONS]
    written = []
    note = ("\n\n---\n_This page is the user manual that comes with Craft Conductor (Help → User manual in the app). "
            "It's made from [manual.md](https://github.com/silverWRX03/craft-conductor/blob/main/src/craft_conductor/webui/manual.md): "
            "change it there, not here._\n")
    for i, (title, body) in enumerate(everyday):
        nav = []
        if i:
            nav.append(f"← [{TITLES.get(everyday[i - 1][0], everyday[i - 1][0])}]({page_name(everyday[i - 1][0])})")
        if i + 1 < len(everyday):
            nav.append(f"[{TITLES.get(everyday[i + 1][0], everyday[i + 1][0])}]({page_name(everyday[i + 1][0])}) →")
        text = f"# {TITLES.get(title, title)}\n\n{with_images(title, body)}\n\n" + (" · ".join(nav)) + note
        (out / f"{page_name(title)}.md").write_text(text, encoding="utf-8")
        written.append(page_name(title))
    for title, body in power:
        (out / f"{page_name(title)}.md").write_text(f"# {title}\n\n{body}{note}", encoding="utf-8")
        written.append(page_name(title))
    contents = "\n".join(f"{n}. [{TITLES.get(t, t)}]({page_name(t)})" for n, (t, _) in enumerate(everyday, 1))
    (out / f"{START}.md").write_text(
        f"# Craft Conductor user manual\n\n{intro}\n\n## Contents\n\n{contents}\n\n"
        f"**Power users:** the command line, `craft-conductor.toml`, running it as a service and more: see [Power users](Power-Users).{note}",
        encoding="utf-8")
    written.append(START)
    for path in PAGES.rglob("*"):  # the hand-written pages and the icon
        if path.is_file():
            target = out / path.relative_to(PAGES)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(path, target)
            if path.suffix == ".md" and path.parent == PAGES:
                written.append(path.stem)
    (out / "images").mkdir(exist_ok=True)
    for path in SHOTS.glob("*.png"):  # the screenshots
        shutil.copyfile(path, out / "images" / path.name)
    sidebar = ["**[Home](Home)**", "", "**User manual**", "", f"- [Start here]({START})"]
    sidebar += [f"- [{TITLES.get(t, t)}]({page_name(t)})" for t, _ in everyday]
    sidebar += ["", "**Power users**", ""]
    sidebar += [f"- [{title}]({page})" for page, title in POWER_PAGES]
    sidebar += [f"- [{t}]({page_name(t)})" for t, _ in power]
    sidebar += ["", "---", "", "[Download](https://github.com/silverWRX03/craft-conductor/releases/latest) · "
                "[What's new](https://github.com/silverWRX03/craft-conductor/blob/main/CHANGELOG.md) · "
                "[Report a bug](https://github.com/silverWRX03/craft-conductor/issues/new/choose)"]
    (out / "_Sidebar.md").write_text("\n".join(sidebar) + "\n", encoding="utf-8")
    return written


def links(out: Path) -> list[tuple[str, str]]:
    """Links between pages and to images that point nowhere: [(page, target)]."""
    pages = {p.stem for p in out.glob("*.md")}
    bad = []
    for p in out.glob("*.md"):
        for target in re.findall(r"\]\(([^)\s]+)\)", p.read_text(encoding="utf-8")):
            if re.match(r"[a-z]+:|#", target):
                continue  # (a web address or a place on the page)
            if target.startswith("images/"):
                if not (out / target).is_file():
                    bad.append((p.stem, target))
            elif target.split("#")[0] not in pages:
                bad.append((p.stem, target))
    return bad


if __name__ == "__main__":
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "wiki-out")
    names = build(out)
    missing = links(out)
    print(f"wrote {len(names)} pages to {out}")
    if missing:
        sys.exit("broken links: " + ", ".join(f"{p} → {t}" for p, t in missing))
