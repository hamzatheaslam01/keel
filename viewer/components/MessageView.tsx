import { messageText, type Message } from "@/lib/api";
import Highlight from "./Highlight";

const ROLE_STYLE: Record<string, string> = {
  system: "bg-purple-100 text-purple-800",
  user: "bg-blue-100 text-blue-800",
  assistant: "bg-green-100 text-green-800",
  tool: "bg-orange-100 text-orange-800",
};

export default function MessageView({ m, terms }: { m: Message; terms: string[] }) {
  const text = messageText(m);
  const body = <Highlight text={text} terms={terms} />;
  return (
    <div className="rounded border bg-white p-2 text-sm">
      <div className="mb-1 flex items-center gap-2">
        <span className={`rounded px-1.5 py-0.5 text-xs font-medium ${ROLE_STYLE[m.role] ?? "bg-gray-100"}`}>
          {m.role}
        </span>
        {m.tool_call_id && <span className="font-mono text-xs text-gray-500">{m.tool_call_id}</span>}
      </div>
      {text.length > 1500 ? (
        <details>
          <summary className="cursor-pointer whitespace-pre-wrap text-gray-700">
            {text.slice(0, 300)}… show all ({text.length} chars)
          </summary>
          <div className="mt-1 whitespace-pre-wrap">{body}</div>
        </details>
      ) : (
        <div className="whitespace-pre-wrap">{body}</div>
      )}
    </div>
  );
}
