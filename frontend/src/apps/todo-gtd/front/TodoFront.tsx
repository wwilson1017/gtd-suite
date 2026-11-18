import { BASE } from '../../../core/app';
// Todo GTD's front page (/ on the todo address): the pitch, a recording of the app itself, the
// scripted "your AI adds it" exchange, the sibling apps, and the way in.
import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import type { AppConfig } from '../api';
import { PolicyNav } from '../../../paid/PolicyLinks';
import appPoster from './app-poster.webp';
import appVideo from './app.mp4';
import boardShot from './board.webp';
import { enhance } from './enhance';
import './front.css';
import inboxShot from './inbox.webp';
import notesShot from './notes.webp';
import todayShot from './today.webp';
import todoShot from './todo.webp';

/** Where each caption's part starts in the recording, in seconds. */
const CAPTIONS: [number, string, string][] = [
  [0, 'Type it the way you’d say it.', '“Call the dentist tomorrow” lands in the Inbox with the date already set.'],
  [7.1, 'File it in three taps.', 'What kind of action it is, any detail, and where you can do it.'],
  [17.2, 'See what your AI added.', 'Its items sit in the same list, marked with its name.'],
  [23.8, 'Check it off.', 'Today shows what is due and what you starred.'],
];

const TOUR = [
  {
    k: '01 · Today',
    h: 'Start with what needs you today.',
    p: 'Today shows what is due and what you starred, and nothing else. Anything your AI added carries its name, so you always know where an item came from.',
    img: todayShot,
    alt: 'Today: two items due and two starred',
  },
  {
    k: '02 · To Do',
    h: 'Every next action, by where you can do it.',
    p: 'At the computer, on the phone, out running errands. Each to-do is one clear action, so you can pick one and do it. Check it off and your AI knows it is done.',
    img: todoShot,
    alt: 'To Do: next actions grouped by context, some marked as added by Claude and ChatGPT',
  },
  {
    k: '03 · Inbox',
    h: 'Capture it now. File it later.',
    p: 'Anything on your mind goes into the Inbox, from you or from your AI, and waits there until you say what it is.',
    img: inboxShot,
    alt: 'Inbox: items waiting to be filed',
  },
];

const WITHOUT_AI = [
  'Today and Inbox',
  'Type-it-naturally quick add',
  'Projects and areas',
  'Capture link for your phone',
  'Weekly review',
  'Contexts like @calls',
];
const WITH_AI = [
  'Adds what you mention in chat',
  'A morning “brain tickle”',
  'Runs the weekly review with you',
  'Imports from your old app',
];
const AI_TOOLS = ['Claude', 'ChatGPT', 'Gemini', 'Grok', 'Cursor', 'Claude Code', 'Codex', 'Le Chat'];

function Shot({ src, alt }: { src: string; alt: string }) {
  return (
    <div className="pop" data-pop>
      <div className="shot">
        <img src={src} width={1280} height={800} alt={alt} loading="lazy" />
      </div>
    </div>
  );
}

export function TodoFront({
  config,
  busy,
  error,
  name,
  onName,
  onStart,
  signIn,
}: {
  /** Null until the server has said what it offers; the buttons wait for it. */
  config: AppConfig | null;
  busy: boolean;
  error: string;
  name: string;
  onName: (name: string) => void;
  onStart: () => void;
  /** The app's own sign-in card, when the server can send mail. */
  signIn: ReactNode;
}) {
  const root = useRef<HTMLDivElement>(null);
  const nameId = useId();
  const [aiOn, setAiOn] = useState(false);
  useEffect(() => (root.current ? enhance(root.current) : undefined), []);

  const hosted = config?.open_signup !== false;
  const mail = config?.mail === true;
  const { notes, projects, sites, brain } = config?.apps ?? {};
  const family = [notes, projects].filter(Boolean).length;
  const start = (
    <button type="button" className="btn go" disabled={busy || !config} onClick={onStart}>
      {busy ? 'Creating…' : 'Start your list'}
    </button>
  );

  return (
    <div className="tf" ref={root}>
      <a href="#main" className="skip-link">
        Skip to content
      </a>
      <nav>
        <div className="wrap">
          <a className="brand" href="#">
            <img src={BASE + '/icon.svg'} alt="" width={28} height={28} />
            Todo GTD
          </a>
          <div className="nl">
            <a href="#try">See it</a>
            <a href="#ai">Your AI</a>
            <a href="#tour">Tour</a>
            {family > 0 && <a href="#family">{notes && projects ? 'Notes & Projects' : 'More apps'}</a>}
            <a href="#why">Why it’s simple</a>
            {mail && <a href="#get">Sign in</a>}
            <button type="button" className="btn go btn-sm" disabled={busy || !config} onClick={onStart}>
              Start your list
            </button>
          </div>
        </div>
      </nav>
      {error && (
        <p role="alert" className="alert">
          {error}
        </p>
      )}

      <main id="main">
        <header className="hero">
          <div className="wrap">
            <div className="mark" aria-hidden="true">
              <div className="tilt" data-tilt>
                <img className="mk" src={BASE + '/icon.svg'} alt="" />
              </div>
              <div className="plate" />
            </div>
            <p className="wordmark">
              Todo<b>GTD</b>
            </p>
            <div className="pill">
              <b>Free</b> No sign-up · works with Claude, ChatGPT and more
            </div>
            <h1>
              <span>Get things done with your AI.</span>
            </h1>
            <p className="lede">
              <strong>
                Your AI already keeps your to-dos, notes and projects in its memory, where you can’t see them.
              </strong>{' '}
              Todo GTD puts them in one simple app you both work from.
            </p>
            <div className="ctas">
              {start}
              <a className="btn btn-ghost" href="#try">
                Watch it work ↓
              </a>
              <a className="btn btn-ghost" href="#ai">
                See it with an AI ↓
              </a>
            </div>
            <p className="fine">One click to start. No account, no password, no card.</p>
            {config?.signed_in && (
              <p className="signed">
                <a href={BASE + '/app'}>Open my list</a> &mdash; this browser is signed in to one.
              </p>
            )}

            <div className="phonewrap" id="try">
              <div>
                <p className="eyebrow">// the real app · 30 seconds</p>
                <h2>A to-do list that fits in your pocket.</h2>
                <p className="intro">This is Todo GTD itself, recorded at phone size. Nothing here is a mock-up.</p>
                <ul id="caps" data-captions>
                  {CAPTIONS.map(([at, head, text]) => (
                    <li key={at} data-at={at}>
                      <button type="button">
                        <b>{head}</b> {text}
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
              <div className="phone">
                <div className="screen vid">
                  <video
                    data-app-video
                    src={appVideo}
                    poster={appPoster}
                    width={752}
                    height={1372}
                    muted
                    playsInline
                    loop
                    preload="auto"
                    aria-label="A 30-second recording of Todo GTD on a phone: a to-do is typed, filed from the Inbox, and two items are checked off on Today"
                  />
                </div>
              </div>
            </div>
          </div>
        </header>

        <section id="ai">
          <div className="wrap">
            <div className="center">
              <div className="bkhello">
                <span className="bkav" aria-hidden="true">
                  ✦
                </span>
                <span>Bring your AI</span>
              </div>
              <h2 className="bkh">Now add your AI.</h2>
              <p className="bksub">It writes. You see it. You both keep it current.</p>
              <p className="intro">
                Add one link to the AI you already use. From then on it can read your list, add what you mention and
                check things off, and everything it adds shows up here with its name on it.
              </p>
            </div>
            <div className="bakerframe">
              <div className="aid" data-ai-demo>
                <div className="aid-chat">
                  <div className="aid-h">
                    <span className="aid-dot" />
                    Your AI <small>Claude, in this demo</small>
                  </div>
                  <div className="aid-msgs" data-msgs />
                </div>
                <div className="aid-list">
                  <div className="aid-h">
                    <img src={BASE + '/icon.svg'} alt="" width={18} height={18} />
                    Todo GTD <small>Today</small>
                    <button type="button" data-replay>
                      ↻ Replay
                    </button>
                  </div>
                  <ul data-rows />
                </div>
              </div>
            </div>
            <div className="bnotes">
              <div>
                <b>One link</b> connects it to Claude, ChatGPT, Gemini, Grok or the tool you code with. The Connect page
                has the steps for each, and there is no password to hand over.
              </div>
              <div>
                <b>It signs its work.</b> Whatever an AI adds is marked with its name. Use two AIs and both see the same
                list.
              </div>
              <div>
                <b>It cannot delete.</b> An AI can add, change and archive. Nothing is ever deleted, and you can bring
                anything back. This demo is scripted.
              </div>
            </div>
          </div>
        </section>

        <div className="wrap">
          <div className="facts">
            <div className="fact">
              <b>1</b>
              <span>
                click to start,
                <br />
                no sign-up
              </span>
            </div>
            <div className="fact">
              <b>1</b>
              <span>
                link connects
                <br />
                your AI
              </span>
            </div>
            {family > 0 ? (
              <div className="fact">
                <b>{family + 1}</b>
                <span>
                  apps on that link:
                  <br />
                  {['to-dos', notes && 'notes', projects && 'projects'].filter(Boolean).join(', ')}
                </span>
              </div>
            ) : (
              <div className="fact">
                <b>0</b>
                <span>
                  passwords
                  <br />
                  to remember
                </span>
              </div>
            )}
            <div className="fact">
              <b>0</b>
              <span>
                things an AI
                <br />
                can delete
              </span>
            </div>
          </div>
        </div>

        <section id="tour" style={{ paddingBottom: 40 }}>
          <div className="wrap">
            <div className="center">
              <p className="eyebrow">// the tour</p>
              <h2>This is the whole thing.</h2>
              <p className="intro">No setup wizard and nothing to configure. Three screens cover your day.</p>
            </div>
            {TOUR.map((s) => (
              <div className="step" key={s.k}>
                <div className="txt">
                  <div className="k">{s.k}</div>
                  <h3>{s.h}</h3>
                  <p>{s.p}</p>
                </div>
                <Shot src={s.img} alt={s.alt} />
              </div>
            ))}
          </div>
        </section>

        {family > 0 && (
          <section id="family" style={{ paddingTop: 40 }}>
            <div className="wrap">
              <div className="center">
                <p className="eyebrow">// the family</p>
                <h2>{family === 2 ? 'Two more apps. Same link.' : 'One more app. Same link.'}</h2>
                <p className="intro">
                  Todo GTD comes with {[notes && 'Notes GTD', projects && 'Projects GTD'].filter(Boolean).join(' and ')}
                  . Each is its own app with its own look. Open one from the bar at the top of your list, and your AI
                  reaches it through the same connection.
                </p>
              </div>
              {notes && (
                <div className="step notes">
                  <div className="txt">
                    <a className="k" href={notes.url}>
                      <img src={BASE + '/icon-notes.svg'} alt="" width={22} height={22} />
                      Notes GTD
                    </a>
                    <h3>Notes you both write in.</h3>
                    <p>
                      Packing lists, quotes, things worth keeping. Your AI adds to a note instead of leaving it buried
                      in a chat, and you can read and edit every one.
                    </p>
                  </div>
                  <Shot src={notesShot} alt="Notes GTD: a grid of coloured notes" />
                </div>
              )}
              {projects && (
                <div className="step projects">
                  <div className="txt">
                    <a className="k" href={projects.url}>
                      <img src={BASE + '/icon-projects.svg'} alt="" width={22} height={22} />
                      Projects GTD
                    </a>
                    <h3>A board for the bigger things.</h3>
                    <p>
                      A to-do is one action. A project in Todo GTD is an outcome that takes a few of them. Work that
                      needs files, research and other people gets a board here: cards move from To do to Done, whether
                      you drag them or your AI moves them.
                    </p>
                  </div>
                  <Shot src={boardShot} alt="Projects GTD: a board with To do, Doing and Done columns" />
                </div>
              )}
              {sites && brain && (
                <p className="also">
                  Also from us, on the same account:{' '}
                  <a href={sites.url} style={{ color: '#1d4ed8' }}>
                    Simple Sites
                  </a>
                  , a place to park the pages your AI makes, and{' '}
                  <a href={brain.url} style={{ color: '#6d4aff' }}>
                    Common Brain
                  </a>
                  . Todo GTD is what your AI helps you do; Common Brain is what your AI knows about you, where you can
                  see it and change it.
                </p>
              )}
            </div>
          </section>
        )}

        <section id="why">
          <div className="wrap">
            <p className="eyebrow">// what it is</p>
            <h2>Simple on purpose.</h2>
            <p className="intro">
              It does a few things and stays out of your way. Everything it leaves out is a thing you never have to
              learn.
            </p>
            <div className="bento">
              <div className="box s2">
                <div className="big">$0</div>
                {hosted ? (
                  <>
                    <h4>Free to start</h4>
                    <p>No card and no trial clock.{mail && ' Confirm an email when you want more room.'}</p>
                  </>
                ) : (
                  <>
                    <h4>Yours to run</h4>
                    <p>This copy runs on its own server, with one list and no account anywhere else.</p>
                  </>
                )}
              </div>
              <div className={aiOn ? 'box s4 on-ai' : 'box s4'}>
                <div className="toggle">
                  <button
                    type="button"
                    className="sw"
                    role="switch"
                    aria-checked={aiOn}
                    aria-label="AI connected"
                    onClick={() => setAiOn(!aiOn)}
                  />
                  <span>{aiOn ? 'AI: connected' : 'AI: not connected'}</span>
                </div>
                <h4>Works before you connect anything</h4>
                <p style={{ marginBottom: 18 }}>
                  By itself this is a complete to-do app. Flip the switch to see what your AI adds.
                </p>
                <ul className="feat">
                  {WITHOUT_AI.map((f) => (
                    <li key={f}>{f}</li>
                  ))}
                  {WITH_AI.map((f) => (
                    <li key={f} className="ai">
                      {f}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="box s3">
                <h4>Nothing is ever deleted</h4>
                <p>Not by you and not by an AI. Archive anything, and bring it back whenever you like.</p>
                <div className="never">⊘ no delete tool for any AI</div>
              </div>
              <div className="box s3">
                <h4>Bring your AI</h4>
                <p>One link connects each of them. A few offer connections only on their paid plans.</p>
                <div className="models">
                  {AI_TOOLS.map((t) => (
                    <span key={t}>{t}</span>
                  ))}
                </div>
              </div>
              <div className="box s3">
                <h4>No AI runs on our side</h4>
                <p>Todo GTD stores your list and shows it to you. The only AI that reads it is the one you connect.</p>
              </div>
              <div className="box s3">
                <h4>Capture from anywhere</h4>
                <p>A capture link drops whatever is on your mind into the Inbox from your phone, with no sign-in.</p>
                <div className="tg">
                  <div className="m me">Ask about the gym’s family plan</div>
                  <div className="m">In your Inbox.</div>
                </div>
              </div>
            </div>
          </div>
        </section>

        <section className="get center" id="get">
          <div className="wrap">
            <p className="eyebrow">// get it</p>
            <h2>Running in 30 seconds.</h2>
            <p className="intro">Three steps. The third one is optional.</p>
            <div className="cmds">
              <div className="cmd">
                <div className="n">01</div>
                <h4>Start</h4>
                <p>Click “Start your list”. That is the whole sign-up: no email, no password.</p>
              </div>
              <div className="cmd">
                <div className="n">02</div>
                <h4>Connect your AI</h4>
                <p>
                  Copy your link from the Connect page and add it to your AI. Then tell it something you need to do.
                </p>
              </div>
              <div className="cmd">
                <div className="n">03 · optional</div>
                {mail ? (
                  <>
                    <h4>Add your email</h4>
                    <p>Confirm an email to sign in on your other devices{hosted && ' and get more room'}.</p>
                  </>
                ) : (
                  <>
                    <h4>Open it on your phone</h4>
                    <p>The Connect page makes a sign-in link for each of your other devices.</p>
                  </>
                )}
              </div>
            </div>
            {/* Nothing here is required: one click on the button still makes a list. */}
            <form
              className="start"
              onSubmit={(e) => {
                e.preventDefault();
                onStart();
              }}
            >
              <div>
                <label htmlFor={nameId}>Name your list (optional)</label>
                <input
                  id={nameId}
                  value={name}
                  maxLength={80}
                  autoComplete="off"
                  onChange={(e) => onName(e.target.value)}
                  placeholder="Home, Work, …"
                />
              </div>
              <button type="submit" className="btn go" disabled={busy || !config}>
                {busy ? 'Creating…' : 'Start your list'}
              </button>
            </form>
            {signIn && <div className="tw">{signIn}</div>}
          </div>
        </section>
      </main>

      <footer>
        <div className="wrap">
          <span>
            Todo GTD
            {family > 0 && `, with ${[notes && 'Notes GTD', projects && 'Projects GTD'].filter(Boolean).join(' and ')}`}
            . Nothing is ever deleted: items are archived, and you can bring them back.
          </span>
          <span>
            {sites && <a href={sites.url}>Simple Sites</a>}
            {brain && <a href={brain.url}>Common Brain</a>}
          </span>
          <PolicyNav config={config} className="policies" />
        </div>
      </footer>
    </div>
  );
}
