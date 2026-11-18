import { BASE } from '../../core/app';
// Projects GTD — the web app at /app on Projects GTD's address. The account and its
// session are Todo GTD's (SessionGate, session.ts): one account, every app.
// Home, a project (it opens on its board, Trello's way; its Overview and tools are
// tabs beside it), an item's page, and the pages the header's tabs open.
import { BrowserRouter, Navigate, Route, Routes, useParams } from 'react-router-dom';
import { SessionGate } from '../todo-gtd/PublicTodoApp';
import { BoardPage } from './BoardPage';
import { ChatPage, DoorsPage } from './ChatPage';
import { CalendarPage } from './CalendarPage';
import { CheckinsPage, LineupPage } from './CheckinsPage';
import { DocsPage } from './DocsPage';
import { ArchivePage, EverythingPage, SearchPage } from './EverythingPage';
import { HomePage } from './HomePage';
import { ItemPage } from './ItemPage';
import { MessageBoardPage, NewMessagePage } from './MessageBoardPage';
import { ActivityPage, BookmarksPage, BoostsPage, DraftsPage, MyTasksPage, PeoplePage } from './MyPages';
import { ProjectPage } from './ProjectPage';
import { PeopleProvider } from './ProjectsShell';
import { ProjectsConnectPage, ProjectsYourAIPage } from './ProjectsConnectPage';
import { PersonTasks, ReportPage, ReportsIndex } from './ReportsPage';
import { TodosPage } from './TodosPage';

/** The beta's board address opens that project, which is its board. */
function OldBoard() {
  return <Navigate to={`/p/${useParams().id}`} replace />;
}

export function ProjectsApp() {
  return (
    <SessionGate>
      <PeopleProvider>
        <BrowserRouter basename={BASE + '/app'}>
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/p/:id" element={<BoardPage />} />
            <Route path="/p/:id/overview" element={<ProjectPage />} />
            <Route path="/p/:id/messages" element={<MessageBoardPage />} />
            <Route path="/p/:id/messages/new" element={<NewMessagePage />} />
            <Route path="/p/:id/todos" element={<TodosPage />} />
            <Route path="/p/:id/cards" element={<BoardPage />} />
            <Route path="/p/:id/docs" element={<DocsPage />} />
            <Route path="/p/:id/chat" element={<ChatPage />} />
            <Route path="/p/:id/doors" element={<DoorsPage />} />
            <Route path="/p/:id/calendar" element={<CalendarPage />} />
            <Route path="/p/:id/checkins" element={<CheckinsPage />} />
            <Route path="/calendar" element={<CalendarPage />} />
            <Route path="/lineup" element={<LineupPage />} />
            <Route path="/p/:id/archive" element={<ArchivePage />} />
            <Route path="/everything" element={<EverythingPage />} />
            <Route path="/search" element={<SearchPage />} />
            <Route path="/reports" element={<ReportsIndex />} />
            <Route path="/reports/:kind" element={<ReportPage />} />
            <Route path="/reports/person/:person" element={<PersonTasks />} />
            <Route path="/i/:id" element={<ItemPage />} />
            <Route path="/b/:id" element={<OldBoard />} />
            <Route path="/activity" element={<ActivityPage />} />
            <Route path="/my/tasks" element={<MyTasksPage />} />
            <Route path="/my/bookmarks" element={<BookmarksPage />} />
            <Route path="/my/drafts" element={<DraftsPage />} />
            <Route path="/my/boosts" element={<BoostsPage />} />
            <Route path="/people" element={<PeoplePage />} />
            <Route path="/ai" element={<ProjectsYourAIPage />} />
            <Route path="/connect" element={<ProjectsConnectPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Routes>
        </BrowserRouter>
      </PeopleProvider>
    </SessionGate>
  );
}
