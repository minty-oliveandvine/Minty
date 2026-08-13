"""The users page names the SUBSCRIBER, because the role column alone cannot.

Changing what a company is billed for takes two things at once: ``MODULE_MANAGE`` (admin
rank) and ``may_manage_subscription`` (being the payer). The page showed only the first,
so every admin on the list looked equally able to — and the ones who are not the payer
opened module settings to find the buttons gone, with nothing anywhere saying why.

The payer is not derivable from the role beside it. It is recorded per entity on the
subscription rows (``store.payer_for_entity``), so it is a separate lookup and a separate
tag rather than a sixth role.
"""
from __future__ import annotations


def _user(uid, first="Ada", last="Lovelace"):
    return type(
        "U",
        (),
        {
            "id": uid,
            "first_name": first,
            "last_name": last,
            "username": f"{first.lower()}@example.com",
        },
    )()


def _render(app, users, subscriber_id=None, can_edit=True, can_remove=True):
    """The shared users block, as both the Petty Cash and Bills pages include it."""
    from flask import render_template

    with app.test_request_context():
        return render_template(
            "entity/settings_users_main_block.html",
            users=users,
            subscriber_id=subscriber_id,
            is_view_only=False,
            can_edit_users=can_edit,
            can_remove_users=can_remove,
        )


def _row_for(html, name):
    """The rendered card for one person, split off the user list."""
    rows = html.split('rounded-lg shadow-sm p-4')
    for row in rows:
        if name in row:
            return row
    raise AssertionError(f"no user row rendered for {name}")


def test_the_payer_is_tagged_and_nobody_else_is(app):
    """One tag on one person — the fact the page was missing."""
    html = _render(
        app,
        [(_user("u1", "Ada"), "admin"), (_user("u2", "Grace"), "admin")],
        subscriber_id="u1",
    )

    assert "Subscriber" in _row_for(html, "Ada")
    assert "Subscriber" not in _row_for(html, "Grace")
    assert html.count("data-subscriber") == 1


def test_an_entity_with_no_payer_tags_nobody(app):
    """Nothing has ever been billed for this company, so there is no subscriber to name —
    and an untagged list must not imply the first admin is one."""
    html = _render(
        app, [(_user("u1", "Ada"), "admin")], subscriber_id=None
    )

    assert "data-subscriber" not in html


def test_the_tag_is_the_payer_not_the_rank(app):
    """A payer who is NOT an admin still carries the tag: it states who is billed, which
    is true regardless of what they are allowed to do.

    This combination is worth seeing precisely because it is a dead end — module settings
    need admin AND payer, so nobody on this company can change its modules until either
    this person is made an admin or the subscription moves. Hiding the tag would hide the
    only clue.
    """
    html = _render(
        app,
        [(_user("u1", "Ada"), "cashier"), (_user("u2", "Grace"), "admin")],
        subscriber_id="u1",
    )

    ada = _row_for(html, "Ada")
    assert "Subscriber" in ada
    assert "Cashier" in ada, "the role tag stays — the two are separate facts"
    assert "Subscriber" not in _row_for(html, "Grace")


def test_each_row_button_follows_its_own_endpoints_permission(app):
    """Edit and Remove post to endpoints guarded differently — USER_ROLE_ASSIGN (min shop
    manager) and USER_ROLE_DELETE (min accountant). Both used to hang off ``is_view_only``,
    which asks about INVITING, so a shop manager was shown a Remove button that the API
    answers with a 403."""
    users = [(_user("u1", "Ada"), "admin")]

    both = _render(app, users)
    assert "openEditUserModal" in both
    assert "openDeleteUserModal" in both

    # A shop manager: may edit, may not remove.
    edit_only = _render(app, users, can_remove=False)
    assert "openEditUserModal" in edit_only
    assert "openDeleteUserModal" not in edit_only

    neither = _render(app, users, can_edit=False, can_remove=False)
    assert "openEditUserModal" not in neither
    assert "openDeleteUserModal" not in neither


def test_the_id_comparison_survives_a_uuid(app):
    """``payer_for_entity`` can hand back a UUID rather than a str, and the row ids come
    off the ORM. Both sides are compared as strings, or the tag silently never renders."""
    import uuid

    uid = uuid.uuid4()
    html = _render(app, [(_user(uid, "Ada"), "admin")], subscriber_id=str(uid))

    assert "data-subscriber" in html
