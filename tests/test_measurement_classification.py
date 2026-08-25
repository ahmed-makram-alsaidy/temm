"""Whether an attempt measured the route, per failure mode the CLI actually produces.

Every signature here was captured from the real `opencode --format json` stream on
this machine, because the defect these tests pin down was not a logic slip: TEMM
read a non-zero exit as the route's answer, and the CLI exits non-zero for at least
four reasons the model was never present for. Production evidence 2026-08-20,
`run-133922d95108` / `attempt-2204ab86ef54` - exit 1 after 1931ms, empty diff, no
stderr, one stdout event, provider declared in a config the isolated workspace could
not see - was recorded as proof the route could not code, read files, or write them.

The classification is therefore inverted: a capability conclusion requires positive
proof that the model executed, never merely the absence of a reason it did not.
"""

import json
import os
import unittest
import unittest.mock

from core.ai_fleet.services.measurement import (
    EXECUTOR_LOCAL_FAILURE,
    MAX_AVAILABILITY_HOLD_SECONDS,
    MAX_ERROR_EVENTS,
    MAX_ERROR_MESSAGE,
    MAX_STDOUT_TAIL,
    MODEL_EXECUTED,
    NO_EXECUTION_SIGNAL,
    NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS,
    PERMANENCE_HOLD_SECONDS,
    PERMANENCE_PERMANENT,
    PERMANENCE_ROUTE_UNSERVED,
    PERMANENCE_TRANSIENT,
    PROVIDER_REFUSAL,
    PROVIDER_UNAVAILABLE,
    classify_measurement,
    non_measurement_hold,
    stdout_tail,
)
from core.ai_fleet.services.quota import detect_provider_refusal


def chunks(*lines: str):
    """Wrap CLI event lines the way the run-output pipeline hands them over."""
    return [{"stream": "stdout", "content": line + "\n"} for line in lines]


def error_event(name: str, message: str, status: int | None = None) -> str:
    """One `error` event in the shape the CLI emits, built rather than escaped.

    The provider bodies these carry are quoted JSON documents captured verbatim from
    production, and hand-escaping them into a literal is how a fixture stops matching
    the thing it was captured from.
    """
    data = {"message": message}
    if status is not None:
        data["statusCode"] = status
    return json.dumps({"type": "error", "error": {"name": name, "data": data}})


# The captured signature of a provider the executor could not resolve. Identical -
# to the byte, apart from `ref` - to a provider name that does not exist and to a
# model name that does not exist, which is why no text-matching rule can separate
# the three and why none of them may be read as an answer about the route.
UNKNOWN_ERROR_EVENT = (
    '{"type":"error","error":{"name":"UnknownError","data":'
    '{"message":"Unexpected server error. Check server logs for details.","ref":"err_2204ab86ef54"}}}'
)
# Reached the provider: the CLI emitted a model step before failing. Captured from
# `run-1a23ad2eff63`, where the provider answered with a body the client could not
# use. Measured directly afterwards against that same endpoint: the credential is
# valid and the model is real - a non-streaming completion returns Claude Opus 4.8
# output in 2.4s - but the streamed response the CLI actually consumes carries a
# literal `data: null` SSE event mid-stream, which the strict chunk schema in
# `@ai-sdk/openai-compatible` rejects. Hence this exact message, and hence why it is
# no measurement of the model: the model produced text, and the transport between
# the two discarded it.
STEP_START_EVENT = '{"type":"step_start"}'
TYPE_VALIDATION_EVENT = (
    '{"type":"error","error":{"name":"UnknownError","data":'
    '{"message":"Type validation failed: Value: null."}}}'
)
# The event types a model that ran actually produces, in the order three successful
# production attempts produced them.
EXECUTION_EVENTS = (
    STEP_START_EVENT,
    '{"type":"tool_use","part":{"tool":"write","input":{"filePath":"temm-write-proof.txt"}}}',
    '{"type":"tool","part":{"tool":"write","state":{"status":"completed"}}}',
    '{"type":"file","path":"temm-write-proof.txt"}',
    '{"type":"text","part":{"text":"Created temm-write-proof.txt as instructed."}}',
    '{"type":"step_finish","part":{"tokens":{"input":1204,"output":337},"cost":0.0041}}',
)


class LocalResolutionFailureTests(unittest.TestCase):
    """Nothing left this machine, so nothing about the route was measured."""

    def test_unresolvable_provider_is_non_measurement_not_incapacity(self):
        measurement = classify_measurement(chunks(UNKNOWN_ERROR_EVENT), outcome="completed")
        self.assertEqual(measurement["classification"], EXECUTOR_LOCAL_FAILURE)
        self.assertEqual(measurement["reason"], "local_resolution_failed")
        self.assertFalse(measurement["measured"])
        self.assertFalse(measurement["capability_conclusion_admissible"], "This is the verdict production wrote. It must not be available.")
        self.assertFalse(measurement["resolution_reached"])
        self.assertEqual(measurement["execution_proof"], [])

    def test_unknown_provider_and_unknown_model_classify_with_the_unresolvable_one(self):
        """All three produce the same event, so all three must reach the same verdict.

        Not a convenience: a rule that separated them would be separating them on
        something the stream does not contain.
        """
        for label, ref in (("unknown provider", "err_aaaa"), ("unknown model", "err_bbbb")):
            with self.subTest(label):
                event = UNKNOWN_ERROR_EVENT.replace("err_2204ab86ef54", ref)
                measurement = classify_measurement(chunks(event), outcome="completed")
                self.assertEqual(measurement["classification"], EXECUTOR_LOCAL_FAILURE)
                self.assertFalse(measurement["capability_conclusion_admissible"])
                self.assertEqual(measurement["error_events"][0]["ref"], ref, "The diagnostic that distinguishes the attempt has to be kept.")

    def test_launch_failure_outranks_an_empty_stream(self):
        measurement = classify_measurement([], outcome="launch_failed")
        self.assertEqual(measurement["classification"], EXECUTOR_LOCAL_FAILURE)
        self.assertEqual(measurement["reason"], "executor_launch_failed")
        self.assertFalse(measurement["measured"])

    def test_a_bound_reached_before_any_model_step_measured_nothing(self):
        """A timeout is only the provider's silence once a step has begun."""
        measurement = classify_measurement([], outcome="timed_out")
        self.assertEqual(measurement["classification"], EXECUTOR_LOCAL_FAILURE)
        self.assertEqual(measurement["reason"], "timed_out_before_execution")
        after_resolution = classify_measurement(chunks(STEP_START_EVENT), outcome="timed_out")
        self.assertEqual(after_resolution["classification"], PROVIDER_UNAVAILABLE)
        self.assertEqual(after_resolution["reason"], "no_provider_response_before_bound")
        self.assertFalse(after_resolution["measured"], "Neither side of that line is a measurement.")

    def test_a_silent_exit_names_itself_and_still_concludes_nothing(self):
        measurement = classify_measurement([], outcome="completed")
        self.assertEqual(measurement["classification"], NO_EXECUTION_SIGNAL)
        self.assertFalse(measurement["capability_conclusion_admissible"])


class ProviderReachedButUnusableTests(unittest.TestCase):
    """The request arrived and the answer was not usable. Still not the model's answer."""

    def test_a_step_that_began_moves_the_failure_to_the_provider(self):
        measurement = classify_measurement(chunks(STEP_START_EVENT, TYPE_VALIDATION_EVENT), outcome="completed")
        self.assertEqual(measurement["classification"], PROVIDER_UNAVAILABLE)
        self.assertEqual(measurement["reason"], "provider_response_unusable")
        self.assertTrue(measurement["resolution_reached"])
        self.assertFalse(measurement["measured"])
        self.assertIn("Type validation failed", measurement["error_events"][0]["message"])

    def test_an_unauthenticated_provider_is_unavailable_not_incapable(self):
        """A rejected client is not a statement about the model.

        401 is not one of the statuses a provider refuses a well-formed request
        with, and the request never reached a model to be a verdict on one.
        """
        event = (
            '{"type":"error","error":{"name":"APICallError","data":{"statusCode":401,'
            '"message":"UNAUTHENTICATED","responseBody":"{\\"type\\":\\"unauthorized_client_error\\"}"}}}'
        )
        measurement = classify_measurement(chunks(event), outcome="completed")
        self.assertEqual(measurement["classification"], PROVIDER_UNAVAILABLE)
        self.assertEqual(measurement["reason"], "provider_http_401")
        self.assertFalse(measurement["capability_conclusion_admissible"])
        self.assertEqual(measurement["error_events"][0]["status_code"], 401)


class NonMeasurementHoldDurationTests(unittest.TestCase):
    """How long a non-measured route is withheld, on the provider's own authority.

    Every fixture below was captured on 2026-08-21 from one bounded NEXA dispatch
    loop against NVIDIA's discovered catalog. Dispatches 4 through 14 each spent their
    single probe on a different nvidia route and each was answered `410 Gone` with an
    end-of-life date or `404 Not Found`; each was then held for 600 seconds, which is
    the interval sized to a provider that *might* answer in ten minutes. A retired
    model does not, so some ninety dead routes re-entered the probe pool every ten
    minutes indefinitely, ahead of every provider whose credentials TEMM had never
    tried at all.
    """

    # `nvidia/abacusai/dracarys-llama-3.1-70b-instruct`, attempt-87d241d43de8.
    GONE_EVENT = error_event(
        "APIError",
        'Gone: {"type":"about:blank","title":"Gone","status":410,"detail":"The model \'abacusai/dracarys-llama-3.1-70b-instruct\' has reached its end of life on 2026-07-27 and is no longer available."}',
        410,
    )
    # `nvidia/baai/bge-m3`, attempt-ed0401e7b50f - an embedding model behind a chat
    # endpoint. The provider serves the route no answer and says nothing further.
    NOT_FOUND_EVENT = error_event("APIError", "Not Found: 404 page not found", 404)
    # `nvidia/google/gemma-3-12b-it`, attempt-2a84440ec3cd - the deployment this
    # account does not have, which is a fact about the account and the route together.
    ACCOUNT_NOT_FOUND_EVENT = error_event(
        "APIError",
        'Not Found: {"status":404,"title":"Not Found","detail":"Function \'ee47df99-c92b-4dc9-b3a7-f3fb0f087b73\': Not found for account \'nYDbNYQHdCPBO\'"}',
        404,
    )
    # `azure-router/model-router`, attempt-25c4b84fc64e.
    UNAUTHORIZED_EVENT = error_event(
        "APIError",
        "Access denied due to invalid subscription key or wrong API endpoint.",
        401,
    )
    # `aliyun/qwen3-livetranslate-flash` - the request TEMM sent was wrong for this
    # model, which is TEMM's to fix and says nothing about whether the route exists.
    BAD_REQUEST_EVENT = error_event(
        "APIError",
        "invalid_parameter_error: The parameter max_tokens is not supported for this model.",
        400,
    )

    def hold(self, *events, outcome="completed", **kwargs):
        """The hold for a stream that reached its provider and then failed."""
        return non_measurement_hold(classify_measurement(chunks(STEP_START_EVENT, *events), outcome=outcome, **kwargs))

    def test_a_route_the_provider_says_is_gone_is_not_held_as_a_ten_minute_outage(self):
        hold = self.hold(self.GONE_EVENT)
        self.assertEqual(hold["permanence"], PERMANENCE_PERMANENT)
        self.assertEqual(hold["permanence_basis"], "http_410_gone")
        self.assertEqual(hold["ttl_seconds"], MAX_AVAILABILITY_HOLD_SECONDS)
        self.assertGreater(
            hold["ttl_seconds"], NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS[PROVIDER_UNAVAILABLE],
            "Held for the transient interval, a retired catalog returns to the probe pool every ten minutes forever.",
        )
        self.assertEqual(hold["default_ttl_seconds"], NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS[PROVIDER_UNAVAILABLE])

    def test_an_end_of_life_the_provider_states_without_a_status_is_still_its_word(self):
        """The sentence is the verdict; the status code is one way of carrying it."""
        hold = self.hold(error_event("APIError", "This model has been retired and is no longer supported."))
        self.assertEqual(hold["permanence"], PERMANENCE_PERMANENT)
        self.assertEqual(hold["permanence_basis"], "provider_stated_end_of_life")
        self.assertEqual(hold["ttl_seconds"], MAX_AVAILABILITY_HOLD_SECONDS)

    def test_a_route_the_provider_does_not_serve_is_held_long_but_not_as_gone(self):
        """`404` is not a retirement announcement, and it does not clear on its own either."""
        for label, event in (("no route at all", self.NOT_FOUND_EVENT), ("not for this account", self.ACCOUNT_NOT_FOUND_EVENT)):
            with self.subTest(label):
                hold = self.hold(event)
                self.assertEqual(hold["permanence"], PERMANENCE_ROUTE_UNSERVED)
                self.assertEqual(hold["permanence_basis"], "http_404_not_found")
                self.assertEqual(hold["ttl_seconds"], PERMANENCE_HOLD_SECONDS[PERMANENCE_ROUTE_UNSERVED])
                self.assertLess(hold["ttl_seconds"], MAX_AVAILABILITY_HOLD_SECONDS, "The provider did not say the route is gone.")

    def test_a_key_an_outage_or_a_bad_request_keeps_the_short_self_healing_hold(self):
        """None of these is about the route, and all of them can be true for ten minutes."""
        cases = (
            ("rejected credential", self.UNAUTHORIZED_EVENT, "http_401_is_not_about_the_route"),
            ("TEMM's own request", self.BAD_REQUEST_EVENT, "http_400_is_not_about_the_route"),
            ("provider outage", error_event("APIError", "Service Unavailable", 503), "http_503_is_not_about_the_route"),
            ("body TEMM could not read", TYPE_VALIDATION_EVENT, "provider_stated_no_permanence"),
        )
        for label, event, basis in cases:
            with self.subTest(label):
                hold = self.hold(event)
                self.assertEqual(hold["permanence"], PERMANENCE_TRANSIENT)
                self.assertEqual(hold["permanence_basis"], basis)
                self.assertEqual(hold["ttl_seconds"], NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS[PROVIDER_UNAVAILABLE])

    def test_a_status_about_the_account_outranks_whatever_its_body_says(self):
        """An outage page that quotes a retirement notice must not retire a live route."""
        hold = self.hold(error_event("APIError", "Service Unavailable: upstream says the model is no longer available", 503))
        self.assertEqual(hold["permanence"], PERMANENCE_TRANSIENT)
        self.assertEqual(hold["ttl_seconds"], NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS[PROVIDER_UNAVAILABLE])

    def test_a_failure_below_the_provider_cannot_retire_the_route_it_never_reached(self):
        """No provider answered, so nothing in the transcript is a provider's word.

        The executor's own errors are not quoting anyone, and the local hold is already
        the longer of the two - a local misconfiguration will not fix itself between
        two tasks, but it is fixed by an operator in an afternoon, not a day.
        """
        local = non_measurement_hold(classify_measurement(
            chunks(error_event("UnknownError", "The model has reached its end of life.")), outcome="completed",
        ))
        self.assertEqual(local["permanence"], PERMANENCE_TRANSIENT)
        self.assertEqual(local["permanence_basis"], "classification_default")
        self.assertEqual(local["ttl_seconds"], NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS[EXECUTOR_LOCAL_FAILURE])

    def test_a_measured_route_and_a_refused_one_carry_no_hold_at_all(self):
        """One has an answer to be judged on; the other is carried by the quota ledger."""
        measured = classify_measurement(chunks(*EXECUTION_EVENTS), outcome="completed")
        self.assertEqual(measured["classification"], MODEL_EXECUTED)
        self.assertIsNone(non_measurement_hold(measured)["ttl_seconds"])
        stream = chunks(STEP_START_EVENT, ProviderRefusalTests.EXHAUSTED_EVENT)
        refused = classify_measurement(stream, outcome="completed", provider_refusal=detect_provider_refusal(stream))
        self.assertEqual(refused["classification"], PROVIDER_REFUSAL)
        self.assertIsNone(non_measurement_hold(refused)["ttl_seconds"], "A refusal is already held by the allowance ledger.")

    def test_every_hold_is_one_the_registry_will_accept_and_never_shortens_the_floor(self):
        """`record_observation` rejects a TTL outside 10..86400, and a permanence that
        shortened a hold would be permanence making a route more available."""
        self.assertEqual(MAX_AVAILABILITY_HOLD_SECONDS, 86400)
        floor = max(NON_MEASUREMENT_UNAVAILABILITY_TTL_SECONDS.values())
        for permanence, ttl in PERMANENCE_HOLD_SECONDS.items():
            with self.subTest(permanence):
                self.assertGreaterEqual(ttl, floor)
                self.assertLessEqual(ttl, MAX_AVAILABILITY_HOLD_SECONDS)


class ProviderRefusalTests(unittest.TestCase):
    """A provider that would not serve the request exercised nothing."""

    FORBIDDEN_EVENT = (
        '{"type":"error","error":{"name":"ProviderAuthError","data":{"statusCode":403,'
        '"message":"Access to this model is not allowed for your account.",'
        '"responseBody":"{\\"error\\":{\\"code\\":\\"model_not_allowed\\"}}"}}}'
    )
    EXHAUSTED_EVENT = (
        '{"type":"error","error":{"name":"ProviderAuthError","data":{"statusCode":429,'
        '"message":"You exceeded your current quota.",'
        '"responseBody":"{\\"error\\":{\\"code\\":\\"insufficient_quota\\"}}",'
        '"responseHeaders":{"retry-after":"60"}}}}'
    )

    def test_a_forbidden_model_is_refusal_not_incapacity(self):
        stream = chunks(STEP_START_EVENT, self.FORBIDDEN_EVENT)
        refusal = detect_provider_refusal(stream)
        measurement = classify_measurement(stream, outcome="completed", provider_refusal=refusal)
        self.assertEqual(refusal["status_code"], 403)
        self.assertFalse(refusal["allowance_exhausted"], "A forbidden model is not a spent allowance.")
        self.assertEqual(measurement["classification"], PROVIDER_REFUSAL)
        self.assertEqual(measurement["reason"], "provider_refused")
        self.assertFalse(measurement["capability_conclusion_admissible"])

    def test_quota_exhaustion_is_named_as_such_and_concludes_nothing(self):
        """Production evidence 2026-08-19: `aliyun/qwen3-coder-next`, HTTP 403
        `insufficient_quota` in 4.8s, recorded as unable to code, read, or write."""
        stream = chunks(STEP_START_EVENT, self.EXHAUSTED_EVENT)
        refusal = detect_provider_refusal(stream)
        measurement = classify_measurement(stream, outcome="completed", provider_refusal=refusal)
        self.assertTrue(refusal["allowance_exhausted"])
        self.assertEqual(refusal["retry_after_seconds"], 60)
        self.assertEqual(measurement["classification"], PROVIDER_REFUSAL)
        self.assertEqual(measurement["reason"], "provider_allowance_exhausted")
        self.assertFalse(measurement["measured"])

    def test_a_refusal_after_real_work_still_refuses_the_measured_request(self):
        """The provider's own account of the request outranks TEMM's reading of it.

        A stream can hold a completed tool call and then a refusal of the next
        request. What the attempt was judged on is the request that was refused.
        """
        stream = chunks(*EXECUTION_EVENTS, self.EXHAUSTED_EVENT)
        refusal = detect_provider_refusal(stream)
        measurement = classify_measurement(stream, outcome="completed", provider_refusal=refusal)
        self.assertEqual(measurement["classification"], PROVIDER_REFUSAL)
        self.assertFalse(measurement["capability_conclusion_admissible"])


class GenuineModelExecutionTests(unittest.TestCase):
    """The one case where the route may be judged: the model actually answered."""

    def test_a_model_that_ran_and_failed_acceptance_is_a_real_negative(self):
        measurement = classify_measurement(
            chunks(STEP_START_EVENT, '{"type":"text","part":{"text":"I could not complete this."}}',
                   '{"type":"step_finish","part":{"tokens":{"input":900,"output":40}}}'),
            outcome="completed", effect_observed=False, acceptance_satisfied=False,
        )
        self.assertEqual(measurement["classification"], MODEL_EXECUTED)
        self.assertEqual(measurement["reason"], "model_produced_work")
        self.assertTrue(measurement["measured"])
        self.assertTrue(measurement["capability_conclusion_admissible"], "A model that answered and failed the contract is measurable.")
        self.assertEqual(measurement["tokens_reported"], 940)
        self.assertIn("text", measurement["execution_proof"])

    def test_a_nonzero_exit_after_real_work_remains_a_measurement(self):
        """The exit code is not the discriminator - the work is."""
        measurement = classify_measurement(chunks(*EXECUTION_EVENTS), outcome="failed", acceptance_satisfied=False)
        self.assertEqual(measurement["classification"], MODEL_EXECUTED)
        self.assertTrue(measurement["capability_conclusion_admissible"])

    def test_a_capability_success_is_measured_and_proven(self):
        measurement = classify_measurement(
            chunks(*EXECUTION_EVENTS), outcome="completed", effect_observed=True, acceptance_satisfied=True,
        )
        self.assertEqual(measurement["classification"], MODEL_EXECUTED)
        self.assertTrue(measurement["measured"])
        self.assertEqual(measurement["event_counts"]["tool_use"], 1)
        self.assertEqual(measurement["tokens_reported"], 1541)
        for proof in ("tool_use", "tool", "file", "text", "step_finish", "token_usage", "workspace_diff", "acceptance_satisfied"):
            self.assertIn(proof, measurement["execution_proof"])

    def test_a_change_on_disk_alone_proves_the_model_ran(self):
        """A diff cannot appear without something having executed, whatever the stream says."""
        measurement = classify_measurement(chunks(UNKNOWN_ERROR_EVENT), outcome="failed", effect_observed=True)
        self.assertEqual(measurement["classification"], MODEL_EXECUTED)
        self.assertEqual(measurement["execution_proof"], ["workspace_diff"])

    def test_a_model_step_beginning_is_never_by_itself_proof(self):
        """`step_start` precedes the provider's answer, so it cannot stand for one."""
        measurement = classify_measurement(chunks(STEP_START_EVENT), outcome="completed")
        self.assertTrue(measurement["resolution_reached"])
        self.assertFalse(measurement["measured"])
        self.assertEqual(measurement["execution_proof"], [])


class DiagnosticBoundsTests(unittest.TestCase):
    """Enough of the stream to classify the failure, and no secret, at any size."""

    def test_persisted_diagnostics_are_redacted(self):
        secret = "sk-probe-secret-value-1234567890"
        event = (
            '{"type":"error","error":{"name":"APICallError","data":{"statusCode":401,'
            f'"message":"Rejected credential {secret} for this account."}}}}}}'
        )
        with unittest.mock.patch.dict(os.environ, {"AI_FLEET_TEST_PROBE_API_KEY": secret}, clear=False):
            measurement = classify_measurement(chunks(event), outcome="completed")
            tail = stdout_tail(chunks(event))
        self.assertNotIn(secret, measurement["error_events"][0]["message"])
        self.assertIn("[REDACTED]", measurement["error_events"][0]["message"])
        self.assertNotIn(secret, tail)

    def test_the_stdout_tail_is_kept_and_bounded(self):
        """The autopsy of `attempt-2204ab86ef54` kept a stderr tail and no stdout tail,
        and the CLI writes its errors to stdout - so the one event that explained the
        attempt was the one thing the receipt did not have."""
        stream = chunks("x" * 50000, UNKNOWN_ERROR_EVENT)
        tail = stdout_tail(stream)
        self.assertLessEqual(len(tail), MAX_STDOUT_TAIL)
        self.assertIn("err_2204ab86ef54", tail, "The end of stdout is where the explanation is.")

    def test_error_events_and_messages_are_bounded(self):
        long_message = "z" * 5000
        event = (
            '{"type":"error","error":{"name":"UnknownError","data":'
            f'{{"message":"{long_message}"}}}}}}'
        )
        measurement = classify_measurement(chunks(*([event] * 40)), outcome="completed")
        self.assertEqual(len(measurement["error_events"]), MAX_ERROR_EVENTS)
        self.assertLessEqual(len(measurement["error_events"][0]["message"]), MAX_ERROR_MESSAGE)
        self.assertEqual(measurement["event_counts"]["error"], 40, "Counting every event is cheap; keeping every event is not.")

    def test_file_content_echoed_on_stdout_is_not_mistaken_for_an_event(self):
        """A task whose own subject is error handling would otherwise classify itself."""
        echoed = '  {"type":"error","error":{"name":"UnknownError","data":{"message":"example"}}}'
        measurement = classify_measurement(
            chunks(json.dumps({"type": "text", "part": {"text": echoed}})), outcome="completed",
        )
        self.assertEqual(measurement["classification"], MODEL_EXECUTED)
        self.assertEqual(measurement["error_events"], [], "Only a line that is itself an event counts as one.")


class TokenCensusTests(unittest.TestCase):
    """What the attempt spent, counted from the executor's own per-step report.

    Both defects here were found in the same production attempt.
    `attempt-bb0eb9e3118f` ran 18 steps whose reported totals sum to 481355 tokens.
    TEMM recorded 73302: the maximum of its events, and that maximum was itself
    double-counted, because summing a step's `tokens` dict adds the executor's stated
    `total` to the components it is the total of.
    """

    # Captured verbatim from `opencode --format json` on this machine. The census is
    # self-consistent: 762 + 116 + 0 + 36608 + 0 == 37486.
    FIRST_STEP = (
        '{"type":"step_finish","part":{"id":"prt-first","tokens":'
        '{"total":37486,"input":762,"output":116,"reasoning":0,"cache":{"write":0,"read":36608}},"cost":0}}'
    )
    SECOND_STEP = (
        '{"type":"step_finish","part":{"id":"prt-second","tokens":'
        '{"total":1216,"input":900,"output":300,"reasoning":16,"cache":{"write":0,"read":0}},"cost":0}}'
    )

    def census(self, *lines: str) -> dict:
        return classify_measurement(chunks(*lines), outcome="completed")

    def test_a_step_is_not_added_to_its_own_total(self):
        measurement = self.census(STEP_START_EVENT, self.FIRST_STEP)
        census = measurement["token_census"]
        self.assertEqual(measurement["tokens_reported"], 37486, "The executor stated 37486. Anything near 74972 is the total counted twice.")
        self.assertEqual(census["input"], 762)
        self.assertEqual(census["output"], 116)
        self.assertEqual(census["cache_read"], 36608)
        self.assertEqual(census["cache_write"], 0)
        self.assertEqual(census["reporting_events"], 1)

    def test_the_attempt_is_the_sum_of_its_steps_and_not_the_largest_of_them(self):
        measurement = self.census(STEP_START_EVENT, self.FIRST_STEP, self.SECOND_STEP)
        census = measurement["token_census"]
        self.assertEqual(measurement["tokens_reported"], 38702)
        self.assertNotEqual(measurement["tokens_reported"], 37486, "Reading the largest step is how a 481355-token attempt was exported as 73302.")
        self.assertEqual(census["input"], 1662)
        self.assertEqual(census["output"], 416)
        self.assertEqual(census["reasoning"], 16)
        self.assertEqual(census["reporting_events"], 2)

    def test_a_part_re_emitted_as_it_settles_is_billed_once(self):
        """The CLI can re-emit a part. Counting per event would bill the step twice."""
        measurement = self.census(self.FIRST_STEP, self.FIRST_STEP, self.SECOND_STEP)
        self.assertEqual(measurement["tokens_reported"], 38702)
        self.assertEqual(measurement["token_census"]["reporting_events"], 2)

    def test_the_executor_stated_total_outranks_the_parts_it_breaks_out(self):
        """It is the authority on what it was billed for, including dimensions it
        does not itemise."""
        event = '{"type":"step_finish","part":{"tokens":{"total":5000,"input":900,"output":100}}}'
        measurement = self.census(event)
        self.assertEqual(measurement["tokens_reported"], 5000)
        self.assertEqual(measurement["token_census"]["input"], 900)

    def test_a_stream_that_reported_nothing_is_unknown_usage_not_zero_usage(self):
        """Zero reported tokens and no report at all are different facts, and the
        difference is the provenance the run row is allowed to claim."""
        measurement = self.census(STEP_START_EVENT, '{"type":"text","part":{"text":"done"}}')
        self.assertEqual(measurement["token_census"]["reporting_events"], 0)
        self.assertEqual(measurement["tokens_reported"], 0)
        self.assertEqual(measurement["token_census"]["total"], 0)


if __name__ == "__main__":
    unittest.main()
