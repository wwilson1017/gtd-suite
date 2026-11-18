import { BASE } from '../../core/app';
// Simple Sites — the web app at /app on its own address. The account and its
// session are Todo GTD's (SessionGate, session.ts): one account, every app.
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { SessionGate } from '../todo-gtd/PublicTodoApp';
import { SitesConnectPage } from './SitesConnectPage';
import { SitesPage } from './SitesPage';

export function SitesApp() {
  return (
    <SessionGate>
      <BrowserRouter basename={BASE + '/app'}>
        <Routes>
          <Route path="/" element={<SitesPage />} />
          <Route path="/connect" element={<SitesConnectPage />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </BrowserRouter>
    </SessionGate>
  );
}
