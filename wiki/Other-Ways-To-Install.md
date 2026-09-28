# Other ways to install

## With Python

If you have Python 3.11 or newer (for example on an Intel Mac, or a computer without a download of its own):

```sh
pipx install git+https://github.com/silverWRX03/craft-conductor
mcsm
```

## On Linux, from a terminal

**Linux:** the Linux downloads run on practically any distribution from 2014 onward
(glibc 2.17 or newer: Ubuntu, Debian, Fedora, Rocky/Alma/RHEL 7+, Arch, openSUSE,
Raspberry Pi OS 64-bit, and so on). Alpine and other musl-based systems need the
[Python install](#with-python) instead.

```sh
curl -LO https://github.com/silverWRX03/craft-conductor/releases/latest/download/craft-conductor-linux-x64
chmod +x craft-conductor-linux-x64
sudo mv craft-conductor-linux-x64 /usr/local/bin/mcsm     # optional: makes `mcsm` a command
mcsm
```

On a Raspberry Pi or another ARM machine, use `craft-conductor-linux-arm64` instead.

## Checking a download

**Verifying a download (optional):** every release includes `SHA256SUMS.txt`. Compare it with
`sha256sum craft-conductor-linux-x64` (Linux), `shasum -a 256 craft-conductor-macos-arm64` (Mac), or
`Get-FileHash craft-conductor-windows-x64.exe` (Windows PowerShell). The built-in updater checks this for you.

## Docker

See the [Docker guide](https://github.com/silverWRX03/craft-conductor/blob/main/docs/docker.md).

---
[← Power users](Power-Users)
