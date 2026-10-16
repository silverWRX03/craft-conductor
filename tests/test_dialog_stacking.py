"""A question asked from inside a panel (Check my setup's "Read and accept the EULA") must open on top of it."""

import re
from importlib import resources


def _z(css: str, selector: str) -> int:
    rule = re.search(re.escape(selector) + r"[^{]*\{([^}]*)\}", css)
    assert rule, selector
    return int(re.search(r"z-index:\s*(\d+)", rule.group(1)).group(1))


def test_questions_and_messages_open_above_panels():
    css = resources.files("craft_conductor").joinpath("webui", "style.css").read_text(encoding="utf-8")
    panel = _z(css, "\n.modal-backdrop ")
    assert _z(css, "\n.modal-backdrop.blur,") > panel  # (ask() and stickyToast() use .modal-backdrop.blur)
