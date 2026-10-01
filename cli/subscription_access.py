"""``flask subscriptions`` CLI — subscription maintenance tasks.

``sweep-access`` reconciles module access (``entity_function_map``) with the module
rows. Nothing else closes the gate when a grace window lapses: the boundary is a
DATE (``cancelled_at + 30d``, or ``paid_through + 15d`` for past_due) and no event
fires when a date passes. This command reads each entity's rows and disables any
module whose access has ended — and switches back on any whose entitlement has
RETURNED, which is the same "no event fires" problem in the other direction: an
account that pays off a past-due balance regains its entitlement without anything
touching the access map.

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

Those five run daily. ``run-daily`` is the pass that runs them, in order, and it is what
the in-process scheduler calls — see ``services/app_runtime/scheduler.py``. The individual
commands below remain for running ONE job by hand:

    flask subscriptions run-daily --issue

    # or, one at a time:
    flask subscriptions notify-trial-ending
    flask subscriptions close-trials
    flask subscriptions run-renewals --issue
    flask subscriptions retry-dunning
    flask subscriptions sweep-access

Order matters on a shared schedule: close-trials before run-renewals, so a trial that
converted today is billed by today's run rather than waiting a month; retry-dunning after
run-renewals, so a renewal that fails this morning enters dunning before the retry pass
looks at it.

SWEEP-ACCESS RUNS LAST, and this list used to put it third. The sweep judges a paid
module by the payer's ``paid_through``, and ``run-renewals`` is the only thing that
advances it — so running the sweep first meant a payer whose period had just elapsed was
``active`` with a past ``paid_through``, failed ``access.grants_access``, and had their
modules revoked seconds before the renewal step billed them for the new period. Nothing
re-syncs the map after a successful renewal (only dunning does, on recovery), so access
returned only on the next day's run: every payer, every renewal, charged and locked out
for a day. Running it last, the sweep sees settled state — renewed payers keep access,
genuinely failed ones sit in the past-due grace, and dunning's recoveries are restored in
the same run.

close-trials must still precede sweep-access, which running it last satisfies. It always
had to, so a converting trial was not swept as lapsed mid-conversion. (It also once kept an
expired trial from being announced twice; both the "trial has ended" and the "access
revoked" notices are retired now, so neither job mails a lapse.)

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
    "run-daily",
    help="Run a subscription pass: --mode full is all five jobs, light is the hourly "
         "two. Use --issue to let the renewal step charge.",
)
@click.option(
    "--issue",
    is_flag=True,
    default=False,
    help="Let the RENEWAL step charge. Without it that one step only reports. It does "
         "not make the pass read-only - see the command's help text.",
)
@click.option(
    "--mode",
    type=click.Choice(["full", "light"]),
    default="full",
    show_default=True,
    help="full = all five jobs. light = close-trials, run-renewals, and a sweep narrowed "
         "to the payers they touched (what the scheduler runs every non-full hour).",
)
@click.option(
    "--days-before",
    type=int,
    default=None,
    help="Trial-ending warning window, in days. Default: the pass's own default.",
)
def run_daily_cmd(issue: bool, mode: str, days_before: int | None) -> None:
    """The pass the scheduler runs, runnable by hand.

    THIS IS NOT A DRY RUN WITHOUT ``--issue``, and the flag name is inherited from
    ``run-renewals`` where it does mean that. Here it gates ONE of the five jobs. The
    other four always do their real work, and one of them spends money: ``close-trials``
    converts a due trial to paid, which cuts an invoice and charges the card on file.
    Trials also expire, access is revoked and restored, and dunning retries declined
    invoices — all of it for real, with or without the flag.

    Withholding ``--issue`` is therefore worth doing (it is the largest, least reversible
    step) but it is not a way to preview the pass. To see what tonight will bill without
    touching anything, run ``run-renewals`` on its own.

    Safe to run while the scheduler is mid-pass — it takes the same advisory lock, and
    reports that it did nothing rather than interleaving with the pass already running.
    """
    from blueprints.subscription.services import clock, daily

    kwargs = {} if days_before is None else {"days_before": days_before}
    with daily.daily_lock() as acquired:
        if not acquired:
            click.echo("A pass is already running elsewhere. Nothing done.")
            return
        result = daily.run_daily(clock.now(), issue=issue, mode=mode, **kwargs)

    if not issue:
        click.echo(
            "No --issue: the renewal step only reported. The other four jobs ran for "
            "real, and close-trials charges converting trials."
        )
    for entry in result["jobs"]:
        if entry.get("skipped"):
            click.echo(f"  skipped {entry['job']}: {entry['reason']}")
        elif entry["ok"]:
            counts = ", ".join(
                f"{key} {len(value) if isinstance(value, (list, tuple, set, dict)) else value}"
                for key, value in sorted((entry["summary"] or {}).items())
            )
            click.echo(f"  ok      {entry['job']}: {counts or 'nothing to do'}")
        else:
            click.echo(f"  FAILED  {entry['job']}: {entry['error']}")
    if result["behind"]:
        # The one thing a summary of counts cannot show: these payers were billed for a
        # period and are STILL due, so tomorrow's pass charges them again.
        click.echo(
            f"  {len(result['behind'])} payer(s) more than one period behind; they will "
            f"be billed again tomorrow: {', '.join(result['behind'])}"
        )
    click.echo("Daily pass complete." if result["ok"] else "Daily pass FINISHED WITH ERRORS.")


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
    "revoke-ungranted",
    help="Switch off every module grant that no subscription row backs - the step "
         "migration m1a01 never takes. Dry by default; --apply writes. Grants nothing, "
         "starts nothing.",
)
@click.option("--apply", is_flag=True, default=False, help="Write the revocation. Without it, list only.")
def revoke_ungranted_cmd(apply: bool) -> None:
    from blueprints.subscription.services.access_sweep import revoke_ungranted_module_access

    hits = revoke_ungranted_module_access(dry_run=not apply)
    verb = "Switched off" if apply else "Would switch off"
    click.echo(f"{verb} {len(hits)} module grant(s) with no subscription row.")
    for item in hits:
        click.echo(f"  - {item['code']} (entity {item['entity_id']})")


@subscriptions_cli.command(
    "sweep-access",
    help="Reconcile module access with the subscriptions: disable what has lapsed past "
         "its grace window, restore what is entitled again.",
)
def sweep_access_cmd() -> None:
    summary = sweep_expired_module_access()
    disabled = summary["disabled"]
    click.echo(f"Disabled {len(disabled)} module(s) past their access grace.")
    for item in disabled:
        click.echo(f"  - {item['code']} (entity {item['entity_id']})")
    # Restorations are printed even when there are none. A silent zero and a job that
    # cannot restore at all look identical in a cron log, and telling those apart is the
    # whole point of the line.
    restored = summary.get("restored", [])
    click.echo(f"Restored {len(restored)} module(s) whose entitlement returned.")
    for item in restored:
        click.echo(f"  + {item['code']} (entity {item['entity_id']})")


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
            "Ambiguous payers need a manual merge in Stripe - pick the customer holding "
            "the live card, move any others' history onto it, and clear their stamp."
        )
