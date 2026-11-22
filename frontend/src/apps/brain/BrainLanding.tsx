import { BASE } from '../../core/app';
import { BrainExtra, BrainExtraLink } from '../../plans/offers';
// Common Brain — the front door, the main page of the whole suite: the
// pitch, the live demo (ChatGPT saves, the brain keeps it, Claude uses it), how to connect,
// what every AI hears first, the suite's other apps, account options, and the one
// button that starts a brain. Starting turns on every app of the suite (lists.create_list).
import { useEffect, useRef, type ReactNode } from 'react';
import type { AppConfig } from '../todo-gtd/api';
import { Mark } from './Mark';
import { PolicyLinks } from '../../plans/PolicyLinks';
import './brain.css';

/** The suite's other apps, in the order they're shown. Each links to its own address
 *  (config.apps), so a server without one leaves it out. */
const SUITE: [string, string, string][] = [
  [
    'todo',
    'Todo GTD',
    'A to-do list you and your AIs share. Capture everything, then sort it the Getting Things Done way.',
  ],
  ['notes', 'Notes GTD', 'Quick notes and lists, like Google Keep, that every AI can read, search and add to.'],
  ['projects', 'Projects GTD', 'Simple project boards you and your AIs work on together, card by card.'],
  ['sites', 'Simple Sites', 'Put what your AI makes on the web, a page or a short link, in one step.'],
];

export function BrainLanding({
  onStart,
  busy,
  ready,
  error,
  signedIn,
  signIn,
  apps,
  config,
}: {
  onStart: () => void;
  busy: boolean;
  ready: boolean;
  error: string;
  signedIn: boolean;
  signIn: ReactNode;
  apps: Record<string, { title: string; url: string }>;
  config: AppConfig | null;
}) {
  const address = apps.brain?.url ? new URL(apps.brain.url) : null;
  const suite = SUITE.filter(([key]) => apps[key]?.url);
  useEffect(() => {
    document.title = 'Common Brain · one brain for every AI';
  }, []);
  const start = signedIn ? (
    <a href={BASE + '/app'} className="cb-btn">
      Open my brain
    </a>
  ) : (
    <button type="button" onClick={onStart} disabled={busy || !ready} className="cb-btn">
      {busy ? 'Starting…' : 'Start my brain, free'}
    </button>
  );
  return (
    <div className="cb-site">
      <div className="in">
        <header className="top">
          <a href={BASE + '/'} className="brand">
            <Mark className="h-[30px] w-[30px] text-[#e9ecff]" small />
            Common Brain
          </a>
          <nav className="links" aria-label="Common Brain">
            <a href="#how">How it works</a>
            {suite.length > 0 && <a href="#apps">Apps</a>}
            <BrainExtraLink config={config} />
            <a href={signedIn ? BASE + '/app' : '#signin'}>{signedIn ? 'Open' : 'Sign in'}</a>
            {!signedIn && (
              <button type="button" onClick={onStart} disabled={busy || !ready} className="cb-btn px-3.5 py-2 text-sm">
                Start free
              </button>
            )}
          </nav>
        </header>

        <div className="hero">
          <div className="eyebrow mono">ONE BRAIN · EVERY AI</div>
          <h1>
            Your AIs don&rsquo;t talk to each other. <span className="cb-grad-text">Now they share a brain.</span>
          </h1>
          <p className="lede">
            Tell ChatGPT something on Monday. Claude knows it on Tuesday. One memory for every AI you use. You can read
            it, fix it and take it with you.
          </p>
          <div className="cta">
            {start}
            <a href="#how" className="cb-btn-ghost px-5 py-3">
              See how it works
            </a>
          </div>
          {error && (
            <p role="alert" className="fine" style={{ color: '#ff9db0' }}>
              {error}
            </p>
          )}
          <p className="fine">Nothing to install. Connect your first AI in about two minutes.</p>
        </div>

        <Demo />

        <section id="how">
          <h2>Connect every AI you use</h2>
          <p className="sub2">Chat apps, phone apps and terminal agents all connect to the same brain with one link.</p>
          <Network />
          <div className="grid3" style={{ marginTop: 22 }}>
            <div className="glass">
              <div className="n mono">STEP 1</div>
              <h3>Start your brain</h3>
              <p>One tap. Nothing to install.</p>
            </div>
            <div className="glass">
              <div className="n mono">STEP 2</div>
              <h3>Connect your AI</h3>
              <p>Copy one link into ChatGPT, Claude, Grok or your terminal. Each app gets its own steps.</p>
            </div>
            <div className="glass">
              <div className="n mono">STEP 3</div>
              <h3>Say &ldquo;set up my brain&rdquo;</h3>
              <p>Your AI brings what it already knows about you, asks about the gaps, and you watch it fill in.</p>
            </div>
          </div>
        </section>

        <section>
          <h2>What every AI hears first</h2>
          <p className="sub2">Every new chat opens with the brain: your memory, what changed and the house rules.</p>
          <div className="term mono">
            <div className="d"># Claude, opening a new chat</div>
            <div>
              <span className="c">→ brain_start</span>
            </div>
            <div>&nbsp;&nbsp;memory: 41 facts about Maya (3 locked)</div>
            <div>
              &nbsp;&nbsp;since you were last here: <span className="c">Grok</span> added 2 ·{' '}
              <span className="c">ChatGPT</span> edited trips/japan-april
            </div>
            <div>&nbsp;&nbsp;todo: 3 in the inbox, 12 next actions (2 starred)</div>
            <div>&nbsp;&nbsp;rules: short facts → memory · long things → pages · never save passwords</div>
          </div>
        </section>

        <section>
          <h2>Built like a real second brain</h2>
          <p className="sub2">The same system a company brain runs on, made simple enough for one person.</p>
          <div className="grid3">
            <div className="glass">
              <h3>Memory + pages</h3>
              <p>Facts every AI loads first, and Markdown or HTML pages in folders for everything longer.</p>
            </div>
            <div className="glass">
              <h3>Full history</h3>
              <p>Every change, which AI made it and when. Restore anything.</p>
            </div>
            <div className="glass">
              <h3>Free curator</h3>
              <p>
                A skill you run in Claude Code, Codex or any chat. It sorts the inbox, merges duplicates and fills gaps.
              </p>
            </div>
            <div className="glass">
              <h3>Set up once per AI</h3>
              <p>Each new AI brings what it knows, then the brain asks you about anything that conflicts.</p>
            </div>
            <div className="glass">
              <h3>Lock what matters</h3>
              <p>Lock a memory and no AI can change it. Forget anything for good; your AIs can only ask.</p>
            </div>
            <div className="glass">
              <h3>Yours to take</h3>
              <p>Export your whole brain as plain .md and .html files, any time.</p>
            </div>
          </div>
        </section>

        {suite.length > 0 && (
          <section id="apps">
            <h2>Every app your AIs need</h2>
            <p className="sub2">
              One account and one link. Common Brain remembers; these get things done. Every one of them is on when you
              start your brain, and your AIs use them all through the same connection.
            </p>
            <div className="suite">
              {suite.map(([key, name, pitch]) => (
                <a key={key} href={apps[key].url} className="glass app">
                  <img
                    src={key === 'todo' ? BASE + '/icon.svg' : `${BASE}/icon-${key}.svg`}
                    alt=""
                    width={44}
                    height={44}
                  />
                  <span>
                    <b>{name}</b>
                    <span>{pitch}</span>
                  </span>
                </a>
              ))}
            </div>
          </section>
        )}

        <BrainExtra config={config} />

        <div className="trust">
          <h2>We never run AI on your brain.</h2>
          <p>Your AIs do the thinking. We keep the notebook, and you can read every page of it.</p>
          {start}
        </div>
        <div id="signin" className="signin">
          {signIn}
        </div>
        <footer>
          <span>
            Also on your account:{' '}
            {suite.map(([key, name], i) => (
              <span key={key}>
                {i > 0 && ' · '}
                <a href={apps[key].url}>{name}</a>
              </span>
            ))}
          </span>
          <PolicyLinks />
          {address && <span className="mono">{address.host + address.pathname.replace(/\/$/, '')}</span>}
        </footer>
      </div>
    </div>
  );
}

/** ChatGPT saves two memories, the brain shows them arrive, Claude uses them; then again. */
function Demo() {
  const gpt = useRef<HTMLDivElement>(null);
  const cl = useRef<HTMLDivElement>(null);
  const mem = useRef<HTMLDivElement>(null);
  const feed = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const [g, c, m, f] = [gpt.current!, cl.current!, mem.current!, feed.current!];
    const seed = m.innerHTML;
    const timers: number[] = [];
    const add = (box: HTMLElement, cls: string, html: string) => {
      const d = document.createElement('div');
      d.className = cls;
      d.innerHTML = html; // the fixed lines below, never user text
      box.appendChild(d);
      return d;
    };
    const bullet = (text: string) => {
      m.querySelectorAll('.bul.new').forEach((x) => x.classList.remove('new'));
      add(m, 'bul new', `<span>${text}</span><span>ChatGPT · now</span>`);
    };
    let typing: HTMLElement | null = null;
    const steps: [number, () => void][] = [
      [600, () => add(g, 'm u', "I'm training for a half marathon in March.")],
      [
        900,
        () => {
          typing = add(g, 'typing', '…');
        },
      ],
      [
        1100,
        () => {
          typing?.remove();
          add(g, 'm a', 'Nice. <em>Saved to your brain.</em>');
        },
      ],
      [
        500,
        () => {
          bullet('Training for a half marathon, race in March');
          f.textContent = '+ ChatGPT added 1 memory';
        },
      ],
      [1300, () => add(g, 'm u', 'My left knee hurts on downhills.')],
      [
        1000,
        () => {
          add(g, 'm a', "<em>Saved.</em> I'll keep that in mind.");
          bullet('Left knee hurts on downhill runs');
          f.textContent = '+ ChatGPT added 2 memories';
        },
      ],
      [1800, () => add(c, 'm u', 'Plan my runs this week?')],
      [
        600,
        () => {
          f.textContent = '→ Claude read the brain: 2 new since its last visit';
        },
      ],
      [
        900,
        () => {
          typing = add(c, 'typing', '…');
        },
      ],
      [
        1400,
        () => {
          typing?.remove();
          add(
            c,
            'm a',
            "Your brain says <em>half marathon in March</em> and <em>a sore knee on downhills</em>, so here's a flat-route week, short and simple.",
          );
        },
      ],
      [
        4200,
        () => {
          g.innerHTML = '';
          c.innerHTML = '';
          m.innerHTML = seed;
          f.textContent = 'Waiting for an AI…';
        },
      ],
    ];
    if (window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) {
      steps.slice(0, -1).forEach(([, run]) => run());
      return;
    }
    let i = 0;
    const next = () => {
      const [wait, run] = steps[i];
      timers.push(
        window.setTimeout(() => {
          run();
          i = (i + 1) % steps.length;
          next();
        }, wait),
      );
    };
    next();
    return () => {
      timers.forEach((t) => window.clearTimeout(t));
    };
  }, []);
  return (
    <>
      <div className="stage" aria-label="A demo: ChatGPT saves to the brain, and Claude uses it">
        <div className="win">
          <div className="bar">
            <span className="dot" style={{ background: '#10a37f' }} />
            ChatGPT
          </div>
          <div className="msgs" ref={gpt} />
        </div>
        <div className="win cb-glow">
          <div className="bar">
            <Mark className="h-[22px] w-[22px] text-[#e9ecff]" live small />
            Maya&rsquo;s brain
          </div>
          <div className="sect">Memory</div>
          <div ref={mem}>
            <div className="bul">
              <span>Nurse; works nights Tue–Thu</span>
              <span>ChatGPT · Oct 2</span>
            </div>
            <div className="bul">
              <span>🔒 Short answers, no bullet points</span>
              <span>Maya</span>
            </div>
          </div>
          <div className="feed mono" ref={feed}>
            Waiting for an AI…
          </div>
        </div>
        <div className="win">
          <div className="bar">
            <span className="dot" style={{ background: '#d97757' }} />
            Claude
          </div>
          <div className="msgs" ref={cl} />
        </div>
      </div>
      <p className="caption">
        This is what really happens: ChatGPT saves a memory, the brain keeps it, and Claude picks it up.
      </p>
    </>
  );
}

const NODES: [number, number, number, string][] = [
  [130, 70, 120, 'ChatGPT'],
  [110, 250, 110, 'Claude'],
  [300, 300, 100, 'Grok'],
  [520, 300, 110, 'Gemini'],
  [700, 250, 140, 'Claude Code'],
  [690, 70, 100, 'Codex'],
];

function Network() {
  return (
    <svg className="net" viewBox="0 0 820 330" role="img" aria-label="Six AIs connected to one brain">
      <defs>
        <radialGradient id="cb-net-glow">
          <stop offset="0" stopColor="#7c5cff" stopOpacity=".55" />
          <stop offset="1" stopColor="#7c5cff" stopOpacity="0" />
        </radialGradient>
      </defs>
      <circle cx="410" cy="165" r="120" fill="url(#cb-net-glow)" />
      <g stroke="#3b4580" strokeWidth="1.5" fill="none">
        {NODES.map(([x, y]) => (
          <path key={x} d={`M410 165 L${x} ${y}`} />
        ))}
      </g>
      <g stroke="#22d3ee" strokeWidth="2.2" fill="none" strokeLinecap="round">
        {NODES.map(([x, y], i) => (
          <path
            key={x}
            className={`flow${i % 2 ? ' r' : ''}`}
            d={i % 2 ? `M410 165 L${x} ${y}` : `M${x} ${y} L410 165`}
          />
        ))}
      </g>
      <circle className="pulse" cx="410" cy="165" r="56" fill="#7c5cff" opacity=".4" />
      <circle cx="410" cy="165" r="54" fill="#0d1230" />
      <foreignObject x="350" y="105" width="120" height="120">
        <Mark className="h-[120px] w-[120px] text-[#e9ecff]" live />
      </foreignObject>
      <g fontFamily="ui-monospace,Menlo,monospace" fontSize="15" fill="#e9ecff" textAnchor="middle">
        {NODES.map(([x, y, w, name]) => (
          <g key={name}>
            <rect x={x - w / 2} y={y - 20} width={w} height="40" rx="20" fill="#121a40" stroke="#3b4580" />
            <text x={x} y={y + 5}>
              {name}
            </text>
          </g>
        ))}
      </g>
    </svg>
  );
}
