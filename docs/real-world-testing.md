# Real-world testing on your own computers

What the automated tests can't cover: a real Windows installed from scratch, antivirus, OneDrive
and non-English folders, the power going off, a full disk, real routers and carrier-grade NAT,
and phones. CI already runs every loader with real downloads on Linux, and Fabric on Windows and
macOS (`e2e.yml`); this page is for everything else.

It's written so a Claude Code session on your PC can carry it out with you: Claude runs the
commands, watches the logs and writes up the results; you do what needs hands (clicking in the
control panel, the router, a phone, turning a VM off). The prompts to start each part are in
[section 4](#4-prompts-to-paste).

## 1. Set up (once)

**A test machine.** Each part says which it needs:

- **A Windows 11 virtual machine** (Hyper-V on Windows Pro, or VirtualBox), installed from
  Microsoft's Windows 11 evaluation ISO, with a checkpoint/snapshot named `clean` taken before
  anything else is installed. Needed for part 3: turning the VM off is pulling the plug, and a
  small extra virtual disk is the full disk. Give it 8 GB of memory and 80 GB of disk.
- **Windows Sandbox** (Windows Pro: *Turn Windows features on or off* → *Windows Sandbox*): a
  clean Windows every time it opens, gone when it closes. Enough for part 1; copy the results out
  before closing it.
- **Your everyday PC**, for OneDrive and the antivirus you really use (parts 4 and 5).
- **Your home network and a phone with mobile data**, for part 6.

**On the machine Claude Code runs on** (PowerShell):

1. Install [Git for Windows](https://git-scm.com/download/win) (Claude Code on Windows uses its
   Git Bash) and [Python 3.12](https://www.python.org/downloads/) (tick *Add python.exe to PATH*).
2. Install Claude Code with `irm https://claude.ai/install.ps1 | iex`, then run `claude` once to
   sign in.
3. Get the code and its test tools:
   ```powershell
   git clone https://github.com/silverWRX03/craft-conductor C:\cc\craft-conductor
   cd C:\cc\craft-conductor
   python -m pip install -e ".[dev]"
   ```
4. Download the release to test from the
   [latest release](https://github.com/silverWRX03/craft-conductor/releases/latest):
   `craft-conductor-windows-x64.exe` and `SHA256SUMS.txt`, into `C:\cc\release`. Download them in
   a browser (not with `curl`), so Windows checks them the way it does for everyone.
5. `mkdir C:\cc\results`, then start Claude Code in the repository:
   `cd C:\cc\craft-conductor; claude`.

Running real servers means accepting the [Minecraft EULA](https://aka.ms/MinecraftEULA) for the
test servers (`--accept-eula`). Each running server needs 2–4 GB of memory.

## 2. How each part runs

Start a **fresh Claude Code session for each part** (`/clear`, or a new window) and paste the
prompt from section 4. In every part, Claude:

- keeps every test server under `C:\cc\servers\part-N` (or the folder the part names), with
  `CRAFT_CONDUCTOR_HOME` set to it, so your own servers are never touched;
- runs the release (`C:\cc\release\craft-conductor-windows-x64.exe`, *the exe* below), not the
  source code, and checks `the exe --version` first;
- doesn't change the repository's code: it reports, it doesn't fix;
- tells you exactly what to do when a step needs you, and waits until you say it's done;
- drives the control panel's API the way `packaging/e2e_test.py` does (its `Web` class) when a
  step has no command, and otherwise asks you to click;
- writes `C:\cc\results\part-N.md`: a table of every check (pass / fail / couldn't test, and
  why), the evidence (commands, their output, lines from the activity log
  `<home>\.craft-conductor\craft-conductor.log` and from the failure reports in
  `<server>\.craft-conductor\logs\`), the Windows version, and for each failure a bug report
  ready for GitHub's **Report a bug** form (what happened, the steps, what was expected);
- stops every test server and Craft Conductor at the end.

Useful commands (all take `-C <server folder>`): `create`, `check`, `update -y`, `run --web`,
`stop`, `status`, `backup --label X`, `backup --list`, `restore [archive] -y`, `cmd <command>`
(over RCON, with `create --rcon`), `self-update --check`.

## 3. The parts

### Part 1: a clean Windows (VM or Sandbox)

1. **The download:** `Get-FileHash -Algorithm SHA256` of the exe matches its line in
   `SHA256SUMS.txt`.
2. **Windows' reaction:** what SmartScreen says on the first run (until code signing is set up,
   unsigned builds get "Windows protected your PC"; record the exact wording and that
   *More info → Run anyway* works), and whether Defender flags it: `Get-MpThreatDetection`, and
   `Start-MpScan -ScanType CustomScan -ScanPath C:\cc\release`.
3. **Every loader, with real downloads:** run `python packaging\e2e_test.py <the exe> <args>`
   once per line (each creates, boots and stops a real server with real mods and Java; the first
   also updates it). Copy `e2e-logs\` into the results after a failure.
   - `--loader fabric --minecraft 1.21.1 --mod fabric-api --mod lithium --upgrade`
   - `--loader neoforge --minecraft 1.21.1 --mod ferrite-core`
   - `--loader forge --minecraft 1.20.1 --mod ferrite-core`
   - `--loader paper --minecraft 1.21.1 --mod chunky`
   - `--loader purpur --minecraft 1.21.1`
   - `--loader quilt --minecraft 1.21.1`
   - `--loader vanilla --minecraft latest`
4. **The control panel, first time:** start the exe with no arguments (with
   `CRAFT_CONDUCTOR_HOME=C:\cc\servers\part-1`); you go through the guided setup in the browser and
   create a Fabric server while Claude watches the activity log. Record anything confusing or slow.

Passes when the hash matches, every e2e run passes, and there are no antivirus detections (or
each one is recorded with its detection name).

### Part 2: the safety checks on a real Windows (any Windows)

Use a Fabric server made with `create C:\cc\servers\part-2\srv --loader fabric --minecraft 1.21.1
--mod fabric-api --rcon --accept-eula`, run once so it has a world, and the control panel
(`run --web`).

1. **Restore with a file in use:** make a backup, then hold a file in the server folder open:
   `$h = [IO.File]::Open("<server>\server.properties", 'Open', 'Read', 'None')`, and
   `restore -y`. Expected: refused, saying a program may be using a file and the server was left
   as it was; the server folder unchanged. `$h.Close()`, restore again: it works. Then repeat with
   the server folder open in File Explorer, with the preview pane on a file (you).
2. **A hostile world `.zip`** (control panel: the server's Settings page → World → **Replace the
   world…**, or New server → **Import a world**): Claude makes a zip holding `world/level.dat`, a normal region file, and
   `world/../../escaped.txt`, `world/region/NUL`, `world/region/COM1.mca`,
   `world/level.dat:hidden`, `world/trailing./x.dat`. Expected: the world imports with only the
   normal files; one "left 5 file(s) out of the world …" line in the activity log; no
   `escaped.txt` anywhere under `C:\cc` (search for it).
3. **A world folder name outside the server:** with the server stopped, set
   `level-name=..\precious` in `server.properties`, with a folder `precious` next to the server
   holding a file. Expected: **Replace the world…** refuses ("must be a plain folder name") and `precious`
   is untouched. Put `level-name=world` back.
4. **A junction in the config folder:** `cmd /c mklink /J <server>\config\shared C:\cc\outside`,
   with a `secret.json` in `C:\cc\outside`. Expected: the Mods page's config files don't list it,
   and asking the API for `config/shared/secret.json` is refused ("reached through a link").
5. **The console:** paste a command with a line break into the Console page (you). Expected:
   refused; nothing after the line break runs.
6. **Ordinary odd names:** a world `.zip` with `region/space (1) [copy] naïve_日本.dat` imports
   with that name.

Passes when each expectation holds, with the log lines as evidence.

### Part 3: power cuts, crashes and a full disk (VM)

Start from the `clean` checkpoint with section 1's setup. Use a Fabric server on Minecraft 1.21.1
with `fabric-api` and `lithium`, made with `create`, and check `check` shows an update to a newer
Minecraft (pick an older version if it doesn't).

1. **Killed in the middle of an update:** start `update -y` and kill Craft Conductor
   (a) while it downloads, (b) right after "backing up …", (c) when it says it's starting the
   server. Once with `taskkill /F /IM craft-conductor-windows-x64.exe` (only Craft Conductor),
   then with `/T` added (with everything it started). After each kill: whether a `java` process is
   still running (`Get-Process java`). A Minecraft server left running after the first kind of kill
   is a known risk: then the next start should refuse to put the backup back because a program is
   using a file (the safe outcome: record it, end that `java`, and start again). Then start it again
   (`run`). Expected: the
   activity log says it was stopped in the middle of an update and put the backup back; `status`
   shows the old Minecraft version; the world is intact; no `server.restoring`,
   `server.replaced`, `*.part` or `.craft-conductor\update-in-progress.json` left.
2. **The power goes off:** start an update and turn the VM off hard (you: Hyper-V *Action → Turn
   Off*, VirtualBox *Close → Power off the machine*) right after "backing up …", and again while
   the new version starts. Boot, start Craft Conductor: as in 1, and `craft-conductor.lock.json`
   is valid JSON.
3. **A full disk:** add a 4 GB virtual disk as `E:` (Disk Management: *Action → Create VHD*, then
   initialize and format it). With `CRAFT_CONDUCTOR_HOME=E:\cc`, create the server there, make one
   backup, then fill the disk to about 20 MB free: `fsutil file createnew E:\fill.bin <bytes>`
   (from `Get-PSDrive E`). Then:
   - `backup`: expected "the disk is full", and no `*.part` file left;
   - `update -y`: expected "Update not done … the disk is full … Nothing was changed", and a
     server that was running is running again;
   - import a world `.zip` bigger than the free space: expected "there isn't enough free disk
     space";
   - `restore -y` of that backup: expected refused ("there isn't enough free disk space"), the
     server as it was;
   - and what the running Minecraft server says when it can't save (record it).

   Delete `fill.bin`: each of them works again.
4. **Damaged saves:** with the server stopped, cut `world\level.dat` to half its size and make a
   backup: expected "doesn't look right … level.dat" (and the notification). Restore an earlier
   backup: the world is back. Cut a `world\region\r.0.0.mca` short and start the server: record
   what Minecraft and Craft Conductor say.
5. **Crash restarts:** with the server running under `run`, kill Java (`Stop-Process -Name java
   -Force`). Expected: restarted within about a minute, with a failure report's path in the log.
   Kill it four times within ten minutes: expected to stop restarting and say so.

Passes when, after every step, the server starts on the version its files say, with the world
intact, a clear message, and no leftovers.

### Part 4: OneDrive and non-English folders (your PC, or the VM signed in with a Microsoft account)

1. **OneDrive:** `CRAFT_CONDUCTOR_HOME=$env:OneDrive\Documents\cc-test`: create a server, make
   backups, update, restore. In Explorer, right-click the backups folder → *Free up space* (the
   backups become online-only) and restore one: record whether it downloads and restores, or what
   it says. Then Settings → Backup copies → *Also copy every backup to* a OneDrive folder: the
   copies appear; with OneDrive paused, backups still work.
2. **A non-English user name and folder:** create a local Windows user `José Müller` (Settings →
   Accounts → Other users), sign in as them (you), and run part 1's Fabric e2e line and a backup
   and restore from that profile. Then, as yourself, the same with
   `CRAFT_CONDUCTOR_HOME=C:\cc\Документы\Майнкрафт`.
3. **Long paths:** with `CRAFT_CONDUCTOR_HOME` about 150 characters deep, create a NeoForge server
   (its libraries have long paths). Record whether long paths are on
   (`Get-ItemProperty HKLM:\SYSTEM\CurrentControlSet\Control\FileSystem LongPathsEnabled`) and any
   "path too long" error.
4. **Controlled folder access** (Windows Security → Virus & threat protection → Ransomware
   protection): turn it on (you), create a server under Documents, and record whether Windows
   blocks Craft Conductor or Java, and how that shows in Craft Conductor.

### Part 5: antivirus (the VM with a third-party antivirus, then your PC)

Once with only Defender, then with one third-party antivirus installed (for example Avast Free or
Bitdefender Free):

1. Download the release in a browser and run it: record any warning, quarantine or blocked
   network access.
2. Create a Fabric server, start it, make three backups, update it, restore one, and
   `self-update --check`. Record "being used by another process" errors, steps that are much
   slower than with Defender alone, and anything quarantined (the exe, the Java it downloads, mod
   jars, backups).
3. Anything flagged: the detection name and file, so you can submit it as a false positive
   (Microsoft: <https://www.microsoft.com/wdsi/filesubmission>; other vendors have their own
   forms).

### Part 6: routers, carrier-grade NAT and phones (your home; you do the router and the phone)

Record your router's make, model and firmware, and your internet provider, so a failure can be
reproduced.

1. **Your router:** start the control panel; a server's Dashboard → 🩺 **Check my setup** →
   **Test from the internet**. Then Craft Conductor settings → Connections → Sharing with friends
   → Router: switch on **Open the ports on my router by itself (UPnP)**; record the warning text.
   In the router's admin page (UPnP or port forwarding list) check what was opened: the server's
   port only, never the control panel's port or RCON. **Test from the internet** again; your phone
   on mobile data (Wi-Fi off) joins the server. Switch UPnP off: the router's mapping goes away.
2. **Carrier-grade NAT:** connect the PC to your phone's hotspot (mobile networks usually use
   CGNAT) and run **Check my setup**: record whether it says friends can't reach you directly and
   suggests playit.gg or Tailscale; try the playit.gg route.
3. **Invite links on a phone:** Friends page → make an invite link; open it on the phone on mobile
   data; record what works, and that it stops working when **Links work for** says.
4. **The phone app over Tailscale** (the manual's *The phone app* section): pair, sign in, start
   and stop a server from the phone, and get a notification.

## 4. Prompts to paste

**For each part** (in a fresh session, replace `N` with the part's number):

```text
You're testing a released build of Craft Conductor on this Windows PC, together with me.
Read docs/real-world-testing.md in this repository (sections 2 and 3) and carry out Part N
exactly as written there, against the release in C:\cc\release (check its --version first).
Rules: don't change any code in this repository; keep all test data under C:\cc; when a step
needs me (clicking in the control panel, the router, the phone, turning the VM off), tell me
exactly what to do and wait until I say it's done; write the results to C:\cc\results\part-N.md
as section 2 describes; stop every test server at the end. Before you start, tell me in a few
lines what you'll do and what you'll need from me.
```

**When the parts are done:**

```text
Read every file in C:\cc\results. For each failure: check whether it's a bug in Craft Conductor
(reproduce it with the release if you can; otherwise say why not), look for an existing GitHub
issue at https://github.com/silverWRX03/craft-conductor/issues, and draft a new issue in the
format of the repository's "Report a bug" form (.github/ISSUE_TEMPLATE), with the evidence from
the results. Then give me a short summary: what passed, what failed, and what couldn't be tested
and why. Don't file anything or change any code until I say so.
```
