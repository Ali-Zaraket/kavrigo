"""A locally synthetic rehearsal is never reported as a market or paper result."""

from typing import Literal

from pydantic import BaseModel, ConfigDict


class RehearsalLaunch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str
    input_hash: str
    dispatch_state: Literal["dispatched", "queued"]
    replayed: bool
    input_kind: Literal["synthetic_rehearsal"] = "synthetic_rehearsal"
    execution_enabled: Literal[False] = False
