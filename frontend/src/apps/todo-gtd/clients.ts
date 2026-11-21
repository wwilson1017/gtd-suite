// Todo GTD — how each AI tool is pointed at a list's agent link.
//
// ONE module for all of it: the per-client setup strings shown on the Connect
// page. The agent link is a complete credential in a URL — no header, no
// sign-in — so every recipe below is "use the link as the server URL". Its
// address is built in ONE place, the backend (router.agent_url).

import { APP } from '../../core/app';

/** The name the list is registered under in a tool's own server list. */
const SERVER_NAME = 'gtd';

/** What to paste into an AI that can run on a schedule. It names the two brain-tickle
 *  tools of the list's MCP server; the server, not this text, enforces the five-day rest. */
export const BRAIN_TICKLE_PROMPT = `Every morning, send me one "brain tickle" from my todo-gtd list.

1. Call the todo_brain_tickle tool. It returns my open next actions that have not been tickled in the last five days, along with the rules.
2. Pick exactly ONE. Fit it to my day if you can see it: my calendar, who I am meeting, where I will be.
3. Send me that one item with a single short "why now" line. Never nag, never mention a second item, and never change the todo.
4. If the item comes back flagged stale, ask me to decide instead: do it, defer it, or drop it.
5. Then call todo_brain_tickle_record with that item's id, so it rests for five days.

If the tool returns nothing, send nothing.`;

/** The one message that points an AI agent at the list. "Open" steers the agent to its
 *  fetch tool, the task gives it a reason to read the guide now, and "my own" answers
 *  the permission question. It names no protocol, and it does not say "follow the
 *  instructions on the page", which a cautious assistant reads as prompt injection.
 *  On Projects GTD the task is the boards, on Notes GTD the notes and on Simple Sites the pages: the same link,
 *  read where the user is. */
export const pastePrompt = (url: string) =>
  APP === 'projects'
    ? `Open ${url} and show me my project boards. They are my own, and that page explains how to read and update them.`
    : APP === 'sites'
      ? `Open ${url} and show me my pages and short links. They are my own, and that page explains how to publish and update them.`
      : APP === 'notes'
        ? `Open ${url} and show me my notes. They are my own, and that page explains how to read and update them.`
        : `Open ${url} and show me my next actions. It is my own todo list, and that page explains how to read and update it.`;

export interface ClientSetup {
  name: string;
  /** One-click install address, for the tools that have a documented URL scheme. */
  deeplink?: (url: string) => string;
  /** A command or config snippet to paste, with the link filled in. */
  command?: (url: string) => string;
  /** Where the snippet goes, when it is not a terminal command. */
  commandLabel?: string;
  /** Click path for the chat apps; the last step is always "paste the link". */
  steps?: string[];
  /** Plan or region limits worth knowing before starting. */
  note?: string;
}

export const CLIENTS: ClientSetup[] = [
  {
    name: 'Cursor',
    // config = base64 of the inner server object.
    deeplink: (url) =>
      `cursor://anysphere.cursor-deeplink/mcp/install?name=${SERVER_NAME}` +
      `&config=${encodeURIComponent(btoa(JSON.stringify({ url })))}`,
    command: (url) => JSON.stringify({ mcpServers: { [SERVER_NAME]: { url } } }),
    commandLabel: 'Or add to ~/.cursor/mcp.json',
  },
  {
    name: 'VS Code',
    deeplink: (url) =>
      `vscode:mcp/install?${encodeURIComponent(JSON.stringify({ name: SERVER_NAME, type: 'http', url }))}`,
    command: (url) => `code --add-mcp '${JSON.stringify({ name: SERVER_NAME, type: 'http', url })}'`,
    commandLabel: 'Or run in a terminal',
  },
  {
    name: 'Claude Code',
    command: (url) => `claude mcp add --transport http ${SERVER_NAME} ${url}`,
  },
  {
    name: 'Codex',
    command: (url) => `codex mcp add ${SERVER_NAME} --url ${url}`,
  },
  {
    name: 'Gemini CLI',
    command: (url) => `gemini mcp add --transport http ${SERVER_NAME} ${url}`,
  },
  {
    name: 'Claude (claude.ai)',
    steps: [
      'Open Customize → Connectors.',
      'Choose “Add custom connector”.',
      'Paste your agent link as the remote MCP server URL and choose Add. Leave the sign-in fields empty.',
    ],
  },
  {
    name: 'ChatGPT',
    steps: [
      'Open Settings → Security and login and turn on Developer mode.',
      'Go to chatgpt.com/plugins and select the plus button.',
      'Give it a name, paste your agent link as the MCP server URL, choose “No Authentication”, and create it.',
    ],
    note: 'Paid plans, on the web. ChatGPT will not open a pasted link that holds a key, so this connector is the way in.',
  },
  {
    name: 'Grok',
    steps: [
      'Go to grok.com/connectors.',
      'Choose New Connector → Custom.',
      'Paste your agent link as the MCP server URL.',
    ],
    note: 'Paid plans.',
  },
  {
    name: 'Gemini',
    steps: [
      'On a computer, open gemini.google.com → Settings → Connected Apps.',
      'Under “Custom apps”, choose “Add a custom app”.',
      'Paste your agent link as the MCP server URL and follow the prompts.',
    ],
    note: 'US only, personal Google accounts, with Keep Activity on.',
  },
  {
    name: 'Le Chat',
    steps: [
      'Open Connectors → “+ Add Connector” → “Custom MCP Connector”.',
      `Name it ${SERVER_NAME} and paste your agent link as the Server URL.`,
      'Choose Connect.',
    ],
  },
  {
    name: 'Perplexity',
    steps: [
      'Open Settings → Connectors and add a custom remote connector.',
      'Paste your agent link as the server URL and choose no authentication.',
      'Turn the connector on in the thread or Space you are working in.',
    ],
    note: 'Paid plans, web and desktop.',
  },
];

/** What the agent link reaches in each app it serves (backend/apps.py keys). */
const REACHES: Record<string, string[]> = {
  todo: ['todos'],
  projects: ['project boards'],
  sites: ['pages', 'short links'],
  notes: ['notes'],
  brain: ['brain'],
};

/** What the agent link reaches in the apps turned on: "todos, notes, and project boards". */
export function reachOf(apps: string[]): string {
  return new Intl.ListFormat('en').format(apps.flatMap((key) => REACHES[key] ?? []));
}
