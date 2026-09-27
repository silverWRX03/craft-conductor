# Code signing policy

mcsm's Windows downloads (`mcsm-windows-x64.exe` and the friends' `mcsm-join-windows-x64.exe`)
are to be code-signed, so Windows shows who made them instead of saying it "protected your PC".

Free code signing provided by [SignPath.io](https://about.signpath.io), certificate by
[SignPath Foundation](https://signpath.org). *(Once the project is accepted; until then the
downloads are unsigned.)*

## What gets signed

Only files built by this repository's `release` workflow on GitHub Actions, from the source
code in this repository. SignPath checks that origin before it signs anything. Nothing built on
a personal computer is ever signed. The macOS and Linux downloads aren't signed (SignPath
Foundation's certificate is for Windows).

## Team roles

- **Committers and reviewers:** the repository's collaborators, see
  [contributors](https://github.com/silverWRX03/mc-server-management/graphs/contributors).
  Every change reaches `main` through a pull request.
- **Approvers:** the repository owner, [silverWRX03](https://github.com/silverWRX03), who starts
  each release. Everyone with those rights uses two-factor authentication on GitHub.

## Privacy

mcsm doesn't collect or send any information about you or your computer to its authors. It
connects only to the services it needs for what you ask it to do: Mojang (Minecraft versions),
the mod loaders' sites, Modrinth and CurseForge (mods), Adoptium (Java), GitHub (mcsm updates),
and, when you use those features, Discord, your friends' computers or a public-address lookup.
See [What mcsm can and can't do](../src/mcsm/webui/manual.md#what-mcsm-can-and-cant-do) and
*mcsm settings → About mcsm → Online services* in the app.

## Setting it up (maintainers)

1. Apply at [signpath.org](https://signpath.org) (Apply for Free Code Signing) with the repository
   URL, the releases page as the download page, and a short description.
2. When accepted, in the SignPath project: add GitHub as the trusted build system, the
   artifact configuration for a single `.exe` (Authenticode), and a `release-signing` signing
   policy with origin verification for the `main` branch.
3. In this repository's settings: the **variable** `SIGNPATH_ORGANIZATION_ID` and the **secret**
   `SIGNPATH_API_TOKEN` (and the variables `SIGNPATH_PROJECT_SLUG` / `SIGNPATH_POLICY_SLUG` if
   they aren't `mc-server-management` / `release-signing`).

From the next release on, the `release` workflow sends the Windows file to SignPath, waits for
the signed file, checks it still runs, and publishes that (the checksums in `SHA256SUMS.txt`, which
mcsm's updater verifies, are of the signed file). Without the variable, releases work as before.
