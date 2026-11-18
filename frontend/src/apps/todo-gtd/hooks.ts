// Todo GTD — shared page plumbing.
import { useCallback, useEffect, useRef, useState } from 'react';
import { updateTodo } from './api';
import { toast } from './toast';
import type { Todo, TodoStatus } from './types';
import { dropUndo, queueUndo, takeAll, takeEntry, type UndoEntry } from './undoQueue';
import { refreshMeta } from './useTodoMeta';

/** Reopening a completed repeating todo leaves its already-spawned successor in
 *  place — the backend spawns on the transition INTO done and never unspawns
 *  (`service.py::_spawn_next_occurrence`), so both copies are now live. Said
 *  the same way whether the user unchecked the box by hand or used the undo pill;
 *  a silent duplicate is the failure mode this notice exists to prevent. */
const REOPENED_REPEAT_ONE = 'Reopened — its next occurrence already exists from when it was completed.';
const REOPENED_REPEAT_MANY = 'Reopened — their next occurrences already exist from when they were completed.';

// ── "The todo lists changed" broadcast ───────────────────────────────────────
// Every list page owns a page-local reload(). That is enough for a mutation made
// ON that page, but not for an undo: the pill outlives the shell (module state,
// see undoQueue.ts), so a revert can land while the user is standing on a
// DIFFERENT list than the one they completed from — and undo must make the todo
// reappear in its original list, not merely on the server. Fired only by the
// undo path, so no other mutation's refetch behavior changes.
const listListeners = new Set<() => void>();

// where the Inbox's triage card should land next, set by an undo that put an
// item back in the inbox. Module state for the same reason the queue itself is: TodoShell
// unmounts on every tab switch, so an undo clicked from Today has no InboxPage
// listening, and the request has to wait until the Inbox is actually looking.
// Deliberately NOT owner-scoped: todo ids are global, so a request left by a
// previous occupant of the tab simply misses `items.find` and falls through to the
// head of the list — the same no-op a stale selection already is.
let pendingInboxFocus: number | null = null;

/** `focusInboxId` asks the Inbox to promote that todo to its triage card. */
export function notifyTodosChanged(focusInboxId?: number) {
  if (focusInboxId !== undefined) pendingInboxFocus = focusInboxId;
  listListeners.forEach((l) => l());
}

/** Reload this page's list whenever `notifyTodosChanged()` fires. `useTodos`
 *  calls it for you; pages that keep their own loadSeq (Search, Project detail)
 *  call it directly. The ref keeps the subscription stable across renders while
 *  still calling the latest reload. */
export function useTodosChanged(reload: () => void) {
  const reloadRef = useRef(reload);
  useEffect(() => {
    reloadRef.current = reload;
  });
  useEffect(() => {
    const listener = () => {
      reloadRef.current();
    };
    listListeners.add(listener);
    return () => {
      listListeners.delete(listener);
    };
  }, []);
}

/** Forget any triage focus still waiting to be taken. For tests: `pendingInboxFocus`
 *  is module state that deliberately OUTLIVES the page (that is the whole point —
 *  see above), so without this a focus raised by one case is drained by the next
 *  harness that mounts, and an assertion about what an undo asked for reads the
 *  previous test's request. `undoQueue.resetUndoQueue` and `toast.resetToasts`
 *  exist for the same reason. */
export function resetInboxFocus() {
  pendingInboxFocus = null;
}

/** Take the triage focus an undo left behind, if there is one. Fires on mount as
 *  well as on the broadcast, which is what makes a revert clicked from another tab
 *  still land on the card once the user walks back to the Inbox. Drained on read —
 *  a focus is one request, not a standing preference. */
export function useInboxFocus(focus: (id: number) => void) {
  const focusRef = useRef(focus);
  useEffect(() => {
    focusRef.current = focus;
  });
  useEffect(() => {
    const take = () => {
      const id = pendingInboxFocus;
      if (id === null) return;
      pendingInboxFocus = null;
      focusRef.current(id);
    };
    take();
    listListeners.add(take);
    return () => {
      listListeners.delete(take);
    };
  }, []);
}

/** Load todos for a page. `refetchKey` re-runs the fetch when a page-level
 * input changes (e.g. DonePage's done|dropped toggle); reload() re-runs it
 * after a mutation. Unmounted/superseded responses are dropped. */
export function useTodos(fetcher: () => Promise<Todo[]>, refetchKey: unknown = null) {
  const [todos, setTodos] = useState<Todo[] | null>(null);
  const [failed, setFailed] = useState(false);
  const [loadSeq, setLoadSeq] = useState(0);
  const fetcherRef = useRef(fetcher);

  useEffect(() => {
    fetcherRef.current = fetcher;
  });

  useEffect(() => {
    let cancelled = false;
    fetcherRef
      .current()
      .then((result) => {
        if (cancelled) return;
        setTodos(result);
        setFailed(false);
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [loadSeq, refetchKey]);

  const reload = useCallback(() => {
    setLoadSeq((s) => s + 1);
  }, []);
  useTodosChanged(reload);
  return { todos, failed, reload };
}

/** Put ONE queued row back the way it was. Takes the entry off the queue FIRST:
 *  that clears its 7s timer and makes a double-click idempotent, so the revert can
 *  never race its own expiry. A failed revert leaves the write standing and says
 *  so — the todo is still reachable, from the Done list or from its new list. */
export async function undoOne(key: number): Promise<void> {
  const entry = takeEntry(key);
  if (!entry) return;
  if (!(await revertEntry(entry))) return;
  // Only a completion spawned anything to warn about.
  if (entry.kind === 'done' && entry.repeat) toast.info(REOPENED_REPEAT_ONE);
  afterUndo(focusIdOf(entry));
}

/** Put every currently-queued row back ("Undo all"). */
export async function undoAll(): Promise<void> {
  const entries = takeAll();
  if (entries.length === 0) return;
  const results = await Promise.all(entries.map(revertEntry));
  const restored = entries.filter((_, i) => results[i]);
  const reopenedRepeats = restored.filter((e) => e.kind === 'done' && e.repeat).length;
  if (reopenedRepeats === 1) toast.info(REOPENED_REPEAT_ONE);
  else if (reopenedRepeats > 1) toast.info(REOPENED_REPEAT_MANY);
  if (restored.length === 0) return;
  // The LAST inbox item that actually made it back — a revert that failed never
  // returned to the inbox, so pointing the card at it would show an empty card.
  afterUndo(
    restored
      .map(focusIdOf)
      .filter((id) => id !== undefined)
      .pop(),
  );
}

/** An undo that puts an item back in the INBOX has somewhere to be looked at:
 *  Undoing a filing requires the item to come back as the CURRENT triage card, not to be
 *  corrected silently behind the list the user is standing on. Keyed on where the
 *  revert lands rather than on the kind: every filing lands there, and so does a
 *  completion made from triage ("Took 2 minutes — Done ✓", or the edit sheet opened
 *  off the card), which would otherwise reappear wherever `items[0]` happens to
 *  put it — or behind the filter bar, where the undo looks like it did nothing. */
function focusIdOf(entry: UndoEntry): number | undefined {
  return entry.restore.status === 'inbox' ? entry.id : undefined;
}

async function revertEntry(entry: UndoEntry): Promise<boolean> {
  try {
    await updateTodo(entry.id, entry.restore);
    return true;
  } catch {
    const still = { filed: "it's still filed", deleted: "it's still deleted", done: "it's still marked done" }[
      entry.kind
    ];
    toast.error(`Couldn't undo “${entry.title}” — ${still}.`);
    return false;
  }
}

function afterUndo(focusInboxId?: number) {
  void refreshMeta();
  notifyTodosChanged(focusInboxId);
}

/** Row mutations every list page shares. Each mutation reloads the page's
 * list AND the shared meta so the inbox badge/counts stay honest. Failures
 * surface as a toast — one-click row actions have no inline error slot. */
export function useRowActions(reload: () => void) {
  const after = useCallback(() => {
    reload();
    void refreshMeta();
  }, [reload]);

  const patch = useCallback(async (id: number, fields: Record<string, unknown>) => {
    try {
      await updateTodo(id, fields);
      return true;
    } catch {
      toast.error('Failed to update todo.');
      return false;
    }
  }, []);

  const toggleDone = useCallback(
    async (todo: Todo, uncheckStatus: TodoStatus = 'next_action') => {
      const markingDone = todo.status !== 'done';
      const ok = await patch(todo.id, {
        status: markingDone ? 'done' : uncheckStatus,
      });
      if (ok && markingDone) {
        // the 7s undo row. Queued with the todo AS IT WAS, so undo restores
        // the status it actually held (not always 'next_action': the Done page's
        // Dropped tab completes a 'dropped' row).
        queueUndo(todo);
      }
      if (ok && !markingDone) {
        // Unchecked by hand inside the window — the pending "Undo?" for this todo
        // now offers to redo what the user just did themselves.
        dropUndo(todo.id);
        if (todo.repeat) {
          // Completing a repeating todo already spawned its successor; reopening
          // this one means both copies are now live.
          toast.info(REOPENED_REPEAT_ONE);
        }
      }
      after();
    },
    [after, patch],
  );

  const toggleStar = useCallback(
    async (todo: Todo) => {
      await patch(todo.id, { star: !todo.star });
      after();
    },
    [after, patch],
  );

  const setStatus = useCallback(
    async (todo: Todo, status: TodoStatus) => {
      const ok = await patch(todo.id, { status });
      // Same invariant as `toggleDone`'s un-done branch: an explicit status write
      // invalidates any undo row still pending for this todo, which would otherwise
      // revert the decision the user just made.
      if (ok && status !== 'done') dropUndo(todo.id);
      after();
    },
    [after, patch],
  );

  return { toggleDone, toggleStar, setStatus, after };
}
