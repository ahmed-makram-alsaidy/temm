import json
import unittest
from datetime import datetime, timedelta

import httpx
from sqlalchemy import delete, select

from core.ai_fleet.main import app
from core.ai_fleet.services.quota import ALLOWANCE_STATUS_CODES, EXHAUSTION_PHRASES, SPENT_ALLOWANCE_BASE_TTL_SECONDS, SPENT_ALLOWANCE_MAX_TTL_SECONDS, detect_provider_refusal, quota_service
from core.ai_fleet.storage.database import AsyncSessionLocal, init_db
from core.ai_fleet.storage.models import ProviderInstanceRecord, QuotaObservationRecord
from core.ai_fleet.storage.secret_vault import secret_vault


def error_event(**data) -> str:
    """One stdout line shaped like the CLI's own provider-error event."""
    return json.dumps({"type": "error", "sessionID": "ses_x", "error": {"name": "APIError", "data": data}})


class ProviderRefusalDetectionTests(unittest.TestCase):
    """The refusal is read from the executor's stream, which is the only place it appears.

    Every payload here is the shape production produced: attempt-e2cd417ed8aa,
    2026-08-19, `aliyun/deepseek-v4-flash-0731`.
    """

    def test_spent_allowance_is_read_from_the_providers_own_words(self):
        line = error_event(
            message='Free quota exhausted. To continue accessing the model on a paid basis, please add funds or disable the "use free tier only" mode in the management console.',
            statusCode=403,
            isRetryable=False,
            responseBody='{"error":{"message":"Free quota exhausted.","type":"insufficient_quota","code":"insufficient_quota"}}',
        )
        refusal = detect_provider_refusal([{"stream": "stdout", "content": f'{{"type":"step_start"}}\n{line}\n'}])
        self.assertEqual(refusal["status_code"], 403)
        self.assertEqual(refusal["provider_code"], "insufficient_quota")
        self.assertTrue(refusal["allowance_exhausted"])

    def test_a_refusal_split_across_chunk_boundaries_is_still_read(self):
        line = error_event(message="Quota exceeded", statusCode=429, responseHeaders={"retry-after": "120"})
        half = len(line) // 2
        refusal = detect_provider_refusal([
            {"stream": "stdout", "content": line[:half]},
            {"stream": "stdout", "content": line[half:] + "\n"},
        ])
        self.assertEqual(refusal["status_code"], 429)
        self.assertEqual(refusal["retry_after_seconds"], 120)
        self.assertTrue(refusal["allowance_exhausted"])

    def test_a_refusal_that_is_not_about_an_allowance_makes_no_quota_claim(self):
        """A bad key answers 403 too, and recording "remaining: 0" for it would be a lie."""
        line = error_event(message="Invalid API key provided.", statusCode=403, responseBody='{"error":{"code":"invalid_api_key"}}')
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}])
        self.assertEqual(refusal["status_code"], 403)
        self.assertFalse(refusal["allowance_exhausted"])

    def test_a_rate_refusal_is_an_allowance_fact_in_whatever_words_it_arrives(self):
        """429 states a spent allowance itself, so no phrase has to be recognised.

        Reading the fact from the wording made the fleet's only durable record of a
        spent allowance depend on the provider's choice of synonym. Production
        evidence 2026-08-21: `opencode:openai` answered 429 "The usage limit has been
        reached" - no "quota", no "rate limit", no "too many requests" - and because
        the whole quota-ledger write is gated on this flag, attempt-ac22ecc832d8
        recorded no observation, no horizon and no scope for the one route that had
        been serving NEXA all afternoon.
        """
        line = error_event(message="The usage limit has been reached", statusCode=429, responseBody="{}")
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}], model="openai/gpt-5.4-fast")
        self.assertNotIn("usage limit", " ".join(EXHAUSTION_PHRASES), "Guards the premise: this wording is matched by no phrase.")
        self.assertTrue(refusal["allowance_exhausted"], "429 is the provider saying an allowance is used up.")
        self.assertEqual(refusal["provider_code"], "", "The body named no code; the status still carries the fact.")

    def test_a_payment_required_refusal_is_an_allowance_fact_too(self):
        """402 is "Payment Required", which is a spent allowance by definition."""
        line = error_event(message="Add a payment method to continue.", statusCode=402, responseBody="{}")
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}])
        self.assertTrue(refusal["allowance_exhausted"])
        self.assertEqual(ALLOWANCE_STATUS_CODES, {402, 429}, "403 is excluded on purpose - a rejected key answers it too.")

    def test_an_unexplained_403_still_makes_no_quota_claim(self):
        """The boundary the status-code reading must not cross.

        403 is the one refusal code that does not say which fact it is about, and a
        rejected credential answers it identically. Recording that as `remaining: 0`
        is the false quota claim this ledger exists to stop making, so for 403 the
        wording remains the only thing that can establish an allowance.
        """
        line = error_event(message="Forbidden.", statusCode=403, responseBody="{}")
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}])
        self.assertEqual(refusal["status_code"], 403)
        self.assertFalse(refusal["allowance_exhausted"])

    def test_a_rate_refusal_that_states_its_reset_is_still_obeyed_verbatim(self):
        """Reading the fact from the status must not discard the provider's own date."""
        line = error_event(message="Slow down.", statusCode=429, responseHeaders={"retry-after": "45"}, responseBody="{}")
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}])
        self.assertTrue(refusal["allowance_exhausted"])
        self.assertEqual(refusal["retry_after_seconds"], 45)

    def test_an_account_level_refusal_is_scoped_to_the_provider_not_one_model(self):
        """The provider named its account's free tier, so that is the fact recorded.

        Scoping this to the requested model records a claim the provider never
        made and leaves the same spent tier to be rediscovered once per model.
        Production evidence 2026-08-21: thirteen model-scoped `opencode:aliyun`
        observations written inside two minutes from this identical message, each
        holding out one route of roughly eighty, while every dispatch in that
        window answered `execution_unavailable`.
        """
        line = error_event(
            message='Free quota exhausted. To continue accessing the model on a paid basis, please add funds or disable the "use free tier only" mode in the management console.',
            statusCode=403,
            responseBody='{"error":{"type":"insufficient_quota","code":"insufficient_quota"}}',
        )
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}], model="qwen3-coder-plus")
        self.assertTrue(refusal["allowance_exhausted"])
        self.assertEqual(refusal["refusal_scope"], "provider")
        self.assertTrue(refusal["refusal_scope_basis"].startswith("provider_named_account_allowance:"))

    def test_a_refusal_that_names_the_requested_model_stays_scoped_to_it(self):
        """Naming the model is the narrowest true statement, and it outranks the rest.

        A per-model limit says nothing about the account's other models, so the
        account-allowance phrases that also appear in such a message - here the
        advice to add funds - must not widen it to the whole provider.
        """
        line = error_event(
            message="Model qwen3-coder-plus is over its per-model rate limit. Add funds to raise it.",
            statusCode=429,
            responseBody='{"error":{"code":"rate_limit_exceeded"}}',
        )
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}], model="aliyun/qwen3-coder-plus")
        self.assertTrue(refusal["allowance_exhausted"])
        self.assertEqual(refusal["refusal_scope"], "model")
        self.assertEqual(refusal["refusal_scope_basis"], "provider_named_requested_model")

    def test_a_refusal_that_attributes_nothing_is_read_narrowly(self):
        """An unattributed refusal is guessed at the model, the cheaper mistake.

        Too narrow costs one further probe to learn the same fact; too wide
        withholds a provider that would have served the request.
        """
        line = error_event(message="Quota exceeded", statusCode=429)
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}], model="qwen3-coder-plus")
        self.assertEqual(refusal["refusal_scope"], "model")
        self.assertEqual(refusal["refusal_scope_basis"], "unattributed_refusal_read_narrowly")

    def test_a_rejected_credential_belongs_to_the_provider_not_one_model(self):
        """A key the provider will not accept is refused by every model behind it.

        Production evidence 2026-08-21: thirteen consecutive dispatches probed
        thirteen different `amazon-bedrock` models and each was answered with this
        identical message. Read at model scope, the remaining hundred-odd bedrock
        routes were each still queued to buy the same fact one dispatch at a time,
        and no other provider was sampled meanwhile.
        """
        line = error_event(
            message='Forbidden: {"Message":"Authentication failed: Please make sure your API Key is valid."}',
            statusCode=403,
        )
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}], model="anthropic.claude-opus-5")
        self.assertEqual(refusal["refusal_scope"], "provider")
        self.assertEqual(refusal["refusal_kind"], "credential")
        self.assertTrue(refusal["refusal_scope_basis"].startswith("provider_rejected_credential:"), refusal)
        # No allowance was named, so no allowance claim may be made: a rejected key
        # is an availability fact, and recording it as a spent quota would restate
        # the false quota claim that ledger was fixed to stop making.
        self.assertFalse(refusal["allowance_exhausted"])

    def test_a_credential_refusal_that_names_the_model_stays_scoped_to_it(self):
        """A key can be valid and still not entitle the account to one model.

        The narrowest true reading wins here too: this message is about a single
        model's entitlement, so widening it would withhold every other model the
        same key does serve.
        """
        line = error_event(
            message="You do not have access to model claude-opus-5 with this API key.",
            statusCode=403,
        )
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}], model="amazon-bedrock/claude-opus-5")
        self.assertEqual(refusal["refusal_scope"], "model")
        self.assertEqual(refusal["refusal_scope_basis"], "provider_named_requested_model")

    def test_a_spent_allowance_is_still_read_as_an_allowance_not_a_credential(self):
        """The two provider-wide readings are owed different ledgers, so they stay apart.

        An allowance refusal carries a real quota claim and returns on its own; a
        rejected credential carries none and holds until an operator repairs it.
        """
        line = error_event(
            message="Your account has no remaining credit. Please add funds.",
            statusCode=403,
        )
        refusal = detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}], model="qwen3-coder-plus")
        self.assertEqual(refusal["refusal_scope"], "provider")
        self.assertEqual(refusal["refusal_kind"], "allowance")

    def test_a_task_that_merely_discusses_quota_is_not_a_refusal(self):
        """The executor echoes the files it writes, so prose about quotas flows through this stream."""
        chunks = [
            {"stream": "stdout", "content": json.dumps({"type": "text", "part": {"text": "I will add a 403 insufficient_quota handler with statusCode checks."}}) + "\n"},
            {"stream": "stdout", "content": json.dumps({"type": "step_finish", "part": {"reason": "tool-calls"}}) + "\n"},
        ]
        self.assertIsNone(detect_provider_refusal(chunks))

    def test_a_server_fault_is_the_routes_problem_and_not_a_refusal(self):
        line = error_event(message="Internal server error", statusCode=500)
        self.assertIsNone(detect_provider_refusal([{"stream": "stdout", "content": line + "\n"}]))

    def test_an_empty_stream_yields_nothing(self):
        self.assertIsNone(detect_provider_refusal([]))


class QuotaObservationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        await init_db()
        self.provider_id = f"quota-provider-{id(self)}"
        async with AsyncSessionLocal() as session:
            session.add(ProviderInstanceRecord(id=self.provider_id, name="Quota Provider", adapter_id="test", capabilities='["quota"]'))
            await session.commit()
        self.transport = httpx.ASGITransport(app=app)

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(QuotaObservationRecord).where(QuotaObservationRecord.provider_instance_id == self.provider_id))
            provider = await session.get(ProviderInstanceRecord, self.provider_id)
            if provider:
                await session.delete(provider)
            await session.commit()

    async def test_unknown_values_remain_null_and_stale_is_filtered(self):
        now = datetime.utcnow()
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            unknown = await client.post(f"/api/providers/{self.provider_id}/quota", json={"scope": "monthly", "source": "unknown", "checked_at": now.isoformat(), "ttl_seconds": 60})
            current = await client.get(f"/api/providers/{self.provider_id}/quota")
        self.assertEqual(unknown.status_code, 200)
        self.assertIsNone(unknown.json()["limit"])
        self.assertIsNone(unknown.json()["remaining"])
        self.assertEqual(len(current.json()), 1)
        async with AsyncSessionLocal() as session:
            record = (await session.execute(__import__("sqlalchemy").select(QuotaObservationRecord).where(QuotaObservationRecord.provider_instance_id == self.provider_id))).scalar_one()
            record.expires_at = datetime.utcnow() - timedelta(seconds=1)
            await session.commit()
        async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
            stale = await client.get(f"/api/providers/{self.provider_id}/quota")
        self.assertEqual(stale.json(), [])

    async def test_invalid_remaining_and_secret_evidence(self):
        secret = "quota-secret-820394"
        secret_vault.set_key("quota-test", secret)
        try:
            async with httpx.AsyncClient(transport=self.transport, base_url="http://test") as client:
                invalid = await client.post(f"/api/providers/{self.provider_id}/quota", json={"scope": "daily", "limit": 10, "remaining": 11, "source": "provider_reported"})
                observed = await client.post(f"/api/providers/{self.provider_id}/quota", json={"scope": "daily", "limit": 10, "remaining": 3, "source": "provider_reported", "evidence": {"token": secret}})
            self.assertEqual(invalid.status_code, 422)
            self.assertNotIn(secret, observed.text)
        finally:
            secret_vault.delete_key("quota-test")


class SpentAllowanceHorizonTests(unittest.IsolatedAsyncioTestCase):
    """How long a spent allowance is withheld, and what shortens it again.

    A provider that names no reset is being guessed at, and the fleet acts on that
    guess by withholding every route behind the account. Production evidence
    2026-08-21: `opencode:aliyun` answered "Free quota exhausted ... please add
    funds" five times between 23:33 and 08:42, each look dated exactly one hour
    ahead and each costing the single probe a dispatch is allowed - because the guess
    was reset to the same hour however often it had already been contradicted. At
    08:42 all ten renewable routes in the fleet were that one spent account's, so
    five ready NEXA tasks answered `execution_unavailable` behind a fact the ledger
    had already recorded four times.
    """

    async def asyncSetUp(self):
        await init_db()
        self.provider_id = f"horizon-provider-{id(self)}"
        self.now = datetime.utcnow()
        async with AsyncSessionLocal() as session:
            session.add(ProviderInstanceRecord(id=self.provider_id, name="Horizon Provider", adapter_id="test", capabilities='["quota"]'))
            await session.commit()

    async def asyncTearDown(self):
        async with AsyncSessionLocal() as session:
            await session.execute(delete(QuotaObservationRecord).where(QuotaObservationRecord.provider_instance_id == self.provider_id))
            provider = await session.get(ProviderInstanceRecord, self.provider_id)
            if provider:
                await session.delete(provider)
            await session.commit()

    async def _spent(self, session, *, scope="*", ago_hours=0.0):
        """One look at this allowance that found it spent, dated in the past."""
        return await quota_service.record(session, self.provider_id, {
            "scope": scope, "unit": "requests", "remaining": 0, "source": "measured",
            "ttl_seconds": SPENT_ALLOWANCE_BASE_TTL_SECONDS,
            "checked_at": self.now - timedelta(hours=ago_hours),
            "evidence": {"reason": "provider_refusal"},
        })

    async def test_a_spent_allowance_the_provider_never_dated_is_held_longer_as_it_repeats(self):
        """Each expiry answered by the identical refusal is that horizon proven short."""
        async with AsyncSessionLocal() as session:
            first = await quota_service.refusal_horizon(session, self.provider_id, "*")
            widened = []
            for index in range(6):
                await self._spent(session, ago_hours=6 - index)
                widened.append(await quota_service.refusal_horizon(session, self.provider_id, "*"))
        self.assertEqual((first["ttl_seconds"], first["reconfirmations"]), (SPENT_ALLOWANCE_BASE_TTL_SECONDS, 0))
        self.assertEqual(first["basis"], "first_look_at_this_allowance", "Nothing has been contradicted yet, so the guess is the base one.")
        self.assertEqual([item["ttl_seconds"] for item in widened], [7200, 14400, 28800, 57600, 86400, 86400])
        self.assertEqual({item["basis"] for item in widened}, {"reconfirmed_spent_allowance"})
        self.assertEqual(widened[-1]["ttl_seconds"], SPENT_ALLOWANCE_MAX_TTL_SECONDS, "Bounded: a topped-up account must not be withheld indefinitely.")

    async def test_a_reset_the_provider_states_is_obeyed_however_often_the_refusal_repeats(self):
        """The account's owner is a better source on its allowance than any inference."""
        async with AsyncSessionLocal() as session:
            for index in range(4):
                await self._spent(session, ago_hours=4 - index)
            derived = await quota_service.refusal_horizon(session, self.provider_id, "*")
            stated = await quota_service.refusal_horizon(session, self.provider_id, "*", retry_after_seconds=120)
            brief = await quota_service.refusal_horizon(session, self.provider_id, "*", retry_after_seconds=3)
            distant = await quota_service.refusal_horizon(session, self.provider_id, "*", retry_after_seconds=999999)
        self.assertEqual(derived["ttl_seconds"], 57600, "Four looks with no reset stated is what the escalation is for.")
        self.assertEqual((stated["ttl_seconds"], stated["basis"]), (120, "provider_stated_retry_after"))
        self.assertEqual(stated["reconfirmations"], 0, "Nothing was inferred, so nothing was reconfirmed.")
        self.assertEqual(brief["ttl_seconds"], 10, "The ledger holds nothing shorter, and a stated three seconds is not an hour.")
        self.assertEqual(distant["ttl_seconds"], SPENT_ALLOWANCE_MAX_TTL_SECONDS, "The ledger holds nothing longer than a day.")

    async def test_a_served_request_ends_the_escalation_without_erasing_what_earned_it(self):
        """Serving a request is the one measurement that contradicts a spent allowance."""
        async with AsyncSessionLocal() as session:
            for index in range(3):
                await self._spent(session, ago_hours=3 - index)
            escalated = await quota_service.refusal_horizon(session, self.provider_id, "*")
            served = await quota_service.note_served(session, self.provider_id, model="horizon-provider/coder")
            recovered = await quota_service.refusal_horizon(session, self.provider_id, "*")
            looks = (await session.execute(select(QuotaObservationRecord).where(
                QuotaObservationRecord.provider_instance_id == self.provider_id,
            ))).scalars().all()
        self.assertEqual(escalated["ttl_seconds"], 28800)
        self.assertIsNone(served.remaining_value, "A served request says the allowance was not spent, not how much is left.")
        self.assertEqual(json.loads(served.evidence)["reason"], "provider_served_request")
        self.assertEqual(json.loads(served.evidence)["model"], "horizon-provider/coder", "The observation names the run's own route.")
        self.assertEqual((recovered["ttl_seconds"], recovered["reconfirmations"]), (SPENT_ALLOWANCE_BASE_TTL_SECONDS, 0))
        self.assertEqual(len([look for look in looks if look.remaining_value == 0]), 3, "Recovery corrects the horizon; it does not erase the looks that earned it.")

    async def test_a_served_request_is_recorded_only_where_it_contradicts_the_ledger(self):
        """One row per successful attempt would bury the looks that mean something."""
        async with AsyncSessionLocal() as session:
            unprompted = await quota_service.note_served(session, self.provider_id)
            await self._spent(session, ago_hours=1)
            correcting = await quota_service.note_served(session, self.provider_id)
            repeated = await quota_service.note_served(session, self.provider_id)
        self.assertIsNone(unprompted, "A provider the ledger says nothing about has nothing to correct.")
        self.assertIsNotNone(correcting, "The newest look says spent, and this request was served.")
        self.assertIsNone(repeated, "The correction is already on record.")

    async def test_one_models_spent_allowance_is_no_look_at_another_models(self):
        """A per-model allowance is the narrowest thing a provider can refuse."""
        async with AsyncSessionLocal() as session:
            for index in range(3):
                await self._spent(session, scope="coder-a", ago_hours=3 - index)
            own = await quota_service.refusal_horizon(session, self.provider_id, "coder-a")
            sibling = await quota_service.refusal_horizon(session, self.provider_id, "coder-b")
        self.assertEqual(own["ttl_seconds"], 28800)
        self.assertEqual((sibling["ttl_seconds"], sibling["reconfirmations"]), (SPENT_ALLOWANCE_BASE_TTL_SECONDS, 0))

    async def test_an_account_the_provider_keeps_refusing_lengthens_its_models_holds_too(self):
        """An account that refuses everything refuses this model, so its looks count."""
        async with AsyncSessionLocal() as session:
            for index in range(2):
                await self._spent(session, ago_hours=2 - index)
            model_scope = await quota_service.refusal_horizon(session, self.provider_id, "coder-a")
        self.assertEqual((model_scope["ttl_seconds"], model_scope["reconfirmations"]), (14400, 2))


if __name__ == "__main__":
    unittest.main()
