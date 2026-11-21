# Servers and players: recent servers, server icon, webhook help link (design)

Roadmap items 51, 50 and 37 of `TODO.md`, released together (0.31.0). Item 56 (#254) shipped in
0.30.6 and is only ticked off.

## Why

Small everyday conveniences from the owner's list of 2026-10-16: jump between servers without going
back to Your servers, give a server its own picture in Minecraft's server list, and find out how to
make a Discord webhook without searching.

## Approaches

Each item has one sensible way, so no alternatives were weighed beyond where the recent list shows
(the owner picked "always, also inside a server" over "only outside a server", which would repeat
the Servers page).

## 51. Recent servers in the left panel

- A **Recent** group at the top of the left panel, on every page, with up to 3 servers. Hidden when
  there is only one server (single-server mode, or only one the person can see).
- Order: running servers first, the one that last had players on first; then the others by when
  they were last started. Never-started servers come last (by name), so a new installation with
  2–3 servers still shows them.
- "Last started" is new: kept per server, survives Craft Conductor restarts. "Last had players" comes
  from the activity record already kept (`activity.py`).
- A running server shows a green dot (with a text alternative for screen readers).
- Only servers the person can see (`access` grants) are listed.
- Choosing one opens the same page on that server when it has it (and the person may view it),
  otherwise its Dashboard.

## 50. Custom server icon

- A **Server icon** card in a server's **Settings**: the current picture (or "Minecraft's default"),
  **Choose a picture…** and **Remove**.
- The page resizes any picture to 64×64 PNG with a canvas before upload (no new script origins;
  CSP unchanged). The server accepts only a real PNG of exactly 64×64 (signature and IHDR checked
  with the standard library), bounded in size, written atomically to `server-icon.png`.
- The card says Minecraft shows it from the next restart.
- The server's card on **Your servers** shows the icon; friends already receive it in their setup.
- Permission: `settings.safe` on that server (the owner always).

## 37. Discord webhook help link

- Next to **Discord webhook URL** in a server's Settings: a link to Discord's own help article on
  webhooks, new tab, `rel="noopener noreferrer"`. The address is checked before it's added.

## Every change (CLAUDE.md)

Manual and Help, screenshots retaken, translations (`tr/*.txt`, built into `webui/i18n`),
CHANGELOG under 0.31.0 (not released yet), pytest, real-world tests in `testing/catalog.json`
(`tools/real_world_tests.py add-test`), security then efficiency review, PR.

## Left to the builder

Where "last started" is stored; the exact size limit for an icon upload; route names.
