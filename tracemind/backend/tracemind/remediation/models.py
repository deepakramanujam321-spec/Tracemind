from __future__ import annotations

from datetime import datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

RemediationStatus = Literal["patch_generated", "tested", "verified"]


class PatchProposal(BaseModel):
    """Structured output requested from the model."""
    diff: str = Field(description="Unified diff (git format, a/ b/ prefixes, paths relative to repo root)")
    explanation: str = ""


class CommandRun(BaseModel):
    phase: str                    # sandbox_create | baseline_test | patch_check | patch_apply | test | regression_test
    command: list[str]
    exit_code: int | None         # None on timeout
    stdout: str = ""              # truncated
    stderr: str = ""              # truncated
    started_at: datetime
    duration_ms: float


class RemediationStore(Protocol):
    """Persistence seam (Team B backs it with remediations / command_runs tables)."""

    def record_command(self, remediation_id: str, run: CommandRun) -> None: ...
    def set_status(self, remediation_id: str, status: RemediationStatus, **fields: object) -> None: ...
    def save_diff(self, remediation_id: str, diff: str) -> None: ...


class InMemoryRemediationStore:
    def __init__(self) -> None:
        self.commands: dict[str, list[CommandRun]] = {}
        self.statuses: dict[str, list[RemediationStatus]] = {}
        self.fields: dict[str, dict[str, object]] = {}
        self.diffs: dict[str, str] = {}

    def record_command(self, remediation_id: str, run: CommandRun) -> None:
        self.commands.setdefault(remediation_id, []).append(run)

    def set_status(self, remediation_id: str, status: RemediationStatus, **fields: object) -> None:
        self.statuses.setdefault(remediation_id, []).append(status)
        self.fields.setdefault(remediation_id, {}).update(fields)

    def save_diff(self, remediation_id: str, diff: str) -> None:
        self.diffs[remediation_id] = diff


class RemediationResult(BaseModel):
    remediation_id: str
    status: RemediationStatus | None      # None: no valid patch was produced/applied
    diff: str = ""
    explanation: str = ""
    sandbox_path: str = ""
    base_sha: str = ""
    baseline_reproduced: bool | None = None  # regression test failed BEFORE the patch
    tests_passed: bool | None = None
    regression_passed: bool | None = None
    error: str | None = None
