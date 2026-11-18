# T-35: Viewer scaffold and session list

## Goal
Create the Next.js + Tailwind trace viewer in `viewer/`, with a typed client for Keel's trace API and a home page listing sessions newest first.

## Context
PRD FR-16: Next.js trace viewer with a session list, per-turn timeline, a before/after diff of each compaction, and pins highlighted (the detail views are T-36). The viewer talks **only** to the trace API. Use Next.js App Router **server components** that fetch server-side, so Keel needs no CORS. The API base URL comes from `process.env.KEEL_API_URL` (default `http://127.0.0.1:8400`).

Dependencies named by this task: `next@14.2.15`, `react@18.3.1`, `react-dom@18.3.1`, `tailwindcss@3.4.x`, `typescript`, `eslint`, `eslint-config-next@14.2.15`, all installed by `create-next-app`. Add nothing else.

Trace API responses:
```
GET /v1/traces?limit=100 -> {"data": [{"id": str, "created_at": str, "n_requests": int, "n_compactions": int}]}
GET /v1/traces/{session_id} -> {"session": {"id","created_at","config":{},"extracted_upto","extracted_hash"},
   "requests": [RequestRow], "compactions": [CompactionRow], "pins": [PinRow]}
```
Types (put them in `viewer/lib/api.ts` exactly):
```ts
export type SessionRow = { id: string; created_at: string; n_requests: number; n_compactions: number };
export type Message = { role: string; content?: string | null | Array<{ type: string; text?: string }>;
  tool_calls?: Array<{ id: string; function: { name: string; arguments: string } }>; tool_call_id?: string; name?: string };
export type RequestRow = { id: number; session_id: string | null; turn_idx: number; upstream_model: string; status: number;
  cache_status: string; compacted: number; tokenizer: string; tokens_in_raw: number; tokens_in_sent: number;
  tokens_out: number | null; pin_tokens: number; proxy_ms: number; upstream_ms: number; llm_ms: number;
  error: string | null; created_at: string };
export type CompactionRow = { id: number; session_id: string; turn_idx: number; strategy: string; prefix_len: number;
  prefix_hash: string; prefix_hashes: string[]; tokens_before: number; tokens_after: number; evicted: Message[];
  compacted: Message[]; summary_text: string | null; pins_injected: string[]; validator: Record<string, unknown> | null;
  llm_tokens: number; active: boolean };
export type PinRow = { id: number; session_id: string; text: string; source: "explicit" | "auto";
  source_turn: number | null; confidence: number; active: boolean };
export type TraceDetail = { session: { id: string; created_at: string; config: Record<string, unknown> };
  requests: RequestRow[]; compactions: CompactionRow[]; pins: PinRow[] };
```

## Files
Generate the scaffold with the command below; generated files don't count toward the file limit. Then modify or create:
- `viewer/lib/api.ts`
- `viewer/app/page.tsx`
- `viewer/app/layout.tsx`
- `viewer/.env.example`

Read: none beyond this file.

## Implement
1. From the repo root: `npx create-next-app@14.2.15 viewer --ts --tailwind --eslint --app --no-src-dir --import-alias "@/*" --use-npm`. Accept no other prompts; if asked, answer No.
2. `lib/api.ts`:
   - The types above, plus `export const API = process.env.KEEL_API_URL ?? "http://127.0.0.1:8400";`.
   - `export async function listSessions(): Promise<SessionRow[]>` and `export async function getTrace(id: string): Promise<TraceDetail | null>` (404 → null). Both use `fetch(url, { cache: "no-store" })`; `encodeURIComponent` the id.
   - `export function messageText(m: Message): string`: string content, or text parts joined, plus `→ name(arguments)` lines for tool calls.
3. `app/layout.tsx`: title "Keel traces"; a simple header with a link to `/`; Tailwind base styles.
4. `app/page.tsx` (async server component):
   - A table with columns Session (a link to `/sessions/[id]`, URL-encoded), Created, Requests, Compactions.
   - Empty state: "No sessions yet. Point an agent at Keel with an X-Keel-Session header."
   - If the fetch fails, show an error box naming `KEEL_API_URL`.
5. `.env.example`: `KEEL_API_URL=http://127.0.0.1:8400`.

## Tests
No JS test framework (no new deps). The type-check and build are the tests.

## Acceptance
```bash
cd viewer && npm run lint
cd viewer && npm run build
```
Both exit 0. The build must not need Keel to be running: the page uses `cache: "no-store"`, so it renders dynamically. If the build tries to prerender `/`, add `export const dynamic = "force-dynamic";` to `page.tsx`.

## Out of scope
The session detail page (T-36), any Python changes, CORS.

## Depends on
T-10

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
