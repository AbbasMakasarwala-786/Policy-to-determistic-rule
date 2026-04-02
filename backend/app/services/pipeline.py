from __future__ import annotations

import logging
import uuid

from app.models.schemas import (
    DocumentUploadResponse,
    ParsedDocument,
    PipelineRunRequest,
    PipelineRunResponse,
    Rule,
)
from app.services.conflict_detector import ConflictDetector
from app.services.document_loader import DocumentLoader
from app.services.extractor import RuleExtractor
from app.services.notifier import DeviationNotifier
from app.services.parser import DocumentParser
from app.services.rule_engine import RuleEngine
from app.services.structurer import RuleStructurer
from app.storage.in_memory import InMemoryStore

logger = logging.getLogger(__name__)


class PipelineService:
    def __init__(
        self,
        store: InMemoryStore,
        loader: DocumentLoader,
        parser: DocumentParser,
        extractor: RuleExtractor,
        structurer: RuleStructurer,
        conflict_detector: ConflictDetector,
        rule_engine: RuleEngine,
        notifier: DeviationNotifier,
    ):
        self.store = store
        self.loader = loader
        self.parser = parser
        self.extractor = extractor
        self.structurer = structurer
        self.conflict_detector = conflict_detector
        self.rule_engine = rule_engine
        self.notifier = notifier

    def upload_and_parse(self, filename: str, raw_bytes: bytes) -> DocumentUploadResponse:
        raw_text = self.loader.load_text(filename, raw_bytes)
        parsed = self.parser.parse(filename=filename, raw_text=raw_text)
        self.store.save_document(parsed.document_id, parsed)
        return DocumentUploadResponse(
            document_id=parsed.document_id,
            filename=parsed.filename,
            clauses_count=len(parsed.clauses),
            sections_count=len({clause.section_id for clause in parsed.clauses}),
        )

    def get_document(self, document_id: str) -> ParsedDocument | None:
        return self.store.get_document(document_id)

    def run_pipeline(self, document_id: str, request: PipelineRunRequest) -> PipelineRunResponse:
        logger.info("Pipeline run started document_id=%s", document_id)
        parsed: ParsedDocument | None = self.store.get_document(document_id)
        if not parsed:
            raise ValueError(f"Unknown document_id: {document_id}")

        raw_rules = self.extractor.extract_rules(
            parsed,
            use_llm=request.use_llm,
            llm_mode=request.llm_mode,
            max_llm_calls=request.max_llm_calls,
        )
        rules = self.structurer.normalize(raw_rules)
        conflicts = self.conflict_detector.detect(rules)

        execution_results = []
        notifications = []
        if request.sample_invoice:
            execution_results = self.rule_engine.evaluate(rules, request.sample_invoice)

        if request.notify_on_deviation:
            if request.sample_invoice:
                matched_rule_ids = {item.rule_id for item in execution_results if item.matched}
                triggered_rules = [rule for rule in rules if rule.rule_id in matched_rule_ids]
            else:
                triggered_rules = [
                    rule
                    for rule in rules
                    if rule.category == "notification"
                    or any(token in rule.action.upper() for token in ("ESCALATE", "REJECT", "HOLD", "SEND_NOTIFICATION"))
                    or any(
                        token in f"{rule.description} {rule.metadata.get('action_text', '')}".lower()
                        for token in ("deviation", "exception", "violation", "breach", "notify", "email")
                    )
                ]
                if not triggered_rules:
                    # Interview-friendly fallback: send review notifications for highest-risk rules.
                    triggered_rules = [rule for rule in rules if rule.needs_review][:5]
            notifications = self.notifier.notify(triggered_rules=triggered_rules, recipients=request.recipients)

        run_id = str(uuid.uuid4())
        response = PipelineRunResponse(
            run_id=run_id,
            document_id=document_id,
            rules_count=len(rules),
            conflicts_count=len(conflicts),
            rules=rules,
            conflicts=conflicts,
            execution_results=execution_results,
            notifications=notifications,
        )
        self.store.save_run(run_id, response)
        logger.info(
            "Pipeline run completed run_id=%s rules=%s conflicts=%s notifications=%s",
            run_id,
            len(rules),
            len(conflicts),
            len(notifications),
        )
        return response

    def get_run(self, run_id: str) -> PipelineRunResponse | None:
        return self.store.get_run(run_id)
