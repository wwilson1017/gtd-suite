import { BASE } from '../../core/app';
// Common Brain — the web app at /app on Common Brain's address. The account and its
// session are the suite's (SessionGate, session.ts): one account, every app.
import { useEffect, useRef } from 'react';
import { useNavigate } from 'react-router-dom';
import { useBrainSelection } from '../todo-gtd/brainSelection';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';
import { SessionGate } from '../todo-gtd/PublicTodoApp';
import { ArchivePage } from './ArchivePage';
import { BrainSettings } from './BrainSettings';
import { BrainHome } from './BrainHome';
import { ChangesPage } from './ChangesPage';
import { FilesPage } from './FilesPage';
import { ForgetPage } from './ForgetPage';
import { PageView } from './PageView';

export function BrainApp() {
  return (
    <SessionGate>
      <BrowserRouter basename={BASE + '/app'}>
        <BrainRoutes />
      </BrowserRouter>
    </SessionGate>
  );
}

function BrainRoutes() {
  const { id, generation, notice } = useBrainSelection();
  const navigate = useNavigate();
  const redirected = useRef<number | null>(null);
  useEffect(() => {
    if (notice && redirected.current !== generation) {
      redirected.current = generation;
      navigate('/', { replace: true });
    }
  }, [notice, generation, navigate]);
  return (
    <Routes key={`${id}:${generation}`}>
      <Route path="/brains" element={<Navigate to="/connect/brains" replace />} />
      <Route path="/brains/new" element={<Navigate to="/connect/brains?new" replace />} />
      <Route path="/" element={<BrainHome />} />
      <Route path="/p/:id" element={<PageView />} />
      <Route path="/files" element={<FilesPage />} />
      <Route path="/changes" element={<ChangesPage />} />
      <Route path="/archive" element={<ArchivePage />} />
      <Route path="/connect" element={<BrainSettings />} />
      <Route path="/connect/:section" element={<BrainSettings />} />
      <Route path="/forget/:kind/:id" element={<ForgetPage />} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
