from __future__ import annotations

import itertools
import logging
import re
import uuid

from app.models.schemas import Conflict, Rule

logger = logging.getLogger(__name__)


class ConflictDetector:
    def detect(self, rules: list[Rule]) -> list[Conflict]:
        logger.info("Conflict detection started for rules=%s", len(rules))
        conflicts: list[Conflict] = []
        seen_pairs: set[tuple[str, str]] = set()

        approval_rules = [rule for rule in rules if rule.category == "approval_matrix"]
        for left, right in itertools.combinations(approval_rules, 2):
            if self._is_overlap(left, right) and left.action != right.action:
                self._append_conflict(
                    conflicts,
                    seen_pairs,
                    left,
                    right,
                    "Overlapping approval range with different actions.",
                    "high",
                )

        for left, right in itertools.combinations(rules, 2):
            if left.rule_id == right.rule_id:
                continue
            if self._is_semantic_conflict(left, right):
                self._append_conflict(
                    conflicts,
                    seen_pairs,
                    left,
                    right,
                    "Potential contradiction in rule intent for similar scope.",
                    "medium",
                )

        logger.info("Conflict detection completed conflicts=%s", len(conflicts))
        return conflicts

    @staticmethod
    def _append_conflict(
        conflicts: list[Conflict],
        seen_pairs: set[tuple[str, str]],
        left: Rule,
        right: Rule,
        reason: str,
        severity: str,
    ) -> None:
        key = tuple(sorted((left.rule_id, right.rule_id)))
        if key in seen_pairs:
            return
        seen_pairs.add(key)
        conflicts.append(
            Conflict(
                conflict_id=f"CF-{uuid.uuid4().hex[:8]}",
                rule_ids=[left.rule_id, right.rule_id],
                source_clauses=[left.source_clause, right.source_clause],
                reason=reason,
                severity=severity,
            )
        )

    @staticmethod
    def _is_overlap(left: Rule, right: Rule) -> bool:
        left_min, left_max = ConflictDetector._range_from_rule(left)
        right_min, right_max = ConflictDetector._range_from_rule(right)

        if left_min is None and left_max is None:
            return False
        if right_min is None and right_max is None:
            return False

        left_min = float("-inf") if left_min is None else left_min
        left_max = float("inf") if left_max is None else left_max
        right_min = float("-inf") if right_min is None else right_min
        right_max = float("inf") if right_max is None else right_max
        return max(left_min, right_min) <= min(left_max, right_max)

    @staticmethod
    def _range_from_rule(rule: Rule) -> tuple[int | None, int | None]:
        if rule.metadata:
            return rule.metadata.get("amount_min"), rule.metadata.get("amount_max")
        condition = rule.condition
        if condition.get("op") == "between":
            return condition.get("min"), condition.get("max")
        if condition.get("op") == "<=":
            return None, condition.get("value")
        if condition.get("op") == ">":
            value = condition.get("value")
            return (value + 1 if isinstance(value, int) else value), None
        return None, None

    @staticmethod
    def _is_semantic_conflict(left: Rule, right: Rule) -> bool:
        if left.action.upper() == right.action.upper():
            return False

        left_scope = ConflictDetector._scope_key(left)
        right_scope = ConflictDetector._scope_key(right)
        opposite_intent = ConflictDetector._is_opposite_intent(left, right)
        if not opposite_intent:
            return False

        if left_scope == right_scope and left_scope:
            return True

        return ConflictDetector._is_exception_override_conflict(left, right)

    @staticmethod
    def _is_opposite_intent(left: Rule, right: Rule) -> bool:
        left_action = left.action.upper()
        right_action = right.action.upper()
        opposite_pairs = {
            ("ALLOW", "PROHIBIT"),
            ("APPROVE", "REJECT"),
            ("REQUIRE", "REJECT"),
            ("REQUIRE", "PROHIBIT"),
            ("HOLD", "APPROVE"),
            ("ALLOW", "REJECT"),
            ("APPROVE", "PROHIBIT"),
        }
        pair = (left_action, right_action)
        reverse_pair = (right_action, left_action)
        if pair in opposite_pairs or reverse_pair in opposite_pairs:
            return True

        left_text = f"{left.description} {left.metadata.get('action_text', '')}".lower()
        right_text = f"{right.description} {right.metadata.get('action_text', '')}".lower()
        has_allow = "allow" in left_text or "permitted" in left_text or "may " in left_text
        has_prohibit = "not allowed" in right_text or "never" in right_text or "prohibited" in right_text
        reverse_allow = "allow" in right_text or "permitted" in right_text or "may " in right_text
        reverse_prohibit = "not allowed" in left_text or "never" in left_text or "prohibited" in left_text
        return (has_allow and has_prohibit) or (reverse_allow and reverse_prohibit)

    @staticmethod
    def _is_exception_override_conflict(left: Rule, right: Rule) -> bool:
        left_text = f"{left.description} {left.metadata.get('condition_text', '')} {left.metadata.get('action_text', '')}".lower()
        right_text = f"{right.description} {right.metadata.get('condition_text', '')} {right.metadata.get('action_text', '')}".lower()

        disallow_markers = ("no exceptions", "never", "not allowed", "prohibited", "under any circumstances")
        allow_markers = ("exception", "unless", "override", "may", "allowed", "retroactive")

        left_disallow = any(marker in left_text for marker in disallow_markers)
        right_disallow = any(marker in right_text for marker in disallow_markers)
        left_allow = any(marker in left_text for marker in allow_markers)
        right_allow = any(marker in right_text for marker in allow_markers)

        if not ((left_disallow and right_allow) or (right_disallow and left_allow)):
            return False

        left_tokens = set(re.findall(r"[a-z]{4,}", left_text))
        right_tokens = set(re.findall(r"[a-z]{4,}", right_text))
        common = left_tokens.intersection(right_tokens)
        return len(common) >= 2

    @staticmethod
    def _scope_key(rule: Rule) -> str:
        expression = rule.condition.get("expression", "")
        if expression:
            return re.sub(r"\s+", " ", expression.lower()).strip()
        metric = rule.condition.get("metric", "")
        if metric == "always_true":
            return ""
        op = rule.condition.get("op", "")
        value = rule.condition.get("value", "")
        return f"{metric}:{op}:{value}"
