// The [[link]] plugin over real Markdown parsing: which text becomes a link and which is left
// alone, plus the frontmatter split and the "we removed" note (util.ts).
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Markdown } from '../notes-gtd/Markdown';
import { removedNote, splitFront } from './util';
import { remarkWikilinks, wikiTargets } from './wikilinks';

const html = (body: string) => renderToStaticMarkup(<Markdown body={body} plugins={[remarkWikilinks]} />);
const wiki = (target: string) => `href="#wiki:${encodeURIComponent(target)}"`;

describe('wikilinks', () => {
  it('splits two links in one text node, with a label, and encodes the target', () => {
    const out = html('See [[people/maya]] and [[Q3 plan #2?|the plan]] today.');
    expect(out).toContain(`<a ${wiki('people/maya')}`);
    expect(out).toContain(
      `${wiki('Q3 plan #2?')} target="_blank" rel="noopener noreferrer" class="text-brand-ink underline">the plan</a>`,
    );
    expect(out).toContain('See <a');
    expect(out).toContain('</a> today.');
  });

  it('leaves code, inline code and existing links alone', () => {
    expect(html('`[[x]]`')).toBe(
      '<div class="note-md break-words text-sm text-charcoal"><p><code>[[x]]</code></p></div>',
    );
    expect(html('```\n[[x]]\n```')).not.toContain('#wiki:');
    const linked = html('[see [[x]] here](https://example.com) then [[y]]');
    expect(linked.match(/<a /g)).toHaveLength(2);
    expect(linked).toContain('>see [[x]] here</a>');
    expect(linked).toContain(wiki('y'));
  });

  it('takes an escaped \\[[ as a link too (the documented simplification), beside a real one', () => {
    expect(html('literal \\[[a]] and [[b]]').match(/#wiki:/g)).toHaveLength(2);
  });

  it('collects each target once, for the batch resolve', () => {
    expect(wikiTargets('[[a]] [[ b |B]] [[a|again]] [[]] [x]')).toEqual(['a', 'b']);
  });
});

describe('splitFront', () => {
  it('reads flat keys, bracket lists and item lists, and returns the Markdown after', () => {
    const { props, rest } = splitFront(
      '---\ntitle: Maya\ntags: [people, acme]\naliases:\n  - M\n  - Maya L\n  nested: skipped\n---\n# Maya\n',
    );
    expect(props).toEqual([
      ['title', 'Maya'],
      ['tags', 'people, acme'],
      ['aliases', 'M, Maya L'],
    ]);
    expect(rest).toBe('# Maya\n');
    expect(splitFront('# No frontmatter\n---\n')).toEqual({ props: [], rest: '# No frontmatter\n---\n' });
  });
});

describe('removedNote', () => {
  it('says what went, never the values', () => {
    expect(removedNote([])).toBe('');
    expect(removedNote([{ kind: 'password', count: 1 }])).toMatch(/^We removed a password:/);
    expect(
      removedNote([
        { kind: 'card number', count: 2 },
        { kind: 'key', count: 1 },
      ]),
    ).toMatch(/^We removed 2 card numbers and a key:/);
  });
});
