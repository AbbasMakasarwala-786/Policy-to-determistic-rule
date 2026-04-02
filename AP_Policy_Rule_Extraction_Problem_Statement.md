# Problem A: Policy Document to Deterministic Rule Conversion

---

## Overview

In Accounts Payable (AP) automation, companies follow detailed policy documents that govern how invoices are validated, matched against Purchase Orders (POs) and Goods Receipt Notes (GRNs), and routed for approval. Today, human analysts manually read these policies and hand-code business rules into rule engines — a process that is slow, error-prone, and doesn't scale.

**Your task** is to build a system that takes an AP policy document as input and produces a structured, deterministic set of rules as output — rules that a machine can execute without ambiguity.

---

## Problem Definition

### Input

A policy document (**PDF or plain text**) containing AP business rules.

> A sample **Cashflo AP Policy Document** is provided as the primary input, covering:
> - Three-way match rules (PO → GRN → Invoice)
> - Tax compliance
> - Approval thresholds
> - Deviation handling

### Output

A **structured rule representation** (JSON, YAML, or a domain-specific format) that captures every condition, threshold, exception, and action from the document in a machine-executable format.

---

## What Your Solution Should Demonstrate

### 1. Document Parsing

Extract and segment text from the AP policy. Your parser must handle:

- Sections and subsections
- Numbered clauses
- Cross-references (e.g., *"Refer Section 2.3(b)"*)
- Conditional tables

### 2. Rule Extraction

Use an LLM (or a combination of LLM + NLP) to identify rules. Each extracted rule must have:

| Component | Description |
|-----------|-------------|
| **Conditions** (`IF`) | The triggering criteria |
| **Actions** (`THEN`) | What the system must do |
| **Exceptions** (`ELSE` / `UNLESS`) | Override or edge-case logic |

Pay special attention to **three-way match logic**:

- PO Amount vs. Invoice Amount
- PO Qty vs. Invoice Qty
- GRN Qty vs. Invoice Qty
- Tolerance thresholds
- Escalation paths

### 3. Structured Output

Produce **deterministic rules** in a structured format. Each rule must be unambiguously machine-executable.

**Example rule (JSON format):**

```json
{
  "rule_id": "AP-TWM-001",
  "source_clause": "Section 2.2(c)",
  "description": "Escalate invoice if amount exceeds PO by >= 10%",
  "condition": {
    "operator": "AND",
    "operands": [
      { "field": "invoice_total", "op": ">", "value": "po_amount * 1.10" },
      { "field": "deviation_pct", "op": ">=", "value": 10 }
    ]
  },
  "action": "ESCALATE_TO_FINANCE_CONTROLLER",
  "requires_justification": true,
  "notification": {
    "type": "email",
    "to": ["finance_controller", "internal_audit"],
    "within_minutes": 15
  }
}
```

### 4. Conflict Detection

Identify **contradictory or overlapping rules** within the document and flag them.

> **Example conflict:** Section 2.2(b) and Section 5.1 may conflict on who approves invoices in the INR 1L–10L range.

### 5. Traceability

Every generated rule **must map back** to the specific section and clause in the source document so a human reviewer can verify it.

---

## Key Rules to Extract (from the attached policy)

The sample AP policy contains rules across these categories. Your system should extract **all** of them.

### Three-Way Match Rules

#### Invoice Amount vs. PO Amount

| Deviation | Action |
|-----------|--------|
| Within ±1% | Auto-approve |
| 1% – 10% over | Route to Department Head |
| ≥ 10% over | Escalate to Finance Controller |
| > 5% under (under-invoicing) | Flag for review |

#### Line-Item Quantity

| Condition | Action |
|-----------|--------|
| Invoice Qty > PO Qty | Hold invoice |
| Unit Rate differs > 2% | Flag and route to Procurement |

#### GRN Match

| Condition | Action |
|-----------|--------|
| Invoice Qty > GRN Qty | Reject invoice |
| GRN date is after Invoice date | Flag for review |

---

### Compliance & Tax Rules

- **GSTIN validation** against vendor master
- **PAN-GSTIN cross-check**
- **Intra-state transactions:** CGST = SGST; IGST must be absent
- **Inter-state transactions:** IGST only; CGST and SGST must be absent
- **Grand Total check:** Taxable Amount + Tax = Grand Total (within INR 1 rounding tolerance)

---

### Approval Matrix

| Invoice Amount (INR) | Approver |
|----------------------|----------|
| Up to 1 Lakh | Auto-approve |
| 1 Lakh – 10 Lakh | Department Head |
| 10 Lakh – 50 Lakh | Finance Controller |
| > 50 Lakh | CFO |

> **Exception:** Watchlist vendors **always** require Department Head approval, regardless of invoice amount.

---

## Bonus: Extend Your Solution

The core deliverable is rule extraction. The following extensions demonstrate additional depth and are encouraged but not required.

### Email Notifications on Deviation *(Bonus)*

When a rule fires a deviation (e.g., Invoice Amount > PO Amount by 10%), generate and send an email notification to the relevant stakeholder.

Use the notification rules from **Section 6** of the attached policy. Include the following in the email body:

- Invoice Number
- Vendor Name
- Deviation Type
- Recommended Action

---

### Rule Execution Engine *(Bonus)*

Don't just extract rules — build a **lightweight engine** that executes them against a sample invoice JSON and returns pass/fail results with reasons.

---

### Visual Rule Graph *(Bonus)*

Render the extracted rules as a **decision tree or flowchart** showing the routing logic visually.

---

### Confidence Scoring *(Bonus)*

For each extracted rule, output a **confidence score** indicating how certain the LLM is about the extraction. Flag low-confidence rules for human review.

---

### Multi-Document Support *(Bonus)*

Show that your pipeline works on a second, different policy document (e.g., a procurement policy or an HR reimbursement policy).

---

## Evaluation Criteria

| Criteria | What We Look For |
|----------|-----------------|
| **Accuracy** | Does the system correctly extract conditions, thresholds, and exceptions from the AP policy? |
| **Completeness** | Are all rules captured, including edge cases, cross-references, and the approval matrix? |
| **Determinism** | Can the output be fed into a rule engine and executed without human interpretation? |
| **Architecture** | Is the pipeline modular? (`parsing → extraction → structuring → validation`) |
| **AI Usage** | How thoughtfully is the LLM used? Are prompts well-engineered? Is the LLM used only where it adds value over deterministic code? |

---

## Suggested Pipeline Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    AP Policy Document                    │
│                   (PDF / Plain Text)                     │
└──────────────────────────┬──────────────────────────────┘
                           │
                           ▼
              ┌────────────────────────┐
              │    1. Document Parser  │
              │  (sections, clauses,   │
              │   cross-references,    │
              │   conditional tables)  │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │   2. Rule Extractor    │
              │  (LLM + NLP: IF/THEN/  │
              │   UNLESS conditions,   │
              │   thresholds, actions) │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │   3. Rule Structurer   │
              │  (JSON/YAML output,    │
              │   source traceability, │
              │   confidence scores)   │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │  4. Conflict Detector  │
              │  (overlap detection,   │
              │   contradiction flags) │
              └───────────┬────────────┘
                          │
                          ▼
              ┌────────────────────────┐
              │   5. Rule Engine       │
              │  (execute against      │
              │   sample invoice,      │
              │   pass/fail + reason)  │
              └────────────────────────┘
```

---

## Deliverables Checklist

- [ ] Source code with clear module separation
- [ ] Structured rule output (JSON or YAML) for the provided Cashflo AP policy
- [ ] Conflict/overlap report for detected contradictions
- [ ] Traceability map: `rule_id → source_clause → section`
- [ ] *(Bonus)* Rule execution results against a sample invoice
- [ ] *(Bonus)* Visual decision tree / flowchart
- [ ] *(Bonus)* Confidence scores per rule
- [ ] README with setup instructions and architecture explanation

---

*Primary input document: **Cashflo AP Policy Document** (attached)*
