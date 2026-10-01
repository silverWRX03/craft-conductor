from __future__ import annotations

import logging

from .http import HttpClient

log = logging.getLogger(__name__)


class Notifier:
    def __init__(self, http: HttpClient, discord_webhook: str = ""):
        self.http = http
        self.discord_webhook = discord_webhook
        #: also told every message (phone notifications, see push.py); never allowed to fail a send
        self.listeners: list = []

    def send(self, message: str) -> None:
        log.info("%s", message)
        for listener in list(self.listeners):
            try:
                listener(message)
            except Exception:
                log.exception("a notification listener failed")
        if not self.discord_webhook:
            return
        try:
            self.http.post_json(self.discord_webhook, {"content": message[:2000], "username": "Craft Conductor"})
        except Exception as e:  # a notification failure must never break an upgrade
            log.warning("discord notification failed: %s", e)
