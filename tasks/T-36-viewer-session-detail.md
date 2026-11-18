# T-36: Viewer session detail: timeline, compaction diff, pins

## Goal
Add the session detail page: a per-turn request timeline, a before/after diff for each compaction (evicted messages vs compacted form, summary, validator result), and pins highlighted wherever their text appears.

## Context
PRD G4: the trace viewer shows exactly what each compaction evicted and what was re-injected. Week-5 exit: the viewer shows evicted spans and injected pins for any session.

Data comes from `getTrace(id)` in `viewer/lib/api.ts` (T-35). It returns `TraceDetail | null`:
```ts
type TraceDetail = { session: { id; created_at; config }; requests: RequestRow[]; compactions: CompactionRow[]; pins: PinRow[] };
// RequestRow: turn_idx, upstream_model, status, cache_status, compacted (0|1), tokens_in_raw, tokens_in_sent,
//             tokens_out, pin_tokens, proxy_ms, upstream_ms, llm_ms, error
// CompactionRow: id, turn_idx, strategy, prefix_len, tokens_before, tokens_after, evicted: Message[],
//                compacted: Message[], summary_text, pins_injected: string[], validator, active
// PinRow: id, text, source ("explicit"|"auto"), source_turn, confidence, active
// messageText(m: Message): string
```
Summary messages start with `[Summary of earlier conversation]`. Validator repairs append a block starting `Standing instructions (verbatim):`. Truncated tool outputs contain `[truncated N tokens]`.

## Files
Create:
- `viewer/app/sessions/[id]/page.tsx`
- `viewer/components/MessageView.tsx`
- `viewer/components/CompactionDiff.tsx`
- `viewer/components/Highlight.tsx`

Read: `viewer/lib/api.ts`.

## Implement
1. `Highlight.tsx`: `({ text, terms }: { text: string; terms: string[] })`. Split the text on case-insensitive occurrences of any term (escape regex chars) and wrap matches in `<mark className="bg-yellow-200">`. Also wrap `[truncated N tokens]` markers in a gray badge.
2. `MessageView.tsx`: a role badge (system / user / assistant / tool, each a different color), `tool_call_id` if present, and the content via `Highlight` with `whitespace-pre-wrap`. Content over 1,500 chars is collapsed behind a `<details>` "show all".
3. `CompactionDiff.tsx`: props `{ c: CompactionRow; pins: string[] }`.
   - Header: `turn {c.turn_idx} · {c.strategy} · {tokens_before} → {tokens_after} tokens · prefix {prefix_len}`, plus an "inactive" tag if `!c.active`.
   - Two columns: "Evicted (before)" lists `c.evicted` with `MessageView`; "Compacted (after)" lists `c.compacted`.
   - Below: `summary_text` (pre-repair), `pins_injected` as a highlighted list, and `validator` as a small key/value table (`missing`, `parse_error`, the per-pin covered ✓/✗).
4. `sessions/[id]/page.tsx` (async server component; `export const dynamic = "force-dynamic"`):
   - `notFound()` if `getTrace` returns null.
   - Sections:
     a) Session id, created, and strategy from `config.strategy`.
     b) The pins table (text, source, confidence, source_turn, active).
     c) The timeline table with one row per request: turn, model, status, cache, compacted ✓, tokens raw→sent, pin tokens, proxy/upstream/llm ms, and error in red.
     d) One `CompactionDiff` per compaction, ordered by id.
   - Highlight terms = the texts of all pins (active and inactive).

## Tests
No JS test framework. The lint and build are the tests.

Manual check (record the result in PROGRESS): run `keel serve` and a toy loop session, open `http://localhost:3000/sessions/toy-1`, and confirm the timeline renders.

## Acceptance
```bash
cd viewer && npm run lint
cd viewer && npm run build
```

## Out of scope
Python changes, auth, client-side fetching, new npm packages.

## Depends on
T-35

---
## Implementer protocol
1. Read only this task file and the files it lists.
2. Do not change any contract from ARCHITECTURE.md. If a contract seems wrong, stop and write the problem to docs/BLOCKERS.md.
3. Run the Acceptance commands. The task is done only when all of them pass.
4. Append one line to docs/PROGRESS.md: task ID, date, files changed, test result.
5. No new dependencies unless the task names them.
