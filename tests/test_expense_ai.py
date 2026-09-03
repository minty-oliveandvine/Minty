"""Unit tests for the expense extraction service (plan §15 Stage 2).

These cover the paths that decide whether a suggestion is safe to show:
schema validation, rejection of ids we did not send, out-of-range amounts,
safety blocks, truncation, timeouts, malformed JSON, and the model not being
served where we are calling.

No network. The client is a stand-in throughout — a test that reached Google
would be a test of Google.
"""

from __future__ import annotations

import json

import pytest

from blueprints.report.services import expense_ai as ai


# --------------------------------------------------------------------------
# Fixtures: one entity's context, and a fake interaction/client.
# --------------------------------------------------------------------------
CONTEXT = {
    "entity": {
        "id": "ent-1",
        "name": "Vine Consulting Limited",
        "country": "HK",
        "currency": "HKD",
    },
    "accounts": [
        {"id": "acc-courier", "code": "5100", "name": "Courier Expense"},
        {"id": "acc-tel", "code": "5200", "name": "Telephone"},
    ],
    "contacts": [
        {"id": "con-sf", "name": "SF Express"},
        {"id": "con-pns", "name": "PARKnSHOP"},
    ],
}


def _reply(**overrides):
    """A well-formed model reply, with high confidence everywhere."""
    body = {
        "supplier_contact_id": "con-sf",
        "supplier_name": "SF Express",
        "supplier_confidence": 0.93,
        "account_id": "acc-courier",
        "account_code": "5100",
        "account_name": "Courier Expense",
        "account_confidence": 0.88,
        "amount_value": 120.0,
        "amount_confidence": 0.97,
        "description_value": "Courier delivery",
        "description_confidence": 0.81,
        "currency": "HKD",
        "document_date": "2026-08-28",
        "document_date_confidence": 0.9,
    }
    body.update(overrides)
    return json.dumps(body)


class FakeUsage:
    total_input_tokens = 5000
    total_output_tokens = 300
    total_thought_tokens = 400
    total_cached_tokens = 0


class FakeInteraction:
    def __init__(self, output_text=None, status="completed", errors=None):
        self.id = "interaction-1"
        self.output_text = output_text
        self.status = status
        self.errors = errors or []
        self.usage = FakeUsage()


class FakeInteractions:
    def __init__(self, result):
        self._result = result
        self.calls = 0

    def create(self, **kwargs):
        self.calls += 1
        self.last_request = kwargs
        if isinstance(self._result, Exception):
            raise self._result
        if callable(self._result):
            return self._result(self.calls)
        return self._result


class FakeClient:
    def __init__(self, result):
        self.interactions = FakeInteractions(result)


@pytest.fixture(autouse=True)
def _stable_cutoffs(monkeypatch):
    """Pin the confidence bands so these tests do not depend on the deployed
    cut-offs, which are meant to move as spike data arrives (§6.2)."""
    monkeypatch.setenv("EXPENSE_AI_CONF_HIGH", "0.85")
    monkeypatch.setenv("EXPENSE_AI_CONF_MEDIUM", "0.60")
    monkeypatch.setenv("EXPENSE_AI_MODEL", "gemini-3.8-flash")


def _run(monkeypatch, result):
    client = FakeClient(result)
    monkeypatch.setattr(ai, "_get_client", lambda: client)
    extraction = ai.extract(b"%PDF-1.4 fake", "application/pdf", CONTEXT)
    return extraction, client


# --------------------------------------------------------------------------
# The happy path, and what it proves about the request we send.
# --------------------------------------------------------------------------
def test_valid_reply_fills_all_four_fields(monkeypatch):
    extraction, client = _run(monkeypatch, FakeInteraction(_reply()))

    assert extraction.reason is None
    suggestions = extraction.suggestions
    assert suggestions["amount"]["value"] == "120.00"
    assert suggestions["amount"]["applied"] is True
    assert suggestions["supplier"]["contact_id"] == "con-sf"
    assert suggestions["supplier"]["value"] == "SF Express"
    assert suggestions["account"]["account_id"] == "acc-courier"
    assert suggestions["account"]["name"] == "Courier Expense"
    assert suggestions["description"]["value"] == "Courier delivery"
    assert suggestions["currency"] == "HKD"


def test_request_puts_the_stable_prefix_first(monkeypatch):
    """Gemini's caching is implicit prefix matching with no marker to set
    (§7.3), so the cacheable half must lead and the receipt must follow."""
    _, client = _run(monkeypatch, FakeInteraction(_reply()))
    request_input = client.interactions.last_request["input"]

    assert request_input[0]["type"] == "text"
    assert "Chart of accounts" in request_input[0]["text"]
    assert request_input[1]["type"] == "document"
    # Accounts sorted by code then id, so the prefix stays byte-stable (§3.2).
    assert request_input[0]["text"].index("5100") < request_input[0]["text"].index("5200")


def test_schema_is_sent_and_carries_no_account_enum(monkeypatch):
    """The chart of accounts belongs in the prompt, not the schema (§6.1)."""
    _, client = _run(monkeypatch, FakeInteraction(_reply()))
    schema = client.interactions.last_request["response_format"]["schema"]

    assert client.interactions.last_request["response_format"]["mime_type"] == (
        "application/json"
    )
    assert "acc-courier" not in json.dumps(schema)
    assert set(schema["required"]) == set(schema["properties"])


# --------------------------------------------------------------------------
# §8.3 — the reply is untrusted input.
# --------------------------------------------------------------------------
def test_supplier_id_not_in_the_sent_list_is_dropped(monkeypatch):
    extraction, _ = _run(
        monkeypatch,
        FakeInteraction(_reply(supplier_contact_id="con-invented")),
    )
    supplier = extraction.suggestions["supplier"]
    assert supplier["contact_id"] == ""
    assert supplier["applied"] is False
    # The rest of the reply survives — one bad field is not a bad reply.
    assert extraction.suggestions["amount"]["applied"] is True


def test_account_id_not_in_the_sent_list_is_dropped(monkeypatch):
    extraction, _ = _run(
        monkeypatch, FakeInteraction(_reply(account_id="acc-hallucinated"))
    )
    account = extraction.suggestions["account"]
    assert account["account_id"] == ""
    assert account["applied"] is False


def test_a_plausible_name_does_not_rescue_a_bad_id(monkeypatch):
    """We never 'repair' a suggestion by matching on the name instead."""
    extraction, _ = _run(
        monkeypatch,
        FakeInteraction(
            _reply(supplier_contact_id="", supplier_name="SF Express")
        ),
    )
    assert extraction.suggestions["supplier"]["contact_id"] == ""


@pytest.mark.parametrize("amount", [0, -50, 99_999_999_999])
def test_out_of_range_amount_is_dropped(monkeypatch, amount):
    extraction, _ = _run(monkeypatch, FakeInteraction(_reply(amount_value=amount)))
    assert extraction.suggestions["amount"]["value"] == ""
    assert extraction.suggestions["amount"]["applied"] is False


def test_description_is_length_capped(monkeypatch):
    extraction, _ = _run(
        monkeypatch, FakeInteraction(_reply(description_value="x" * 5000))
    )
    assert len(extraction.suggestions["description"]["value"]) == 200


def test_unknown_currency_is_dropped(monkeypatch):
    extraction, _ = _run(monkeypatch, FakeInteraction(_reply(currency="dollars")))
    assert extraction.suggestions["currency"] == ""


# --------------------------------------------------------------------------
# §6.2 — confidence bands. Below the medium cut-off nothing is prefilled.
# --------------------------------------------------------------------------
def test_low_confidence_field_is_not_prefilled(monkeypatch):
    extraction, _ = _run(
        monkeypatch, FakeInteraction(_reply(amount_confidence=0.2))
    )
    amount = extraction.suggestions["amount"]
    assert amount["band"] == "low"
    assert amount["applied"] is False
    # The value is still recorded for the audit trail, just not shown.
    assert amount["value"] == "120.00"


def test_medium_confidence_is_prefilled_and_banded_for_review(monkeypatch):
    extraction, _ = _run(
        monkeypatch, FakeInteraction(_reply(amount_confidence=0.7))
    )
    assert extraction.suggestions["amount"]["band"] == "medium"
    assert extraction.suggestions["amount"]["applied"] is True


def test_nothing_usable_reports_a_reason(monkeypatch):
    everything_low = {
        key: 0.1
        for key in (
            "supplier_confidence",
            "account_confidence",
            "amount_confidence",
            "description_confidence",
            "document_date_confidence",
        )
    }
    extraction, _ = _run(monkeypatch, FakeInteraction(_reply(**everything_low)))
    assert extraction.reason == ai.REASON_NO_USABLE_FIELD


# --------------------------------------------------------------------------
# §9.1 — the failure matrix. Every one of these degrades to "no suggestion".
# --------------------------------------------------------------------------
def test_malformed_json_is_discarded_whole(monkeypatch):
    extraction, _ = _run(monkeypatch, FakeInteraction("not json at all"))
    assert extraction.suggestions is None
    assert extraction.reason == ai.REASON_INVALID_REPLY


def test_reply_failing_schema_validation_is_discarded_whole(monkeypatch):
    bad = json.dumps({"amount_value": "one hundred and twenty"})
    extraction, _ = _run(monkeypatch, FakeInteraction(bad))
    assert extraction.suggestions is None
    assert extraction.reason == ai.REASON_INVALID_REPLY


def test_safety_block_is_treated_as_no_suggestion_and_not_retried(monkeypatch):
    class Err:
        message = "Blocked by safety filters: dangerous_content"

    extraction, client = _run(
        monkeypatch, FakeInteraction(None, status="incomplete", errors=[Err()])
    )
    assert extraction.reason == ai.REASON_SAFETY_BLOCKED
    assert client.interactions.calls == 1


def test_truncated_reply_is_discarded(monkeypatch):
    class Err:
        message = "max output tokens reached"

    extraction, _ = _run(
        monkeypatch, FakeInteraction(None, status="incomplete", errors=[Err()])
    )
    assert extraction.reason == ai.REASON_TRUNCATED


def test_timeout_is_not_retried(monkeypatch):
    extraction, client = _run(monkeypatch, TimeoutError("deadline exceeded"))
    assert extraction.reason == ai.REASON_TIMEOUT
    assert client.interactions.calls == 1


def _status_error(klass, status, message):
    """Build a real SDK status error. `interactions.create` raises this family
    (`google.genai._gaos.lib.compat_errors`), NOT `google.genai.errors` — the
    legacy ClientError/ServerError belong to `models.generate_content`."""
    import httpx

    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/x")
    response = httpx.Response(status, request=request)
    return klass(message, response=response, body=None)


def test_interactions_raises_a_different_family_than_the_legacy_api():
    """A regression guard for the bug this suite missed once already: catching
    only `google.genai.errors` sends every 429 down the generic branch."""
    from google.genai import errors as legacy
    from google.genai._gaos.lib import compat_errors as compat

    assert not issubclass(compat.RateLimitError, legacy.APIError)
    assert compat.RateLimitError.status_code == 429


def test_model_not_found_in_region_is_not_retried(monkeypatch):
    """A 404 means the configured model is not served where we are calling.
    Retrying cannot fix that, and it pages on-call instead (§9.1)."""
    from google.genai._gaos.lib import compat_errors as compat

    error = _status_error(compat.NotFoundError, 404, "model not found")
    extraction, client = _run(monkeypatch, error)
    assert extraction.reason == ai.REASON_PROVIDER_ERROR
    assert client.interactions.calls == 1


def test_permission_denied_is_not_retried(monkeypatch):
    from google.genai._gaos.lib import compat_errors as compat

    error = _status_error(compat.PermissionDeniedError, 403, "permission denied")
    extraction, client = _run(monkeypatch, error)
    assert extraction.reason == ai.REASON_PROVIDER_ERROR
    assert client.interactions.calls == 1


def test_rate_limit_is_reported_as_rate_limited_not_a_transport_error(monkeypatch):
    """The bug that made a spent free-tier quota look like a network fault."""
    from google.genai._gaos.lib import compat_errors as compat

    monkeypatch.setattr(ai.time, "sleep", lambda _seconds: None)
    error = _status_error(compat.RateLimitError, 429, "quota exceeded")
    extraction, _ = _run(monkeypatch, error)
    assert extraction.reason == ai.REASON_RATE_LIMITED


def test_rate_limit_does_not_retry_when_the_advised_wait_blows_the_deadline(
    monkeypatch,
):
    """Retrying into a 40-second cool-off spends a second request from the
    quota to earn a second 429, and misses the deadline anyway (§9.2)."""
    from google.genai._gaos.lib import compat_errors as compat

    monkeypatch.setenv("EXPENSE_AI_TIMEOUT_S", "25")
    slept = []
    monkeypatch.setattr(ai.time, "sleep", lambda seconds: slept.append(seconds))
    error = _status_error(
        compat.RateLimitError, 429, "Quota exceeded. Please retry in 39.6s."
    )
    extraction, client = _run(monkeypatch, error)

    assert extraction.reason == ai.REASON_RATE_LIMITED
    assert client.interactions.calls == 1
    assert slept == []


def test_rate_limit_retries_once_when_the_advised_wait_fits(monkeypatch):
    from google.genai._gaos.lib import compat_errors as compat

    monkeypatch.setenv("EXPENSE_AI_TIMEOUT_S", "25")
    monkeypatch.setattr(ai.time, "sleep", lambda _seconds: None)

    def flaky(call_number):
        if call_number == 1:
            raise _status_error(
                compat.RateLimitError, 429, "Slow down. Please retry in 1.5s."
            )
        return FakeInteraction(_reply())

    extraction, client = _run(monkeypatch, flaky)
    assert extraction.reason is None
    assert client.interactions.calls == 2


def test_sdk_timeout_is_not_retried(monkeypatch):
    """APITimeoutError subclasses APIConnectionError, not APIStatusError, so
    it carries no status and must be recognised by type."""
    import httpx
    from google.genai._gaos.lib import compat_errors as compat

    request = httpx.Request("POST", "https://generativelanguage.googleapis.com/x")
    extraction, client = _run(monkeypatch, compat.APITimeoutError(request=request))
    assert extraction.reason == ai.REASON_TIMEOUT
    assert client.interactions.calls == 1


def test_server_error_retries_once_then_succeeds(monkeypatch):
    from google.genai._gaos.lib import compat_errors as compat

    monkeypatch.setattr(ai.time, "sleep", lambda _seconds: None)

    def flaky(call_number):
        if call_number == 1:
            raise _status_error(compat.InternalServerError, 503, "unavailable")
        return FakeInteraction(_reply())

    extraction, client = _run(monkeypatch, flaky)
    assert extraction.reason is None
    assert client.interactions.calls == 2


def test_client_not_configured_makes_no_call(monkeypatch):
    def boom():
        raise RuntimeError("GEMINI_API_KEY is not set")

    monkeypatch.setattr(ai, "_get_client", boom)
    extraction = ai.extract(b"%PDF-1.4", "application/pdf", CONTEXT)
    assert extraction.suggestions is None
    assert extraction.reason == ai.REASON_NOT_CONFIGURED


# --------------------------------------------------------------------------
# Thinking tokens. Invisible in the reply, billed as output, and drawn from
# max_output_tokens — the combination that truncated a real call.
# --------------------------------------------------------------------------
def test_thinking_tokens_are_reported_separately(monkeypatch):
    """Still tracked, now only in the log line: without it a truncation
    caused by thinking looks like a model that barely answered."""
    extraction, _ = _run(monkeypatch, FakeInteraction(_reply()))
    assert extraction.audit["output_tokens"] == 300
    assert extraction.audit["thought_tokens"] == 400


def test_cost_bills_thinking_at_the_output_rate(monkeypatch):
    """Omitting thinking understated a measured call by ~60 %, and a cost
    model must not be wrong in that direction."""
    monkeypatch.setenv("EXPENSE_AI_MODEL", "gemini-3.8-flash")
    extraction, _ = _run(monkeypatch, FakeInteraction(_reply()))
    expected = (5000 / 1_000_000) * 0.75 + ((300 + 400) / 1_000_000) * 3.75
    assert extraction.audit["estimated_cost"] == round(expected, 6)


def test_output_budget_leaves_room_to_think(monkeypatch):
    """The plan's 1,024 sized the JSON reply and forgot that thinking shares
    the allowance. A truncated reply is a wasted call and a wasted quota slot."""
    monkeypatch.delenv("EXPENSE_AI_MAX_OUTPUT_TOKENS", raising=False)
    _, client = _run(monkeypatch, FakeInteraction(_reply()))
    budget = client.interactions.last_request["generation_config"]["max_output_tokens"]
    assert budget >= 4096


# --------------------------------------------------------------------------
# §7.2 — content sniffing, and §8.6 — rate limiting.
# --------------------------------------------------------------------------
@pytest.mark.parametrize(
    "data,expected",
    [
        (b"%PDF-1.7 ...", "application/pdf"),
        (b"\xff\xd8\xff\xe0 JFIF", "image/jpeg"),
        (b"\x89PNG\r\n\x1a\n rest", "image/png"),
        (b"MZ\x90\x00 an executable named receipt.pdf", None),
        (b"", None),
    ],
)
def test_mime_is_sniffed_from_content_not_the_extension(data, expected):
    assert ai.sniff_mime(data) == expected


def test_rate_limiter_sheds_load_on_our_terms(monkeypatch):
    monkeypatch.setenv("EXPENSE_AI_RATE_USER_PER_MIN", "3")
    monkeypatch.setenv("EXPENSE_AI_RATE_ENTITY_PER_HOUR", "1000")
    ai._user_hits.clear()
    ai._entity_hits.clear()

    assert [ai.check_rate_limit("user-rl", "ent-rl") for _ in range(4)] == [
        True,
        True,
        True,
        False,
    ]
    # A different user is unaffected by the first one's burst.
    assert ai.check_rate_limit("user-rl-2", "ent-rl") is True


def test_entity_limit_is_separate_from_the_user_limit(monkeypatch):
    monkeypatch.setenv("EXPENSE_AI_RATE_USER_PER_MIN", "1000")
    monkeypatch.setenv("EXPENSE_AI_RATE_ENTITY_PER_HOUR", "2")
    ai._user_hits.clear()
    ai._entity_hits.clear()

    assert ai.check_rate_limit("user-a", "ent-shared") is True
    assert ai.check_rate_limit("user-b", "ent-shared") is True
    assert ai.check_rate_limit("user-c", "ent-shared") is False


# --------------------------------------------------------------------------
# §11.1 / §5.3 — the switches that keep this feature safe by default.
# --------------------------------------------------------------------------
def test_feature_is_off_by_default(monkeypatch):
    monkeypatch.delenv("EXPENSE_AI_ENABLED", raising=False)
    assert ai.is_enabled() is False


def test_direct_api_requires_an_explicit_opt_in(monkeypatch):
    """The direct Gemini API must never be reached by accident: on the free
    tier human reviewers may read submitted content (§8.5)."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.delenv("EXPENSE_AI_ALLOW_DIRECT_API", raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "a-key-that-should-not-be-used")
    ai.reset_client()

    with pytest.raises(RuntimeError, match="not opted in"):
        ai._get_client()
    ai.reset_client()


def test_vertex_is_the_route_whenever_a_project_is_configured(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "minty-expense-ai")
    monkeypatch.delenv("EXPENSE_AI_USE_VERTEX", raising=False)
    assert ai.uses_vertex() is True
    assert ai.location() == "asia-southeast1"


def test_location_records_the_direct_route_distinctly(monkeypatch):
    """`location` is the audit row's evidence of where a receipt was
    processed. On the direct API there is no region to name, so it records the
    route and the tier — which is the compliance-relevant fact there."""
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    assert ai.uses_vertex() is False
    assert ai.location().startswith("gemini-api-direct")


# --------------------------------------------------------------------------
# Direct API tier (business decision, 3 Sep 2026: direct paid, not Vertex).
# The tiers are indistinguishable at the call site, so these guard the only
# two things that keep them apart: a stated setting, and a tripwire.
# --------------------------------------------------------------------------
def test_tier_defaults_to_free_when_unstated(monkeypatch):
    """The safe assumption about an unconfirmed key is the restrictive one."""
    monkeypatch.delenv("EXPENSE_AI_DIRECT_TIER", raising=False)
    assert ai.direct_tier() == "free"


def test_an_unrecognised_tier_is_treated_as_free(monkeypatch):
    monkeypatch.setenv("EXPENSE_AI_DIRECT_TIER", "enterprise")
    assert ai.direct_tier() == "free"


def test_location_records_the_tier_so_the_audit_row_evidences_the_terms(
    monkeypatch,
):
    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("EXPENSE_AI_DIRECT_TIER", "paid")
    assert ai.location() == "gemini-api-direct-paid"
    monkeypatch.setenv("EXPENSE_AI_DIRECT_TIER", "free")
    assert ai.location() == "gemini-api-direct-free"


def test_free_tier_quota_error_while_configured_paid_is_reported(monkeypatch):
    """Billing lapsing is invisible everywhere else. Google's own quota error
    naming the free-tier metric is the only place the truth leaks."""
    from google.genai._gaos.lib import compat_errors as compat

    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("EXPENSE_AI_DIRECT_TIER", "paid")
    error = _status_error(
        compat.RateLimitError,
        429,
        "Quota exceeded for metric: "
        "generativelanguage.googleapis.com/generate_content_free_tier_requests",
    )
    assert ai._check_tier_matches_reality(error) is True


def test_no_mismatch_reported_when_the_quota_is_a_paid_one(monkeypatch):
    from google.genai._gaos.lib import compat_errors as compat

    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("EXPENSE_AI_DIRECT_TIER", "paid")
    error = _status_error(compat.RateLimitError, 429, "Quota exceeded. Retry later.")
    assert ai._check_tier_matches_reality(error) is False


def test_no_mismatch_reported_when_we_already_know_we_are_on_free(monkeypatch):
    """Not a mismatch — it is the configuration doing what it says."""
    from google.genai._gaos.lib import compat_errors as compat

    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("EXPENSE_AI_DIRECT_TIER", "free")
    error = _status_error(
        compat.RateLimitError, 429, "generate_content_free_tier_requests"
    )
    assert ai._check_tier_matches_reality(error) is False


def test_a_tier_mismatch_does_not_disable_the_feature(monkeypatch):
    """The signal only appears on a quota error, so it is loud but not
    authoritative. Turning the feature off is a human decision (§8.6)."""
    from google.genai._gaos.lib import compat_errors as compat

    monkeypatch.delenv("GOOGLE_CLOUD_PROJECT", raising=False)
    monkeypatch.setenv("EXPENSE_AI_DIRECT_TIER", "paid")
    monkeypatch.setenv("EXPENSE_AI_ENABLED", "true")
    error = _status_error(
        compat.RateLimitError, 429, "generate_content_free_tier_requests"
    )
    ai._check_tier_matches_reality(error)
    assert ai.is_enabled() is True
