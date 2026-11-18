// Common Brain — small helpers for its pages.

/** "just now", "5 min ago", "3 h ago", "2 d ago", else the date. */
export function ago(iso: string, now = Date.now()): string {
  const s = Math.max(0, (now - new Date(iso).getTime()) / 1000);
  if (s < 45) return 'just now';
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  if (s < 7 * 86400) return `${Math.round(s / 86400)} d ago`;
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/** Who made a change, as the page says it: the AI's name, or You. */
export const who = (by: string) => (by === 'you' ? 'You' : by);

/** What a change did, in words. */
export const ACTIONS: Record<string, string> = {
  added: 'added',
  edited: 'changed',
  locked: 'locked',
  unlocked: 'unlocked',
  archived: 'archived',
  unarchived: 'brought back',
  restored: 'restored',
  moved: 'moved',
};

// A leading `---` block (backend/brain.py _front): a byte-order mark or blank lines before it still count.
const FRONT = /^\uFEFF?\s*---[ \t]*\r?\n([\s\S]*?)(?<=\n)---[ \t]*(?:\r?\n|$)/;

/** A page's frontmatter as [key, value] lines (lists joined by commas), and the Markdown after it. */
export function splitFront(body: string): { props: [string, string][]; rest: string } {
  const m = FRONT.exec(body);
  if (!m) return { props: [], rest: body };
  const props: [string, string[]][] = [];
  for (const line of m[1].split(/\r?\n/)) {
    const item = /^\s*-\s+(.*)/.exec(line);
    const at = line.indexOf(':');
    if (item && props.length) props[props.length - 1][1].push(item[1].trim());
    else if (at > 0 && !/^\s/.test(line)) {
      const v = line.slice(at + 1).trim();
      props.push([
        line.slice(0, at).trim(),
        /^\[.*\]$/.test(v)
          ? v
              .slice(1, -1)
              .split(',')
              .map((s) => s.trim())
              .filter(Boolean)
          : v
            ? [v]
            : [],
      ]);
    }
  }
  return { props: props.map(([k, v]) => [k, v.join(', ')]), rest: body.slice(m[0].length) };
}

/** What a write blanked out (backend/brain.py _blank_secrets), as the app says it; '' for nothing. */
export function removedNote(removed: { kind: string; count: number }[] = []): string {
  const parts = removed.map((r) => (r.count === 1 ? `a ${r.kind}` : `${r.count} ${r.kind}s`));
  if (!parts.length) return '';
  const said = parts.length > 1 ? `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}` : parts[0];
  return `We removed ${said}: Common Brain never keeps secrets. Keep them in a password manager.`;
}
