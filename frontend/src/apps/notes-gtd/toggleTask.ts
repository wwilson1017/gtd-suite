// Ticking a checklist item on a rendered note: flip the `[ ]` / `[x]` in the
// markdown source itself, so the body stays the one source of truth.

const TASK = /^([ \t]*(?:[-*+]|\d+[.)])[ \t]+)\[([ xX])\]/;

/** `body` with the task item that starts at `offset` (its list marker, as the
 *  markdown parser reports the item's position) ticked or unticked. Anything else
 *  at `offset` leaves the body as it was. */
export function toggleTask(body: string, offset: number): string {
  const match = TASK.exec(body.slice(offset));
  if (!match) return body;
  const at = offset + match[1].length + 1;
  return body.slice(0, at) + (match[2] === ' ' ? 'x' : ' ') + body.slice(at + 1);
}
