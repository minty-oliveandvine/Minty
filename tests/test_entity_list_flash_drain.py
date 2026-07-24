"""Regression: the populated entity-list template (entity/index.html) must
render AND drain flash messages.

Bug: index.html had the toast close/auto-hide JS but no
``get_flashed_messages`` block, so a flash queued by a prior request (e.g. a
redirect into the entity list that flashed "Hmm, I looked everywhere but couldn't find that one.") was never
consumed there. It survived in the session and popped up on the next page that
renders the ``danger`` category — the dashboard — i.e. "when you enter an
entity". The empty-state sibling (entity_list_empty.html) already drained.

This test renders index.html with a stale flash queued and asserts the message
appears in the output (rendered) and that the session flash queue is emptied
afterwards (drained).
"""

from __future__ import annotations

import pathlib

from flask import Flask, render_template_string, session

TEMPLATES = pathlib.Path(__file__).resolve().parents[1] / "templates"


# The entity list pulls in three component partials and several entity-scoped
# url_for targets / globals. Stub them so the template renders standalone and
# the test stays focused on the flash block.
_STUB_INCLUDES = {
    "components/hover_effects.html": "",
    "components/page_transitions.html": "<script>window.PageTransition={init(){},navigateWithFade(){}}</script>",
    "components/sidepanel.html": "",
}


def _build_app() -> Flask:
    app = Flask(__name__, template_folder=str(TEMPLATES))
    app.config["TESTING"] = True
    app.secret_key = "test-secret"

    # Resolve every entity url_for target to a dummy path and provide the
    # template globals index.html calls.
    app.jinja_env.globals["url_for"] = lambda *a, **kw: "/stub"
    app.jinja_env.globals["bills_app_profile_unscoped_url"] = lambda *a, **kw: "/stub"
    app.jinja_env.globals["toggleMenu"] = lambda *a, **kw: ""
    return app


def _render_index(app: Flask) -> str:
    # Swap component includes for stubs, then render the real index.html body.
    from jinja2 import ChoiceLoader, DictLoader

    app.jinja_loader = ChoiceLoader([DictLoader(_STUB_INCLUDES), app.jinja_loader])
    source = (TEMPLATES / "entity" / "index.html").read_text(encoding="utf-8")
    return render_template_string(
        source,
        organizations=[],
        current_user=type("U", (), {"first_name": "A", "last_name": "B"})(),
    )


def test_entity_list_renders_and_drains_stale_flash():
    app = _build_app()
    with app.test_request_context("/entity"):
        session["_flashes"] = [("danger", "Hmm, I looked everywhere but couldn't find that one.")]

        html = _render_index(app)

        # Rendered: the stale message is shown on the list (not silently dropped).
        assert "Hmm, I looked everywhere but couldn't find that one." in html
        # Drained from the session (the cross-request leak vector) so it can't
        # resurface on the dashboard next render.
        assert session.get("_flashes", []) == []


def test_entity_list_renders_success_flash():
    """A legitimate list-bound flash (e.g. delete_entity success) is visible."""
    app = _build_app()
    with app.test_request_context("/entity"):
        session["_flashes"] = [("success", "Entity deleted successfully.")]

        html = _render_index(app)

        assert "Entity deleted successfully." in html
        assert session.get("_flashes", []) == []
