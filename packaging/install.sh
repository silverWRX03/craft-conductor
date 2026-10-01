#!/bin/sh
# Installs craft-conductor on a Linux computer (a spare PC, a home server, a Raspberry Pi 4/5 with a
# 64-bit OS) and runs its control panel in the background, so you can manage everything
# from a browser on another computer. Run it on that computer, e.g. over SSH:
#
#   ssh you@192.168.1.50 "curl -fsSL https://raw.githubusercontent.com/silverWRX03/craft-conductor/main/packaging/install.sh | sh"
#
# It downloads the newest release for this CPU, checks it against the release's SHA256SUMS,
# puts it in ~/.local/bin (CRAFT_CONDUCTOR_BIN_DIR to change), and runs `craft-conductor service install --panel`,
# which prints the address to open and a one-time password. Nothing is run as root.
set -eu

REPO="silverWRX03/craft-conductor"
BASE="${CRAFT_CONDUCTOR_RELEASE_URL:-https://github.com/$REPO/releases/latest/download}"
case "$(uname -s)-$(uname -m)" in
  Linux-x86_64|Linux-amd64) ASSET="craft-conductor-linux-x64" ;;
  Linux-aarch64|Linux-arm64) ASSET="craft-conductor-linux-arm64" ;;
  *) echo "Craft Conductor: this installer is for 64-bit Linux (x86_64 or arm64); this is $(uname -s) $(uname -m)." >&2
     echo "On Windows or macOS, download craft-conductor from https://github.com/$REPO/releases/latest" >&2
     exit 1 ;;
esac
if [ "$(id -u)" = "0" ]; then
  echo "craft-conductor: please run this as the user that should own the servers, not root" >&2
  echo "      (e.g. make one: sudo adduser minecraft, then ssh minecraft@this-computer)." >&2
  exit 1
fi

BIN_DIR="${CRAFT_CONDUCTOR_BIN_DIR:-$HOME/.local/bin}"
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT INT TERM
fetch() {
  if command -v curl >/dev/null 2>&1; then curl -fsSL --retry 3 -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then wget -q -O "$2" "$1"
  else echo "craft-conductor: needs curl or wget" >&2; exit 1; fi
}

echo "Downloading $ASSET ..."
fetch "$BASE/$ASSET" "$tmp/craft-conductor"
fetch "$BASE/SHA256SUMS.txt" "$tmp/SHA256SUMS.txt"
expected="$(grep " \*\{0,1\}$ASSET\$" "$tmp/SHA256SUMS.txt" | cut -d' ' -f1)"
actual="$(sha256sum "$tmp/craft-conductor" | cut -d' ' -f1)"
if [ -z "$expected" ] || [ "$expected" != "$actual" ]; then
  echo "craft-conductor: the download doesn't match the release's checksum; not installing it" >&2
  exit 1
fi

mkdir -p "$BIN_DIR"
install -m 755 "$tmp/craft-conductor" "$BIN_DIR/craft-conductor"
echo "Installed $BIN_DIR/craft-conductor"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) echo "(add $BIN_DIR to your PATH to type 'craft-conductor' directly)" ;; esac

if command -v systemctl >/dev/null 2>&1 && [ -d /run/systemd/system ]; then
  if [ "${CRAFT_CONDUCTOR_PANEL_LOCAL:-}" = "1" ]; then
    # A rented server on the internet: the control panel stays on this machine; reach it through SSH.
    "$BIN_DIR/craft-conductor" service install --panel --local-only
  else
    "$BIN_DIR/craft-conductor" service install --panel
  fi
else
  echo
  echo "This system doesn't use systemd, so craft-conductor can't start itself at boot here."
  echo "Start it with:  $BIN_DIR/craft-conductor start --no-browser --web-host 0.0.0.0"
fi
