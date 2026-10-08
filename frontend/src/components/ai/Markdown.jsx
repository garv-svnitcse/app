import { Fragment } from "react";
import { cn } from "@/lib/utils";

/*
 * A small, safe Markdown renderer for assistant replies. It only builds React elements
 * (never HTML strings), so model output cannot inject markup. Supported: paragraphs,
 * headings, bullet / numbered lists, block quotes, fenced code, inline code, bold,
 * italic, simple tables, horizontal rules and http(s) links.
 */

const INLINE = /(`[^`\n]+`)|(\*\*[^*\n]+?\*\*|__[^_\n]+?__)|(\*[^*\s\n][^*\n]*?\*|(?<![\w])_[^_\s\n][^_\n]*?_(?![\w]))|(\[([^\]\n]+)\]\((https?:\/\/[^)\s]+)\))/g;

function renderInline(text, keyPrefix = "i", depth = 0) {
  const out = [];
  let last = 0;
  let n = 0;
  const re = new RegExp(INLINE.source, "g");
  let m;
  while ((m = re.exec(text)) !== null) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const key = `${keyPrefix}-${n++}`;
    const [token] = m;
    if (m[1]) {
      out.push(<code key={key} className="rounded bg-muted px-1 py-0.5 font-mono text-[0.85em] break-words">{token.slice(1, -1)}</code>);
    } else if (m[2]) {
      const inner = token.slice(2, -2);
      out.push(<strong key={key} className="font-semibold text-foreground">{depth < 2 ? renderInline(inner, key, depth + 1) : inner}</strong>);
    } else if (m[3]) {
      const inner = token.slice(1, -1);
      out.push(<em key={key}>{depth < 2 ? renderInline(inner, key, depth + 1) : inner}</em>);
    } else if (m[4]) {
      out.push(
        <a key={key} href={m[6]} target="_blank" rel="noopener noreferrer nofollow" className="text-primary underline underline-offset-2 break-all">
          {m[5]}
        </a>
      );
    }
    last = m.index + token.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
}

const RE = {
  fence: /^\s*```\s*([\w+-]*)\s*$/,
  heading: /^(#{1,4})\s+(.*)$/,
  ul: /^(\s*)[-*•]\s+(.*)$/,
  ol: /^(\s*)(\d+)[.)]\s+(.*)$/,
  quote: /^>\s?(.*)$/,
  hr: /^\s*([-*_])(\s*\1){2,}\s*$/,
  tableSep: /^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$/,
};

function splitRow(line) {
  return line.trim().replace(/^\|/, "").replace(/\|$/, "").split("|").map((c) => c.trim());
}

function parseBlocks(src) {
  const lines = src.replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let para = [];
  const flush = () => {
    if (para.length) blocks.push({ type: "p", lines: para });
    para = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    let m;
    if ((m = line.match(RE.fence))) {
      flush();
      const code = [];
      i++;
      while (i < lines.length && !RE.fence.test(lines[i])) code.push(lines[i++]);
      blocks.push({ type: "code", lang: m[1], text: code.join("\n") });
      continue;
    }
    if (!line.trim()) { flush(); continue; }
    if (RE.hr.test(line)) { flush(); blocks.push({ type: "hr" }); continue; }
    if ((m = line.match(RE.heading))) { flush(); blocks.push({ type: "h", level: m[1].length, text: m[2] }); continue; }
    if (line.includes("|") && i + 1 < lines.length && RE.tableSep.test(lines[i + 1])) {
      flush();
      const head = splitRow(line);
      const rows = [];
      i += 2;
      while (i < lines.length && lines[i].includes("|") && lines[i].trim()) rows.push(splitRow(lines[i++]));
      i--;
      blocks.push({ type: "table", head, rows });
      continue;
    }
    if (RE.ul.test(line) || RE.ol.test(line)) {
      flush();
      const ordered = !RE.ul.test(line);
      const items = [];
      while (i < lines.length) {
        const l = lines[i];
        const um = l.match(RE.ul);
        const om = l.match(RE.ol);
        const hit = ordered ? om : um;
        if (hit) {
          items.push({ indent: Math.min(3, Math.floor(hit[1].length / 2)), text: ordered ? hit[3] : hit[2], n: ordered ? Number(hit[2]) : null });
          i++;
        } else if ((um || om) && items.length) {
          // A nested list of the other kind: keep it inside this list as indented items.
          items.push({ indent: Math.max(1, Math.min(3, Math.floor((um || om)[1].length / 2))), text: um ? um[2] : om[3], n: null });
          i++;
        } else if (l.trim() && /^\s{2,}/.test(l) && items.length) {
          items[items.length - 1].text += " " + l.trim();
          i++;
        } else break;
      }
      i--;
      blocks.push({ type: ordered ? "ol" : "ul", items });
      continue;
    }
    if ((m = line.match(RE.quote))) {
      flush();
      const q = [m[1]];
      while (i + 1 < lines.length && RE.quote.test(lines[i + 1])) q.push(lines[++i].match(RE.quote)[1]);
      blocks.push({ type: "quote", lines: q });
      continue;
    }
    para.push(line);
  }
  flush();
  return blocks;
}

function Lines({ lines, k }) {
  return lines.map((l, idx) => (
    <Fragment key={`${k}-${idx}`}>
      {idx > 0 && <br />}
      {renderInline(l, `${k}-${idx}`)}
    </Fragment>
  ));
}

export function Markdown({ text, className }) {
  const blocks = parseBlocks(text || "");
  return (
    <div className={cn("space-y-2.5 text-[13.5px] leading-relaxed text-foreground break-words", className)}>
      {blocks.map((b, bi) => {
        const k = `b${bi}`;
        switch (b.type) {
          case "code":
            return (
              <pre key={k} className="rounded-md border border-border bg-muted/60 p-3 overflow-x-auto scrollbar-thin text-[12.5px] leading-snug">
                <code className="font-mono whitespace-pre">{b.text}</code>
              </pre>
            );
          case "h": {
            const size = b.level <= 2 ? "text-[15px]" : "text-[14px]";
            return <div key={k} className={cn("font-display font-semibold text-foreground pt-1", size)}>{renderInline(b.text, k)}</div>;
          }
          case "hr":
            return <hr key={k} className="border-border" />;
          case "quote":
            return <blockquote key={k} className="border-l-2 border-primary/40 pl-3 text-muted-foreground"><Lines lines={b.lines} k={k} /></blockquote>;
          case "table":
            return (
              <div key={k} className="overflow-x-auto scrollbar-thin rounded-md border border-border">
                <table className="w-full text-[12.5px]">
                  <thead className="bg-muted/60">
                    <tr>{b.head.map((c, ci) => <th key={ci} className="px-2.5 py-1.5 text-left font-semibold whitespace-nowrap">{renderInline(c, `${k}-h${ci}`)}</th>)}</tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {b.rows.map((r, ri) => (
                      <tr key={ri}>{r.map((c, ci) => <td key={ci} className="px-2.5 py-1.5 align-top">{renderInline(c, `${k}-${ri}-${ci}`)}</td>)}</tr>
                    ))}
                  </tbody>
                </table>
              </div>
            );
          case "ul":
          case "ol":
            return (
              <ul key={k} className="space-y-1">
                {b.items.map((it, ii) => (
                  <li key={ii} className="flex gap-2" style={{ paddingLeft: `${it.indent * 16}px` }}>
                    <span className="shrink-0 text-muted-foreground select-none min-w-[1em] text-right">
                      {b.type === "ol" && it.n != null ? `${it.n}.` : "•"}
                    </span>
                    <span className="min-w-0">{renderInline(it.text, `${k}-${ii}`)}</span>
                  </li>
                ))}
              </ul>
            );
          default:
            return <p key={k}><Lines lines={b.lines} k={k} /></p>;
        }
      })}
    </div>
  );
}

export default Markdown;
