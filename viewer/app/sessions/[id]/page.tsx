import { notFound } from "next/navigation";
import CompactionDiff from "@/components/CompactionDiff";
import { getTrace } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SessionPage({ params }: { params: { id: string } }) {
  const t = await getTrace(decodeURIComponent(params.id));
  if (!t) notFound();
  const terms = t.pins.map((p) => p.text);
  const strategy = String((t.session.config as { strategy?: string }).strategy ?? "");
  const compactions = [...t.compactions].sort((a, b) => a.id - b.id);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="font-mono text-lg font-semibold">{t.session.id}</h1>
        <p className="text-sm text-gray-600">
          created {new Date(t.session.created_at).toLocaleString()} · strategy {strategy || "–"}
        </p>
      </div>

      <section>
        <h2 className="mb-2 font-semibold">Pins</h2>
        {t.pins.length === 0 ? (
          <p className="text-sm text-gray-600">No pins.</p>
        ) : (
          <table className="w-full bg-white text-sm">
            <thead>
              <tr className="border-b text-left text-gray-600">
                <th className="p-1">text</th>
                <th className="p-1">source</th>
                <th className="p-1">confidence</th>
                <th className="p-1">source turn</th>
                <th className="p-1">active</th>
              </tr>
            </thead>
            <tbody>
              {t.pins.map((p) => (
                <tr key={p.id} className="border-b">
                  <td className="p-1">
                    <mark className="bg-yellow-200">{p.text}</mark>
                  </td>
                  <td className="p-1">{p.source}</td>
                  <td className="p-1">{p.confidence.toFixed(2)}</td>
                  <td className="p-1">{p.source_turn ?? "–"}</td>
                  <td className="p-1">{p.active ? "✓" : "✗"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <h2 className="mb-2 font-semibold">Timeline</h2>
        <table className="w-full bg-white text-sm">
          <thead>
            <tr className="border-b text-left text-gray-600">
              <th className="p-1">turn</th>
              <th className="p-1">model</th>
              <th className="p-1">status</th>
              <th className="p-1">cache</th>
              <th className="p-1">compacted</th>
              <th className="p-1">tokens raw → sent</th>
              <th className="p-1">pin tokens</th>
              <th className="p-1">proxy / upstream / llm ms</th>
            </tr>
          </thead>
          <tbody>
            {t.requests.map((r) => (
              <tr key={r.id} className="border-b align-top">
                <td className="p-1">{r.turn_idx}</td>
                <td className="p-1">{r.upstream_model}</td>
                <td className="p-1">{r.status}</td>
                <td className="p-1">{r.cache_status}</td>
                <td className="p-1">{r.compacted ? "✓" : ""}</td>
                <td className="p-1">
                  {r.tokens_in_raw} → {r.tokens_in_sent}
                </td>
                <td className="p-1">{r.pin_tokens}</td>
                <td className="p-1">
                  {r.proxy_ms.toFixed(1)} / {r.upstream_ms.toFixed(0)} / {r.llm_ms.toFixed(0)}
                  {r.error && <div className="text-red-700">{r.error}</div>}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>

      <section className="space-y-3">
        <h2 className="font-semibold">Compactions</h2>
        {compactions.length === 0 && <p className="text-sm text-gray-600">No compactions.</p>}
        {compactions.map((c) => (
          <CompactionDiff key={c.id} c={c} pins={terms} />
        ))}
      </section>
    </div>
  );
}
