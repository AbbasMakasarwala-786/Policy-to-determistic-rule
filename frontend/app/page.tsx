"use client";

import { ChangeEvent, FormEvent, ReactNode, useMemo, useState } from "react";

type Rule = {
  rule_id: string;
  source_clause: string;
  category: string;
  description: string;
  action: string;
  confidence: number;
  needs_review: boolean;
};

type Conflict = {
  conflict_id: string;
  reason: string;
  severity: string;
  rule_ids: string[];
  source_clauses: string[];
};

type ExecutionResult = {
  rule_id: string;
  matched: boolean;
  reason: string;
  action?: string | null;
};

type NotificationEvent = {
  recipient: string;
  subject: string;
  status: string;
  rule_id: string;
};

type PipelineResponse = {
  run_id: string;
  document_id: string;
  rules_count: number;
  conflicts_count: number;
  rules: Rule[];
  conflicts: Conflict[];
  execution_results: ExecutionResult[];
  notifications: NotificationEvent[];
};

type GraphNode = {
  id: string;
  label: string;
  kind: "start" | "category" | "action" | "end";
  x: number;
  y: number;
  meta?: string;
};

type GraphEdge = {
  id: string;
  from: string;
  to: string;
  conflict: boolean;
};

const API_BASE = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8000/api/v1";
const REQUIRED_AP_CATEGORIES = ["three_way_match", "compliance_tax", "approval_matrix"] as const;

export default function Home() {
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [documentId, setDocumentId] = useState<string>("");
  const [useLlm, setUseLlm] = useState<boolean>(true);
  const [notifyOnDeviation, setNotifyOnDeviation] = useState<boolean>(false);
  const [status, setStatus] = useState<string>("Drop the policy doc and run extraction.");
  const [isUploading, setIsUploading] = useState<boolean>(false);
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [categoryFilter, setCategoryFilter] = useState<string>("all");
  const [matchFilter, setMatchFilter] = useState<"all" | "matched" | "not_matched">("all");
  const [requiredOnly, setRequiredOnly] = useState<boolean>(false);
  const [result, setResult] = useState<PipelineResponse | null>(null);
  const [invoiceJson, setInvoiceJson] = useState<string>(
    JSON.stringify(
      {
        invoice_amount: 1200000,
        invoice_po_deviation_pct: 12,
        invoice_po_deviation_pct_abs: 12,
        invoice_qty_gt_po_qty: false,
        unit_rate_deviation_pct_abs: 1.8,
        invoice_qty_gt_grn_qty: false,
        grn_date_after_invoice_date: false,
        gstin_matches_vendor_master: true,
        pan_gstin_matches: true,
        vendor_watchlist: false,
        compliance_failure: false,
        deviation_detected: true
      },
      null,
      2
    )
  );

  const needsReviewCount = useMemo(
    () => result?.rules.filter((rule) => rule.needs_review).length ?? 0,
    [result]
  );
  const executionByRuleId = useMemo(() => {
    if (!result) {
      return new Map<string, ExecutionResult>();
    }
    return new Map(result.execution_results.map((entry) => [entry.rule_id, entry]));
  }, [result]);
  const filteredRules = useMemo(() => {
    if (!result) {
      return [] as Rule[];
    }
    return result.rules.filter((rule) => {
      if (requiredOnly && !REQUIRED_AP_CATEGORIES.includes(rule.category as (typeof REQUIRED_AP_CATEGORIES)[number])) {
        return false;
      }
      if (categoryFilter !== "all" && rule.category !== categoryFilter) {
        return false;
      }
      const execution = executionByRuleId.get(rule.rule_id);
      if (matchFilter === "matched") {
        return Boolean(execution?.matched);
      }
      if (matchFilter === "not_matched") {
        return execution ? !execution.matched : true;
      }
      return true;
    });
  }, [result, categoryFilter, matchFilter, requiredOnly, executionByRuleId]);
  const keyCategoryCounts = useMemo(() => {
    const counts = {
      three_way_match: 0,
      compliance_tax: 0,
      approval_matrix: 0
    };
    if (!result) {
      return counts;
    }
    result.rules.forEach((rule) => {
      if (rule.category === "three_way_match") counts.three_way_match += 1;
      if (rule.category === "compliance_tax") counts.compliance_tax += 1;
      if (rule.category === "approval_matrix") counts.approval_matrix += 1;
    });
    return counts;
  }, [result]);
  const allCategories = useMemo(() => {
    if (!result) {
      return [] as string[];
    }
    return [...new Set(result.rules.map((rule) => rule.category))].sort();
  }, [result]);
  const graphData = useMemo(() => {
    if (!result) {
      return { nodes: [] as GraphNode[], edges: [] as GraphEdge[] };
    }
    return buildRuleGraph(result);
  }, [result]);

  const uploadDocument = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedFile) {
      setStatus("Choose a document first.");
      return;
    }

    setIsUploading(true);
    setStatus("Uploading and parsing document...");
    try {
      const formData = new FormData();
      formData.append("file", selectedFile);
      const response = await fetch(`${API_BASE}/documents/upload`, {
        method: "POST",
        body: formData
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const payload = await response.json();
      setDocumentId(payload.document_id);
      setStatus(`Parsed ${payload.clauses_count} clauses from ${payload.filename}.`);
    } catch (error) {
      setStatus(`Upload failed: ${String(error)}`);
    } finally {
      setIsUploading(false);
    }
  };

  const runPipeline = async () => {
    if (!documentId) {
      setStatus("Upload a document before running extraction.");
      return;
    }

    setIsRunning(true);
    setStatus("Running extraction + conflict detection...");

    try {
      let sampleInvoice: Record<string, unknown> | null = null;
      if (invoiceJson.trim()) {
        sampleInvoice = JSON.parse(invoiceJson);
      }
      const response = await fetch(`${API_BASE}/pipeline/run/${documentId}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          use_llm: useLlm,
          llm_mode: useLlm ? "assist" : "off",
          max_llm_calls: 4,
          notify_on_deviation: notifyOnDeviation,
          recipients: [],
          sample_invoice: sampleInvoice
        })
      });
      if (!response.ok) {
        throw new Error(await response.text());
      }
      const payload: PipelineResponse = await response.json();
      setResult(payload);
      setStatus(`Run ${payload.run_id} finished with ${payload.rules_count} rules.`);
    } catch (error) {
      setStatus(`Pipeline failed: ${String(error)}`);
    } finally {
      setIsRunning(false);
    }
  };

  const onFileChange = (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] ?? null;
    setSelectedFile(file);
  };

  const showProblemStatementRules = () => {
    setRequiredOnly(true);
    setCategoryFilter("all");
    setMatchFilter("all");
  };

  const showUnmatchedRequiredRules = () => {
    setRequiredOnly(true);
    setCategoryFilter("all");
    setMatchFilter("not_matched");
  };

  const resetRuleFilters = () => {
    setRequiredOnly(false);
    setCategoryFilter("all");
    setMatchFilter("all");
  };

  return (
    <div className="grain min-h-screen p-4 md:p-8">
      <main className="mx-auto max-w-7xl">
        <section className="mb-6 rounded-3xl border border-black/10 bg-[var(--panel)] p-6 shadow-[0_14px_40px_-18px_rgba(15,17,20,0.35)] md:p-8">
          <div className="flex flex-col gap-5 md:flex-row md:items-end md:justify-between">
            <div>
              <p className="font-mono text-xs uppercase tracking-[0.22em] text-[var(--ink-soft)]">
                AP Policy Rule Studio
              </p>
              <h1 className="mt-2 text-3xl font-semibold leading-tight md:text-5xl">
                Upload. Extract. Validate.
              </h1>
              <p className="mt-2 max-w-2xl text-sm text-[var(--ink-soft)] md:text-base">
                Interview-ready UI for rule extraction with deterministic JSON, conflict detection, execution checks, and email triggering.
              </p>
            </div>
            <div className="rounded-2xl bg-black px-4 py-3 text-sm text-white">
              Backend: <span className="font-mono">{API_BASE}</span>
            </div>
          </div>
        </section>

        <section className="grid gap-6 lg:grid-cols-[1.15fr_0.85fr]">
          <div className="space-y-6">
            <article className="rounded-3xl border border-black/10 bg-[var(--panel)] p-6">
              <h2 className="text-xl font-semibold">1) Upload Policy Document</h2>
              <form className="mt-4 space-y-4" onSubmit={uploadDocument}>
                <label className="block rounded-2xl border-2 border-dashed border-black/20 bg-white/80 p-5 text-sm">
                  <span className="block text-[var(--ink-soft)]">Supported: `.md`, `.txt`, `.pdf`</span>
                  <input className="mt-3 block w-full text-sm" type="file" accept=".md,.txt,.pdf" onChange={onFileChange} />
                </label>
                <button
                  disabled={isUploading}
                  className="rounded-xl bg-[var(--accent)] px-5 py-2.5 font-semibold text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                  type="submit"
                >
                  {isUploading ? "Uploading..." : "Upload & Parse"}
                </button>
              </form>
              {documentId ? (
                <p className="mt-3 font-mono text-xs text-[var(--accent-2)]">document_id: {documentId}</p>
              ) : null}
            </article>

            <article className="rounded-3xl border border-black/10 bg-[var(--panel)] p-6">
              <h2 className="text-xl font-semibold">2) Run Extraction Pipeline</h2>
              <div className="mt-4 flex flex-wrap gap-4 text-sm">
                <label className="inline-flex items-center gap-2 rounded-full border border-black/15 bg-white px-3 py-2">
                  <input type="checkbox" checked={useLlm} onChange={(e) => setUseLlm(e.target.checked)} />
                  Use LLM (Mistral)
                </label>
                <label className="inline-flex items-center gap-2 rounded-full border border-black/15 bg-white px-3 py-2">
                  <input
                    type="checkbox"
                    checked={notifyOnDeviation}
                    onChange={(e) => setNotifyOnDeviation(e.target.checked)}
                  />
                  Notify on deviations
                </label>
              </div>
              <label className="mt-4 block">
                <span className="text-sm text-[var(--ink-soft)]">Sample Invoice JSON</span>
                <textarea
                  className="mt-2 h-52 w-full rounded-2xl border border-black/15 bg-white p-3 font-mono text-xs outline-none focus:border-[var(--accent-2)]"
                  value={invoiceJson}
                  onChange={(e) => setInvoiceJson(e.target.value)}
                />
              </label>
              <button
                disabled={isRunning}
                onClick={runPipeline}
                className="mt-4 rounded-xl bg-[var(--accent-2)] px-5 py-2.5 font-semibold text-white transition hover:brightness-95 disabled:cursor-not-allowed disabled:opacity-60"
                type="button"
              >
                {isRunning ? "Running..." : "Run Pipeline"}
              </button>
            </article>
          </div>

          <aside className="space-y-6">
            <article className="rounded-3xl border border-black/10 bg-[var(--panel)] p-6">
              <h2 className="text-lg font-semibold">Live Status</h2>
              <p className="mt-3 rounded-2xl border border-black/10 bg-white p-3 text-sm">{status}</p>
            </article>

            <article className="rounded-3xl border border-black/10 bg-[var(--panel)] p-6">
              <h2 className="text-lg font-semibold">Run Snapshot</h2>
              <div className="mt-3 grid grid-cols-2 gap-3">
                <MetricCard label="Rules" value={result?.rules_count ?? 0} tone="orange" />
                <MetricCard label="Conflicts" value={result?.conflicts_count ?? 0} tone="red" />
                <MetricCard label="Needs Review" value={needsReviewCount} tone="teal" />
                <MetricCard label="Emails" value={result?.notifications.length ?? 0} tone="ink" />
              </div>
            </article>
          </aside>
        </section>

        {result ? (
          <section className="mt-6 rounded-3xl border border-black/10 bg-[var(--panel)] p-4 md:p-6">
            <h2 className="text-xl font-semibold">Problem Statement Visibility</h2>
            <p className="mt-1 text-sm text-[var(--ink-soft)]">
              Required AP categories are surfaced here: Three-Way Match, Compliance & Tax, and Approval Matrix.
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-3">
              <MetricCard label="Three-Way Match" value={keyCategoryCounts.three_way_match} tone="teal" />
              <MetricCard label="Compliance & Tax" value={keyCategoryCounts.compliance_tax} tone="orange" />
              <MetricCard label="Approval Matrix" value={keyCategoryCounts.approval_matrix} tone="ink" />
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                onClick={showProblemStatementRules}
                className="rounded-full bg-[var(--accent-2)] px-3 py-1 text-xs text-white"
              >
                Show only Problem Statement Rules
              </button>
              <button
                type="button"
                onClick={showUnmatchedRequiredRules}
                className="rounded-full bg-red-700 px-3 py-1 text-xs text-white"
              >
                Show only unmatched required rules
              </button>
              <button
                type="button"
                onClick={resetRuleFilters}
                className="rounded-full border border-black/25 bg-white px-3 py-1 text-xs"
              >
                Reset filters
              </button>
            </div>
          </section>
        ) : null}

        {result ? (
          <section className="mt-6 grid gap-6 lg:grid-cols-3">
            <Panel title={`Rules (${filteredRules.length}/${result.rules.length})`}>
              <div className="mb-3 space-y-2">
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setRequiredOnly(false);
                      setCategoryFilter("all");
                    }}
                    className={`rounded-full px-3 py-1 text-xs ${categoryFilter === "all" ? "bg-black text-white" : "bg-white border border-black/20"}`}
                  >
                    all
                  </button>
                  {allCategories.map((category) => (
                    <button
                      key={category}
                      type="button"
                      onClick={() => {
                        setRequiredOnly(false);
                        setCategoryFilter(category);
                      }}
                      className={`rounded-full px-3 py-1 text-xs ${
                        categoryFilter === category ? "bg-[var(--accent-2)] text-white" : "bg-white border border-black/20"
                      }`}
                    >
                      {category}
                    </button>
                  ))}
                </div>
                <div className="flex flex-wrap gap-2">
                  <button
                    type="button"
                    onClick={() => setMatchFilter("all")}
                    className={`rounded-full px-3 py-1 text-xs ${matchFilter === "all" ? "bg-black text-white" : "bg-white border border-black/20"}`}
                  >
                    all match states
                  </button>
                  <button
                    type="button"
                    onClick={() => setMatchFilter("matched")}
                    className={`rounded-full px-3 py-1 text-xs ${matchFilter === "matched" ? "bg-teal-700 text-white" : "bg-white border border-black/20"}`}
                  >
                    matched
                  </button>
                  <button
                    type="button"
                    onClick={() => setMatchFilter("not_matched")}
                    className={`rounded-full px-3 py-1 text-xs ${matchFilter === "not_matched" ? "bg-red-700 text-white" : "bg-white border border-black/20"}`}
                  >
                    not matched
                  </button>
                </div>
                {requiredOnly ? <p className="text-xs text-[var(--ink-soft)]">quick filter: required AP categories only</p> : null}
              </div>
              <div className="space-y-3">
                {filteredRules.map((rule) => {
                  const execution = executionByRuleId.get(rule.rule_id);
                  return (
                  <div key={rule.rule_id} className="rounded-2xl border border-black/10 bg-white p-3">
                    <div className="flex items-start justify-between gap-2">
                      <p className="font-mono text-xs">{rule.rule_id}</p>
                      <span className="rounded-full bg-black px-2 py-1 font-mono text-[10px] text-white">{rule.category}</span>
                    </div>
                    <p className="mt-2 text-sm">{rule.description}</p>
                    <div className="mt-2 flex items-center justify-between text-xs">
                      <span>clause: {rule.source_clause}</span>
                      <span>confidence: {rule.confidence.toFixed(2)}</span>
                    </div>
                    <div className="mt-1 text-xs text-[var(--ink-soft)]">
                      status:{" "}
                      <span className={execution?.matched ? "text-teal-700" : "text-red-700"}>
                        {execution ? (execution.matched ? "matched" : "not matched") : "not executed"}
                      </span>
                    </div>
                  </div>
                  );
                })}
              </div>
            </Panel>

            <Panel title={`Conflicts (${result.conflicts.length})`}>
              <div className="space-y-3">
                {result.conflicts.length === 0 ? (
                  <p className="text-sm text-[var(--ink-soft)]">No conflicts detected.</p>
                ) : (
                  result.conflicts.map((conflict) => (
                    <div key={conflict.conflict_id} className="rounded-2xl border border-[var(--danger)]/25 bg-red-50 p-3">
                      <p className="font-mono text-xs text-[var(--danger)]">{conflict.conflict_id}</p>
                      <p className="mt-1 text-sm">{conflict.reason}</p>
                      <p className="mt-1 text-xs text-[var(--ink-soft)]">rules: {conflict.rule_ids.join(", ")}</p>
                    </div>
                  ))
                )}
              </div>
            </Panel>

            <Panel title={`Execution (${result.execution_results.length})`}>
              <div className="space-y-2">
                {result.execution_results.length === 0 ? (
                  <p className="text-sm text-[var(--ink-soft)]">No sample invoice executed.</p>
                ) : (
                  result.execution_results.map((item) => (
                    <div
                      key={item.rule_id}
                      className={`rounded-xl border p-2 text-sm ${
                        item.matched ? "border-teal-700/30 bg-teal-50" : "border-black/10 bg-white"
                      }`}
                    >
                      <div className="flex items-center justify-between">
                        <span className="font-mono text-xs">{item.rule_id}</span>
                        <span className="text-xs">{item.matched ? "matched" : "not matched"}</span>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </Panel>
          </section>
        ) : null}

        {result ? (
          <section className="mt-6">
            <article className="rounded-3xl border border-black/10 bg-[var(--panel)] p-4 md:p-6">
              <div className="mb-4 flex flex-col gap-2 md:flex-row md:items-end md:justify-between">
                <div>
                  <h2 className="text-2xl font-semibold">Visual Rule Graph</h2>
                  <p className="text-sm text-[var(--ink-soft)]">
                    Decision flow from categories to actions. Conflict-linked actions are marked in red.
                  </p>
                </div>
                <div className="flex gap-2 text-xs">
                  <Legend label="Start/End" className="bg-black text-white" />
                  <Legend label="Category" className="bg-teal-100 text-teal-900" />
                  <Legend label="Action" className="bg-orange-100 text-orange-900" />
                  <Legend label="Conflict Edge" className="bg-red-100 text-red-900" />
                </div>
              </div>
              <RuleGraph nodes={graphData.nodes} edges={graphData.edges} />
            </article>
          </section>
        ) : null}
      </main>
    </div>
  );
}

function RuleGraph({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const width = 1200;
  const height = Math.max(520, nodes.length * 36);

  const byId = new Map(nodes.map((node) => [node.id, node]));
  return (
    <div className="overflow-x-auto rounded-2xl border border-black/10 bg-white p-3">
      <svg width={width} height={height} className="block min-w-[960px]">
        <defs>
          <marker id="arrow-teal" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse">
            <path d="M0,0 L8,4 L0,8 z" fill="#0f766e" />
          </marker>
          <marker id="arrow-red" markerWidth="8" markerHeight="8" refX="7" refY="4" orient="auto-start-reverse">
            <path d="M0,0 L8,4 L0,8 z" fill="#b91c1c" />
          </marker>
        </defs>
        {edges.map((edge) => {
          const from = byId.get(edge.from);
          const to = byId.get(edge.to);
          if (!from || !to) {
            return null;
          }
          return (
            <line
              key={edge.id}
              x1={from.x + 86}
              y1={from.y + 20}
              x2={to.x}
              y2={to.y + 20}
              stroke={edge.conflict ? "#b91c1c" : "#0f766e"}
              strokeWidth={edge.conflict ? 2.8 : 1.8}
              strokeDasharray={edge.conflict ? "6 5" : "0"}
              markerEnd={edge.conflict ? "url(#arrow-red)" : "url(#arrow-teal)"}
              opacity={0.85}
            />
          );
        })}
        {nodes.map((node) => (
          <g key={node.id}>
            <rect
              x={node.x}
              y={node.y}
              width={172}
              height={40}
              rx={12}
              fill={
                node.kind === "start" || node.kind === "end"
                  ? "#14110f"
                  : node.kind === "category"
                  ? "#ccfbf1"
                  : "#ffedd5"
              }
              stroke={node.kind === "action" && node.meta === "conflict" ? "#b91c1c" : "#14110f"}
              strokeWidth={node.kind === "action" && node.meta === "conflict" ? 2.2 : 1}
            />
            <text
              x={node.x + 10}
              y={node.y + 24}
              fill={node.kind === "start" || node.kind === "end" ? "#ffffff" : "#14110f"}
              style={{ fontSize: 11, fontFamily: "var(--font-ibm-plex-mono)" }}
            >
              {truncate(node.label, 24)}
            </text>
          </g>
        ))}
      </svg>
    </div>
  );
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <article className="rounded-3xl border border-black/10 bg-[var(--panel)] p-4 md:p-5">
      <h3 className="mb-3 text-lg font-semibold">{title}</h3>
      <div className="max-h-[32rem] overflow-auto pr-1">{children}</div>
    </article>
  );
}

function MetricCard({ label, value, tone }: { label: string; value: number; tone: "orange" | "red" | "teal" | "ink" }) {
  const toneClass =
    tone === "orange"
      ? "bg-orange-100 text-orange-900"
      : tone === "red"
      ? "bg-red-100 text-red-900"
      : tone === "teal"
      ? "bg-teal-100 text-teal-900"
      : "bg-black text-white";
  return (
    <div className={`rounded-2xl p-3 ${toneClass}`}>
      <p className="text-xs uppercase tracking-wide opacity-80">{label}</p>
      <p className="text-2xl font-semibold">{value}</p>
    </div>
  );
}

function Legend({ label, className }: { label: string; className: string }) {
  return <span className={`rounded-full px-2.5 py-1 font-mono ${className}`}>{label}</span>;
}

function truncate(input: string, maxLength: number) {
  if (input.length <= maxLength) {
    return input;
  }
  return `${input.slice(0, maxLength - 1)}…`;
}

function buildRuleGraph(result: PipelineResponse): { nodes: GraphNode[]; edges: GraphEdge[] } {
  const nodes: GraphNode[] = [];
  const edges: GraphEdge[] = [];

  const conflictActionIds = new Set<string>();
  result.conflicts.forEach((conflict) => {
    conflict.rule_ids.forEach((ruleId) => conflictActionIds.add(ruleId));
  });

  nodes.push({ id: "start", label: "Policy Input", kind: "start", x: 24, y: 220 });

  const categories = [...new Set(result.rules.map((rule) => rule.category))];
  categories.forEach((category, index) => {
    const categoryNodeId = `cat:${category}`;
    const y = 40 + index * 90;
    nodes.push({
      id: categoryNodeId,
      label: category.replaceAll("_", " "),
      kind: "category",
      x: 310,
      y
    });
    edges.push({
      id: `edge:start:${categoryNodeId}`,
      from: "start",
      to: categoryNodeId,
      conflict: false
    });

    const actions = [...new Set(result.rules.filter((rule) => rule.category === category).map((rule) => rule.action))];
    actions.forEach((action, actionIndex) => {
      const matchedRule = result.rules.find((rule) => rule.category === category && rule.action === action);
      if (!matchedRule) {
        return;
      }
      const actionNodeId = `action:${matchedRule.rule_id}`;
      const actionY = y + actionIndex * 44;
      const isConflict = conflictActionIds.has(matchedRule.rule_id);

      nodes.push({
        id: actionNodeId,
        label: action.replaceAll("_", " "),
        kind: "action",
        x: 610,
        y: actionY,
        meta: isConflict ? "conflict" : undefined
      });
      edges.push({
        id: `edge:${categoryNodeId}:${actionNodeId}`,
        from: categoryNodeId,
        to: actionNodeId,
        conflict: isConflict
      });
      edges.push({
        id: `edge:${actionNodeId}:end`,
        from: actionNodeId,
        to: "end",
        conflict: isConflict
      });
    });
  });

  nodes.push({ id: "end", label: "Approval Outcome", kind: "end", x: 970, y: 220 });
  return { nodes, edges };
}
