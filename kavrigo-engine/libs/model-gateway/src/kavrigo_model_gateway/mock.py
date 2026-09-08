"""Deterministic scripted provider. No key, network, system state or market prediction.

Its token accounting is a MOCK convention: UTF-8 bytes of all input text and output text.
It is deliberately not described as a tokenizer or an estimate for a commercial provider.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

from kavrigo_model_gateway.contracts import ProviderReply, ProviderRequest, Usage


class MockProvider:
    local_only = True

    def __init__(
        self, outputs: Sequence[str | ProviderReply | Exception], *, name: str = "mock"
    ) -> None:
        self.name = name
        self._outputs = deque(outputs)
        self.call_count = 0

    def input_token_bound(self, request: ProviderRequest) -> int:
        return len(
            (request.system_text + request.input_json + request.output_schema_json).encode("utf-8")
        )

    async def complete(self, request: ProviderRequest) -> ProviderReply:
        self.call_count += 1
        if not self._outputs:
            raise RuntimeError("mock script exhausted")
        output = self._outputs.popleft()
        if isinstance(output, Exception):
            raise output
        if isinstance(output, ProviderReply):
            return output
        return ProviderReply(
            model_identifier=request.model_identifier,
            status="completed",
            output_json=output,
            usage=Usage(
                input_tokens=self.input_token_bound(request),
                output_tokens=len(output.encode("utf-8")),
            ),
        )
