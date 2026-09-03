"""``flask expense-ai`` CLI — one command, to prove the route works.

    flask expense-ai check

This is Stage 0's "one successful round-trip call from the application's
own network path — not from a laptop". It sends a tiny generated image, not a
customer receipt, and prints the model, the region, the latency and the token
usage so the answer to "is this configured correctly" is a fact rather than a
guess.
"""

from __future__ import annotations

import click
from flask.cli import AppGroup

from blueprints.report.services import expense_ai

expense_ai_cli = AppGroup(
    "expense-ai", help="Connectivity check for AI expense capture."
)


@expense_ai_cli.command("check", help="One round-trip call, from where the code runs.")
def check_cmd() -> None:
    click.echo(f"enabled          : {expense_ai.is_enabled()}")
    click.echo(f"route            : {'Vertex AI' if expense_ai.uses_vertex() else 'direct Gemini API'}")
    click.echo(f"location         : {expense_ai.location()}")
    click.echo(f"model            : {expense_ai.model_id()}")
    click.echo(f"thinking_level   : {expense_ai.thinking_level()}")

    if not expense_ai.uses_vertex():
        click.secho(
            "WARNING: the direct Gemini API has no regional endpoint and no "
            "residency commitment. On the free tier Google may use submitted "
            "content to develop its products and human reviewers may read it. "
            "Use non-customer receipts only.",
            fg="yellow",
        )

    # A generated 2x2 PNG, so the check exercises the real call path without
    # sending anything belonging to anyone.
    from io import BytesIO

    from PIL import Image

    buffer = BytesIO()
    Image.new("RGB", (2, 2), (255, 255, 255)).save(buffer, format="PNG")

    context = {
        "entity": {"id": "check", "name": "Connectivity check", "country": "HK",
                   "currency": "HKD"},
        "accounts": [{"id": "acc-1", "code": "5100", "name": "Courier Expense"}],
        "contacts": [{"id": "con-1", "name": "SF Express"}],
    }

    result = expense_ai.extract(buffer.getvalue(), "image/png", context)

    click.echo(f"latency_ms       : {result.audit.get('latency_ms')}")
    click.echo(f"request id       : {result.audit.get('provider_request_id')}")
    click.echo(f"tokens in / out  : {result.audit.get('input_tokens')} / "
               f"{result.audit.get('output_tokens')}")
    # Zero across repeated same-entity calls means the prefix is under the
    # 4,096-token minimum or is not byte-stable (§7.3).
    click.echo(f"cached tokens    : {result.audit.get('cached_tokens')}")
    click.echo(f"estimated cost   : {result.audit.get('estimated_cost')}")

    if result.reason in (None, expense_ai.REASON_NO_USABLE_FIELD):
        click.secho(
            "Round trip OK — the model answered and the reply passed the "
            "schema. (A blank image yields no usable field, as expected.)",
            fg="green",
        )
    else:
        click.secho(f"FAILED: {result.reason}", fg="red")
        raise SystemExit(1)
