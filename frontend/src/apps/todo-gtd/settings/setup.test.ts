// How far an account is set up: step 1 once an AI tool has called, step 2 (only where
// the server can mail) once the email is confirmed, with "pending" while its link waits.
import { describe, expect, it } from 'vitest';
import type { Session } from '../types';
import { setupOf } from './setup';

const BASE: Session = {
  list_id: 7,
  state: 'active',
  email: null,
  verified: false,
  hosted: true,
  mail: true,
  caps: { todos: 200, projects: 20, areas: 10 },
  apps: ['todo'],
  ai_tools: [],
};
const AI = { ai_tools: [{ name: 'Claude', last_used: '2026-11-21', days_ago: 0 }] };
const states = (session: Partial<Session>) => {
  const { steps, next } = setupOf({ ...BASE, ...session });
  return [steps.map((s) => `${s.key}:${s.state}`).join(' '), next?.key ?? null];
};

describe('setupOf', () => {
  it.each<[string, Partial<Session>, string, string | null]>([
    ['brand new', {}, 'ai:todo email:todo', 'ai'],
    ['an email saved first', { email: 'me@example.com' }, 'ai:todo email:pending', 'ai'],
    ['an AI connected', AI, 'ai:done email:todo', 'email'],
    ['the email sent', { ...AI, email: 'me@example.com' }, 'ai:done email:pending', 'email'],
    ['all set', { ...AI, email: 'me@example.com', verified: true }, 'ai:done email:done', null],
    ['no mail on the server', { mail: false }, 'ai:todo', 'ai'],
    ['no mail, the AI connected', { ...AI, mail: false }, 'ai:done', null],
  ])('%s', (_, session, steps, next) => {
    expect(states(session)).toEqual([steps, next]);
  });

  it('shows nothing while the session is loading', () => {
    expect(setupOf(null)).toEqual({ steps: [], next: null });
  });
});
