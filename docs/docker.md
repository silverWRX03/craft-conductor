# Running Craft Conductor in Docker

The image holds Craft Conductor and Python. Craft Conductor downloads Minecraft, the mod loader, mods and Java
into `/data` when you create a server. Keep `/data` on a volume and your servers survive
image updates.

## Start it

```sh
docker run -d --name craft-conductor --restart unless-stopped \
  -p 127.0.0.1:8765:8765 -p 25565:25565 -p 8798:8798 \
  -v craft-conductor-data:/data \
  -e CRAFT_CONDUCTOR_LAN_IP=192.168.1.20 \
  ghcr.io/silverwrx03/craft-conductor:latest
```

Or use [`docker-compose.yml`](../docker-compose.yml): `docker compose up -d`.

| Port | What |
|---|---|
| 8765 | the control panel. Open `http://localhost:8765` on the Docker host. `127.0.0.1:` keeps it there; to open it from other devices on your network, publish it as `-p 8765:8765` instead. **Don't forward this one on your router.** |
| 25565 | Minecraft. Each extra server needs its own port: map a range, e.g. `-p 25565-25570:25565-25570`. |
| 8798 | friends' downloads (HTTPS; the invites), only needed if you use them |

`CRAFT_CONDUCTOR_LAN_IP` is the Docker host's address on your network. Inside a container Craft Conductor can't
see it, and it goes into invite links and the phone-pairing QR code.

## First sign-in

Inside the container, Craft Conductor listens on all of the container's addresses (Docker needs
that to pass the port on); which of the host's addresses it's published on is up to the `-p`
above. To Craft Conductor every browser looks like another device, and those need a strong
password (12+ characters, upper and lower case, and a special character). On the first start
Craft Conductor makes a **one-time password** and prints it:

```sh
docker logs craft-conductor | grep Password
```

Sign in with it and choose your own. Until you do, it can't be used for anything else. You
can also set a strong password up front with `-e CRAFT_CONDUCTOR_INITIAL_PASSWORD='Your-Strong-Pass1'`.
It's only used when `/data` is new.

Forgot the password? Stop the container, delete `/data/.craft-conductor/web-auth.json` in the volume,
and start it again for a new one-time password.

## Memory

Give the container at least the memory your servers use, plus about 1 GB. With
`--memory`, leave that headroom or the kernel stops the server abruptly.

## Updating

```sh
docker pull ghcr.io/silverwrx03/craft-conductor:latest
docker rm -f craft-conductor && docker run ...   # same command as before; /data keeps everything
```

Craft Conductor's own "update Craft Conductor" button doesn't apply to containers: update the image instead.
`:latest` is the newest stable release; `:beta` is the newest beta (early versions, less tested).

## Stopping

`docker stop craft-conductor` asks Craft Conductor to stop. Every server saves its world and shuts down cleanly.
Allow it time: `docker stop -t 120 craft-conductor`, or `stop_grace_period` in compose.

## Building it yourself

```sh
docker build -t craft-conductor .
```
