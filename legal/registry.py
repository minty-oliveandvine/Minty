"""The published legal documents: their text, versions, and fingerprints.

Loaded once at import. Nothing here touches the database or the request — a
document is a file on disk, and this module is the only thing that reads it.

WHY A FINGERPRINT
-----------------
Recording "this person accepted beta-1" proves they clicked a button with a
label on it. It does not prove what the document said. So every consent row
also stores the SHA-256 of the exact wording shown, and this module is where
that number comes from.

The hash is taken over the `.md`, never a PDF: PDF writers embed a creation
timestamp, so building the same PDF twice yields two different fingerprints.

NEWLINE NORMALISATION MATTERS
-----------------------------
The hash is computed over text normalised to `\\n` endings with trailing
whitespace stripped. Without that, a checkout on Windows with `core.autocrlf`
enabled hashes differently from the same file on the Linux host, and every
consent row written on one would look tampered with from the other. The
normalisation is part of the definition of the fingerprint, not an
implementation detail — it must not change once anything is published.

PINNING
-------
`_PINNED_HASHES` records the fingerprint a published document is expected to
have. `verify_pinned_hashes()` re-checks it at startup, so a file edited by
accident is caught immediately rather than years later when a consent record
needs to be defended.

A version with `None` is NOT yet pinned — it is still a draft. Pin it (and only
then) when the wording is final. See `beta-1` below.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass

from loguru import logger

from legal.render import render_markdown

TERMS = "terms"
PRIVACY = "privacy"
DOCUMENT_KINDS = (TERMS, PRIVACY)

_LEGAL_DIR = os.path.dirname(os.path.abspath(__file__))

# The single setting that drives who gets asked to agree. Changing it moves
# every user from AGREED_CURRENT to OUT_OF_DATE at once — that is the whole
# mechanism for a Terms revamp, so change it only for meaningful revisions.
# A typo fix gets a new file and leaves this alone.
CURRENT_TERMS_VERSION = os.environ.get("CURRENT_TERMS_VERSION", "beta-1")
CURRENT_PRIVACY_VERSION = os.environ.get("CURRENT_PRIVACY_VERSION", "beta-1")

# Whether an unpinned (draft) document shows its "this wording is not final"
# banner on the acceptance screen.
#
# DEFAULTS TO ON, and should stay on anywhere real people are asked to agree.
# The opt-out exists so a draft can be hidden for demos and screenshots without
# PINNING the hash, which would assert the wording is final — a claim that is
# untrue while beta-1 still contains [DATE], [INSERT EMAIL] and
# [INSERT ADDRESS].
#
# Because it defaults to on, an environment that simply does not set it — a
# fresh production deploy, say — still warns. Hiding the banner has to be a
# deliberate act, recorded in that environment's config.
SHOW_DRAFT_BANNER = os.environ.get(
    "LEGAL_SHOW_DRAFT_BANNER", "1"
).strip().lower() not in {"0", "false", "no", "off"}

# Whether sign-up REFUSES to create an account without agreement.
#
# ON as of Phase 6. A sign-up that does not carry an explicit agreement to the
# live version is rejected with 400 — no account, no consent row.
#
# *** DEPLOY ORDER STILL MATTERS ***
#
# Minty and the onboarding app release separately. If this is on in Flask while
# the onboarding app is still running a bundle that does not send
# `terms_accepted`, EVERY sign-up through it fails. The order is: ship Flask
# accepting the fields, ship onboarding sending them, confirm both are live,
# and only then deploy with this on.
#
# Set REQUIRE_TERMS_AT_SIGNUP=false to fall back to the rollout behaviour
# without a code change — sign-up succeeds and the person meets the acceptance
# gate at their next request instead. That is the lever to pull if sign-ups
# start failing after a deploy.
REQUIRE_TERMS_AT_SIGNUP = (
    os.environ.get("REQUIRE_TERMS_AT_SIGNUP", "true").strip().lower() == "true"
)

# Publication date per version, as printed in the document header.
# `beta-1` carries `Last Updated: [DATE]` — an unresolved blank in the source
# `.docx`. It stays None until the legal owner fills it in, and
# `GET /legal/current` reports null rather than inventing one.
_EFFECTIVE_DATES: dict[tuple[str, str], str | None] = {
    (TERMS, "beta-1"): None,
    (PRIVACY, "beta-1"): None,
}

# Expected SHA-256 per published document. None == draft, not yet pinned.
#
# beta-1 is UNPINNED on purpose: the source .docx still contains [DATE],
# [INSERT EMAIL] and [INSERT ADDRESS], so the wording will change at least
# once more. Pin it in the same commit that fills those blanks, and before any
# consent row is written in production — a record that fingerprints a draft is
# worth less than no record at all.
_PINNED_HASHES: dict[tuple[str, str], str | None] = {
    (TERMS, "beta-1"): None,
    (PRIVACY, "beta-1"): None,
}


@dataclass(frozen=True)
class LegalDocument:
    kind: str
    version: str
    text: str
    html: str
    sha256: str
    effective_date: str | None

    @property
    def is_pinned(self) -> bool:
        return _PINNED_HASHES.get((self.kind, self.version)) is not None

    @property
    def show_draft_notice(self) -> bool:
        """Whether the acceptance screen should warn that this is a draft.

        Kept as a property rather than a second template condition so every
        render site — the standalone page and the modal over the entity list —
        asks one question and cannot disagree about the answer.
        """
        return not self.is_pinned and SHOW_DRAFT_BANNER


def _normalise(raw: str) -> str:
    """Canonical form of a document for hashing and display.

    Part of the fingerprint's definition — see the module docstring.
    """
    return raw.replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _load() -> dict[tuple[str, str], LegalDocument]:
    documents: dict[tuple[str, str], LegalDocument] = {}
    for kind in DOCUMENT_KINDS:
        directory = os.path.join(_LEGAL_DIR, kind)
        if not os.path.isdir(directory):
            logger.warning(f"Legal: no {kind}/ directory at {directory}")
            continue
        for filename in sorted(os.listdir(directory)):
            if not filename.endswith(".md"):
                continue
            version = filename[: -len(".md")]
            path = os.path.join(directory, filename)
            with open(path, encoding="utf-8") as handle:
                text = _normalise(handle.read())
            documents[(kind, version)] = LegalDocument(
                kind=kind,
                version=version,
                text=text,
                html=render_markdown(text),
                sha256=_fingerprint(text),
                effective_date=_EFFECTIVE_DATES.get((kind, version)),
            )
    return documents


_DOCUMENTS = _load()


def get_document(kind: str, version: str) -> LegalDocument | None:
    return _DOCUMENTS.get((kind, version))


def current_version(kind: str) -> str:
    return CURRENT_TERMS_VERSION if kind == TERMS else CURRENT_PRIVACY_VERSION


def get_current(kind: str) -> LegalDocument | None:
    return get_document(kind, current_version(kind))


def all_versions(kind: str) -> list[str]:
    return sorted(v for (k, v) in _DOCUMENTS if k == kind)


def verify_pinned_hashes() -> list[str]:
    """Re-check every pinned document against its file. Returns the problems.

    Called at startup. A mismatch means a published document was edited in
    place, which silently invalidates every consent row pointing at it — so it
    is reported loudly rather than returned quietly.
    """
    problems: list[str] = []

    for (kind, version), expected in _PINNED_HASHES.items():
        document = _DOCUMENTS.get((kind, version))
        if document is None:
            problems.append(f"{kind}/{version}: pinned but the file is missing")
            continue
        if expected is None:
            logger.warning(
                f"Legal: {kind}/{version} is UNPINNED (draft). "
                f"Current fingerprint is {document.sha256}. "
                "Pin it in registry.py before this version is published."
            )
            continue
        if document.sha256 != expected:
            problems.append(
                f"{kind}/{version}: fingerprint changed — "
                f"expected {expected}, file is {document.sha256}"
            )

    # A current version with no file at all is worse than a hash mismatch: the
    # Terms page 404s and the acceptance gate has nothing to show.
    for kind in DOCUMENT_KINDS:
        if get_current(kind) is None:
            problems.append(
                f"{kind}: CURRENT version {current_version(kind)!r} has no file"
            )

    for problem in problems:
        logger.error(f"Legal: {problem}")
    return problems
