import json
import re
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..errors import DomainError
from ..security import SensitiveDataRedactor
from ..storage.models import ProviderInstanceRecord, QuotaObservationRecord
from ..storage.secret_vault import secret_vault

# Statuses with which a provider declines to serve a request that is otherwise
# well formed. They say nothing about the model's ability, so they must never be
# read as capability evidence - only as this route being unusable right now.
REFUSAL_STATUS_CODES = {402, 403, 429}
# Status codes by which a provider states a spent allowance itself, in the one part
# of its response that is not prose. 429 is "Too Many Requests" and 402 is "Payment
# Required": each says an allowance is used up whatever words accompany it, so
# neither needs a phrase to be recognised. 403 is deliberately absent - a rejected
# key answers 403 too, and only the message separates the two.
#
# Read from the status code because reading it from the wording made the fleet's
# only durable memory of a spent allowance depend on a provider's choice of
# synonym. Production evidence 2026-08-21: `opencode:openai` answered 429 "The
# usage limit has been reached", which carries none of the phrases below - not
# "quota", not "rate limit", not "too many requests" - so `allowance_exhausted` came
# back false, and the whole ledger write is gated on that flag. attempt-ac22ecc832d8
# recorded no observation, no horizon and no scope; the account kept no record of
# its own spent limit; and the six dispatches that followed spent six probes on
# uncredentialed providers while the one route that had been serving all afternoon
# was held out by nothing more durable than a one-hour window over attempt receipts.
ALLOWANCE_STATUS_CODES = {402, 429}
# Phrases by which a provider names a spent allowance rather than any other kind
# of refusal, for the codes that do not say it themselves. A bad key also answers
# 403, and recording that as "remaining: 0" would put a quota claim in the records
# that the provider never made.
EXHAUSTION_PHRASES = (
    "quota",
    "insufficient_quota",
    "credit",
    "billing",
    "add funds",
    "rate limit",
    "rate_limit",
    "too many requests",
    "exceeded your current",
    "out of tokens",
)
# Phrases by which a provider names its *account's* allowance rather than one
# model's. The distinction decides how much the observation withholds: an account
# whose free tier is spent refuses every model on it, so recording that fact under
# one model's name leaves the fleet to rediscover it once per model, one dispatch
# at a time, while no task can run in between. Production evidence 2026-08-21:
# `opencode:aliyun` answered thirteen consecutive dispatches with the identical
# account-level message "Free quota exhausted. To continue accessing the model on a
# paid basis, please add funds or disable the \"use free tier only\" mode in the
# management console" - and TEMM wrote thirteen model-scoped observations, each
# holding out exactly one of the roughly eighty aliyun routes.
ACCOUNT_ALLOWANCE_PHRASES = (
    "add funds",
    "billing",
    "credit",
    "free quota",
    "free tier",
    "insufficient_quota",
    "out of tokens",
    "payment",
    "recharge",
    "subscription",
    "top up",
    "your account",
)
# Phrases by which a provider says it rejected the *credential*, not an
# allowance. A rejected key belongs to the provider instance: every model behind
# it is refused identically, and no amount of retrying one model teaches the
# fleet anything about the next. Production evidence 2026-08-21: thirteen
# consecutive dispatches probed thirteen different `amazon-bedrock` models and
# each answered HTTP 403 "Authentication failed: Please make sure your API Key is
# valid." Because the message claims no exhaustion it reached no ledger at all,
# so the remaining hundred-odd bedrock routes were each still queued to buy the
# same fact one dispatch at a time, and no other provider was sampled meanwhile.
CREDENTIAL_REFUSAL_PHRASES = (
    "api key is missing",
    "api key is valid",
    "api key not valid",
    "authentication failed",
    "authentication_error",
    "expired token",
    "incorrect api key",
    "invalid api key",
    "invalid authentication",
    "invalid credentials",
    "invalid token",
    "invalid_api_key",
    "missing api key",
    "no api key",
    "not authorized",
    "re-authenticate",
    "reauthenticate",
    "token expired",
    "token has expired",
    "unauthorized",
)
# How long a spent allowance is withheld when the provider named no reset time,
# and the ceiling no derived horizon may pass. The provider stated a fact without a
# date, so the length is TEMM's guess - and a guess is worth repeating only until it
# is contradicted. Every expiry the next look answers with the identical refusal is
# that contradiction: the fleet spent the one probe a dispatch is allowed to
# re-learn what it already knew, and answered a ready queue `execution_unavailable`
# while doing it. Production evidence 2026-08-21: `opencode:aliyun` answered "Free
# quota exhausted ... please add funds" at 23:33, 00:39, 02:00, 03:27 and 08:42,
# every time with no reset stated and every time held for exactly one hour, and at
# 08:42 all ten renewable routes in the fleet belonged to that one spent account -
# so the horizon that never lengthened was the whole of what stood between five
# ready tasks and a route that could have served them.
SPENT_ALLOWANCE_BASE_TTL_SECONDS = 3600
SPENT_ALLOWANCE_MAX_TTL_SECONDS = 86400
# Locates the lines worth parsing. Whitespace-tolerant because how the producer
# spaced its JSON is no part of what the event means.
ERROR_EVENT_LINE = re.compile(r'"type"\s*:\s*"error"')


def _refusal_scope(haystack: str, model: str | None) -> Dict[str, Any]:
    """How far the refusal reaches, and which allowance it is about.

    Read in that order deliberately. A provider that names the model in its
    refusal has stated the narrowest true thing and said nothing about its other
    models - including when it blames the key, as "you do not have access to
    model X with this key" does. Only when the message names something the whole
    account owns may the refusal be carried provider-wide: a rejected credential
    and a spent account tier are both refused identically by every model behind
    them, and a scope of `*` says exactly that.

    Anything else falls back to the model, the narrower reading: a scope guessed
    too narrow costs one further probe to learn the same fact, while one guessed
    too wide withholds a provider that would have served the request.

    `refusal_kind` is reported alongside because the two provider-wide readings
    are owed different ledgers. A spent allowance is a quota fact and belongs in
    the quota ledger; a rejected key is not, and recording it as `remaining: 0`
    would restate the false quota claim that ledger was fixed to stop making. It
    is an availability fact, holding until an operator repairs the credential.
    """
    candidates = {(model or ""), (model or "").split("/")[-1]}
    if any(len(name) >= 4 and name.lower() in haystack for name in candidates):
        return {"refusal_scope": "model", "refusal_kind": "unattributed", "refusal_scope_basis": "provider_named_requested_model"}
    credential = [phrase for phrase in CREDENTIAL_REFUSAL_PHRASES if phrase in haystack]
    if credential:
        return {"refusal_scope": "provider", "refusal_kind": "credential", "refusal_scope_basis": f"provider_rejected_credential:{credential[0]}"}
    allowance = [phrase for phrase in ACCOUNT_ALLOWANCE_PHRASES if phrase in haystack]
    if allowance:
        return {"refusal_scope": "provider", "refusal_kind": "allowance", "refusal_scope_basis": f"provider_named_account_allowance:{allowance[0]}"}
    return {"refusal_scope": "model", "refusal_kind": "unattributed", "refusal_scope_basis": "unattributed_refusal_read_narrowly"}


def detect_provider_refusal(chunks: Iterable[Dict[str, Any]], *, model: str | None = None) -> Dict[str, Any] | None:
    """Find a provider's own refusal in the executor's event stream.

    The CLI reports a provider error as an event on stdout and then exits
    non-zero, so the exit code alone cannot tell a route that failed at the task
    from a route the provider would not serve at all. Only the event carries that
    distinction, and it is the difference between an attempt worth retrying on
    the same route and one that will be refused identically every time.

    Returns None when the stream holds no refusal, so a caller can treat "no
    refusal found" and "no stream" alike.
    """
    text = "".join(chunk.get("content") or "" for chunk in chunks if (chunk.get("stream") or "stdout") == "stdout")
    if not text:
        return None
    for line in text.splitlines():
        # Parse only the lines that announce an error. The stream is mostly file
        # content and reasoning, and a task whose own subject is quota handling
        # would otherwise be misread as a provider that refused it.
        if not ERROR_EVENT_LINE.search(line):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            # A chunk boundary can split the final line. A refusal that ends the
            # attempt is the last thing written, so a truncated line is expected
            # and is not evidence of anything.
            continue
        if not isinstance(event, dict) or event.get("type") != "error":
            continue
        error = event.get("error")
        data = error.get("data") if isinstance(error, dict) else None
        if not isinstance(data, dict):
            continue
        status_code = data.get("statusCode")
        if status_code not in REFUSAL_STATUS_CODES:
            continue
        message = str(data.get("message") or "")
        body = str(data.get("responseBody") or "")
        haystack = f"{message} {body}".lower()
        code = ""
        match = re.search(r'"code"\s*:\s*"([^"]+)"', body)
        if match:
            code = match.group(1)
        headers = data.get("responseHeaders") if isinstance(data.get("responseHeaders"), dict) else {}
        retry_after = headers.get("retry-after") or headers.get("Retry-After")
        return {
            "status_code": status_code,
            "provider_code": code,
            "message": message[:500],
            "retry_after_seconds": int(retry_after) if str(retry_after or "").isdigit() else None,
            # The status code first, then the wording. A 429 or 402 has already
            # stated the fact; for a 403 the phrases are what separate a spent
            # allowance from a rejected credential.
            "allowance_exhausted": status_code in ALLOWANCE_STATUS_CODES or any(phrase in haystack for phrase in EXHAUSTION_PHRASES),
            **_refusal_scope(haystack, model),
        }
    return None


class QuotaService:
    async def record(self, session: AsyncSession, provider_instance_id: str, values: Dict[str, Any]) -> QuotaObservationRecord:
        if not await session.get(ProviderInstanceRecord, provider_instance_id):
            raise DomainError("resource_not_found", message="Provider instance was not found.")
        source = values["source"]
        if source not in {"provider_reported", "measured", "unknown"}:
            raise DomainError("validation_failed", message="Quota source is invalid.")
        limit_value = values.get("limit")
        remaining = values.get("remaining")
        if any(value is not None and value < 0 for value in [limit_value, remaining]):
            raise DomainError("validation_failed", message="Quota values cannot be negative.")
        if limit_value is not None and remaining is not None and remaining > limit_value:
            raise DomainError("validation_failed", message="Quota remaining cannot exceed limit.")
        ttl = values.get("ttl_seconds", 300)
        if not 10 <= ttl <= 86400:
            raise DomainError("validation_failed", message="Quota TTL is invalid.")
        checked_at = values.get("checked_at") or datetime.utcnow()
        evidence = SensitiveDataRedactor.from_environment(secret_vault.redaction_values()).redact(values.get("evidence", {}))
        record = QuotaObservationRecord(
            id=f"quota-{uuid.uuid4().hex[:12]}", provider_instance_id=provider_instance_id,
            scope=values["scope"], unit=values.get("unit", "unknown"),
            limit_value=limit_value, remaining_value=remaining, resets_at=values.get("resets_at"),
            source=source, checked_at=checked_at, expires_at=checked_at + timedelta(seconds=ttl),
            evidence=json.dumps(evidence),
        )
        session.add(record)
        await session.commit()
        return record

    async def refusal_horizon(self, session: AsyncSession, provider_instance_id: str, scope: str, *, retry_after_seconds: int | None = None) -> Dict[str, Any]:
        """How long to withhold an allowance the provider has just called spent.

        A provider that states a reset has answered the question itself, and its
        answer is obeyed verbatim: nothing here is a better source on someone else's
        account than they are.

        With no reset stated the length is a guess, and the ledger already holds the
        record of how that guess has fared. Each consecutive look at this allowance
        that found it spent is one expiry that turned out to be too early, so the
        horizon doubles per reconfirmation up to a day - long enough that the fleet
        stops paying a probe an hour to re-learn a standing fact, bounded so a
        topped-up account is never withheld indefinitely.

        The chain reads this scope's own history together with the account-wide `*`,
        because an account that refuses everything refuses this scope too, and it
        breaks at the first look that did not find the allowance spent - which is
        what `note_served` records the moment the provider serves anything again. So
        the escalation is never carried across a recovery and never outlives the
        evidence for it. A look at some sibling model is allowed to break a chain it
        was not strictly about: read too wide the fleet spends one further probe to
        re-learn a fact it had, and read too narrow it withholds a provider that
        would have served the request.
        """
        if retry_after_seconds and int(retry_after_seconds) > 0:
            return {
                "ttl_seconds": max(10, min(int(retry_after_seconds), SPENT_ALLOWANCE_MAX_TTL_SECONDS)),
                "basis": "provider_stated_retry_after",
                "reconfirmations": 0,
            }
        looks = (await session.execute(
            select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == provider_instance_id,
                QuotaObservationRecord.scope.in_(sorted({scope, "*"})),
            ).order_by(QuotaObservationRecord.checked_at.desc())
        )).scalars().all()
        reconfirmations = 0
        for look in looks:
            # Read whether or not it has expired. An expired observation is no
            # longer a reason to withhold anything, but it is still a look that was
            # taken and still says what it found - and its expiry is the very thing
            # the chain measures.
            if look.remaining_value != 0:
                break
            reconfirmations += 1
        return {
            "ttl_seconds": min(SPENT_ALLOWANCE_BASE_TTL_SECONDS * 2 ** reconfirmations, SPENT_ALLOWANCE_MAX_TTL_SECONDS),
            "basis": "reconfirmed_spent_allowance" if reconfirmations else "first_look_at_this_allowance",
            "reconfirmations": reconfirmations,
        }

    async def note_served(self, session: AsyncSession, provider_instance_id: str, *, model: str | None = None, evidence: Dict[str, Any] | None = None) -> QuotaObservationRecord | None:
        """Record that a provider served a request, when the ledger says it would not.

        A spent allowance is withheld for as long as the last look says it is spent,
        and `refusal_horizon` lengthens that hold each time the look is confirmed.
        Both need the opposite fact to be recordable, or an account topped up after
        its worst hour keeps the longest hold that hour earned. Nothing else writes
        it: serving a request produces no quota event, so the only measurement that
        can prove recovery is the run itself.

        The observation claims no number. What a served request reveals is that the
        allowance was not spent, not how much of it is left, and `remaining: 0` on no
        evidence is the false claim this ledger exists to stop making - so
        `remaining` stays null, which reads as no exclusion to everything that
        withholds routes and as the end of the chain to the horizon.

        Written only when it contradicts the record, so one row per successful
        attempt does not bury the looks that mean something.
        """
        newest = (await session.execute(
            select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == provider_instance_id,
            ).order_by(QuotaObservationRecord.checked_at.desc()).limit(1)
        )).scalars().first()
        if newest is None or newest.remaining_value != 0:
            return None
        return await self.record(session, provider_instance_id, {
            "scope": "*",
            "unit": "requests",
            "source": "measured",
            "ttl_seconds": SPENT_ALLOWANCE_BASE_TTL_SECONDS,
            "evidence": {"reason": "provider_served_request", "model": model, **(evidence or {})},
        })

    async def current(self, session: AsyncSession, provider_instance_id: str, at: datetime | None = None) -> List[QuotaObservationRecord]:
        at = at or datetime.utcnow()
        return (await session.execute(
            select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == provider_instance_id,
                QuotaObservationRecord.expires_at > at,
            ).order_by(QuotaObservationRecord.checked_at.desc())
        )).scalars().all()


quota_service = QuotaService()
