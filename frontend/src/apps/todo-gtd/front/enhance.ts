// The front page's motion: screenshots that tilt up as they scroll in, the logo leaning toward
// the pointer, the scripted "your AI adds it" exchange, and the recording with its captions.
// Plain DOM on purpose: none of it is state the page renders from.

const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const matches = (q: string) => typeof matchMedia === 'function' && matchMedia(q).matches;

/** Start it all on the page's root; the answer undoes it. */
export function enhance(root: HTMLElement): () => void {
  const off = new AbortController();
  const watchers: IntersectionObserver[] = [];
  const still = matches('(prefers-reduced-motion: reduce)');
  const seen = (el: Element, threshold: number, fn: (showing: boolean) => void) => {
    const io = new IntersectionObserver((es) => es.forEach((e) => fn(e.isIntersecting)), { threshold });
    io.observe(el);
    watchers.push(io);
  };
  const canWatch = 'IntersectionObserver' in window;

  // Each [data-pop] gets --p from 0 (entering at the bottom) to 1 (its top at 20% of the
  // window, or data-pop-end); the stylesheet turns --p into the tilt. Read live, because the
  // Notes and Projects screenshots arrive after the server has said which apps it serves.
  let frame = 0;
  const tick = () => {
    frame = 0;
    const vh = window.innerHeight;
    for (const el of root.querySelectorAll<HTMLElement>('[data-pop]')) {
      const r = el.getBoundingClientRect();
      if (r.top > vh * 1.2 || r.bottom < -vh * 0.2) continue;
      const end = parseFloat(el.dataset.popEnd || '0.2');
      const p = Math.min(1, Math.max(0, (vh - r.top) / (vh * (1 - end))));
      el.style.setProperty('--p', (1 - Math.pow(1 - p, 3)).toFixed(4));
    }
  };
  if (!still) {
    const ask = () => {
      frame ||= requestAnimationFrame(tick);
    };
    window.addEventListener('scroll', ask, { passive: true, signal: off.signal });
    window.addEventListener('resize', ask, { signal: off.signal });
    tick();
  }

  const mark = root.querySelector<HTMLElement>('[data-tilt]');
  if (mark && !still && !matches('(pointer: coarse)'))
    window.addEventListener(
      'pointermove',
      (e) => {
        const r = mark.getBoundingClientRect();
        const dx = (e.clientX - (r.left + r.width / 2)) / window.innerWidth;
        const dy = (e.clientY - (r.top + r.height / 2)) / window.innerHeight;
        mark.style.transform = `rotateY(${(dx * 28).toFixed(1)}deg) rotateX(${(-dy * 20).toFixed(1)}deg)`;
      },
      { passive: true, signal: off.signal },
    );

  // The scripted exchange: a chat on the left, the list it writes to on the right.
  const demo = root.querySelector<HTMLElement>('[data-ai-demo]');
  const msgs = demo?.querySelector<HTMLElement>('[data-msgs]');
  const rows = demo?.querySelector<HTMLElement>('[data-rows]');
  let run = 0;
  if (demo && msgs && rows) {
    const row = (title: string, chips: string[], byAi = false) => {
      const li = document.createElement('li');
      const box = document.createElement('span');
      box.className = 'aid-box';
      const main = document.createElement('div');
      const t = document.createElement('div');
      t.className = 'aid-t';
      t.textContent = title;
      main.append(t);
      for (const c of byAi ? [...chips, '✦ Claude'] : chips) {
        const s = document.createElement('span');
        s.className = c.startsWith('✦') ? 'aid-chip' : 'aid-chip d';
        s.textContent = c;
        main.append(s, ' ');
      }
      if (byAi) li.classList.add('new');
      li.append(box, main);
      return li;
    };
    const say = (text: string, me = false) => {
      const m = document.createElement('div');
      m.className = me ? 'aid-m me' : 'aid-m';
      m.textContent = text;
      msgs.append(m);
      while (msgs.children.length > 4) msgs.firstChild?.remove();
      return m;
    };
    const play = async () => {
      const mine = ++run;
      const live = () => mine === run;
      const step = async (ms: number) => (await wait(ms), live());
      const answer = async (text: string) => {
        const m = say('•••');
        m.classList.add('dots');
        if (!(await step(900))) return false;
        m.classList.remove('dots');
        m.textContent = text;
        return true;
      };
      msgs.replaceChildren();
      const dana = row('Email Dana the Q4 budget draft', ['Today', '@computer']);
      rows.replaceChildren(dana, row('Buy milk and coffee filters', ['@errands']));
      if (!(await step(700))) return;
      say('Remind me to call the dentist tomorrow. And I need to book flights to Denver for the 21st.', true);
      if (!(await step(900)) || !(await answer('Done. I added both to your list and starred the flights.'))) return;
      rows.prepend(row('Book flights to Denver for the 21st', ['★', '@computer'], true));
      if (!(await step(450))) return;
      rows.prepend(row('Call the dentist to book a cleaning', ['Tomorrow', '@calls'], true));
      if (!(await step(2600))) return;
      dana.classList.add('done');
      dana.firstElementChild!.textContent = '✓';
      if (!(await step(1500))) return;
      say('Did I send Dana the budget yet?', true);
      if (await step(900)) await answer('Yes. You checked it off a moment ago.');
    };
    demo.querySelector('[data-replay]')?.addEventListener('click', () => void play(), { signal: off.signal });
    if (canWatch) {
      let played = false;
      seen(demo, 0.35, (showing) => {
        if (showing && !played) {
          played = true;
          void play();
        }
      });
    } else void play();
  }

  // The recording plays while it is on screen, holds on a tap or a key, and lights the caption
  // for the part showing; a caption jumps to its part. With reduced motion (or nothing to say
  // when it is on screen) it waits, with the browser's own controls.
  const video = root.querySelector<HTMLVideoElement>('[data-app-video]');
  const caps = root.querySelector<HTMLElement>('[data-captions]');
  if (video && caps) {
    const lines = [...caps.children] as HTMLElement[];
    const at = lines.map((l) => Number(l.dataset.at));
    const go = () => void video.play().catch(() => {});
    let held = false;
    lines.forEach((l, i) =>
      l.querySelector('button')?.addEventListener(
        'click',
        () => {
          video.currentTime = at[i];
          held = false;
          go();
        },
        { signal: off.signal },
      ),
    );
    const sync = () => {
      const now = at.reduce((k, t, i) => (video.currentTime >= t ? i : k), 0);
      lines.forEach((l, i) => l.classList.toggle('on', i === now));
    };
    caps.classList.add('live');
    video.addEventListener('timeupdate', sync, { signal: off.signal });
    sync();
    const screen = video.parentElement;
    if (still || !canWatch || !screen) {
      video.controls = true;
      video.loop = false;
    } else {
      const toggle = () => {
        held = !video.paused;
        if (held) video.pause();
        else go();
      };
      screen.tabIndex = 0;
      screen.setAttribute('role', 'button');
      screen.setAttribute('aria-label', 'Pause or play the recording');
      screen.addEventListener('click', toggle, { signal: off.signal });
      screen.addEventListener(
        'keydown',
        (e) => {
          if (e.key !== 'Enter' && e.key !== ' ') return;
          e.preventDefault();
          toggle();
        },
        { signal: off.signal },
      );
      seen(video, 0.3, (showing) => {
        if (!showing) video.pause();
        else if (!held) go();
      });
    }
  }

  return () => {
    run++;
    off.abort();
    watchers.forEach((io) => io.disconnect());
    if (frame) cancelAnimationFrame(frame);
  };
}
