// Projects GTD — the landing page's phone: a board held in this page, so a visitor
// opens a card, ticks its checklist, moves it along, adds one, and watches an AI add
// a card, move one to Done, comment and tick a step. Nothing is saved or sent anywhere.
// simplification: its own small card tile and sheet, because BoardPage's talk to a
// project's API; swap them in if they ever take a local store.
import { useRef, useState } from 'react';
import { AppName } from '../todo-gtd/components/Logo';
import { DemoPhone, useToast } from '../todo-gtd/DemoPhone';
import type { Person } from './types';
import { Avatar, AvatarStack, day, dueTone, ymd } from './ui';

const COLUMNS = ['To do', 'Doing', 'Done'];
const DONE = 2;
const LABELS: Record<string, string> = { Design: 'purple', Copy: 'orange', Photos: 'pink', Tech: 'blue' };
const PEOPLE: Record<string, Person> = {
  me: { id: 1, name: 'Me', kind: 'me', color: '#c0272d' },
  ana: { id: 2, name: 'Ana', kind: 'person', color: '#1f845a' },
  claude: { id: 3, name: 'Claude', kind: 'ai', color: '#d97757' },
  chatgpt: { id: 4, name: 'ChatGPT', kind: 'ai', color: '#10a37f' },
};

interface DemoCard {
  id: number;
  col: number;
  title: string;
  labels: string[];
  /** Days from today. */
  due?: number;
  who: string[];
  notes?: string;
  steps: [string, boolean][];
  comments: [string, string][];
}

const card = (id: number, col: number, title: string, rest: Partial<DemoCard> = {}): DemoCard => ({
  id,
  col,
  title,
  labels: [],
  who: [],
  steps: [],
  comments: [],
  ...rest,
});

function seed(): DemoCard[] {
  return [
    card(1, 0, 'Shoot the seasonal cheesecakes', {
      labels: ['Photos'],
      due: 4,
      who: ['ana'],
      steps: [
        ['Pumpkin', false],
        ['Turtle', false],
        ['Key lime', false],
      ],
    }),
    card(2, 0, 'Write the About page', {
      labels: ['Copy'],
      due: 6,
      who: ['me'],
      notes: 'How the bakery started, in five short paragraphs. Warm, never salesy.',
    }),
    card(3, 0, 'Set up the order email address', { labels: ['Tech'], due: 9 }),
    card(4, 1, 'Homepage hero photo', {
      labels: ['Photos', 'Design'],
      due: 1,
      who: ['me', 'ana'],
      steps: [
        ['Pick three shots', true],
        ['Crop for phones', false],
      ],
      comments: [['Ana', 'The one by the window looks best.']],
    }),
    card(5, 1, 'Menu page layout', {
      labels: ['Design'],
      who: ['claude'],
      comments: [['Claude', 'Drafted two layouts in the notes: a grid, and one long list.']],
    }),
    card(6, 2, 'Buy the domain', { labels: ['Tech'], who: ['me'] }),
  ];
}

/** What the "Be the AI" button does, in turn. */
const AI_TURNS: { label: string; run: (cards: DemoCard[]) => [DemoCard[], number, string] }[] = [
  {
    label: 'add a card',
    run: (cards) => {
      const id = Math.max(...cards.map((c) => c.id)) + 1;
      const title = 'Write the launch email';
      return [
        [
          ...cards,
          card(id, 0, title, {
            labels: ['Copy'],
            due: 7,
            who: ['claude'],
            steps: [
              ['Subject line', false],
              ['Opening offer', false],
            ],
          }),
        ],
        id,
        `Claude added “${title}”`,
      ];
    },
  },
  {
    label: 'move a card',
    run: (cards) => {
      const c =
        cards.find((x) => x.id === 4 && x.col !== DONE) ??
        cards.find((x) => x.col === 1) ??
        cards.find((x) => x.col === 0);
      if (!c) return [cards, 0, 'ChatGPT found nothing left to move'];
      return [
        cards.map((x) => (x.id === c.id ? { ...x, col: DONE, steps: x.steps.map(([s]) => [s, true]) } : x)),
        c.id,
        `ChatGPT moved “${c.title}” to Done`,
      ];
    },
  },
  {
    label: 'leave a comment',
    run: (cards) => {
      const c = cards.find((x) => x.id === 2) ?? cards[0];
      return [
        cards.map((x) =>
          x.id === c.id
            ? {
                ...x,
                comments: [
                  ...x.comments,
                  ['Claude', 'First draft is in the notes. Shall I trim it to four paragraphs?'],
                ],
              }
            : x,
        ),
        c.id,
        `Claude commented on “${c.title}”`,
      ];
    },
  },
  {
    label: 'tick a step',
    run: (cards) => {
      const c = cards.find((x) => x.steps.some(([, done]) => !done));
      if (!c) return [cards, 0, 'ChatGPT found every step ticked'];
      const at = c.steps.findIndex(([, done]) => !done);
      return [
        cards.map((x) =>
          x.id === c.id ? { ...x, steps: x.steps.map(([s, done], i): [string, boolean] => [s, done || i === at]) } : x,
        ),
        c.id,
        `ChatGPT ticked “${c.steps[at][0]}”`,
      ];
    },
  },
];

function dueDate(days: number): string {
  const d = new Date();
  d.setDate(d.getDate() + days);
  return ymd(d);
}

/** The board's due chip, in the board's own colours. */
function DueChip({ c }: { c: DemoCard }) {
  if (c.due === undefined) return null;
  return (
    <span className={`rounded px-1.5 py-0.5 font-semibold ${dueTone(dueDate(c.due), c.col === DONE, dueDate(0))}`}>
      🕓 {day(dueDate(c.due))}
    </span>
  );
}

const people = (keys: string[]) => keys.map((k) => PEOPLE[k]);
const smallBtn = 'rounded-lg border border-line bg-cream px-2.5 py-1 text-xs font-heading text-charcoal hover:bg-sand';

export function ProjectsDemo() {
  const [cards, setCards] = useState(seed);
  const [open, setOpen] = useState<number | null>(null);
  const [turn, setTurn] = useState(0);
  const [flash, setFlash] = useState(0);
  const [adding, setAdding] = useState('');
  const [toast, setToast] = useToast();
  const board = useRef<HTMLDivElement>(null);

  const patch = (id: number, change: Partial<DemoCard>) =>
    setCards((all) => all.map((c) => (c.id === id ? { ...c, ...change } : c)));
  /** Bring a column into view inside the phone, never by scrolling the page. */
  const show = (col: number) => {
    const el = board.current?.children[col] as HTMLElement | undefined;
    if (el) board.current?.scrollTo?.({ left: el.offsetLeft - 12, behavior: 'smooth' });
  };
  const aiTurn = () => {
    const step = AI_TURNS[turn % AI_TURNS.length];
    const [next, id, said] = step.run(cards);
    setCards(next);
    setTurn(turn + 1);
    setOpen(null);
    setFlash(id);
    setToast(said);
    const moved = next.find((c) => c.id === id);
    if (moved) requestAnimationFrame(() => show(moved.col));
  };
  const reset = () => {
    setCards(seed());
    setOpen(null);
    setTurn(0);
    setFlash(0);
    setAdding('');
    setToast('Demo reset');
  };
  const add = () => {
    const title = adding.trim();
    if (!title) return;
    setCards((all) => [...all, card(Math.max(...all.map((c) => c.id)) + 1, 0, title, { who: ['me'] })]);
    setAdding('');
  };

  const current = cards.find((c) => c.id === open);
  return (
    <DemoPhone toast={toast} aiLabel={AI_TURNS[turn % AI_TURNS.length].label} onAi={aiTurn}>
      <div className="flex items-end justify-between gap-3 px-5 pt-4">
        <div>
          <h3 className="font-heading text-xl font-bold text-charcoal">
            <AppName app="projects" />
          </h3>
          <p className="text-[13px] text-muted">A working demo. Nothing is sent anywhere.</p>
        </div>
        <button
          type="button"
          onClick={reset}
          className="shrink-0 rounded-lg border border-line px-2.5 py-1 text-xs text-muted hover:border-muted"
        >
          Reset
        </button>
      </div>
      {current ? (
        <div className="min-h-[460px] px-4 pb-6 pt-3">
          <button type="button" onClick={() => setOpen(null)} className="font-heading text-sm text-brand-ink">
            ‹ Board
          </button>
          <div className="mt-3 rounded-xl border border-line bg-cream p-4 text-charcoal shadow-sm">
            {current.labels.length > 0 && (
              <p className="mb-2 flex flex-wrap gap-1">
                {current.labels.map((l) => (
                  <span
                    key={l}
                    className={`bc-c-${LABELS[l]} rounded-sm px-1.5 text-[11px] font-semibold leading-4 text-white`}
                    style={{ background: 'var(--c)' }}
                  >
                    {l}
                  </span>
                ))}
              </p>
            )}
            <h4 className="font-heading text-lg font-bold leading-snug">{current.title}</h4>
            <p className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted">
              in {COLUMNS[current.col]} <DueChip c={current} />
              {current.who.length > 0 && <AvatarStack people={people(current.who)} size={20} />}
            </p>
            {current.notes && <p className="mt-3 text-sm">{current.notes}</p>}
            {current.steps.length > 0 && (
              <ul className="mt-3 space-y-1">
                {current.steps.map(([s, done], i) => (
                  <li key={s}>
                    <label className="flex items-center gap-2 text-sm">
                      <input
                        type="checkbox"
                        checked={done}
                        className="h-4 w-4 accent-[#1f845a]"
                        onChange={() =>
                          patch(current.id, {
                            steps: current.steps.map(([t, d], j): [string, boolean] => [t, j === i ? !d : d]),
                          })
                        }
                      />
                      <span className={done ? 'text-muted line-through' : ''}>{s}</span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
            <p className="mt-4 text-xs font-bold uppercase tracking-wider text-muted">Move along to</p>
            <div className="mt-1 flex flex-wrap gap-2">
              {COLUMNS.map(
                (name, col) =>
                  col !== current.col && (
                    <button
                      key={name}
                      type="button"
                      className={smallBtn}
                      onClick={() => {
                        patch(current.id, { col });
                        setOpen(null);
                        setFlash(current.id);
                        setToast(`Moved to ${name}`);
                        requestAnimationFrame(() => show(col));
                      }}
                    >
                      {name}
                    </button>
                  ),
              )}
            </div>
            {current.comments.length > 0 && (
              <ul className="mt-4 space-y-2 border-t border-line-faint pt-3">
                {current.comments.map(([by, text], i) => (
                  <li key={i} className="flex gap-2 text-sm">
                    <Avatar person={Object.values(PEOPLE).find((p) => p.name === by)} size={24} />
                    <span>
                      <b className="font-heading">{by}</b> {text}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      ) : (
        <div className="min-h-[460px] pb-6 pt-3">
          <p className="px-5 font-heading font-bold text-charcoal">Bakery website launch</p>
          <div ref={board} className="no-scrollbar mt-2 flex snap-x items-start gap-2.5 overflow-x-auto px-3 pb-2">
            {COLUMNS.map((name, col) => {
              const here = cards.filter((c) => c.col === col);
              return (
                <section
                  key={name}
                  aria-label={name}
                  className="w-[240px] shrink-0 snap-start rounded-xl bg-bc-wash p-2"
                >
                  <h4 className="px-1 pb-2 font-heading text-sm font-bold text-charcoal">
                    {name} <span className="font-normal text-muted">{here.length}</span>
                  </h4>
                  <ul className="space-y-2">
                    {here.map((c) => {
                      const done = c.steps.filter(([, d]) => d).length;
                      return (
                        <li key={c.id}>
                          <button
                            type="button"
                            onClick={() => setOpen(c.id)}
                            aria-label={`Open card ${c.title}`}
                            className={`block w-full rounded-lg border bg-bc-canvas px-3 py-2 text-left text-[14px] text-charcoal shadow-[0_1px_1px_rgb(0_0_0/0.12)] transition-shadow ${toast && flash === c.id ? 'border-bc-blue ring-2 ring-bc-blue' : 'border-transparent'}`}
                          >
                            {c.labels.length > 0 && (
                              <span className="mb-1.5 flex gap-1">
                                {c.labels.map((l) => (
                                  <span
                                    key={l}
                                    className={`bc-c-${LABELS[l]} h-2 w-10 rounded-sm`}
                                    style={{ background: 'var(--c)' }}
                                  />
                                ))}
                              </span>
                            )}
                            <span className={`block ${col === DONE ? 'text-muted line-through' : ''}`}>{c.title}</span>
                            <span className="mt-1.5 flex flex-wrap items-center gap-1.5 text-[12px] text-bc-subtle">
                              <DueChip c={c} />
                              {c.comments.length > 0 && <span>💬 {c.comments.length}</span>}
                              {c.steps.length > 0 && (
                                <span
                                  className={`rounded px-1 ${done === c.steps.length ? 'bg-[#e3fcef] font-semibold text-[#1f845a]' : ''}`}
                                >
                                  ☑ {done}/{c.steps.length}
                                </span>
                              )}
                              {c.who.length > 0 && (
                                <span className="ml-auto">
                                  <AvatarStack people={people(c.who)} size={20} max={3} />
                                </span>
                              )}
                            </span>
                          </button>
                        </li>
                      );
                    })}
                  </ul>
                  {col === 0 && (
                    <form
                      className="mt-2"
                      onSubmit={(e) => {
                        e.preventDefault();
                        add();
                      }}
                    >
                      <input
                        value={adding}
                        onChange={(e) => setAdding(e.target.value)}
                        maxLength={80}
                        aria-label="New card in To do"
                        placeholder="+ Add a card"
                        className="w-full rounded-lg border border-transparent bg-transparent px-2 py-1.5 text-base text-charcoal placeholder:text-muted focus:border-line focus:bg-cream focus:outline-none sm:text-sm"
                      />
                    </form>
                  )}
                </section>
              );
            })}
          </div>
          <p className="mt-2 px-5 text-[13px] text-muted">Tap a card to open it. Swipe for more columns.</p>
        </div>
      )}
    </DemoPhone>
  );
}
