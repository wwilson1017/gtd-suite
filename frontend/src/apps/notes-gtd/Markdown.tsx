// Notes GTD — a note's body, rendered. Agents write these notes, so their text is
// untrusted: raw HTML is skipped (never injected), react-markdown's default URL
// filter drops javascript: links, and every link opens a new tab with no opener.
// Checklist boxes are live: ticking one hands the item's source offset to `onToggle`.
// An app may add remark plugins and override elements (Common Brain's [[links]]).
import { createContext, useContext } from 'react';
import ReactMarkdown, { type Components, type Options } from 'react-markdown';
import remarkGfm from 'remark-gfm';

/** The source offset of the nearest list item, for its checkbox. */
const ItemOffset = createContext<number | null>(null);
const Toggle = createContext<((offset: number) => void) | undefined>(undefined);

function TaskBox({ checked }: { checked: boolean }) {
  const offset = useContext(ItemOffset);
  const onToggle = useContext(Toggle);
  return (
    <input
      type="checkbox"
      checked={checked}
      disabled={!onToggle || offset === null}
      aria-label={checked ? 'Done: untick' : 'Tick'}
      onClick={(e) => e.stopPropagation()}
      onChange={() => {
        if (offset !== null) onToggle?.(offset);
      }}
      className="mr-1.5 align-middle accent-brand-dark"
    />
  );
}

const COMPONENTS: Components = {
  li: ({ node, children, ...props }) => (
    <li {...props}>
      <ItemOffset.Provider value={node?.position?.start.offset ?? null}>{children}</ItemOffset.Provider>
    </li>
  ),
  // Raw HTML is skipped, so the only inputs are GFM's task boxes.
  input: ({ checked }) => <TaskBox checked={!!checked} />,
  a: ({ node: _node, ...props }) => {
    void _node; // react-markdown metadata must not become a DOM attribute.
    return (
      <a
        {...props}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="text-brand-ink underline"
      />
    );
  },
  // An image is a link, never fetched: a note's text must not make the browser call
  // an address it names (a tracking pixel). Images are not in v1.
  img: ({ src, alt }) => (
    <a
      href={typeof src === 'string' ? src : undefined}
      target="_blank"
      rel="noopener noreferrer"
      onClick={(e) => e.stopPropagation()}
      className="text-brand-ink underline"
    >
      {alt || 'image'}
    </a>
  ),
};

export function Markdown({
  body,
  onToggle,
  className = 'text-sm text-charcoal',
  plugins = [],
  components,
}: {
  body: string;
  onToggle?: (offset: number) => void;
  className?: string;
  plugins?: NonNullable<Options['remarkPlugins']>;
  components?: Components;
}) {
  return (
    <div className={`note-md break-words ${className}`}>
      <Toggle.Provider value={onToggle}>
        <ReactMarkdown
          remarkPlugins={[remarkGfm, ...plugins]}
          skipHtml
          components={components ? { ...COMPONENTS, ...components } : COMPONENTS}
        >
          {body}
        </ReactMarkdown>
      </Toggle.Provider>
    </div>
  );
}
