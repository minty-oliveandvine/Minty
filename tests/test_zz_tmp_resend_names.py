"""Verify send_invitation_email falls back to the persisted invitation names."""
from unittest.mock import MagicMock


def test_resend_uses_persisted_names(app, monkeypatch):
    import blueprints.invitation.services.invite as inv

    captured = {}

    inv_obj = MagicMock()
    inv_obj.token = "tok123"
    inv_obj.entity_id = "e1"
    inv_obj.invited_by = None
    inv_obj.email = "new@example.com"
    inv_obj.first_name = "Ada"
    inv_obj.last_name = "Lovelace"

    def fake_url_for(endpoint, **kw):
        if endpoint == "static":
            return "http://x/static/"
        return "http://x/invite/" + kw.get("token", "")

    def fake_build(**ctx):  # the mail body is built here, not by render_template
        captured["accept_url"] = ctx.get("accept_url")
        return "<html></html>"

    mail = MagicMock()
    monkeypatch.setattr(inv, "url_for", fake_url_for)
    monkeypatch.setattr(inv, "_build_invitation_html", fake_build)
    monkeypatch.setattr(inv, "_record_sent", lambda _id: None)
    with app.app_context():  # reading ``Model.query`` to replace it needs a context
        monkeypatch.setattr(inv.Entity, "query", MagicMock(get=lambda _id: None))
        monkeypatch.setattr(inv.User, "query", MagicMock(get=lambda _id: None))
    monkeypatch.setattr(inv, "current_app", MagicMock(extensions={"mail": mail},
                                                      config={"PETTY_CASH_URL": "http://x"}))
    monkeypatch.setattr(inv, "Message", MagicMock())

    # Resend shape: no name args, exactly how api.py:205 calls it.
    inv.send_invitation_email(inv_obj)

    url = captured.get("accept_url", "")
    print("ACCEPT_URL:", url)
    assert "fn=Ada" in url, f"first name missing from {url!r}"
    assert "ln=Lovelace" in url, f"last name missing from {url!r}"
