from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core.config import Settings
from app.models.schemas import Clause, ParsedDocument, Rule

logger = logging.getLogger(__name__)

IF_THEN_RE = re.compile(
    r"^\s*(if|when|whenever|where|in case)\s+(?P<cond>.+?)(?:,\s*|\s+then\s+)(?P<act>.+)$",
    re.IGNORECASE,
)
UNLESS_RE = re.compile(r"^\s*unless\s+(?P<cond>.+?)(?:,\s*|\s+then\s+)(?P<act>.+)$", re.IGNORECASE)
EXCEPTION_RE = re.compile(r"^\s*(except|exception)\b[:\-]?\s*(?P<act>.+)$", re.IGNORECASE)
MUST_RE = re.compile(r"\b(must|shall|required to|requires?|needs to|has authority to)\b", re.IGNORECASE)
MAY_RE = re.compile(r"\b(may|can)\b", re.IGNORECASE)
NEVER_RE = re.compile(r"\b(never|must not|shall not|not allowed|prohibited)\b", re.IGNORECASE)


class ExtractionOutput(BaseModel):
    rules: list[Rule] = Field(default_factory=list)


class RuleExtractor:
    def __init__(self, settings: Settings):
        self.settings = settings
        self._structured_llm = None
        self._system_message_cls = None
        self._human_message_cls = None
        self._graph = None
        self._setup_llm_graph()

    def _setup_llm_graph(self) -> None:
        if not self.settings.llm_enabled_and_configured:
            logger.info("LLM disabled or not configured. Falling back to deterministic extractor.")
            return

        try:
            from langchain_core.messages import HumanMessage, SystemMessage
            from langchain_mistralai import ChatMistralAI
            from langgraph.graph import StateGraph
        except ImportError:
            logger.warning("LangChain/LangGraph not installed. Using fallback deterministic extraction.")
            return

        self._system_message_cls = SystemMessage
        self._human_message_cls = HumanMessage
        self._structured_llm = ChatMistralAI(
            model=self.settings.mistral_model,
            api_key=self.settings.mistral_api_key,
            temperature=0,
            timeout=self.settings.llm_timeout_seconds,
        )

        def extract_node(state: dict[str, Any]) -> dict[str, Any]:
            clauses: list[Clause] = state["clauses"]
            extracted_rules: list[Rule] = []
            for clause in clauses:
                rules_from_clause = self._extract_from_clause_with_llm(
                    clause,
                    system_message_cls=SystemMessage,
                    human_message_cls=HumanMessage,
                )
                if not rules_from_clause:
                    rules_from_clause = self._extract_from_clause_deterministic(clause)
                extracted_rules.extend(rules_from_clause)
            return {"rules": extracted_rules}

        builder = StateGraph(dict)
        builder.add_node("extract", extract_node)
        builder.set_entry_point("extract")
        builder.set_finish_point("extract")
        self._graph = builder.compile()
        logger.info("LLM extraction graph initialized successfully.")

    def extract_rules(
        self,
        parsed_document: ParsedDocument,
        use_llm: bool = True,
        llm_mode: str = "assist",
        max_llm_calls: int = 6,
    ) -> list[Rule]:
        llm_mode_normalized = (llm_mode or "assist").lower()
        logger.info(
            "Rule extraction started document_id=%s use_llm=%s llm_mode=%s max_llm_calls=%s",
            parsed_document.document_id,
            use_llm,
            llm_mode_normalized,
            max_llm_calls,
        )

        deterministic_by_clause: dict[str, list[Rule]] = {}
        for clause in parsed_document.clauses:
            deterministic_by_clause[clause.clause_id] = self._extract_from_clause_deterministic(clause)

        if not use_llm or llm_mode_normalized == "off" or self._structured_llm is None:
            rules = [rule for clause_rules in deterministic_by_clause.values() for rule in clause_rules]
            logger.info("Deterministic rule extraction completed rules=%s", len(rules))
            return rules

        if llm_mode_normalized == "full":
            candidate_clauses = list(parsed_document.clauses)
        else:
            candidate_clauses = self._select_assist_candidates(parsed_document.clauses, deterministic_by_clause)

        if not candidate_clauses or self._system_message_cls is None or self._human_message_cls is None:
            rules = [rule for clause_rules in deterministic_by_clause.values() for rule in clause_rules]
            logger.info("No LLM candidate clauses found. Using deterministic rules=%s", len(rules))
            return rules

        llm_call_cap = max(0, min(int(max_llm_calls), 20))
        llm_calls = 0
        for clause in candidate_clauses:
            if llm_calls >= llm_call_cap:
                break
            try:
                llm_rules = self._extract_from_clause_with_llm(
                    clause,
                    system_message_cls=self._system_message_cls,
                    human_message_cls=self._human_message_cls,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("LLM clause extraction failed clause=%s error=%s", clause.clause_id, exc)
                llm_rules = []
            llm_calls += 1
            if llm_rules:
                deterministic_by_clause[clause.clause_id] = llm_rules

        merged_rules = [rule for clause_rules in deterministic_by_clause.values() for rule in clause_rules]
        logger.info(
            "Hybrid extraction completed rules=%s llm_calls=%s candidate_clauses=%s",
            len(merged_rules),
            llm_calls,
            len(candidate_clauses),
        )
        return merged_rules

    def _select_assist_candidates(
        self,
        clauses: list[Clause],
        deterministic_by_clause: dict[str, list[Rule]],
    ) -> list[Clause]:
        candidate_ids: set[str] = set()
        for clause in clauses:
            clause_rules = deterministic_by_clause.get(clause.clause_id, [])
            if not clause_rules:
                candidate_ids.add(clause.clause_id)
                continue
            all_generic = all(rule.category in {"general_policy", "validation"} for rule in clause_rules)
            low_conf = any(rule.confidence < 0.85 or rule.needs_review for rule in clause_rules)
            if all_generic or low_conf:
                candidate_ids.add(clause.clause_id)

        all_rules = [rule for rules in deterministic_by_clause.values() for rule in rules]
        required_categories = {"three_way_match", "compliance_tax", "approval_matrix"}
        extracted_categories = {rule.category for rule in all_rules}
        if not required_categories.issubset(extracted_categories):
            keywords = ("po", "grn", "gstin", "pan", "approval", "watch list", "cgst", "sgst", "igst", "tax")
            for clause in clauses:
                text = f"{clause.heading or ''} {clause.text}".lower()
                if any(keyword in text for keyword in keywords):
                    candidate_ids.add(clause.clause_id)

        return [clause for clause in clauses if clause.clause_id in candidate_ids]

    def _extract_from_clause_with_llm(
        self,
        clause: Clause,
        system_message_cls: Any,
        human_message_cls: Any,
    ) -> list[Rule]:
        if self._structured_llm is None:
            return []

        system_prompt = (
            "You extract deterministic policy rules from business documents across any domain "
            "(finance, HR, procurement, operations, compliance, legal). "
            "Return valid structured rules with machine-executable conditions. "
            "Return ONLY raw JSON. Do not use markdown fences. "
            "Set rule_id empty string if unknown. "
            "Output MUST be an object with a single key 'rules' whose value is an array of rule objects. "
            "Each rule object must use fields: "
            "rule_id, source_clause, section_id, category, description, condition, action, "
            "exception, confidence, needs_review, notification, metadata. "
            "Condition must be a JSON object with fields: "
            "'metric' (snake_case field), 'op' (one of: ==, !=, >, >=, <, <=, between), "
            "and 'value' or 'min'/'max' for between. "
            "Never use free-text descriptions as conditions. "
            "Preserve source intent, exceptions, thresholds, and escalation/approval actions."
        )
        human_prompt = json.dumps(
            {
                "clause_id": clause.clause_id,
                "section_id": clause.section_id,
                "section_title": clause.section_title,
                "heading": clause.heading,
                "text": clause.text,
                "references": clause.references,
            },
            ensure_ascii=True,
        )

        response = self._structured_llm.invoke(
            [
                system_message_cls(content=system_prompt),
                human_message_cls(content=human_prompt),
            ]
        )
        content = getattr(response, "content", "")
        parsed_response = self._parse_llm_json_response(content)
        if parsed_response is None:
            return []

        rules = []
        for index, rule in enumerate(parsed_response.rules, start=1):
            if not rule.rule_id:
                rule.rule_id = f"POL-{clause.clause_id.replace('.', '-')}-{index}"
            if not rule.source_clause:
                rule.source_clause = clause.clause_id
            if not rule.section_id:
                rule.section_id = clause.section_id
            if not rule.category:
                rule.category = self._infer_category(clause)
            if not self._is_structured_condition(rule.condition):
                rule.needs_review = True
                rule.confidence = min(rule.confidence, 0.55)
                rule.metadata["condition_validation_error"] = "Condition is not executable metric/op/value format."
            rules.append(rule)
        return rules

    @staticmethod
    def _parse_llm_json_response(content: Any) -> ExtractionOutput | None:
        if isinstance(content, list):
            text = "".join(
                part.get("text", "")
                for part in content
                if isinstance(part, dict)
            ).strip()
        else:
            text = str(content).strip() if content is not None else ""

        if not text:
            logger.warning("LLM response content is empty.")
            return None
        text = RuleExtractor._strip_json_fences(text)

        try:
            payload = json.loads(text)
            normalized = RuleExtractor._normalize_llm_payload(payload)
            return ExtractionOutput(**normalized)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Failed to parse LLM JSON output. error=%s payload=%s", exc, text[:400])
            return None

    @staticmethod
    def _strip_json_fences(text: str) -> str:
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    @staticmethod
    def _normalize_llm_payload(payload: Any) -> dict[str, Any]:
        if isinstance(payload, dict) and "rules" in payload:
            rules = payload.get("rules") or []
            return {"rules": [RuleExtractor._normalize_rule_dict(rule) for rule in rules if isinstance(rule, dict)]}

        if isinstance(payload, list):
            return {"rules": [RuleExtractor._normalize_rule_dict(rule) for rule in payload if isinstance(rule, dict)]}

        if isinstance(payload, dict):
            return {"rules": [RuleExtractor._normalize_rule_dict(payload)]}

        return {"rules": []}

    @staticmethod
    def _normalize_rule_dict(raw: dict[str, Any]) -> dict[str, Any]:
        condition = raw.get("condition")
        if not isinstance(condition, dict):
            condition = {"metric": "always_true", "op": "==", "value": True}

        action_value = raw.get("action")
        action_text = RuleExtractor._normalize_llm_action(action_value, raw)
        exception_text = RuleExtractor._normalize_llm_exception(raw.get("exception"))
        confidence_value = RuleExtractor._normalize_llm_confidence(raw.get("confidence"))

        return {
            "rule_id": str(raw.get("rule_id", "")),
            "source_clause": str(raw.get("source_clause", "")),
            "section_id": str(raw.get("section_id", "")),
            "category": str(raw.get("category", "general_policy")),
            "description": str(raw.get("description") or raw.get("rule_text") or raw.get("heading") or "LLM extracted rule"),
            "condition": condition,
            "action": action_text,
            "exception": exception_text,
            "confidence": confidence_value,
            "needs_review": bool(raw.get("needs_review", False)),
            "notification": raw.get("notification") if isinstance(raw.get("notification"), dict) else {},
            "metadata": raw.get("metadata") if isinstance(raw.get("metadata"), dict) else {},
        }

    @staticmethod
    def _normalize_llm_action(action_value: Any, raw: dict[str, Any]) -> str:
        if isinstance(action_value, str) and action_value.strip():
            return action_value.strip()
        if isinstance(action_value, dict):
            action_type = action_value.get("type") or action_value.get("status") or action_value.get("action")
            if isinstance(action_type, str) and action_type.strip():
                return action_type.strip().upper().replace(" ", "_")
            return "TAKE_ACTION"
        fallback = raw.get("action_type")
        if isinstance(fallback, str) and fallback.strip():
            return fallback.strip().upper().replace(" ", "_")
        return "REVIEW_MANUALLY"

    @staticmethod
    def _normalize_llm_exception(exception_value: Any) -> str | None:
        if exception_value is None:
            return None
        if isinstance(exception_value, str):
            cleaned = exception_value.strip()
            return cleaned if cleaned else None
        if isinstance(exception_value, dict):
            if "reason" in exception_value and exception_value["reason"]:
                return str(exception_value["reason"])
            if "description" in exception_value and exception_value["description"]:
                return str(exception_value["description"])
            return json.dumps(exception_value, ensure_ascii=True)
        if isinstance(exception_value, list):
            if not exception_value:
                return None
            return json.dumps(exception_value, ensure_ascii=True)
        return str(exception_value)

    @staticmethod
    def _normalize_llm_confidence(confidence_value: Any) -> float:
        try:
            if confidence_value is None or str(confidence_value).strip() == "":
                return 0.7
            value = float(confidence_value)
            return min(max(value, 0.0), 1.0)
        except (TypeError, ValueError):
            return 0.7

    def _extract_from_clause_deterministic(self, clause: Clause) -> list[Rule]:
        rule_id_prefix = f"POL-{clause.clause_id.replace('.', '-')}"
        rules: list[Rule] = []
        category = self._infer_category(clause)
        sentences = self._split_sentences(clause.text)

        def build_rule(
            suffix: str,
            inferred_category: str,
            description: str,
            condition: dict[str, Any],
            action: str,
            exception: str | None = None,
            confidence: float = 0.92,
            notification: dict[str, Any] | None = None,
            metadata: dict[str, Any] | None = None,
        ) -> Rule:
            return Rule(
                rule_id=f"{rule_id_prefix}-{suffix}",
                source_clause=clause.clause_id,
                section_id=clause.section_id,
                category=inferred_category,
                description=description,
                condition=condition,
                action=action,
                exception=exception,
                confidence=confidence,
                needs_review=confidence < 0.7,
                notification=notification or {},
                metadata=metadata or {},
            )

        for index, sentence in enumerate(sentences, start=1):
            parsed = self._parse_sentence(sentence)
            if not parsed:
                continue
            condition_text = parsed["condition"]
            action_text = parsed["action"]
            exception_text = parsed.get("exception")
            action_code = self._normalize_action(action_text)
            metric_name = self._metric_name(clause, index, condition_text, action_text)
            condition = self._build_condition(condition_text, metric_name, clause.text, action_text)
            rule_category = self._category_from_condition(category, condition, clause)
            confidence = self._confidence_for_sentence(sentence, condition_text, action_text)

            rules.append(
                build_rule(
                    f"{index:02d}",
                    rule_category,
                    description=sentence,
                    condition=condition,
                    action=action_code,
                    exception=exception_text,
                    confidence=confidence,
                    notification=self._notification_hint(action_text),
                    metadata={
                        "condition_text": condition_text,
                        "action_text": action_text,
                        "raw_sentence": sentence,
                        "references": clause.references,
                    },
                )
            )

        if not rules:
            rules.append(
                build_rule(
                    "99",
                    category,
                    clause.text[:180],
                    {"metric": "always_true", "op": "==", "value": True},
                    "REVIEW_MANUALLY",
                    confidence=0.72,
                    metadata={
                        "raw_sentence": clause.text,
                        "references": clause.references,
                    },
                )
            )

        return rules

    @staticmethod
    def _split_sentences(text: str) -> list[str]:
        chunks = re.split(r"(?<=[.!?;])\s+|\s+(?=(?:if|when|unless|except)\b)", text.strip(), flags=re.IGNORECASE)
        return [chunk.strip(" -") for chunk in chunks if chunk and chunk.strip()]

    def _parse_sentence(self, sentence: str) -> dict[str, str] | None:
        match = IF_THEN_RE.match(sentence)
        if match:
            return {"condition": match.group("cond").strip(), "action": match.group("act").strip()}

        unless_match = UNLESS_RE.match(sentence)
        if unless_match:
            return {
                "condition": f"NOT ({unless_match.group('cond').strip()})",
                "action": unless_match.group("act").strip(),
            }

        exception_match = EXCEPTION_RE.match(sentence)
        if exception_match:
            return {
                "condition": "exception_applicable",
                "action": exception_match.group("act").strip(),
                "exception": sentence.strip(),
            }

        if MUST_RE.search(sentence) or MAY_RE.search(sentence) or NEVER_RE.search(sentence):
            return {"condition": "always_true", "action": sentence.strip()}
        if "no exceptions" in sentence.lower():
            return {"condition": "always_true", "action": sentence.strip()}
        return None

    @staticmethod
    def _normalize_action(action_text: str) -> str:
        lowered = action_text.lower()
        if "reject" in lowered:
            return "REJECT"
        if "auto-approve" in lowered or "auto approve" in lowered or "approved" in lowered:
            return "APPROVE"
        if "escalat" in lowered:
            return "ESCALATE"
        if "route" in lowered:
            return "ROUTE"
        if "hold" in lowered:
            return "HOLD"
        if "flag" in lowered:
            return "FLAG"
        if "email" in lowered or "notify" in lowered:
            return "SEND_NOTIFICATION"
        if "no exceptions" in lowered:
            return "PROHIBIT"
        if NEVER_RE.search(lowered):
            return "PROHIBIT"
        if "allow" in lowered or MAY_RE.search(lowered):
            return "ALLOW"
        if MUST_RE.search(lowered):
            return "REQUIRE"
        return "TAKE_ACTION"

    @staticmethod
    def _notification_hint(action_text: str) -> dict[str, Any]:
        lowered = action_text.lower()
        if "email" not in lowered and "notify" not in lowered:
            return {}
        minutes_match = re.search(r"within\s+(\d+)\s+minute", lowered)
        hours_match = re.search(r"within\s+(\d+)\s+hour", lowered)
        if minutes_match:
            return {"within_minutes": int(minutes_match.group(1))}
        if hours_match:
            return {"within_minutes": int(hours_match.group(1)) * 60}
        return {"enabled": True}

    @staticmethod
    def _build_condition(condition_text: str, metric_name: str, clause_text: str, action_text: str) -> dict[str, Any]:
        lowered = condition_text.lower()
        combined = f"{condition_text} {action_text} {clause_text}".lower()
        if condition_text == "always_true":
            return {"metric": "always_true", "op": "==", "value": True}

        legacy = RuleExtractor._legacy_ap_condition(combined)
        if legacy:
            return legacy

        between_match = re.search(r"between\s+(?:inr\s+)?([\d,]+)\s+and\s+(?:inr\s+)?([\d,]+)", lowered)
        if between_match:
            low = int(between_match.group(1).replace(",", ""))
            high = int(between_match.group(2).replace(",", ""))
            return {
                "metric": metric_name,
                "op": "between",
                "min": low,
                "max": high,
                "expression": condition_text,
            }

        threshold_match = re.search(r"(>=|<=|>|<)\s*(\d+(?:\.\d+)?)", lowered)
        if threshold_match:
            value: float | int = float(threshold_match.group(2))
            if value.is_integer():
                value = int(value)
            return {
                "metric": metric_name,
                "op": threshold_match.group(1),
                "value": value,
                "expression": condition_text,
            }

        up_to_match = re.search(r"(up to|upto|at most)\s+(?:inr\s+)?([\d,]+)", lowered)
        if up_to_match:
            return {
                "metric": metric_name,
                "op": "<=",
                "value": int(up_to_match.group(2).replace(",", "")),
                "expression": condition_text,
            }

        above_match = re.search(r"(above|over|greater than)\s+(?:inr\s+)?([\d,]+)", lowered)
        if above_match:
            return {
                "metric": metric_name,
                "op": ">",
                "value": int(above_match.group(2).replace(",", "")),
                "expression": condition_text,
            }

        pct_more_match = re.search(r"(more than|exceeds?)\s+(\d+(?:\.\d+)?)\s*%", lowered)
        if pct_more_match:
            return {
                "metric": metric_name,
                "op": ">",
                "value": float(pct_more_match.group(2)),
                "expression": condition_text,
            }

        return {
            "metric": metric_name,
            "op": "==",
            "value": True,
            "expression": condition_text,
        }

    @staticmethod
    def _confidence_for_sentence(sentence: str, condition_text: str, action_text: str) -> float:
        confidence = 0.78
        if condition_text and action_text:
            confidence += 0.1
        if re.search(r"\b(may|typically|generally|as needed)\b", sentence, flags=re.IGNORECASE):
            confidence -= 0.15
        if re.search(r"\b(always|must|shall|never|only)\b", sentence, flags=re.IGNORECASE):
            confidence += 0.06
        return min(max(confidence, 0.55), 0.96)

    @staticmethod
    def _metric_name(clause: Clause, index: int, condition_text: str, action_text: str) -> str:
        combined = f"{condition_text} {action_text} {clause.text}".lower()
        legacy_metric = RuleExtractor._legacy_metric_name(combined)
        if legacy_metric:
            return legacy_metric
        safe_clause = clause.clause_id.replace(".", "_").replace("(", "_").replace(")", "")
        return f"clause_{safe_clause}_cond_{index}"

    @staticmethod
    def _infer_category(clause: Clause) -> str:
        text = f"{clause.section_title or ''} {clause.heading or ''} {clause.text}".lower()
        if any(token in text for token in ("approval", "approver", "escalat", "authorize")):
            return "approval_matrix"
        if any(token in text for token in ("email", "notify", "alert")):
            return "notification"
        if any(token in text for token in ("tax", "compliance", "legal", "policy violation", "audit")):
            return "compliance_tax"
        if any(token in text for token in ("exception", "unless", "waiver")):
            return "exception"
        if any(token in text for token in ("invoice", "payment", "po", "grn")):
            return "three_way_match"
        if any(token in text for token in ("match", "validate", "check", "verification")):
            return "validation"
        return "general_policy"

    @staticmethod
    def _is_structured_condition(condition: dict[str, Any]) -> bool:
        if not isinstance(condition, dict) or not condition:
            return False
        if "all" in condition:
            children = condition.get("all", [])
            return isinstance(children, list) and all(RuleExtractor._is_structured_condition(child) for child in children)
        if "any" in condition:
            children = condition.get("any", [])
            return isinstance(children, list) and all(RuleExtractor._is_structured_condition(child) for child in children)
        metric = condition.get("metric")
        op = condition.get("op")
        if not metric or not op:
            return False
        if op == "between":
            return "min" in condition and "max" in condition
        return "value" in condition

    @staticmethod
    def _legacy_metric_name(text: str) -> str | None:
        checks: list[tuple[tuple[str, ...], str]] = [
            (("po amount", "invoice total amount"), "invoice_po_deviation_pct"),
            (("within +/-", "po amount"), "invoice_po_deviation_pct_abs"),
            (("invoice quantity > po quantity",), "invoice_qty_gt_po_qty"),
            (("unit rate differs", "po unit rate"), "unit_rate_deviation_pct_abs"),
            (("invoice quantity > grn quantity",), "invoice_qty_gt_grn_qty"),
            (("grn date", "invoice date"), "grn_date_after_invoice_date"),
            (("gstin", "vendor master"), "gstin_matches_vendor_master"),
            (("pan", "gstin"), "pan_gstin_matches"),
            (("watch list", "regardless of amount"), "vendor_watchlist"),
            (("deviation detected",), "deviation_detected"),
            (("critical deviations",), "invoice_po_deviation_pct"),
            (("invoices up to", "auto-approved"), "invoice_amount"),
            (("between inr", "require approval"), "invoice_amount"),
            (("invoices above", "require approval"), "invoice_amount"),
        ]
        for tokens, metric in checks:
            if all(token in text for token in tokens):
                return metric
        return None

    @staticmethod
    def _legacy_ap_condition(text: str) -> dict[str, Any] | None:
        if "within +/- 1%" in text and "po amount" in text:
            return {"metric": "invoice_po_deviation_pct_abs", "op": "<=", "value": 1}
        if "more than 1%" in text and "less than 10%" in text and "po amount" in text:
            return {
                "all": [
                    {"metric": "invoice_po_deviation_pct", "op": ">", "value": 1},
                    {"metric": "invoice_po_deviation_pct", "op": "<", "value": 10},
                ]
            }
        if ("10% or more" in text or ">= 10%" in text) and "po amount" in text:
            return {"metric": "invoice_po_deviation_pct", "op": ">=", "value": 10}
        if "less than the po amount by more than 5%" in text:
            return {"metric": "invoice_po_deviation_pct", "op": "<", "value": -5}
        if "invoice quantity > po quantity" in text:
            return {"metric": "invoice_qty_gt_po_qty", "op": "==", "value": True}
        if "unit rate differs" in text and "2%" in text:
            return {"metric": "unit_rate_deviation_pct_abs", "op": ">", "value": 2}
        if "invoice quantity > grn quantity" in text:
            return {"metric": "invoice_qty_gt_grn_qty", "op": "==", "value": True}
        if ("grn date is after the invoice date" in text) or ("grn date must be on or before the invoice date" in text):
            return {"metric": "grn_date_after_invoice_date", "op": "==", "value": True}
        if "gstin" in text and "must match" in text and "vendor master" in text:
            return {"metric": "gstin_matches_vendor_master", "op": "==", "value": False}
        if "pan embedded in the vendor's gstin" in text:
            return {"metric": "pan_gstin_matches", "op": "==", "value": False}
        if "watch list" in text and "regardless of amount" in text:
            return {"metric": "vendor_watchlist", "op": "==", "value": True}
        if "deviation detected during the three-way match" in text and ("email notification" in text or "trigger" in text):
            return {"metric": "deviation_detected", "op": "==", "value": True}
        if "critical deviations" in text and "10%" in text:
            return {
                "any": [
                    {"metric": "invoice_po_deviation_pct", "op": ">", "value": 10},
                    {"metric": "compliance_failure", "op": "==", "value": True},
                ]
            }
        return None

    @staticmethod
    def _category_from_condition(base_category: str, condition: dict[str, Any], clause: Clause) -> str:
        metrics = RuleExtractor._collect_condition_metrics(condition)
        if any(
            metric in metrics
            for metric in (
                "invoice_po_deviation_pct",
                "invoice_po_deviation_pct_abs",
                "invoice_qty_gt_po_qty",
                "unit_rate_deviation_pct_abs",
                "invoice_qty_gt_grn_qty",
                "grn_date_after_invoice_date",
                "invoice_amount",
            )
        ):
            return "three_way_match" if base_category != "approval_matrix" else "approval_matrix"
        if any(metric in metrics for metric in ("gstin_matches_vendor_master", "pan_gstin_matches", "compliance_failure")):
            return "compliance_tax"
        if "watch list" in clause.text.lower() and "approval" in clause.text.lower():
            return "approval_matrix"
        return base_category

    @staticmethod
    def _collect_condition_metrics(condition: dict[str, Any]) -> set[str]:
        metrics: set[str] = set()
        if not isinstance(condition, dict):
            return metrics
        if "all" in condition:
            for child in condition.get("all", []):
                metrics.update(RuleExtractor._collect_condition_metrics(child))
            return metrics
        if "any" in condition:
            for child in condition.get("any", []):
                metrics.update(RuleExtractor._collect_condition_metrics(child))
            return metrics
        metric = condition.get("metric")
        if metric:
            metrics.add(metric)
        return metrics
