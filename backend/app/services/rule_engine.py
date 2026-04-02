from __future__ import annotations

import logging
from typing import Any

from app.models.schemas import ExecutionResult, Rule

logger = logging.getLogger(__name__)


class RuleEngine:
    SUPPORTED_OPS = {"==", "!=", ">", ">=", "<", "<=", "between"}
    METRIC_ALIASES: dict[str, list[str]] = {
        "invoice_po_deviation_pct": ["po_invoice_deviation_pct", "amount_deviation_pct"],
        "invoice_po_deviation_pct_abs": ["po_invoice_deviation_abs_pct", "amount_deviation_abs_pct"],
        "invoice_qty_gt_po_qty": ["qty_exceeds_po", "invoice_quantity_gt_po_quantity"],
        "unit_rate_deviation_pct_abs": ["rate_deviation_abs_pct", "unit_price_deviation_pct_abs"],
        "invoice_qty_gt_grn_qty": ["qty_exceeds_grn", "invoice_quantity_gt_grn_quantity"],
        "grn_date_after_invoice_date": ["grn_post_dated"],
        "gstin_matches_vendor_master": ["vendor_gstin_valid"],
        "pan_gstin_matches": ["pan_gstin_valid"],
        "vendor_watchlist": ["vendor_on_watchlist"],
        "deviation_detected": ["match_deviation_detected"],
        "compliance_failure": ["compliance_failed"],
        "invoice_amount": ["invoice_total", "claim_amount", "amount_inr"],
    }

    def evaluate(self, rules: list[Rule], invoice: dict[str, Any]) -> list[ExecutionResult]:
        logger.info("Rule evaluation started rules=%s", len(rules))
        results: list[ExecutionResult] = []
        for rule in rules:
            if self._is_structural_rule(rule):
                results.append(
                    ExecutionResult(
                        rule_id=rule.rule_id,
                        matched=False,
                        reason="Structural rule - not evaluated",
                        action=None,
                    )
                )
                continue

            if not self._is_evaluable_condition(rule.condition):
                results.append(
                    ExecutionResult(
                        rule_id=rule.rule_id,
                        matched=False,
                        reason="Non-executable condition format - not evaluated",
                        action=None,
                    )
                )
                continue

            matched, missing_fields = self._eval_condition(rule.condition, invoice)
            if missing_fields:
                reason = f"Missing invoice fields: {', '.join(sorted(missing_fields))}"
            else:
                reason = "Condition matched" if matched else "Condition not matched"
            results.append(
                ExecutionResult(
                    rule_id=rule.rule_id,
                    matched=matched,
                    reason=reason,
                    action=rule.action if matched else None,
                )
            )
        logger.info("Rule evaluation completed matched=%s", sum(1 for item in results if item.matched))
        return results

    @staticmethod
    def _is_structural_rule(rule: Rule) -> bool:
        return rule.confidence < 0.75 or rule.category == "general_policy"

    def _is_evaluable_condition(self, condition: dict[str, Any]) -> bool:
        if not isinstance(condition, dict) or not condition:
            return False
        if "all" in condition:
            children = condition.get("all", [])
            return isinstance(children, list) and all(self._is_evaluable_condition(child) for child in children)
        if "any" in condition:
            children = condition.get("any", [])
            return isinstance(children, list) and all(self._is_evaluable_condition(child) for child in children)
        metric = condition.get("metric")
        op = condition.get("op")
        if not metric or op not in self.SUPPORTED_OPS:
            return False
        if op == "between":
            return "min" in condition and "max" in condition
        return "value" in condition

    def _eval_condition(self, condition: dict[str, Any], invoice: dict[str, Any]) -> tuple[bool, set[str]]:
        if not condition:
            return False, set()
        if "all" in condition:
            all_match = True
            missing: set[str] = set()
            for child in condition["all"]:
                child_match, child_missing = self._eval_condition(child, invoice)
                all_match = all_match and child_match
                missing.update(child_missing)
            return all_match, missing
        if "any" in condition:
            any_match = False
            missing: set[str] = set()
            for child in condition["any"]:
                child_match, child_missing = self._eval_condition(child, invoice)
                any_match = any_match or child_match
                missing.update(child_missing)
            return any_match, missing

        metric = condition.get("metric")
        op = condition.get("op")
        value = condition.get("value")
        if metric == "always_true":
            return True, set()
        if not metric:
            return False, set()
        metric_found, current = self._get_metric_value(metric, invoice)
        if not metric_found:
            return False, {metric}

        if op == "==":
            return current == value, set()
        if op == "!=":
            return current != value, set()
        if op == ">":
            return self._to_float(current) > self._to_float(value), set()
        if op == ">=":
            return self._to_float(current) >= self._to_float(value), set()
        if op == "<":
            return self._to_float(current) < self._to_float(value), set()
        if op == "<=":
            return self._to_float(current) <= self._to_float(value), set()
        if op == "between":
            min_value = condition.get("min")
            max_value = condition.get("max")
            numeric_current = self._to_float(current)
            return self._to_float(min_value) <= numeric_current <= self._to_float(max_value), set()
        return False, set()

    def _get_metric_value(self, metric: str, invoice: dict[str, Any]) -> tuple[bool, Any]:
        if metric in invoice:
            return True, invoice.get(metric)
        for alias in self.METRIC_ALIASES.get(metric, []):
            if alias in invoice:
                return True, invoice.get(alias)
        return False, None

    @staticmethod
    def _to_float(value: Any) -> float:
        if value is None:
            return 0.0
        if isinstance(value, bool):
            return 1.0 if value else 0.0
        if isinstance(value, (int, float)):
            return float(value)
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
