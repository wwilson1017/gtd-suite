// Notes GTD — the landing page's phone: the app's own cards over notes held in this
// page, so a visitor sees what an AI saved, ticks, edits, searches and pins. Nothing
// is saved or sent anywhere.
// simplification: its own small inline editor, because NoteEditor talks to a list's
// API; swap it in if it ever takes a local store.
import { useState } from 'react';
import { DemoPhone, useToast } from '../todo-gtd/DemoPhone';
import { NOTE_BG, NoteCard } from './NoteCard';
import { AppName } from '../todo-gtd/components/Logo';
import { toggleTask } from './toggleTask';
import type { Note } from './types';

const fieldCls =
  'w-full rounded-lg border border-line bg-cream px-3 py-2 text-base text-charcoal focus:border-brand focus:outline-none';

/** The body's #tags, as the server reads them (simplified: code is not skipped). */
function tagsOf(body: string): string[] {
  return [...new Set([...body.matchAll(/(?<!\S)#([\w/-]+)/g)].map((m) => m[1].toLowerCase()))];
}

/** A note as the server would answer it, `daysAgo` old, saved by `by` (null: you). */
function note(
  id: number,
  title: string,
  body: string,
  by: string | null,
  daysAgo: number,
  rest: Partial<Note> = {},
): Note {
  const at = new Date(Date.now() - daysAgo * 86_400_000).toISOString();
  return {
    id,
    title,
    body,
    tags: tagsOf(body),
    color: '',
    pinned: false,
    status: 'active',
    version: 1,
    source: by ? 'agent' : 'ui',
    source_client: by,
    edited_by: by,
    created_at: at,
    updated_at: at,
    ...rest,
  };
}

function seed(): Note[] {
  return [
    note(
      1,
      'Denver trip: packing list',
      'For the #travel next week:\n\n- [x] Boarding passes\n- [ ] Phone charger\n- [ ] Hiking boots',
      'Claude',
      1,
      { pinned: true, color: 'yellow' },
    ),
    note(
      2,
      'Call with Dana',
      'Budget approved at **$12k**. She wants the revised timeline by Friday. #work',
      'ChatGPT',
      2,
      { color: 'blue' },
    ),
    note(
      3,
      'Paint colours we liked',
      'Kitchen walls: *Sea Salt*. Trim: *Pure White*. Cabinets still open. #home',
      'Claude',
      5,
      { color: 'green' },
    ),
    note(
      4,
      'Gift ideas for Mom',
      'For her birthday #family\n\n- [ ] The garden book she mentioned\n- [ ] A new teapot',
      null,
      6,
    ),
  ];
}

/** What the "Be the AI" button saves, in turn. */
const AI_NOTES: [string, string, string][] = [
  [
    'What the plumber said',
    'The leak is the shut-off valve under the sink. The part is ordered; he is back **Thursday at 9**. #home',
    'Claude',
  ],
  [
    'Ideas from the team meeting',
    'Decided at #work today:\n\n- Move the launch to May\n- Ask Sam for the vendor list\n- [ ] Book the room for the review',
    'ChatGPT',
  ],
  [
    'Restaurants for Saturday',
    'Three #plans with a table for six at 7pm:\n\n- [ ] The Italian place on 5th\n- [ ] The taco spot by the park\n- [ ] Grandma’s diner',
    'Claude',
  ],
];

function Editor({ note: n, onDone }: { note: Note; onDone: (title: string, body: string) => void }) {
  const [title, setTitle] = useState(n.title);
  const [body, setBody] = useState(n.body);
  return (
    <form
      onSubmit={(e) => {
        e.preventDefault();
        onDone(title.trim(), body);
      }}
      className={`mb-3 space-y-2 rounded-xl border border-line p-3 ${NOTE_BG[n.color]}`}
    >
      <input
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        aria-label="Title"
        placeholder="Title"
        className={`${fieldCls} font-heading font-bold`}
      />
      <textarea
        value={body}
        onChange={(e) => setBody(e.target.value)}
        aria-label="Note"
        rows={7}
        autoFocus
        className={`${fieldCls} resize-none text-sm`}
      />
      <button
        type="submit"
        className="rounded-lg bg-brand-dark px-4 py-1.5 font-heading text-sm text-white hover:bg-brand-deep"
      >
        Done
      </button>
    </form>
  );
}

export function NotesDemo() {
  const [notes, setNotes] = useState(seed);
  const [query, setQuery] = useState('');
  /** Showing the archived notes, as the app's Archive does: Restore brings one back. */
  const [archive, setArchive] = useState(false);
  const [editing, setEditing] = useState<number | null>(null);
  const [aiTurn, setAiTurn] = useState(0);
  const [toast, setToast] = useToast();

  /** A change made here, in the app: it is yours now, so no "edited by" line. */
  const patch = (id: number, change: Partial<Note>) =>
    setNotes((all) =>
      all.map((n) => (n.id === id ? { ...n, ...change, edited_by: null, updated_at: new Date().toISOString() } : n)),
    );
  const aiSave = () => {
    const [title, body, by] = AI_NOTES[aiTurn % AI_NOTES.length];
    setNotes((all) => [note(Math.max(...all.map((n) => n.id)) + 1, title, body, by, 0), ...all]);
    setAiTurn(aiTurn + 1);
    setQuery('');
    setToast(`${by} saved “${title}”`);
  };

  const words = query.toLowerCase().split(/\s+/).filter(Boolean);
  const archived = notes.filter((n) => n.status === 'archived').length;
  const shown = notes.filter(
    (n) =>
      n.status === (archive ? 'archived' : 'active') &&
      words.every((w) => `${n.title}\n${n.body}`.toLowerCase().includes(w)),
  );
  const card = (n: Note) =>
    editing === n.id ? (
      <Editor
        key={n.id}
        note={n}
        onDone={(title, body) => {
          setEditing(null);
          // Emptied, it keeps what it had: the app refuses a note with no title and no body.
          if ((title || body.trim()) && (title !== n.title || body !== n.body)) {
            patch(n.id, { title, body, tags: tagsOf(body) });
          }
        }}
      />
    ) : (
      <NoteCard
        key={n.id}
        note={n}
        onOpen={() => setEditing(n.id)}
        onToggle={(offset) => patch(n.id, { body: toggleTask(n.body, offset) })}
        onChange={(fields) => {
          patch(n.id, fields);
          if (fields.status === 'archived') setToast('Archived. Nothing is deleted: see Archive.');
        }}
      />
    );
  const section = (label: string, list: Note[]) =>
    list.length > 0 && (
      <>
        <h4 className="mb-2 mt-3 text-xs font-bold uppercase tracking-wider text-muted">{label}</h4>
        {list.map(card)}
      </>
    );

  return (
    <DemoPhone toast={toast} aiLabel="save a note" onAi={aiSave}>
      <div className="flex items-end justify-between gap-3 px-5 pt-4">
        <div>
          <h3 className="font-heading text-xl font-bold text-charcoal">
            <AppName app="notes" />
          </h3>
          <p className="text-[13px] text-muted">A working demo. Nothing is sent anywhere.</p>
        </div>
        <button
          type="button"
          onClick={() => {
            setNotes(seed());
            setEditing(null);
            setQuery('');
            setArchive(false);
            setToast('Demo reset');
          }}
          className="shrink-0 rounded-lg border border-line px-2.5 py-1 text-xs text-muted hover:border-muted"
        >
          Reset
        </button>
      </div>
      <div className="min-h-[460px] px-4 pb-6 pt-3">
        <input
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          aria-label="Search notes"
          placeholder="Search notes"
          className={fieldCls}
        />
        {(archive || archived > 0) && (
          <button
            type="button"
            onClick={() => {
              setArchive(!archive);
              setEditing(null);
            }}
            className="mt-2 text-xs text-muted underline hover:text-charcoal"
          >
            {archive ? '\u2190 Back to notes' : `Archive (${archived})`}
          </button>
        )}
        {shown.length === 0 && <p className="mt-6 text-center text-sm text-muted">No notes match.</p>}
        {archive ? (
          section('Archived', shown)
        ) : (
          <>
            {section(
              'Pinned',
              shown.filter((n) => n.pinned),
            )}
            {section(
              shown.some((n) => n.pinned) ? 'Others' : 'Notes',
              shown.filter((n) => !n.pinned),
            )}
          </>
        )}
      </div>
    </DemoPhone>
  );
}
