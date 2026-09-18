"""Explicit opt-in destinations; no process-wide automatic OTel configuration."""

from typing import Literal, Self
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


def endpoint(value: str) -> str:
    url = urlsplit(value)
    if (
        not url.hostname
        or url.username
        or url.password
        or url.query
        or url.fragment
        or not (
            url.scheme == "https"
            or (
                url.scheme == "http"
                and url.hostname in {"localhost", "127.0.0.1", "::1", "otel-collector"}
            )
        )
    ):
        raise ValueError("Telemetry requires HTTPS or an explicitly local collector")
    return value.rstrip("/")


class TelemetryConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)
    mode: Literal["off", "console", "otlp"] = "off"
    service: str = Field(pattern=r"^kavrigo-[a-z-]{1,40}$")
    environment: Literal["local", "dev", "staging", "paper-prod"] = "local"
    collector: str | None = None
    langfuse_endpoint: str | None = None
    langfuse_public_key: SecretStr | None = None
    langfuse_secret_key: SecretStr | None = None

    @model_validator(mode="after")
    def valid(self) -> Self:
        if self.mode == "otlp" and not self.collector:
            raise ValueError("OTLP mode requires an explicit collector")
        if self.collector:
            endpoint(self.collector)
        configured = (self.langfuse_endpoint, self.langfuse_public_key, self.langfuse_secret_key)
        if any(x is not None for x in configured):
            if self.mode == "off" or not all(configured):
                raise ValueError("Langfuse requires enabled telemetry, endpoint and both keys")
            assert self.langfuse_endpoint is not None
            endpoint(self.langfuse_endpoint)
            if not self.langfuse_endpoint.endswith("/api/public/otel/v1/traces"):
                raise ValueError("Use Langfuse's explicit OTLP trace endpoint")
        return self
