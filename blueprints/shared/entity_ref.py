"""Company addresses: ``/entity/<shortid>/<name>/...`` (2026-10-05).

The address bar shows the company's name instead of its uuid. The first 8 hex characters of the
id decide which company it is; the name after it is only for reading, so a rename never breaks a
link - an address with an old (or no) name is redirected to the current one. No schema change:
nothing is stored, the name is slugified on the way out.

How it fits together:

* ``EntityRefConverter`` (``<entity:...>`` in a rule) matches either ``<8 hex>/<slug>`` or a
  full uuid and resolves it to the company's uuid as the address is matched - so
  ``require_entity_access(entity_arg=...)``, ``module_guard``, the hooks and the ~90 views
  that look a company up receive exactly what they did before.
* ``redirect_to_canonical`` (an app-wide ``url_value_preprocessor``) 308s a GET whose address
  used a full uuid or a name that is not the current one to the canonical address, query
  string kept, before any ``before_request`` hook runs.
* ``to_url`` builds the canonical form from a uuid, reading each company's name once per
  request, so ``url_for(..., entity_id=org.id)`` keeps working unchanged everywhere.

The other apps (minty-web, the payment request app) know only uuids: they link
``/entity/<uuid>/...`` and the redirect above shows the readable address.
"""

from __future__ import annotations

import re
import unicodedata
import uuid as uuid_mod

from flask import g, has_app_context, request
from loguru import logger
from werkzeug.routing import BaseConverter, RequestRedirect

SHORT_ID_LENGTH = 8
SLUG_MAX = 60
EMPTY_SLUG = "company"
#: What an address naming no company resolves to: a valid uuid no company has.
NIL_UUID = "00000000-0000-0000-0000-000000000000"

_HEX8 = "[0-9a-fA-F]{8}"
_FULL_UUID = _HEX8 + "-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"


def slugify_name(name: str | None) -> str:
    """A company name as an address segment: lowercase, ``&`` as "and", letters and digits of
    any script kept (a browser shows ``/茶餐廳`` as written), anything else a single ``-``."""
    text = unicodedata.normalize("NFKC", name or "").lower().replace("&", " and ")
    slug = "".join(ch if ch.isalnum() else "-" for ch in text)
    slug = re.sub(r"-{2,}", "-", slug).strip("-")[:SLUG_MAX].rstrip("-")
    return slug or EMPTY_SLUG


class ResolvedEntityId(str):
    """The company's uuid, as a plain ``str`` everywhere it is read (``view_args``, guards,
    queries), carrying whether the address that named it was already the canonical one."""

    canonical: bool

    def __new__(cls, value: str, *, canonical: bool):
        obj = super().__new__(cls, value)
        obj.canonical = canonical
        return obj


def _names_for(ids: set[str]) -> dict[str, str]:
    """``{uuid: name}``, cached for the request (or app context) so a page full of links costs
    one query per company at most."""
    cache = g.setdefault("_entity_names", {}) if has_app_context() else {}
    missing = [i for i in ids if i not in cache]
    if missing:
        from models.db import Entity

        for row_id, name in Entity.query.with_entities(Entity.id, Entity.name).filter(
            Entity.id.in_(missing)
        ):
            cache[str(row_id)] = name or ""
    return {i: cache[i] for i in ids if i in cache}


def _as_uuid(value) -> str | None:
    try:
        return str(uuid_mod.UUID(str(value)))
    except (ValueError, AttributeError, TypeError):
        return None


def canonical_ref(entity_id) -> str:
    """``<shortid>/<slug>`` for a company uuid. A value that is not a company's uuid is
    written as it is (the ``<entity:...>`` rule takes a full uuid and resolves it on the way
    in), so building a link never queries the database with something that is not an id."""
    full = _as_uuid(entity_id)
    if full is None:
        return str(entity_id)
    names = _names_for({full})
    if full not in names:
        return full
    return f"{full[:SHORT_ID_LENGTH]}/{slugify_name(names[full])}"


def _lookup_short_id(short_id: str) -> list[tuple[str, str]]:
    """``(uuid, name)`` of every company whose id starts with ``short_id``. A range on the
    primary key, so the index is used."""
    from models.db import Entity

    low = f"{short_id}-0000-0000-0000-000000000000"
    high = f"{short_id}-ffff-ffff-ffff-ffffffffffff"
    rows = Entity.query.with_entities(Entity.id, Entity.name).filter(
        Entity.id >= low, Entity.id <= high
    ).all()
    return [(str(row_id), name or "") for row_id, name in rows]


def resolve(value: str) -> ResolvedEntityId:
    """The uuid an ``<entity:...>`` address segment names.

    An unknown company is NOT answered with a 404 here: the result is a uuid no company has
    (the full one given, or the nil uuid for a short id) and the usual sign-in, Terms and
    membership checks answer as they always did - so an address tells a stranger nothing about
    which short ids exist. A short id two companies share is told apart by the slug, else it
    is logged and treated as unknown."""
    if "/" not in value:
        full = _as_uuid(value) or NIL_UUID
        return ResolvedEntityId(full, canonical=full not in _names_for({full}))
    short_id, slug = value.split("/", 1)
    matches = _lookup_short_id(short_id.lower())
    if len(matches) > 1:
        same_slug = [m for m in matches if slugify_name(m[1]) == slug]
        if len(same_slug) != 1:
            logger.error(
                f"company address /entity/{short_id}/{slug} is ambiguous: "
                f"{len(matches)} companies share the short id"
            )
            return ResolvedEntityId(NIL_UUID, canonical=True)
        matches = same_slug
    if not matches:
        return ResolvedEntityId(NIL_UUID, canonical=True)
    full, name = matches[0]
    if has_app_context():
        g.setdefault("_entity_names", {})[full] = name
    return ResolvedEntityId(full, canonical=slug == slugify_name(name) and short_id == full[:SHORT_ID_LENGTH])


class EntityRefConverter(BaseConverter):
    """``<entity:name>``: ``<8 hex>/<slug>`` or a full uuid, resolved to the company's uuid as
    the address is matched - so nothing that reads ``view_args`` ever sees anything else. Spans
    a ``/``, hence not part isolating. The slug is required in the short form, so
    ``/entity/<shortid>/reports`` can never be read as a company called "reports"."""

    regex = f"(?:{_FULL_UUID}|{_HEX8}/[^/]+)"
    part_isolating = False
    weight = 100

    def to_python(self, value: str) -> ResolvedEntityId:
        return resolve(value)

    def to_url(self, value) -> str:
        return canonical_ref(value)


def redirect_to_canonical(endpoint, values) -> None:
    """308 a GET whose address named a company by a full uuid, an old name or a short id in
    capitals, to the canonical address, query string kept. Runs before every ``before_request``
    hook; a POST is served where it is (its form was drawn by an older page)."""
    if not values or request.method not in ("GET", "HEAD"):
        return
    if all(getattr(v, "canonical", True) for v in values.values()):
        return
    from flask import url_for

    target = url_for(endpoint, **{k: str(v) for k, v in values.items()})
    if request.query_string:
        target += "?" + request.query_string.decode("latin-1")
    raise RequestRedirect(target)


def init_app(app) -> None:
    """Register the converter (before any blueprint adds a rule) and the resolver."""
    app.url_map.converters["entity"] = EntityRefConverter
    app.url_value_preprocessor(redirect_to_canonical)
