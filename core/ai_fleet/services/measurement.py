"""Whether an attempt measured the route at all, before anything is claimed about it.

A capability probe answers one question: can this route do the thing. It can only
answer it if the route was actually asked. TEMM read a non-zero exit as the answer
"no", and a non-zero exit is also what the CLI produces when it never found the
provider, when the provider refused the account, and when the provider answered
with something the client could not parse - none of which the model was present
for.

Production evidence 2026-08-20, `run-133922d95108` / `attempt-2204ab86ef54`: the
CLI exited 1 after 1931ms with an empty workspace diff, no stderr, and a single
stdout event. The provider was declared only in a config the isolated workspace
could not see, so the model was never invoked. TEMM recorded that the route could
not code, could not read files and could not write files, and - because the newest
execution measurement wins aggregation - withdrew the route from both renewal and
bootstrap on the strength of a request that was never sent.

Classifying that correctly cannot be done by matching the error text. Measured on
this machine, an unresolvable provider, a provider name that does not exist, and a
model name that does not exist all produce the *same* 222-byte event: `UnknownError`,
`"Unexpected server error. Check server logs for details."`, no status code. The
three are indistinguishable by message, so the classification is inverted: nothing
counts as a measurement without positive proof that the model executed. Proof is a
tool call, assistant text, a step the provider finished, a file event, reported
token usage, or a change on disk - the things only a model that ran produces.

`step_start` is deliberately not proof. It is emitted when the CLI begins a model
step, before the provider has answered, and it is the one signal that separates a
failure below the provider from a failure at it: the three local failures above
emit none, while a route that reached its provider and got an unusable response
emits one and then errors. That makes it the discriminator between
`executor_local_failure` and `provider_unavailable`, both of which are
non-measurements, and neither of which may be written down as incapacity.
"""

import json
from typing import Any, Dict, Iterable, List

from ..security import SensitiveDataRedactor
from ..storage.secret_vault import secret_vault

# The attempt asked the model and the model answered. Only this admits a negative
# capability conclusion, and only about what the attempt actually exercised.
MODEL_EXECUTED = "model_executed"
# The CLI failed before the request left this machine: provider not resolvable
# from the executor's configuration, model name unknown to it, executable absent.
EXECUTOR_LOCAL_FAILURE = "executor_local_failure"
# The provider was reached and did not serve a usable answer: rejected the client,
# was unreachable, or replied with a body the client could not use.
PROVIDER_UNAVAILABLE = "provider_unavailable"
# The provider declined a well-formed request - spent allowance, forbidden model.
PROVIDER_REFUSAL = "provider_refusal"
# The process ended without producing any signal at all. Not a failure that names
# itself, and still not a measurement.
NO_EXECUTION_SIGNAL = "no_execution_signal"

# How long a non-measurement withdraws the route from selection. A classification
# that names a condition outside the model's control is not a verdict on the route,
# but it does mean the route cannot be exercised right now, and selection has to act
# on that or dispatch re-picks the same dead route on the next task. Bounded and
# self-healing, so a transient outage costs one interval rather than an operator
# intervention: a local configuration failure will not fix itself between two tasks,
# while a provider that rejected or could not answer the request may. A refusal is
# already carried by the quota ledger, and a silent exit names no condition to
# withdraw on, so neither appears here.
NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS = {
    EXECUTOR_LOCAL_FAILURE: 1800,
    PROVIDER_UNAVAILABLE: 600,
}

# The provider said the route is gone, said it does not serve this route, or said
# nothing about how long its answer holds.
PERMANENCE_PERMANENT = "permanent"
PERMANENCE_ROUTE_UNSERVED = "route_unserved"
PERMANENCE_TRANSIENT = "transient"

# The registry accepts no observation longer than this, so a permanent verdict is
# re-confirmed once a day rather than trusted forever. That is the point: a route
# the provider brings back is found again within a day, by one probe, without an
# operator; and a route it does not costs one probe a day instead of one every ten
# minutes. Archiving would be cheaper still and is deliberately not done here - it
# has no reverse, and a permanence read from a body TEMM does not author is not a
# fact worth making irreversible.
MAX_AVAILABILITY_HOLD_SECONDS = 86400
PERMANENCE_HOLD_SECONDS = {
    PERMANENCE_PERMANENT: MAX_AVAILABILITY_HOLD_SECONDS,
    PERMANENCE_ROUTE_UNSERVED: 43200,
}

# `410 Gone` is the one status whose meaning is permanence - the resource was here
# and will not be again. NVIDIA answers it for retired models and states the date.
PERMANENT_STATUS_CODES = {410}
# `404` on the model path says the provider does not serve this route: retired
# without saying so, an embedding or image model behind a chat endpoint, or a
# deployment this account does not have. Long, because none of those clear on their
# own; short of permanent, because the provider did not say it is.
ROUTE_UNSERVED_STATUS_CODES = {404}
# Statuses about the account, the request or the service - never about whether the
# route exists. A revoked key, a spent allowance and a gateway timeout all clear
# without the route changing, and an aliyun `400` naming `max_tokens` is TEMM's own
# request to fix. These keep the short default however the body reads, so a message
# echoed inside an outage cannot retire a live route.
NON_ROUTE_STATUS_CODES = {400, 401, 402, 403, 408, 409, 413, 422, 429, 500, 502, 503, 504, 529}
# What a provider says when it is not coming back. Matched only on an answer the
# provider actually gave - see `stated_permanence`.
END_OF_LIFE_PHRASES = (
    "reached its end of life",
    "end-of-life",
    "decommissioned",
    "has been retired",
    "has been removed",
    "has been sunset",
    "no longer available",
    "no longer supported",
)

# Events only a model that ran produces. `step_start` is excluded on purpose - see
# the module docstring.
EXECUTION_PROOF_EVENT_TYPES = ("tool_use", "tool", "text", "step_finish", "file")
# Emitted when a model step begins, so a non-zero count means provider resolution
# succeeded and the failure lies at or beyond the provider.
RESOLUTION_EVENT_TYPE = "step_start"

# Bounds on what a receipt carries. Enough to classify a failure after the fact,
# far short of the raw transcript - which is already persisted as output chunks.
MAX_ERROR_EVENTS = 5
MAX_ERROR_MESSAGE = 400
MAX_EVENT_TYPES = 24
MAX_STDOUT_TAIL = 2000
# A single line longer than this is not an event worth parsing; it is file content
# the executor echoed, and running the JSON parser over it buys nothing.
MAX_EVENT_LINE = 200000
MAX_EVENT_LINES = 20000
# How deep to look for the token census inside an event before giving up.
MAX_TOKEN_SEARCH_DEPTH = 6
# The dimensions a step's census is kept in. `total` is carried alongside the parts
# rather than derived from them, because the executor states it and may count
# something these five do not break out.
TOKEN_DIMENSIONS = ("input", "output", "reasoning", "cache_read", "cache_write", "total")


def _redactor() -> SensitiveDataRedactor:
    return SensitiveDataRedactor.from_environment(secret_vault.redaction_values())


def stdout_text(chunks: Iterable[Dict[str, Any]]) -> str:
    """Join the executor's stdout, which is where the CLI writes its events."""
    return "".join(
        chunk.get("content") or ""
        for chunk in chunks
        if (chunk.get("stream") or "stdout") == "stdout"
    )


def stdout_tail(chunks: Iterable[Dict[str, Any]], limit: int = MAX_STDOUT_TAIL) -> str:
    """Return the redacted end of stdout.

    The autopsy of `attempt-2204ab86ef54` had a stderr tail and no stdout tail,
    and the CLI writes its errors to stdout - so the one event that explained the
    attempt was the one thing the receipt did not keep.
    """
    return _redactor().redact_text(stdout_text(chunks)[-limit:])


def _events(text: str):
    """Yield the JSON events on stdout, skipping anything that is not one."""
    for index, line in enumerate(text.splitlines()):
        if index >= MAX_EVENT_LINES:
            return
        stripped = line.strip()
        if not stripped.startswith("{") or len(stripped) > MAX_EVENT_LINE:
            continue
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            # A chunk boundary can split a line. A truncated event is not evidence
            # of anything, in either direction.
            continue
        if isinstance(event, dict):
            yield event


def _token_report(node: Any, depth: int = 0) -> Dict[str, int] | None:
    """The token counts one event reports, wherever the CLI nests them.

    Read component by component, because the executor reports a step as
    `{"total":37486,"input":762,"output":116,"reasoning":0,"cache":{"read":36608,
    "write":0}}` - a self-consistent per-step census where `total` is the sum of the
    rest. Summing that dict's values, as this did, adds `total` to its own components
    and reports very nearly double: production evidence 2026-08-20,
    `attempt-bb0eb9e3118f` had its first step (36651 total) recorded as 73302 tokens.

    Returns None when the event carries no census at all, which is how the caller
    tells "reported nothing" apart from "reported zero" - the difference between
    unknown usage and a free step.
    """
    if depth > MAX_TOKEN_SEARCH_DEPTH or not isinstance(node, dict):
        return None
    tokens = node.get("tokens")
    if isinstance(tokens, dict):
        cache = tokens.get("cache")
        cache = cache if isinstance(cache, dict) else {"read": cache}
        report = {
            "input": _count(tokens.get("input")),
            "output": _count(tokens.get("output")),
            "reasoning": _count(tokens.get("reasoning")),
            "cache_read": _count(cache.get("read")),
            "cache_write": _count(cache.get("write")),
        }
        # The executor's own total when it states one, since it is the authority on
        # what it was billed for and may count a dimension not broken out here.
        report["total"] = _count(tokens.get("total")) or sum(report.values())
        return report
    for value in node.values():
        report = _token_report(value, depth + 1)
        if report is not None:
            return report
    return None


def _count(value: Any) -> int:
    """A token dimension as a non-negative integer, or zero when it is not one."""
    return int(value) if isinstance(value, (int, float)) and value > 0 else 0


def _event_identity(event: Dict[str, Any]) -> str | None:
    """The part a token census belongs to, so one part is never counted twice.

    The CLI can re-emit a part as it settles. Counting per event would then bill a
    step once per emission; counting per part identity bills it once, and an event
    with no identity is counted as itself.
    """
    part = event.get("part")
    identifier = part.get("id") if isinstance(part, dict) else None
    return str(identifier) if identifier else None


def _error_summary(event: Dict[str, Any], redactor: SensitiveDataRedactor) -> Dict[str, Any]:
    error = event.get("error") if isinstance(event.get("error"), dict) else {}
    data = error.get("data") if isinstance(error.get("data"), dict) else {}
    message = str(data.get("message") or error.get("message") or "")
    return {
        "name": str(error.get("name") or "")[:120],
        "message": redactor.redact_text(message)[:MAX_ERROR_MESSAGE],
        "status_code": data.get("statusCode"),
        "ref": str(data.get("ref") or "")[:80] or None,
    }


def measurement_signals(chunks: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Census the executor's event stream: what happened, and what errored."""
    redactor = _redactor()
    counts: Dict[str, int] = {}
    errors: List[Dict[str, Any]] = []
    census = {key: 0 for key in TOKEN_DIMENSIONS}
    reporting_events = 0
    counted_parts: set[str] = set()
    for event in _events(stdout_text(chunks)):
        event_type = str(event.get("type") or "")
        if not event_type:
            continue
        counts[event_type] = counts.get(event_type, 0) + 1
        if event_type == "error" and len(errors) < MAX_ERROR_EVENTS:
            errors.append(_error_summary(event, redactor))
        report = _token_report(event)
        if report is None:
            continue
        identity = _event_identity(event)
        if identity is not None and identity in counted_parts:
            continue
        if identity is not None:
            counted_parts.add(identity)
        reporting_events += 1
        for key in TOKEN_DIMENSIONS:
            census[key] += report[key]
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:MAX_EVENT_TYPES]
    return {
        "event_counts": dict(ordered),
        "error_events": errors,
        # The attempt's usage is the sum of the steps it took, not the largest of
        # them. Reading the maximum reported one step of a thirty-three step attempt
        # as the whole attempt, which is how a run that spent an entire free
        # allowance appeared in the fleet's exports as a fraction of it.
        "token_census": {**census, "reporting_events": reporting_events},
        "tokens_reported": census["total"],
        "resolution_reached": counts.get(RESOLUTION_EVENT_TYPE, 0) > 0,
    }


def classify_measurement(
    chunks: Iterable[Dict[str, Any]],
    *,
    outcome: str | None = None,
    provider_refusal: Dict[str, Any] | None = None,
    effect_observed: bool = False,
    acceptance_satisfied: bool = False,
) -> Dict[str, Any]:
    """Decide whether this attempt measured the route, and if not, what stopped it.

    `measured` is the only thing a capability conclusion may be drawn from. It is
    true when the model demonstrably performed work and false in every case where
    the attempt ended without the model having done anything - which is not a
    smaller claim about the route, it is no claim about the route.
    """
    signals = measurement_signals(chunks)
    counts = signals["event_counts"]
    proof = [event_type for event_type in EXECUTION_PROOF_EVENT_TYPES if counts.get(event_type)]
    if signals["tokens_reported"]:
        proof.append("token_usage")
    if effect_observed:
        proof.append("workspace_diff")
    if acceptance_satisfied:
        proof.append("acceptance_satisfied")

    status_codes = [
        error["status_code"] for error in signals["error_events"]
        if isinstance(error.get("status_code"), int)
    ]

    if provider_refusal:
        # A refusal is named by the provider itself and outranks anything TEMM
        # would infer from the transcript it left behind: a request the provider
        # would not serve exercised nothing, however far the CLI got first.
        classification, reason = PROVIDER_REFUSAL, (
            "provider_allowance_exhausted" if provider_refusal.get("allowance_exhausted") else "provider_refused"
        )
    elif proof:
        classification, reason = MODEL_EXECUTED, "model_produced_work"
    elif outcome == "launch_failed":
        classification, reason = EXECUTOR_LOCAL_FAILURE, "executor_launch_failed"
    elif status_codes:
        classification, reason = PROVIDER_UNAVAILABLE, f"provider_http_{status_codes[0]}"
    elif signals["error_events"]:
        classification, reason = (
            (PROVIDER_UNAVAILABLE, "provider_response_unusable")
            if signals["resolution_reached"]
            else (EXECUTOR_LOCAL_FAILURE, "local_resolution_failed")
        )
    elif outcome in {"timed_out", "interrupted", "cancelled"}:
        classification, reason = (
            (PROVIDER_UNAVAILABLE, "no_provider_response_before_bound")
            if signals["resolution_reached"]
            else (EXECUTOR_LOCAL_FAILURE, f"{outcome or 'stopped'}_before_execution")
        )
    else:
        classification, reason = NO_EXECUTION_SIGNAL, "no_execution_signal"

    return {
        "classification": classification,
        "measured": classification == MODEL_EXECUTED,
        "reason": reason,
        "execution_proof": proof,
        "resolution_reached": signals["resolution_reached"],
        "event_counts": counts,
        "error_events": signals["error_events"],
        "tokens_reported": signals["tokens_reported"],
        "token_census": signals["token_census"],
        # Kept explicit so a caller cannot accidentally treat a non-measurement as
        # a soft negative: nothing about the route may be recorded unless this is
        # true, and a refusal that already has its own handling is excluded.
        "capability_conclusion_admissible": classification == MODEL_EXECUTED,
    }


def stated_permanence(error_events: Iterable[Dict[str, Any]]) -> Dict[str, str]:
    """How long the provider's answer holds, according to the provider.

    Only an answer from the provider can carry this. A failure below the provider
    never reached one, so its text is the executor talking about itself and is read
    as nothing - a local error mentioning an end of life must not retire a route.

    The first error event that says something decisive settles it, and a status about
    the account or the request settles it as transient however the body reads.
    """
    for error in error_events:
        status = error.get("status_code")
        message = str(error.get("message") or "").lower()
        if isinstance(status, int) and status in NON_ROUTE_STATUS_CODES:
            return {"permanence": PERMANENCE_TRANSIENT, "basis": f"http_{status}_is_not_about_the_route"}
        if isinstance(status, int) and status in PERMANENT_STATUS_CODES:
            return {"permanence": PERMANENCE_PERMANENT, "basis": f"http_{status}_gone"}
        if any(phrase in message for phrase in END_OF_LIFE_PHRASES):
            return {"permanence": PERMANENCE_PERMANENT, "basis": "provider_stated_end_of_life"}
        if isinstance(status, int) and status in ROUTE_UNSERVED_STATUS_CODES:
            return {"permanence": PERMANENCE_ROUTE_UNSERVED, "basis": f"http_{status}_not_found"}
    return {"permanence": PERMANENCE_TRANSIENT, "basis": "provider_stated_no_permanence"}


def non_measurement_hold(measurement: Dict[str, Any], host: Dict[str, Any] | None = None) -> Dict[str, Any]:
    """How long a non-measured route is withheld, and on whose authority.

    The per-classification TTL is a floor sized to the shortest thing the
    classification can mean - a provider that could not answer may answer in ten
    minutes. It was also the ceiling, and a provider that says the model is gone for
    good is not describing a ten-minute outage. Production evidence 2026-08-21,
    dispatches 4 through 14 of one NEXA loop: NVIDIA answered `410 Gone`, `The model
    'google/gemma-2-2b-it' has reached its end of life on 2026-07-27` and `404 Not
    Found` for route after route, each held for 600 seconds, so a catalog of some
    ninety retired and non-chat routes re-entered the probe pool every ten minutes -
    permanently, and ahead of every provider whose credentials had never been tried.

    So the hold follows the permanence the provider stated, and the classification's
    TTL is what it always was where the provider stated none. The scope is the probed
    route and nothing else: one route's `410` is not a verdict on its provider, and a
    provider-wide misconfiguration must never be able to withdraw a whole catalog.

    A hold also has to have something to be about, and one class of non-measurement is
    not about the route at all. `executor_local_failure` means the failure happened on
    this machine before anything reached a provider, and when the machine was
    simultaneously observed short of memory, the machine is what failed - the route was
    never asked, so withdrawing it neither records anything true nor clears the
    condition. It makes it worse: dispatch moves to the next route, which dies the same
    way and is held the same way, until a single shortage has withdrawn the catalog a
    route at a time. Production evidence 2026-08-21, `attempt-0144bc5d1502`: the CLI
    aborted on `MemoryExhaustion` 31s in with no events, and the fleet's only certified
    route carried the half-hour hold for it. So a local failure observed under host
    pressure is attributed to the host and costs the route nothing.

    That attribution is deliberately narrow. It needs the classification that already
    names this machine as the site of the failure, a host reading that was actually
    taken, and nothing having reached the provider - a request that got an answer is
    described by the answer, and a host reading does not contradict it. It is also
    only ever used to *withhold* a penalty, never to impose one: mistaking a broken
    route for a busy host costs one re-probe, which fails again and is held once the
    host is calm, while the reverse would hide a real outage behind a memory reading.
    """
    classification = measurement.get("classification")
    default_ttl = NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS.get(classification)
    hold = {
        "ttl_seconds": default_ttl,
        "permanence": PERMANENCE_TRANSIENT,
        "permanence_basis": "classification_default",
        "default_ttl_seconds": default_ttl,
        "attribution": "route",
    }
    if measurement.get("measured") or not default_ttl:
        return hold
    if (
        classification == EXECUTOR_LOCAL_FAILURE
        and (host or {}).get("measurable")
        and (host or {}).get("pressure")
        and not measurement.get("resolution_reached")
    ):
        return {
            **hold,
            "ttl_seconds": None,
            "attribution": "host",
            "attribution_basis": host.get("pressure_basis"),
            "host_observation": host,
        }
    if classification != PROVIDER_UNAVAILABLE:
        return hold
    stated = stated_permanence(measurement.get("error_events") or [])
    ttl = PERMANENCE_HOLD_SECONDS.get(stated["permanence"])
    return {
        **hold,
        # Never shorter than the classification asks for: permanence only ever
        # extends a hold, so a lookup that returns nothing leaves the floor standing.
        "ttl_seconds": max(default_ttl, ttl) if ttl else default_ttl,
        "permanence": stated["permanence"],
        "permanence_basis": stated["basis"],
    }


def unmeasured_stage_note(measurement: Dict[str, Any]) -> Dict[str, Any]:
    """Summarize a non-measurement for the record that would have held a verdict."""
    return {
        "unmeasured": True,
        "measurement_classification": measurement.get("classification"),
        "measurement_reason": measurement.get("reason"),
        "resolution_reached": measurement.get("resolution_reached"),
        "error_events": measurement.get("error_events") or [],
    }
