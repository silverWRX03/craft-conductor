# craft-conductor in a container: the control panel and your Minecraft servers.
#
#   docker run -d --name craft-conductor -p 8765:8765 -p 25565:25565 -p 8798:8798 \
#     -v craft-conductor-data:/data -e CRAFT_CONDUCTOR_LAN_IP=192.168.1.20 ghcr.io/silverwrx03/craft-conductor
#
# Everything (servers, worlds, backups, the Java that craft-conductor downloads) lives in /data, so keep
# that volume. See docs/docker.md.
FROM python:3.12-slim

# craft-conductor needs nothing but Python: it downloads Java (Eclipse Temurin) for each Minecraft version itself.
RUN useradd --create-home --uid 1000 craft-conductor && mkdir /data && chown craft-conductor:craft-conductor /data

COPY --chown=craft-conductor:craft-conductor . /tmp/craft-conductor-src
RUN pip install --no-cache-dir /tmp/craft-conductor-src && rm -rf /tmp/craft-conductor-src

USER craft-conductor
ENV CRAFT_CONDUCTOR_HOME=/data \
    CRAFT_CONDUCTOR_CONTAINER=1 \
    PYTHONUNBUFFERED=1
VOLUME /data
WORKDIR /data
# 8765: the control panel; 25565: Minecraft (add more for more servers); 8798: friends' downloads
EXPOSE 8765 25565 8798
HEALTHCHECK --interval=60s --timeout=5s --start-period=30s \
  CMD python -c "import urllib.request,sys; urllib.request.urlopen('http://127.0.0.1:8765/api/auth', timeout=4)" || exit 1
# craft-conductor stops every server cleanly (saving worlds) on SIGTERM, i.e. `docker stop`.
STOPSIGNAL SIGTERM
CMD ["craft-conductor", "start", "--no-browser", "--web-host", "0.0.0.0"]
