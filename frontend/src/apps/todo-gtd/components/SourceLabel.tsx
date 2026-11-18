import type { Todo } from '../types';

/**
 * Provenance for an item an AI tool created: the tool's own name when it gave
 * one, otherwise "AI". Nothing for items a person added.
 *
 * `source_client` is the tool's self-reported name — untrusted text, rendered as
 * a plain text node and nothing more. A plain <span>, deliberately: TodoRow's
 * whole row is a <button>, and a nested interactive element there is invalid HTML.
 */
export function SourceLabel({ todo }: { todo: Pick<Todo, 'source' | 'source_client'> }) {
  if (todo.source !== 'agent') return null;
  return (
    <span className="rounded-full border border-line px-2 py-0.5 text-muted" title="Added by an AI tool">
      <span aria-hidden="true">✦ </span>
      <span className="sr-only">Added by </span>
      {todo.source_client || 'AI'}
    </span>
  );
}
