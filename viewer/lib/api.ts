export const API = process.env.KEEL_API_URL ?? "http://127.0.0.1:8400";

export type SessionRow = { id: string; created_at: string; n_requests: number; n_compactions: number };
export type Message = {
  role: string;
  content?: string | null | Array<{ type: string; text?: string }>;
  tool_calls?: Array<{ id: string; function: { name: string; arguments: string } }>;
  tool_call_id?: string;
  name?: string;
};
export type RequestRow = {
  id: number; session_id: string | null; turn_idx: number; upstream_model: string; status: number;
  cache_status: string; compacted: number; tokenizer: string; tokens_in_raw: number;
  tokens_in_sent: number; tokens_out: number | null; pin_tokens: number; proxy_ms: number;
  upstream_ms: number; llm_ms: number; error: string | null; created_at: string;
};
export type CompactionRow = {
  id: number; session_id: string; turn_idx: number; strategy: string; prefix_len: number;
  prefix_hash: string; prefix_hashes: string[]; tokens_before: number; tokens_after: number;
  evicted: Message[]; compacted: Message[]; summary_text: string | null; pins_injected: string[];
  validator: Record<string, unknown> | null; llm_tokens: number; active: boolean;
};
export type PinRow = {
  id: number; session_id: string; text: string; source: "explicit" | "auto";
  source_turn: number | null; confidence: number; active: boolean;
};
export type TraceDetail = {
  session: { id: string; created_at: string; config: Record<string, unknown> };
  requests: RequestRow[]; compactions: CompactionRow[]; pins: PinRow[];
};

export async function listSessions(): Promise<SessionRow[]> {
  const r = await fetch(`${API}/v1/traces?limit=100`, { cache: "no-store" });
  if (!r.ok) throw new Error(`GET /v1/traces failed: ${r.status}`);
  return (await r.json()).data as SessionRow[];
}

export async function getTrace(id: string): Promise<TraceDetail | null> {
  const r = await fetch(`${API}/v1/traces/${encodeURIComponent(id)}`, { cache: "no-store" });
  if (r.status === 404) return null;
  if (!r.ok) throw new Error(`GET /v1/traces/${id} failed: ${r.status}`);
  return (await r.json()) as TraceDetail;
}

export function messageText(m: Message): string {
  let text = "";
  if (typeof m.content === "string") text = m.content;
  else if (Array.isArray(m.content))
    text = m.content.filter((p) => p.type === "text").map((p) => p.text ?? "").join("\n");
  for (const c of m.tool_calls ?? []) {
    text += `${text ? "\n" : ""}→ ${c.function.name}(${c.function.arguments})`;
  }
  return text;
}
