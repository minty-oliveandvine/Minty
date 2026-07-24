"""Regression coverage for the unified flash-message renderer.

Bug being guarded: Flask keeps flashes in the (server-side) session until a
page calls ``get_flashed_messages()``. Many backend paths queue a flash and
redirect (session expired, "entity not found", read-only write, CSRF). When the
landing page did NOT drain, the message survived and popped up later on some
unrelated page — a "stale toast" appearing "when you enter an entity" or after
logging in.

The fix routes ALL flash rendering through a single partial,
``components/flash_messages.html``, and includes it on every standalone page so
the session flash queue is always consumed on the next page load.

Two guarantees are tested here:
  1. The canonical partial renders the message AND drains the session queue.
  2. Every standalone full-page template includes the partial (or extends the
     base layout, which includes it) — so no page can silently skip the drain
     and reintroduce the leak.
"""

from __future__ import annotations

import pathlib

from flask import Flask, render_template_string, session

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "templates"
PARTIAL = "components/flash_messages.html"


def _build_app() -> Flask:
    app = Flask(__name__, template_folder=str(TEMPLATES))
    app.config["TESTING"] = True
    app.secret_key = "test-secret"
    # The partial only needs url_for('static', ...); stub it.
    app.jinja_env.globals["url_for"] = lambda *a, **kw: "/stub"
    return app


def test_partial_renders_and_drains_stale_flash():
    app = _build_app()
    with app.test_request_context("/anything"):
        session["_flashes"] = [("danger", "Hmm, I looked everywhere but couldn't find that one.")]

        source = (TEMPLATES / "components" / "flash_messages.html").read_text(
            encoding="utf-8"
        )
        html = render_template_string(source)

        # Rendered: the message text is emitted (into the showFlashMessages call).
        assert "Hmm, I looked everywhere but couldn't find that one." in html
        # Drained: the cross-request leak vector is emptied.
        assert session.get("_flashes", []) == []


def test_partial_maps_danger_to_error_tone():
    app = _build_app()
    with app.test_request_context("/anything"):
        session["_flashes"] = [("danger", "boom")]
        source = (TEMPLATES / "components" / "flash_messages.html").read_text(
            encoding="utf-8"
        )
        html = render_template_string(source)
        # danger/error collapse to the 'error' tone in the client call.
        assert '"error"' in html


def _standalone_page_templates() -> list[pathlib.Path]:
    """Full-page templates: those that declare their own <body>. Templates that
    ``{% extends 'base/layout.html' %}`` have no <body> of their own and inherit
    the include, so they are intentionally excluded here (the base carries it)."""
    pages = []
    for p in TEMPLATES.rglob("*.html"):
        if p.name == "flash_messages.html":
            continue
        text = p.read_text(encoding="utf-8")
        if "<body" in text:
            pages.append(p)
    return pages


def test_every_standalone_page_drains_flashes():
    """Invariant: every standalone page must consume the flash queue so a queued
    message can't leak forward. Enforced by requiring the canonical include."""
    missing = []
    for p in _standalone_page_templates():
        text = p.read_text(encoding="utf-8")
        includes_partial = PARTIAL in text
        extends_base = "extends 'base/layout.html'" in text or 'extends "base/layout.html"' in text
        if not (includes_partial or extends_base):
            missing.append(p.relative_to(TEMPLATES).as_posix())
    assert not missing, (
        "These standalone pages do not drain the flash queue (add "
        f"{{% include '{PARTIAL}' %}}): " + ", ".join(sorted(missing))
    )
