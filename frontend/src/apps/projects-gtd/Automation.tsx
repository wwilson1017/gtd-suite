// Projects GTD — Card Table automation, as Trello's: rules written as a sentence
// ("When a card is moved into Done, add the label Shipped and archive it"), card
// buttons that do a few things to one card, and board buttons that do them to
// every card in a column. Rules run by themselves; buttons when pressed. Nothing
// a rule does sets off another rule.
import { useCallback, useEffect, useState } from 'react';
import { apiErrorMessage } from '../../core/api/client';
import { createRule, getRules, updateRule, type Rule, type RuleAction, type RuleKind } from './api';
import { usePeople } from './ProjectsShell';
import type { Board } from './types';
import { when } from './ui';

const TRIGGERS: [string, string][] = [
  ['card_added', 'a card is added to'],
  ['card_moved', 'a card is moved into'],
  ['card_completed', 'a card is completed'],
  ['subtasks_done', "all of a card's subtasks are done"],
  ['due_soon', 'a card is due within'],
  ['scheduled', 'the time comes (a schedule)'],
];
const WEEKDAYS = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];

/** A scheduled rule's when, as words: "Every Monday at 09:00". */
export function scheduleWords(t: Rule['trigger']): string {
  const at = ` at ${t.time ?? '09:00'}`;
  if (t.every === 'day') return `Every day${at}`;
  if (t.every === 'weekday') return `Every weekday${at}`;
  if (t.every === 'month') return `On day ${t.day} of every month${at}`;
  return `Every ${WEEKDAYS[t.day ?? 1]}${at}`;
}
const ACTIONS: [string, string][] = [
  ['move', 'move it to'],
  ['complete', 'complete it'],
  ['reopen', 're-open it'],
  ['assign', 'assign it to'],
  ['unassign_all', 'take everyone off it'],
  ['add_label', 'add the label'],
  ['remove_label', 'remove the label'],
  ['add_subtasks', 'add subtasks'],
  ['comment', 'comment'],
  ['set_due', 'make it due in'],
  ['clear_due', 'clear its due date'],
  ['archive', 'archive it'],
  ['hold', 'put it on hold'],
];

type Named = { columns: Map<number, string>; labels: Map<number, string>; people: Map<number, string> };

/** A rule or button as the sentence Trello writes. */
export function describe(rule: Pick<Rule, 'kind' | 'trigger' | 'actions'>, n: Named): string {
  const act = rule.actions
    .map((a) => {
      const verb = ACTIONS.find(([k]) => k === a.do)?.[1] ?? a.do;
      if (a.do === 'move')
        return `${verb} ${n.columns.get(a.column ?? 0) ?? '?'}${a.position === 'top' ? ' (at the top)' : ''}`;
      if (a.do === 'assign')
        return `${verb} ${(a.people ?? []).map((p) => n.people.get(Number(p)) ?? (p === 'me' ? 'me' : p)).join(', ')}`;
      if (a.do === 'add_label' || a.do === 'remove_label') return `${verb} ${n.labels.get(a.label ?? 0) ?? '?'}`;
      if (a.do === 'add_subtasks') return `${verb} ${(a.titles ?? []).join(', ')}`;
      if (a.do === 'comment') return `${verb} “${a.text}”`;
      if (a.do === 'set_due') return `${verb} ${a.days} day${a.days === 1 ? '' : 's'}`;
      if (a.do === 'hold') return a.on === false ? 'take it off hold' : verb;
      return verb;
    })
    .join(', then ');
  if (rule.kind === 'card_button') return act;
  if (rule.kind === 'board_button') return `For each card in ${n.columns.get(rule.trigger.column ?? 0) ?? '?'}: ${act}`;
  if (rule.trigger.on === 'scheduled') {
    return `${scheduleWords(rule.trigger)}, for each card in ${n.columns.get(rule.trigger.column ?? 0) ?? '?'}: ${act}.`;
  }
  const on = TRIGGERS.find(([k]) => k === rule.trigger.on)?.[1] ?? rule.trigger.on;
  const where =
    rule.trigger.on === 'due_soon'
      ? ` ${rule.trigger.days ?? 1} day${rule.trigger.days === 1 ? '' : 's'}`
      : rule.trigger.column
        ? ` ${n.columns.get(rule.trigger.column) ?? '?'}`
        : rule.trigger.on === 'card_added'
          ? ' any column'
          : '';
  return `When ${on}${where}: ${act}.`;
}

function ActionRow({
  action,
  board,
  onChange,
  onRemove,
}: {
  action: RuleAction;
  board: Board;
  onChange: (a: RuleAction) => void;
  onRemove: () => void;
}) {
  const { people } = usePeople();
  // Subtask titles are typed as one line; split when the field is left, so spaces survive typing.
  const [titlesText, setTitlesText] = useState((action.titles ?? []).join(', '));
  const cls = 'bc-input w-auto py-1 text-[14px]';
  return (
    <li className="flex flex-wrap items-center gap-2">
      <select
        value={action.do}
        aria-label="Action"
        className={cls}
        onChange={(e) =>
          onChange({
            do: e.target.value,
            ...(e.target.value === 'move' ? { column: board.columns[0]?.id } : {}),
            ...(e.target.value === 'set_due' ? { days: 1 } : {}),
          })
        }
      >
        {ACTIONS.map(([k, l]) => (
          <option key={k} value={k}>
            {l}
          </option>
        ))}
      </select>
      {action.do === 'move' && (
        <>
          <select
            value={action.column ?? ''}
            aria-label="To column"
            className={cls}
            onChange={(e) => onChange({ ...action, column: Number(e.target.value) })}
          >
            {board.columns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
          <select
            value={action.position ?? 'bottom'}
            aria-label="Where"
            className={cls}
            onChange={(e) => onChange({ ...action, position: e.target.value as 'top' | 'bottom' })}
          >
            <option value="bottom">at the bottom</option>
            <option value="top">at the top</option>
          </select>
        </>
      )}
      {action.do === 'assign' && (
        <select
          value={String(action.people?.[0] ?? '')}
          aria-label="Whom"
          className={cls}
          onChange={(e) =>
            onChange({
              ...action,
              people: e.target.value ? [e.target.value === 'me' ? 'me' : Number(e.target.value)] : [],
            })
          }
        >
          <option value="">Pick someone…</option>
          {people.map((p) => (
            <option key={p.id} value={p.kind === 'me' ? 'me' : p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}
      {(action.do === 'add_label' || action.do === 'remove_label') && (
        <select
          value={action.label ?? ''}
          aria-label="Label"
          className={cls}
          onChange={(e) => onChange({ ...action, label: Number(e.target.value) })}
        >
          <option value="">Pick a label…</option>
          {(board.labels ?? []).map((l) => (
            <option key={l.id} value={l.id}>
              {l.name || l.color}
            </option>
          ))}
        </select>
      )}
      {action.do === 'add_subtasks' && (
        <input
          value={titlesText}
          aria-label="Subtasks, comma separated"
          placeholder="Measure, Order, Fit"
          className="bc-input w-64 py-1 text-[14px]"
          onChange={(e) => {
            setTitlesText(e.target.value);
            onChange({
              ...action,
              titles: e.target.value
                .split(',')
                .map((t) => t.trim())
                .filter(Boolean),
            });
          }}
        />
      )}
      {action.do === 'comment' && (
        <input
          value={action.text ?? ''}
          aria-label="Comment"
          placeholder="What to say"
          maxLength={2000}
          className="bc-input w-64 py-1 text-[14px]"
          onChange={(e) => onChange({ ...action, text: e.target.value })}
        />
      )}
      {action.do === 'set_due' && (
        <input
          type="number"
          min={0}
          max={365}
          value={action.days ?? 1}
          aria-label="Days"
          className="bc-input w-20 py-1 text-[14px]"
          onChange={(e) => onChange({ ...action, days: Number(e.target.value) })}
        />
      )}
      {action.do === 'hold' && (
        <select
          value={action.on === false ? 'off' : 'on'}
          aria-label="Hold"
          className={cls}
          onChange={(e) => onChange({ ...action, on: e.target.value === 'on' })}
        >
          <option value="on">on</option>
          <option value="off">off (take it off hold)</option>
        </select>
      )}
      <button
        type="button"
        aria-label="Remove this action"
        className="text-bc-faint hover:text-bc-ink"
        onClick={onRemove}
      >
        ×
      </button>
    </li>
  );
}

function NewRule({ board, kind, onDone }: { board: Board; kind: RuleKind; onDone: (saved: boolean) => void }) {
  const [name, setName] = useState('');
  const [on, setOn] = useState('card_moved');
  const [column, setColumn] = useState<number | ''>(board.columns.find((c) => c.kind === 'done')?.id ?? '');
  const [days, setDays] = useState(1);
  const [every, setEvery] = useState('week'); // a scheduled rule's
  const [dayOf, setDayOf] = useState(1);
  const [time, setTime] = useState('09:00');
  // Each row keeps a stable key, so a row's own typing stays with it when another is removed.
  const [rows, setRows] = useState<{ k: number; a: RuleAction }[]>([{ k: 0, a: { do: 'complete' } }]);
  const actions = rows.map((r) => r.a);
  const [error, setError] = useState('');
  const trigger =
    kind === 'card_button'
      ? {}
      : kind === 'board_button'
        ? { column: column || undefined }
        : on === 'scheduled'
          ? {
              on,
              column: column || undefined,
              every,
              ...(every === 'week' || every === 'month' ? { day: dayOf } : {}),
              time,
            }
          : {
              on,
              ...(on === 'due_soon' ? { days } : {}),
              ...((on === 'card_added' || on === 'card_moved') && column ? { column } : {}),
            };
  const save = async () => {
    try {
      await createRule(board.id, { kind, name: name.trim(), trigger, actions });
      onDone(true);
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not save it.'));
    }
  };
  const cls = 'bc-input w-auto py-1 text-[14px]';
  return (
    <form
      className="mt-3 rounded-lg border border-bc-line bg-bc-canvas p-3"
      onSubmit={(e) => {
        e.preventDefault();
        void save();
      }}
    >
      {kind !== 'rule' && (
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          maxLength={100}
          autoFocus
          aria-label="Button name"
          placeholder="What the button says, e.g. Ship it"
          className="bc-input mb-2 w-72 py-1 text-[14px]"
        />
      )}
      {kind === 'rule' && (
        <div className="flex flex-wrap items-center gap-2 text-[15px]">
          <span className="font-bold">When</span>
          <select value={on} onChange={(e) => setOn(e.target.value)} aria-label="When" className={cls}>
            {TRIGGERS.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
          {(on === 'card_added' || on === 'card_moved') && (
            <select
              value={column}
              onChange={(e) => setColumn(e.target.value ? Number(e.target.value) : '')}
              aria-label="Column"
              className={cls}
            >
              {on === 'card_added' && <option value="">any column</option>}
              {board.columns.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          )}
          {on === 'due_soon' && (
            <>
              <input
                type="number"
                min={0}
                max={30}
                value={days}
                onChange={(e) => setDays(Number(e.target.value))}
                aria-label="Days"
                className="bc-input w-16 py-1 text-[14px]"
              />{' '}
              <span>days</span>
            </>
          )}
          {on === 'scheduled' && (
            <>
              <select
                value={every}
                onChange={(e) => {
                  setEvery(e.target.value);
                  setDayOf(1);
                }}
                aria-label="How often"
                className={cls}
              >
                <option value="day">every day</option>
                <option value="weekday">every weekday</option>
                <option value="week">every week, on</option>
                <option value="month">every month, on day</option>
              </select>
              {every === 'week' && (
                <select
                  value={dayOf}
                  onChange={(e) => setDayOf(Number(e.target.value))}
                  aria-label="Day of the week"
                  className={cls}
                >
                  {WEEKDAYS.map((d, i) => (
                    <option key={d} value={i}>
                      {d}
                    </option>
                  ))}
                </select>
              )}
              {every === 'month' && (
                <select
                  value={dayOf}
                  onChange={(e) => setDayOf(Number(e.target.value))}
                  aria-label="Day of the month"
                  className={cls}
                >
                  {Array.from({ length: 28 }, (_, i) => (
                    <option key={i + 1} value={i + 1}>
                      {i + 1}
                    </option>
                  ))}
                </select>
              )}
              <span>at</span>
              <input
                type="time"
                value={time}
                onChange={(e) => setTime(e.target.value)}
                aria-label="Time"
                className={cls}
                required
              />
              <span>, for each card in</span>
              <select
                value={column}
                onChange={(e) => setColumn(e.target.value ? Number(e.target.value) : '')}
                aria-label="Column"
                className={cls}
              >
                <option value="">Pick a column…</option>
                {board.columns.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </>
          )}
        </div>
      )}
      {kind === 'board_button' && (
        <div className="flex flex-wrap items-center gap-2 text-[15px]">
          <span className="font-bold">For each card in</span>
          <select
            value={column}
            onChange={(e) => setColumn(e.target.value ? Number(e.target.value) : '')}
            aria-label="Column"
            className={cls}
          >
            <option value="">Pick a column…</option>
            {board.columns.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </div>
      )}
      <p className="mt-2 text-[14px] font-bold">Then</p>
      <ol className="mt-1 space-y-2">
        {rows.map((row) => (
          // Keyed by kind too: changing what a row does starts its fields afresh.
          <ActionRow
            key={`${row.k}-${row.a.do}`}
            action={row.a}
            board={board}
            onChange={(next) => setRows(rows.map((r) => (r.k === row.k ? { ...r, a: next } : r)))}
            onRemove={() => setRows(rows.filter((r) => r.k !== row.k))}
          />
        ))}
      </ol>
      {actions.length < 20 && (
        <button
          type="button"
          className="mt-2 text-[14px] text-bc-blue underline"
          onClick={() =>
            setRows([...rows, { k: Math.max(0, ...rows.map((r) => r.k)) + 1, a: { do: 'comment', text: '' } }])
          }
        >
          + Add another action
        </button>
      )}
      {error && (
        <p role="alert" className="mt-2 text-sm text-bc-unread">
          {error}
        </p>
      )}
      <div className="mt-3 flex gap-2">
        <button type="submit" className="bc-btn bc-btn-primary bc-btn-sm" disabled={!actions.length}>
          Save
        </button>
        <button type="button" className="bc-btn bc-btn-sm" onClick={() => onDone(false)}>
          Cancel
        </button>
      </div>
    </form>
  );
}

/** The Card Table's ••• → Automation: its rules and buttons, and adding more. */
export function AutomationPanel({ board, onClose }: { board: Board; onClose: () => void }) {
  const { people } = usePeople();
  const [rules, setRules] = useState<Rule[]>([]);
  const [showArchived, setShowArchived] = useState(false);
  const [archived, setArchived] = useState<Rule[]>([]);
  const [adding, setAdding] = useState<RuleKind | null>(null);
  const [error, setError] = useState('');
  const load = useCallback(() => {
    getRules(board.id).then(setRules, (e) => setError(apiErrorMessage(e, 'Could not load the rules.')));
    if (showArchived) getRules(board.id, 'archived').then(setArchived, () => {});
  }, [board.id, showArchived]);
  useEffect(load, [load]);
  const named: Named = {
    columns: new Map(board.columns.map((c) => [c.id, c.name])),
    labels: new Map((board.labels ?? []).map((l) => [l.id, l.name || l.color])),
    people: new Map(people.map((p) => [p.id, p.name])),
  };
  const section = (kind: RuleKind, title: string, blurb: string) => (
    <section className="mt-4">
      <h3 className="font-bold">{title}</h3>
      <p className="text-[14px] text-bc-subtle">{blurb}</p>
      <ul className="mt-2 space-y-2">
        {rules
          .filter((r) => r.kind === kind)
          .map((r) => (
            <li key={r.id} className="flex items-start gap-3 rounded-lg bg-bc-canvas px-3 py-2">
              <div className="min-w-0 flex-1 text-[15px]">
                {r.name && <b>{r.name}: </b>}
                {describe(r, named)}
                <span className="block text-[12px] text-bc-subtle">
                  {r.runs
                    ? `Ran ${r.runs} time${r.runs === 1 ? '' : 's'}${r.last_run_at ? `, last ${when(r.last_run_at)}` : ''}`
                    : 'Not run yet'}
                </span>
                {r.last_error && (
                  <span role="alert" className="block text-[13px] text-bc-unread">
                    Last time it stopped: {r.last_error}
                  </span>
                )}
              </div>
              <button
                type="button"
                className="text-[13px] text-bc-subtle underline"
                onClick={() => void updateRule(r.id, { status: 'archived' }).then(load)}
              >
                Archive
              </button>
            </li>
          ))}
      </ul>
      {adding === kind ? (
        <NewRule
          board={board}
          kind={kind}
          onDone={(saved) => {
            setAdding(null);
            if (saved) load();
          }}
        />
      ) : (
        <button type="button" className="mt-2 bc-btn bc-btn-sm" onClick={() => setAdding(kind)}>
          + Add {title.toLowerCase().replace(/s$/, '')}
        </button>
      )}
    </section>
  );
  return (
    <div role="dialog" aria-label="Automation" className="mt-4 rounded-lg border border-bc-line bg-bc-wash p-4">
      <div className="flex items-center gap-2">
        <h2 className="text-lg font-bold">Automation</h2>
        <button type="button" className="ml-auto bc-btn bc-btn-sm" onClick={onClose}>
          Done
        </button>
      </div>
      <p className="text-[14px] text-bc-subtle">
        What it does shows in the activity as “Automation”. Nothing a rule does sets off another rule.
      </p>
      {error && (
        <p role="alert" className="text-bc-unread">
          {error}
        </p>
      )}
      {section(
        'rule',
        'Rules',
        'They run by themselves when something happens to a card, your AI tools’ cards included.',
      )}
      {section('card_button', 'Card buttons', 'They show on every card; pressing one does these things to that card.')}
      {section(
        'board_button',
        'Board buttons',
        'They show above the table; pressing one does these things to every card in a column.',
      )}
      <div className="mt-4 border-t border-bc-line pt-3">
        {!showArchived ? (
          <button type="button" className="text-[14px] text-bc-subtle underline" onClick={() => setShowArchived(true)}>
            Archived rules and buttons
          </button>
        ) : (
          <>
            <h3 className="font-bold">Archived</h3>
            {archived.length === 0 && <p className="text-[14px] text-bc-subtle">None.</p>}
            <ul className="mt-1 space-y-1">
              {archived.map((r) => (
                <li key={r.id} className="flex items-start gap-3 text-[14px]">
                  <span className="min-w-0 flex-1">
                    {r.name && <b>{r.name}: </b>}
                    {describe(r, named)}
                  </span>
                  <button
                    type="button"
                    className="text-bc-blue underline"
                    onClick={() => void updateRule(r.id, { status: 'active' }).then(load)}
                  >
                    Restore
                  </button>
                </li>
              ))}
            </ul>
          </>
        )}
      </div>
    </div>
  );
}
