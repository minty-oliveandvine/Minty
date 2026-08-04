"""``flask subscriptions`` CLI — subscription maintenance tasks.

``sweep-access`` reconciles module access (``entity_function_map``) with the module
rows. Nothing else closes the gate when a grace window lapses: the boundary is a
DATE (``cancelled_at + 30d``, or ``paid_through + 15d`` for past_due) and no event
fires when a date passes. This command reads each entity's rows and disables any
module whose access has ended.

``close-trials`` ends app-level trials whose term is up. A trial has no billing
object at all, so nothing else notices it ending — this command is the ONLY thing
that converts a due trial to paid (payer has a card and has consented) or expires
it.

``run-renewals`` raises each payer's monthly invoice. Nothing else does: Minty bills
in-house, and unlike a Stripe subscription an in-house cycle does not renew itself —
``paid_through`` only advances when this runs. It is DRY unless given ``--issue``.

``retry-dunning`` retries renewals that were declined, on the schedule in
``services/dunning.py``, and closes accounts that pass the give-up deadline.

``notify-trial-ending`` warns payers whose trial ends in a few days. It reconciles
nothing — it is the one job here that exists purely to send email, and the only
notification in the system that reaches the customer while they can still prevent the
lapse rather than after it.

Those five are intended to run daily (cron / Task Scheduler / a scheduled cloud agent):

    flask subscriptions notify-trial-ending
    flask subscriptions close-trials
    flask subscriptions sweep-access
    flask subscriptions run-renewals --issue
    flask subscriptions retry-dunning

Order matters on a shared schedule: close-trials before run-renewals, so a trial that
converted today is billed by today's run rather than waiting a month; retry-dunning last,
so a renewal that fails this morning enters dunning before the retry pass looks at it.

close-trials must also precede sweep-access, and now for a second reason. It always had
to run first so a converting trial was not swept as lapsed mid-conversion; with email
wired up it is also what keeps an expired trial from being announced twice — the trial
job revokes access itself and sends the "trial has ended" notice, so those modules are
already off by the time the sweep runs and never enter its "access revoked" batch.

Email is a side effect of these jobs, never their purpose: every send is deduped in
``subscription_email_log`` and every failure is swallowed, so a mail outage degrades
these commands to exactly what they did before — silent, but correct.

``reconcile-customers`` is the odd one out — a health check, not a daily job. It finds
payers whose ``user_stripe_customer`` row went missing while their Stripe customer still
exists, which is the one failure ``_seed_user_customer_mapping`` swallows by design. Run
it weekly, or whenever the "recovered it by search and re-seeded" warning appears in the
logs.
"""
from __future__ import annotations

import click
from flask.cli import AppGroup

from blueprints.entity.services.modules import sweep_expired_module_access

subscriptions_cli = AppGroup("subscriptions", help="Subscription maintenance.")


@subscriptions_cli.command(
    "close-trials",
    help="End app-level trials whose term is up: convert to paid, or expire.",
)
@click.option(
    "--limit",
    type=int,
    default=None,
    help="Process at most N due trials (oldest first). Default: all.",
)
def close_trials_cmd(limit: int | None) -> None:
    from blueprints.subscription.services.checkout import convert_or_expire_due_trials

    summary = convert_or_expire_due_trials(limit=limit)
    converted, expired = summary["converted"], summary["expired"]
    click.echo(f"Converted {len(converted)} trial(s) to paid; expired {len(expired)}.")
    for item in converted:
        click.echo(f"  converted: {item['code']} (entity {item['entity_id']})")
    for item in expired:
        click.echo(f"  expired:   {item['code']} (entity {item['entity_id']})")


@subscriptions_cli.command(
    "sweep-access",
    help="Disable modules whose subscription access has lapsed past its grace window.",
)
def sweep_access_cmd() -> None:
    summary = sweep_expired_module_access()
    disabled = summary["disabled"]
    click.echo(f"Disabled {len(disabled)} module(s) past their access grace.")
    for item in disabled:
        click.echo(f"  - {item['code']} (entity {item['entity_id']})")


@subscriptions_cli.command(
    "run-renewals",
    help="Bill payers whose period has ended. Use --issue to actually charge.",
)
@click.option(
    "--issue",
    is_flag=True,
    default=False,
    help="Actually charge. Without it this is a DRY RUN and moves no money.",
)
@click.option(
    "--user",
    "users",
    multiple=True,
    help="Bill only these payer ids. Repeatable. Omit to bill every due payer.",
)
@click.option("--limit", type=int, default=None, help="Bill at most N payers.")
def run_renewals_cmd(issue: bool, users: tuple[str, ...], limit: int | None) -> None:
    """The monthly charge, which nothing else performs.

    Under Stripe the subscription renewed itself. In-house it does not: ``paid_through``
    only advances when this runs, so without it on a schedule every paid customer keeps
    access and is never billed again after their current period.

    DRY BY DEFAULT. ``--issue`` is the only thing that moves money, so a mistyped cron
    entry or a hand-run check cannot charge anybody.
    """
    from blueprints.subscription.services import clock
    from blueprints.subscription.services.renewals import ALL_PAYERS, run_renewals

    # ``scope`` has no default in run_renewals: billing everyone has to be TYPED. A
    # global run driven by an injected clock once charged a live customer for catch-up
    # periods, so "every payer" stays an explicit request rather than an omission.
    scope = list(users) if users else ALL_PAYERS
    result = run_renewals(clock.now(), scope=scope, issue=issue, limit=limit)

    if not issue:
        # ASCII only in CLI output: these commands run under cron on a Windows host,
        # where the console is cp1252 and an em-dash comes out as a replacement char.
        click.echo(f"DRY RUN - nothing charged. {len(result['planned'])} payer(s) due:")
        for item in result["planned"]:
            click.echo(
                f"  would bill {item['total'] / 100:,.2f} to {item['user_id']} "
                f"({item['period_start']:%d %b} - {item['period_end']:%d %b %Y})"
            )
    else:
        click.echo(
            f"Billed {len(result['issued'])}; {len(result['failed'])} failed, "
            f"{len(result['skipped'])} skipped."
        )
        for item in result["issued"]:
            click.echo(
                f"  paid    {item['total'] / 100:,.2f}  {item['user_id']}  "
                f"{item['invoice']}"
            )
    # Failures are the ones that need eyes: each has started dunning and will be retried
    # by ``retry-dunning``, but a run where everything fails is a broken card processor,
    # not fifteen broken cards.
    for item in result["failed"]:
        click.echo(f"  FAILED  {item['total'] / 100:,.2f}  {item['user_id']}  "
                   f"{item.get('status')}")
    for item in result["skipped"]:
        click.echo(f"  skipped {item['user_id']}: {item['reason']}")


@subscriptions_cli.command(
    "retry-dunning",
    help="Retry failed renewals on schedule; close accounts past the deadline.",
)
@click.option("--limit", type=int, default=None, help="Process at most N accounts.")
def retry_dunning_cmd(limit: int | None) -> None:
    """Turn a declined renewal into a retry schedule rather than a silent lapse.

    Unlike ``run-renewals`` this has no dry mode: it retries invoices that were ALREADY
    issued and are already owed, so it cannot bill anything new. Safe at any cadence —
    the schedule is keyed off the first failure, so a job that was down for a week does
    not fire the whole backlog at once.
    """
    from blueprints.subscription.services import clock
    from blueprints.subscription.services.dunning import collect_due

    result = collect_due(clock.now(), limit=limit)
    click.echo(
        f"Retried {len(result['retried'])}; recovered {len(result['recovered'])}; "
        f"gave up on {len(result['given_up'])}."
    )
    for item in result["recovered"]:
        click.echo(f"  recovered: {item['user_id']}")
    for item in result["given_up"]:
        click.echo(f"  gave up:   {item['user_id']} after {item['attempts']} attempt(s)")


@subscriptions_cli.command(
    "notify-trial-ending",
    help="Email payers whose free trial ends in a few days.",
)
@click.option(
    "--days-before",
    type=int,
    default=3,
    show_default=True,
    help="How many days ahead of trial_end to warn.",
)
@click.option("--limit", type=int, default=None, help="Warn at most N trials.")
def notify_trial_ending_cmd(days_before: int, limit: int | None) -> None:
    """The only job here that exists purely to send email.

    Everything else in this group reconciles state and notifies as a side effect. This
    one has no state to reconcile: it looks forward at trials still running and warns the
    payer while they can still act — which is the entire difference between a customer
    who adds a card and a customer who finds out their module is gone.

    Safe to run repeatedly: the send is deduped on entity, module set and trial-end date
    in ``subscription_email_log``, so a double-run or a hand-run mails nobody twice.
    """
    from blueprints.subscription.services.checkout import notify_trials_ending

    result = notify_trials_ending(days_before=days_before, limit=limit)
    warned, skipped = result["warned"], result["skipped"]
    click.echo(f"Warned {len(warned)} entity(ies) about trials ending in {days_before}d.")
    for item in warned:
        flag = "NEEDS CARD" if item["needs_card"] else "will convert"
        click.echo(f"  - {item['entity_id']}: {','.join(item['codes'])} [{flag}]")
    for item in skipped:
        click.echo(f"  skipped {item['entity_id']}: {item['reason']}")


@subscriptions_cli.command(
    "reconcile-customers",
    help="Find payers whose Stripe customer exists but has no local mapping row.",
)
@click.option(
    "--repair",
    is_flag=True,
    default=False,
    help="Write the missing mapping rows. Without it this only reports.",
)
def reconcile_customers_cmd(repair: bool) -> None:
    """Detect (and optionally repair) lost payer->customer mappings.

    ``_seed_user_customer_mapping`` swallows its write failures on purpose: the customer
    already exists in Stripe and carries a ``metadata.user_id`` stamp, so the link is
    recoverable and a transient database blip must not fail a card save. The cost is that
    the failure is SILENT — ``checkout._resolve_customer_id`` quietly repairs it on the
    next billing operation, and nobody hears about it until then. This is how you look.

    It also reports the case that repair cannot fix: TWO Stripe customers stamped with
    the same ``user_id``. The search resolves one arbitrarily, so a duplicate has to be
    merged and deleted in Stripe by hand — which is why ``_adopt_session_customer``
    works so hard never to create one.
    """
    from collections import defaultdict

    from blueprints.subscription.services import store
    from blueprints.subscription.services.stripe_client import get_stripe
    from models.db import UserStripeCustomer, db

    mapped = {row.stripe_customer_id: row.user_id
              for row in UserStripeCustomer.query.all()}
    by_user: dict[str, list[str]] = defaultdict(list)
    for customer in get_stripe().Customer.list(limit=100).auto_paging_iter():
        user_id = (customer.get("metadata") or {}).get("user_id")
        if user_id:
            by_user[user_id].append(customer["id"])

    orphans = [
        (user_id, ids[0])
        for user_id, ids in by_user.items()
        if len(ids) == 1 and ids[0] not in mapped
    ]
    ambiguous = {u: ids for u, ids in by_user.items() if len(ids) > 1}

    click.echo(
        f"{len(mapped)} mapping row(s); {sum(len(v) for v in by_user.values())} "
        f"stamped Stripe customer(s); {len(orphans)} unmapped."
    )
    for user_id, customer_id in orphans:
        click.echo(f"  unmapped: {user_id} -> {customer_id}")
    for user_id, ids in ambiguous.items():
        click.echo(f"  AMBIGUOUS: {user_id} is stamped on {len(ids)}: {', '.join(ids)}")

    if not orphans:
        click.echo("Nothing to repair." if not ambiguous else "No repairable orphans.")
    elif not repair:
        click.echo("Reported only - pass --repair to write these rows.")
    else:
        for user_id, customer_id in orphans:
            store.upsert_customer_mapping(user_id, customer_id)
        db.session.commit()
        click.echo(f"Repaired {len(orphans)} mapping row(s).")

    if ambiguous:
        # Not repairable here on purpose: picking one would silently strand whatever
        # card and history sit on the other.
        click.echo(
            "Ambiguous payers need a manual merge in Stripe — pick the customer holding "
            "the live card, move any others' history onto it, and clear their stamp."
        )
