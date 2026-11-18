// Todo GTD — "don't show me this again", remembered per list on this device: the
// "keep this list" banner (KeepBanner) and the "Connect your AI" card (TodoShell).
import { useState } from 'react';

function wasDismissed(key: string): boolean {
  try {
    return localStorage.getItem(key) === '1';
  } catch {
    return false; // storage blocked: show it
  }
}

/** Whether the person dismissed the thing called `name` for this list, and the way to. */
export function useDismissed(name: string, listId: number | undefined): [boolean, () => void] {
  const key = listId === undefined ? '' : `todo-gtd-${name}-dismissed-${listId}`;
  const [dismissed, setDismissed] = useState(() => key !== '' && wasDismissed(key));
  const dismiss = () => {
    try {
      localStorage.setItem(key, '1');
    } catch {
      // storage blocked: dismissed until the next page
    }
    setDismissed(true);
  };
  return [dismissed, dismiss];
}
