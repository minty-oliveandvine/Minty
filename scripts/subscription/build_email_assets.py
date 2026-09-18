"""Turn the illustration source art into email-sized assets.

The art arrives as full-resolution PNGs — ~1MB each, on canvases where the subject
occupies only a quarter to a half of the frame. Neither property survives contact with
email: the transparent margin renders as empty space that pushes the CTA button down the
message, and a megabyte CID-attached to every notice in a nightly batch is slow on mobile
and refused outright by some gateways.

So: trim to the alpha bounding box, scale to a fixed HEIGHT, and optimise. Height rather
than width because the trimmed aspect ratios run 0.63 (the tall hourglass) to 1.62 (the
wide two-character transfer scene) — matching widths would make the hourglass a third the
visual weight of the transfer scene, where the mockups clearly show them at matched
heights.

Re-runnable and idempotent: the originals stay the source of truth, so new art is dropped
in and this is run again rather than anyone hand-exporting at the right size.

    python scripts/subscription/build_email_assets.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "static" / "img"
DEST = SRC / "email"

# Rendered at ~90px tall; supplied at 2x so it stays sharp on retina.
TARGET_HEIGHT = 180

# The masthead, rendered at 56px. Same treatment for the same reason: the source is a
# 571x379 canvas whose mark occupies 401x315, and it is attached to EVERY message, so the
# 98KB original is the single most expensive byte-per-use asset in the set.
LOGO_SOURCE = "new_logo.png"
LOGO_TARGET = "logo"
LOGO_HEIGHT = 112

# Past this a single notice starts to cost more than the whole rest of the message.
WARN_BYTES = 40 * 1024

# Source file -> the event keys that use it. Two pairs deliberately share art: the
# hourglass reads the same for a trial running out and a handover request running out,
# and one payment-failure illustration covers both the first decline and a later retry.
MAPPING: dict[str, tuple[str, ...]] = {
    "Hourglass 1.png": ("trial_ending", "subscriber_transfer_expired"),
    "Transfer from Minty to Lemon 3.png": ("subscriber_transfer_requested",),
    "Lemon_Approved 1.png": ("subscriber_transfer_accepted",),
    "Rejected envelope 1.png": ("subscriber_transfer_declined",),
    "Minty Payment failed 1.png": ("renewal_failed", "dunning_retry_failed"),
    "Minty with heart 1.png": ("payment_recovered",),
}


def build(source: Path, names: tuple[str, ...],
          height: int = TARGET_HEIGHT) -> list[tuple[str, int, str]]:
    """Trim, scale and write one source image under each of its event-key names."""
    image = Image.open(source).convert("RGBA")

    # The whole point of the trim. getbbox() is alpha-aware, so this is the actual
    # drawn extent rather than whatever canvas the art was exported on.
    box = image.getbbox()
    if box:
        image = image.crop(box)

    width = max(1, round(image.width * height / image.height))
    image = image.resize((width, height), Image.LANCZOS)

    written = []
    for name in names:
        out = DEST / f"{name}.png"
        image.save(out, "PNG", optimize=True)
        size = out.stat().st_size
        note = ""

        if size > WARN_BYTES:
            # Truecolour costs the most on the widest art, which is also the art with the
            # most flat shading to spare. FASTOCTREE is the one PIL quantiser that keeps
            # an alpha channel — the others flatten it to a 1-bit matte and leave a hard
            # fringe around the subject, which is very visible against the white body.
            palette = image.quantize(colors=256, method=Image.FASTOCTREE)
            palette.save(out, "PNG", optimize=True)
            quantised = out.stat().st_size
            if quantised < size:
                note = f"  quantised from {size / 1024:.1f} KB"
                size = quantised
            else:
                # Rare, but a palette can cost more than it saves. Keep the truecolour
                # version rather than shipping a worse image at a worse size.
                image.save(out, "PNG", optimize=True)
            if size > WARN_BYTES:
                note = f"  OVER BUDGET{note}"

        written.append((name, size, note))
    return written


def main() -> int:
    DEST.mkdir(parents=True, exist_ok=True)

    missing = [n for n in (*MAPPING, LOGO_SOURCE) if not (SRC / n).exists()]
    if missing:
        print("Missing source art:", ", ".join(sorted(missing)), file=sys.stderr)
        return 1

    over = 0
    for name, size, note in build(SRC / LOGO_SOURCE, (LOGO_TARGET,), LOGO_HEIGHT):
        print(f"  {name + '.png':38s} {size / 1024:6.1f} KB{note}")
        if "OVER BUDGET" in note:
            over += 1

    for filename, names in MAPPING.items():
        for name, size, note in build(SRC / filename, names):
            print(f"  {name + '.png':38s} {size / 1024:6.1f} KB{note}")
            if "OVER BUDGET" in note:
                over += 1

    print(f"\nWrote {sum(len(v) for v in MAPPING.values()) + 1} files to {DEST}")
    if over:
        print(f"{over} still over {WARN_BYTES // 1024}KB after quantising.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
