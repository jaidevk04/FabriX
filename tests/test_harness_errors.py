import pytest

from cognition.harnesses.errors import FailureCode, HarnessFailure, failure_code
from cognition.harnesses.reference import ReferenceHarness


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("Error 404: model unavailable; secret-api-key", FailureCode.MODEL),
        ("API_KEY_INVALID; secret-api-key", FailureCode.AUTHENTICATION),
        ("HTTP 429 RESOURCE_EXHAUSTED; secret-api-key", FailureCode.QUOTA),
        ("HTTP 403 PERMISSION_DENIED; secret-api-key", FailureCode.ACCESS),
        ("cannot pickle '_thread.RLock' object", FailureCode.CONFIGURATION),
        ("HTTP 503 high demand; secret-api-key", FailureCode.UNAVAILABLE),
        ("model output error: improper format stop reason", FailureCode.TOOL_FORMAT),
    ],
)
def test_provider_errors_become_allowlisted_codes(message, expected):
    assert failure_code(RuntimeError(message)) == expected
    assert "secret-api-key" not in str(HarnessFailure(expected))


def test_unknown_worker_error_code_is_not_reflected():
    assert HarnessFailure("secret-api-key").code == FailureCode.RUNTIME
    assert "secret-api-key" not in str(HarnessFailure("secret-api-key"))


async def test_safe_provider_reason_is_persisted_without_raw_error(platform):
    class Unavailable(ReferenceHarness):
        async def propose(self, request, tools):
            error = RuntimeError("HTTP 404 model unavailable, key=secret-api-key")
            raise HarnessFailure(failure_code(error))

    before = platform.store.plant("kiln")
    incident = await platform.resolve("kiln", Unavailable())
    assert incident.status == "failed"
    assert "GEMINI_MODEL" in incident.reason
    assert "secret-api-key" not in incident.model_dump_json()
    assert "secret-api-key" not in str(platform.store.events(incident.id))
    assert platform.store.plant("kiln") == before
