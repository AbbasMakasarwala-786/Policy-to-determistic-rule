from __future__ import annotations

import json
import logging

from app.models.schemas import Rule

logger = logging.getLogger(__name__)


class RuleStructurer:
    def normalize(self, rules: list[Rule]) -> list[Rule]:
        logger.info("Structuring %s extracted rules", len(rules))
        dedupe_map: dict[str, Rule] = {}
        used_ids: set[str] = set()

        for rule in rules:
            rule.confidence = min(max(rule.confidence, 0.0), 1.0)
            rule.needs_review = rule.confidence < 0.7
            rule.rule_id = self._ensure_unique_rule_id(rule.rule_id, used_ids)
            dedupe_key = self._dedupe_key(rule)
            existing = dedupe_map.get(dedupe_key)
            if existing:
                logger.warning(
                    "Dedup conflict on key source_clause=%s action=%s. keeping rule_id=%s dropping rule_id=%s",
                    existing.source_clause,
                    existing.action,
                    existing.rule_id,
                    rule.rule_id,
                )
            dedupe_map[dedupe_key] = rule

        normalized_rules = list(dedupe_map.values())
        logger.info("Structuring completed. normalized=%s deduplicated=%s", len(normalized_rules), len(rules) - len(normalized_rules))
        return normalized_rules

    @staticmethod
    def _dedupe_key(rule: Rule) -> str:
        return json.dumps(
            {
                "source_clause": rule.source_clause,
                "category": rule.category,
                "condition": rule.condition,
                "action": rule.action,
            },
            sort_keys=True,
            ensure_ascii=True,
        )

    @staticmethod
    def _ensure_unique_rule_id(candidate: str, used_ids: set[str]) -> str:
        if candidate not in used_ids:
            used_ids.add(candidate)
            return candidate
        index = 2
        while True:
            updated = f"{candidate}-{index}"
            if updated not in used_ids:
                used_ids.add(updated)
                return updated
            index += 1
