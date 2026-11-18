import Link from "next/link";
import { API, listSessions, type SessionRow } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function Home() {
  let sessions: SessionRow[] = [];
  let error: string | null = null;
  try {
    sessions = await listSessions();
  } catch (e) {
    error = e instanceof Error ? e.message : String(e);
  }

  if (error) {
    return (
      <div className="rounded border border-red-300 bg-red-50 p-4 text-red-800">
        Could not reach the Keel trace API at <code>{API}</code> ({error}). Set{" "}
        <code>KEEL_API_URL</code> and make sure <code>keel serve</code> is running.
      </div>
    );
  }
  if (sessions.length === 0) {
    return (
      <p className="text-gray-600">
        No sessions yet. Point an agent at Keel with an X-Keel-Session header.
      </p>
    );
  }
  return (
    <table className="w-full border-collapse bg-white text-sm shadow-sm">
      <thead>
        <tr className="border-b text-left text-gray-600">
          <th className="p-2">Session</th>
          <th className="p-2">Created</th>
          <th className="p-2">Requests</th>
          <th className="p-2">Compactions</th>
        </tr>
      </thead>
      <tbody>
        {sessions.map((s) => (
          <tr key={s.id} className="border-b hover:bg-gray-50">
            <td className="p-2 font-mono">
              <Link className="text-blue-700 hover:underline" href={`/sessions/${encodeURIComponent(s.id)}`}>
                {s.id}
              </Link>
            </td>
            <td className="p-2">{new Date(s.created_at).toLocaleString()}</td>
            <td className="p-2">{s.n_requests}</td>
            <td className="p-2">{s.n_compactions}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
