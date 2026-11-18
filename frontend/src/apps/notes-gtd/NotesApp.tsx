import { BASE } from '../../core/app';
// Notes GTD — the web app at /app on Notes GTD's address. The account and its
// session are Todo GTD's (SessionGate, session.ts): one account, every app.
// A note opens over its grid at /n/<id> (or /archive/n/<id>), so the back button
// closes it and a link to it opens it.
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { SessionGate } from '../todo-gtd/PublicTodoApp';
import { NotesConnectPage } from './NotesConnectPage';
import { NotesPage } from './NotesPage';

export function NotesApp() {
  return (
    <SessionGate>
      <BrowserRouter basename={BASE + '/app'}>
        <Routes>
          <Route path="/" element={<NotesPage status="active" />} />
          <Route path="/n/:id" element={<NotesPage status="active" />} />
          <Route path="/archive" element={<NotesPage status="archived" />} />
          <Route path="/archive/n/:id" element={<NotesPage status="archived" />} />
          <Route path="/connect" element={<NotesConnectPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </SessionGate>
  );
}
