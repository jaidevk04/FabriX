"""Allowlisted failure descriptions; raw SDK errors never enter platform records."""

from enum import StrEnum


class FailureCode(StrEnum):
    AUTHENTICATION = "authentication"
    MODEL = "model_unavailable"
    QUOTA = "quota"
    ACCESS = "access_denied"
    NETWORK = "network"
    UNAVAILABLE = "service_unavailable"
    CONFIGURATION = "configuration"
    OUTPUT = "invalid_output"
    TOOL_FORMAT = "invalid_tool_call"
    BUDGET = "tool_budget"
    TIMEOUT = "timeout"
    RUNTIME = "runtime"


MESSAGES = {
    FailureCode.AUTHENTICATION: "Provider rejected the credentials. Check the API key in .env.",
    FailureCode.MODEL: (
        "Configured model is unavailable to this account. Update GEMINI_MODEL in .env."
    ),
    FailureCode.QUOTA: "Provider quota or rate limit exceeded. Check project quota and billing.",
    FailureCode.ACCESS: "Provider denied access. Check project permissions and model access.",
    FailureCode.NETWORK: "Provider connection failed. Check network access and try again.",
    FailureCode.UNAVAILABLE: "Provider is temporarily unavailable. Try again later.",
    FailureCode.CONFIGURATION: "Harness SDK configuration failed. Check adapter compatibility.",
    FailureCode.OUTPUT: "Harness returned an invalid proposal. No control action was applied.",
    FailureCode.TOOL_FORMAT: (
        "Model returned a malformed or unknown tool call. No proposal was produced. "
        "Check model compatibility with Antigravity."
    ),
    FailureCode.BUDGET: "Investigation exceeded its tool budget. No control action was applied.",
    FailureCode.TIMEOUT: "Core run exceeded its time ceiling. No control action was applied.",
    FailureCode.RUNTIME: "Harness worker failed. Check its SDK and runtime configuration.",
}


class HarnessFailure(RuntimeError):
    def __init__(self, code: str | FailureCode):
        try:
            self.code = FailureCode(code)
        except ValueError:
            self.code = FailureCode.RUNTIME
        super().__init__(MESSAGES[self.code])


def failure_code(error: Exception) -> FailureCode:
    if isinstance(error, HarnessFailure):
        return error.code
    message = str(error).lower()
    if any(
        word in message
        for word in ("api_key_invalid", "api key not valid", "401", "unauthenticated")
    ):
        return FailureCode.AUTHENTICATION
    if ("404" in message or "not_found" in message) and "model" in message:
        return FailureCode.MODEL
    if "429" in message or "resource_exhausted" in message or "quota" in message:
        return FailureCode.QUOTA
    if "403" in message or "permission_denied" in message:
        return FailureCode.ACCESS
    if "503" in message or "high demand" in message:
        return FailureCode.UNAVAILABLE
    if "cannot pickle" in message or "gemini_model is required" in message:
        return FailureCode.CONFIGURATION
    if isinstance(error, (ConnectionError, TimeoutError)):
        return FailureCode.NETWORK
    if type(error).__name__ == "ValidationError":
        return FailureCode.OUTPUT
    if any(
        word in message
        for word in ("improper format stop reason", "invalid tool call", "unknown_tool")
    ):
        return FailureCode.TOOL_FORMAT
    if "model output error" in message:
        return FailureCode.OUTPUT
    if isinstance(error, PermissionError) and "budget" in message:
        return FailureCode.BUDGET
    return FailureCode.RUNTIME
