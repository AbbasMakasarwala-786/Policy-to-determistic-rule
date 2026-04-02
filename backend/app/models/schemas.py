from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Clause(BaseModel):
    clause_id: str
    section_id: str
    section_title: str | None = None
    heading: str | None = None
    text: str
    references: list[str] = Field(default_factory=list)
    line_start: int | None = None


class ParsedDocument(BaseModel):
    document_id: str
    filename: str
    raw_text: str
    clauses: list[Clause]
    created_at: datetime = Field(default_factory=datetime.utcnow)


class Rule(BaseModel):
    rule_id: str
    source_clause: str
    section_id: str
    category: str
    description: str
    condition: dict[str, Any] = Field(default_factory=dict)
    action: str
    exception: str | None = None
    confidence: float = 0.75
    needs_review: bool = False
    notification: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Conflict(BaseModel):
    conflict_id: str
    rule_ids: list[str]
    source_clauses: list[str]
    reason: str
    severity: str = "medium"


class ExecutionResult(BaseModel):
    rule_id: str
    matched: bool
    reason: str
    action: str | None = None


class NotificationEvent(BaseModel):
    recipient: str
    subject: str
    body: str
    status: str
    rule_id: str


class DocumentUploadResponse(BaseModel):
    document_id: str
    filename: str
    clauses_count: int
    sections_count: int


class PipelineRunRequest(BaseModel):
    use_llm: bool = True
    llm_mode: str = "assist"
    max_llm_calls: int = 6
    notify_on_deviation: bool = False
    recipients: list[str] = Field(default_factory=list)
    sample_invoice: dict[str, Any] | None = None


class PipelineRunResponse(BaseModel):
    run_id: str
    document_id: str
    rules_count: int
    conflicts_count: int
    rules: list[Rule]
    conflicts: list[Conflict]
    execution_results: list[ExecutionResult] = Field(default_factory=list)
    notifications: list[NotificationEvent] = Field(default_factory=list)
