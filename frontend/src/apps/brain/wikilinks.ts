// Common Brain — [[target]] and [[target|label]] in a page's Markdown become links: a remark
// plugin that splits text nodes. Code and inline code are not text nodes, so they are never
// touched, and text inside a link, a link reference or an image is skipped, so links never
// nest. A link points at WIKI_HREF + the encoded target; PageView's anchor resolves it.
// simplification: \[[…]] is not an escape, since parsing drops the backslash; write literal brackets in inline code

interface MdNode {
  type: string;
  value?: string;
  url?: string;
  children?: MdNode[];
}

const WIKI = /\[\[([^[\]|]+)(?:\|([^[\]]+))?\]\]/g;
const SKIP = new Set(['link', 'linkReference', 'image', 'imageReference']);
export const WIKI_HREF = '#wiki:';

/** The page's link targets, once each: the batch PageView resolves. */
export const wikiTargets = (body: string) => [...new Set([...body.matchAll(WIKI)].map((m) => m[1].trim()))];

export function remarkWikilinks() {
  return (tree: MdNode) => visit(tree);
}

function visit(node: MdNode) {
  if (!node.children || SKIP.has(node.type)) return;
  node.children = node.children.flatMap((child) => {
    if (child.type !== 'text' || !child.value?.includes('[[')) {
      visit(child);
      return [child];
    }
    return split(child.value);
  });
}

function split(text: string): MdNode[] {
  const out: MdNode[] = [];
  let at = 0;
  for (const m of text.matchAll(WIKI)) {
    if (m.index > at) out.push({ type: 'text', value: text.slice(at, m.index) });
    out.push({
      type: 'link',
      url: WIKI_HREF + encodeURIComponent(m[1].trim()),
      children: [{ type: 'text', value: (m[2] ?? m[1]).trim() }],
    });
    at = m.index + m[0].length;
  }
  if (at < text.length) out.push({ type: 'text', value: text.slice(at) });
  return out;
}
