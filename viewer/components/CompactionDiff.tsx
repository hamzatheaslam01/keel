import type { CompactionRow } from "@/lib/api";
import Highlight from "./Highlight";
import MessageView from "./MessageView";

type ValidatorPin = { id: number | null; text: string; covered: boolean };

export default function CompactionDiff({ c, pins }: { c: CompactionRow; pins: string[] }) {
  const v = c.validator;
  const vPins = (v?.pins as ValidatorPin[] | undefined) ?? [];
  return (
    <section className="rounded border bg-gray-50 p-3">
      <h3 className="mb-2 font-semibold">
        turn {c.turn_idx} · {c.strategy} · {c.tokens_before} → {c.tokens_after} tokens · prefix{" "}
        {c.prefix_len}
        {!c.active && <span className="ml-2 rounded bg-gray-300 px-1.5 text-xs">inactive</span>}
      </h3>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2">
        <div>
          <h4 className="mb-1 text-sm font-medium text-red-700">Evicted (before)</h4>
          <div className="space-y-1">
            {c.evicted.map((m, i) => (
              <MessageView key={i} m={m} terms={pins} />
            ))}
          </div>
        </div>
        <div>
          <h4 className="mb-1 text-sm font-medium text-green-700">Compacted (after)</h4>
          <div className="space-y-1">
            {c.compacted.map((m, i) => (
              <MessageView key={i} m={m} terms={pins} />
            ))}
          </div>
        </div>
      </div>
      {c.summary_text && (
        <div className="mt-3 text-sm">
          <h4 className="font-medium">Summary (before repair)</h4>
          <p className="whitespace-pre-wrap rounded bg-white p-2">
            <Highlight text={c.summary_text} terms={pins} />
          </p>
        </div>
      )}
      {c.pins_injected.length > 0 && (
        <div className="mt-3 text-sm">
          <h4 className="font-medium">Pins injected</h4>
          <ul className="list-disc pl-5">
            {c.pins_injected.map((p, i) => (
              <li key={i}>
                <mark className="bg-yellow-200">{p}</mark>
              </li>
            ))}
          </ul>
        </div>
      )}
      {v && (
        <div className="mt-3 text-sm">
          <h4 className="font-medium">Validator</h4>
          <table className="text-xs">
            <tbody>
              <tr>
                <td className="pr-3 text-gray-600">missing</td>
                <td>{String(v.missing ?? "")}</td>
              </tr>
              <tr>
                <td className="pr-3 text-gray-600">parse_error</td>
                <td>{String(v.parse_error ?? "")}</td>
              </tr>
              {v.skipped !== undefined && (
                <tr>
                  <td className="pr-3 text-gray-600">skipped</td>
                  <td>{String(v.skipped)}</td>
                </tr>
              )}
              {vPins.map((p, i) => (
                <tr key={i}>
                  <td className="pr-3">{p.covered ? "✓" : "✗"}</td>
                  <td>{p.text}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
