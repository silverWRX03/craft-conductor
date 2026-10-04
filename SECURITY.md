# Security policy

Craft Conductor runs on your own computer and controls it: it downloads and starts programs,
opens ports when you ask it to, and lets paired phones and friends in. Security problems in it
matter, and reports are very welcome.

## Reporting a problem

**Please don't open a public issue for a security problem.** Report it privately instead:

- **GitHub's private reporting:** [Report a vulnerability](https://github.com/silverWRX03/craft-conductor/security/advisories/new)
  (the repository's **Security** tab → **Report a vulnerability**). Only the maintainers see it.

Helpful to include:

- the Craft Conductor version (Craft Conductor settings → About & updates) and your system
  (Windows, macOS, Linux, Docker);
- what someone could do, and from where (the internet, your home network, a paired phone, a
  friend's invite, a mod, another account on the same computer);
- steps to reproduce it, or a proof of concept.

Never include real passwords, API keys or tokens, yours or anyone else's.

## What happens next

Craft Conductor is a free, volunteer-run project, so these are aims rather than promises:

- an answer within **7 days** saying whether it's confirmed;
- a fix in a release as soon as practical, sooner for problems that can be reached from the
  network;
- credit in the changelog and the advisory, if you'd like it.

Please give us a reasonable time to release a fix before telling others about the problem.
Research done in good faith, on your own computers and servers, is welcome; don't touch other
people's servers, data or accounts.

## Supported versions

Craft Conductor is in beta. Fixes go into the **newest release** only; copies of Craft Conductor
offer to update themselves to it.

| Version | Fixed |
|---|---|
| Newest release (see [Releases](https://github.com/silverWRX03/craft-conductor/releases/latest)) | Yes |
| Anything older | No: update first |

## In scope

- The program itself: the control panel, signing in, paired phones and passkeys, the
  friends' setup page and downloads, invite links, self-updates, router (UPnP) and Windows
  Firewall changes, backups, and how it downloads and checks Java, Minecraft, loaders and mods.
- The invite page ([`site/join/`](site/join/)), the mod-conflict relay ([`relay/`](relay/)),
  and how the downloads are built and released ([`.github/workflows/`](.github/workflows/),
  [`packaging/`](packaging/)).

## Out of scope

- Problems in Minecraft, Java, mod loaders, mods or plugins themselves: please tell their
  authors. (A way for one of them to escape what Craft Conductor lets it do *is* in scope.)
- Attacks that need your computer account already taken over.
- The CurseForge API key built into the downloads. Any app that ships a key can have it read
  out of the program; it's there so CurseForge works for everyone without an account. Do tell
  us if you see it being misused, so it can be replaced.

## How Craft Conductor tries to be safe

Safe by default: the control panel only answers on this computer until you turn on remote
access (which then needs a strong password), and anything risky (remote access, UPnP) is your
choice, with a plain warning. Downloads are checked against their checksums, secrets are kept
in files only your account can read and out of the programs Craft Conductor starts, and there's
no telemetry. The design, and what is still to do, is in the
[threat model](docs/security/THREAT_MODEL.md). Known gaps with failing tests waiting for a fix
are marked in [`tests/security/`](tests/security/).
