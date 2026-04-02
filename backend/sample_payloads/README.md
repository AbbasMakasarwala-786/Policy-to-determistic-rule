# Sample Payloads

- `ap_invoice_legacy_metrics.json`: Uses the original AP metric names so legacy AP rule behavior can be reproduced.
- `hr_claim_aligned_metrics.json`: Minimal HR claim payload aligned to current extractor + metric alias handling.

Use either as `sample_invoice` in `POST /api/v1/pipeline/run/{document_id}`.
