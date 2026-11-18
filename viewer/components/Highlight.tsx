const TRUNC = /\[truncated \d+ tokens\]/;

function escape(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

export default function Highlight({ text, terms }: { text: string; terms: string[] }) {
  const parts = terms.filter((t) => t.trim()).map(escape);
  parts.push(TRUNC.source);
  const re = new RegExp(`(${parts.join("|")})`, "gi");
  const lowered = terms.map((t) => t.toLowerCase());
  return (
    <>
      {text.split(re).map((chunk, i) => {
        if (!chunk) return null;
        if (TRUNC.test(chunk))
          return (
            <span key={i} className="rounded bg-gray-200 px-1 text-xs text-gray-700">
              {chunk}
            </span>
          );
        if (lowered.includes(chunk.toLowerCase()))
          return (
            <mark key={i} className="bg-yellow-200">
              {chunk}
            </mark>
          );
        return <span key={i}>{chunk}</span>;
      })}
    </>
  );
}
