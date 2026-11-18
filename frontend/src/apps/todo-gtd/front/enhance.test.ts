// @vitest-environment jsdom
//
// The front page's motion (enhance.ts) against a bare copy of the markup it looks for: the
// scripted "your AI adds it" exchange, the recording with its captions and its keyboard
// control, and that undoing it stops everything.
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { enhance } from './enhance';

const PAGE = `
  <div data-ai-demo>
    <div data-msgs></div>
    <button data-replay>Replay</button>
    <ul data-rows></ul>
  </div>
  <ul data-captions>
    <li data-at="0"><button>Type it</button></li>
    <li data-at="7.1"><button>File it</button></li>
    <li data-at="17.2"><button>See what your AI added</button></li>
  </ul>
  <div class="screen"><video data-app-video></video></div>
  <div data-pop></div>`;

let root: HTMLDivElement;
let video: HTMLVideoElement;
let paused: boolean;
let undo: () => void;
/** What the page told the stand-in IntersectionObserver to watch, by element. */
let watching: Map<Element, (showing: boolean) => void>;

const rows = () => [...root.querySelectorAll('[data-rows] li')].map((li) => li.textContent);
const lit = () => [...root.querySelectorAll('[data-captions] li')].map((li) => li.classList.contains('on'));
const key = (el: Element, k: string) => el.dispatchEvent(new KeyboardEvent('keydown', { key: k, bubbles: true }));

function watchable() {
  vi.stubGlobal(
    'IntersectionObserver',
    class {
      private readonly cb: (es: { isIntersecting: boolean }[]) => void;
      constructor(cb: (es: { isIntersecting: boolean }[]) => void) {
        this.cb = cb;
      }
      observe(el: Element) {
        watching.set(el, (showing) => this.cb([{ isIntersecting: showing }]));
      }
      disconnect() {}
    },
  );
}

beforeEach(() => {
  vi.useFakeTimers();
  watching = new Map();
  root = document.createElement('div');
  root.innerHTML = PAGE;
  document.body.appendChild(root);
  video = root.querySelector('video')!;
  paused = true;
  Object.defineProperty(video, 'paused', { get: () => paused });
  video.play = vi.fn(() => {
    paused = false;
    return Promise.resolve();
  });
  video.pause = vi.fn(() => {
    paused = true;
  });
});

afterEach(() => {
  undo?.();
  root.remove();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe('the scripted exchange', () => {
  it('adds what the AI was asked for under its name, then the person checks one off', async () => {
    undo = enhance(root);
    expect(rows()).toEqual(['Email Dana the Q4 budget draftToday @computer ', 'Buy milk and coffee filters@errands ']);
    await vi.advanceTimersByTimeAsync(3000);
    expect(rows().slice(0, 2)).toEqual([
      'Call the dentist to book a cleaningTomorrow @calls ✦ Claude ',
      'Book flights to Denver for the 21st★ @computer ✦ Claude ',
    ]);
    expect(root.querySelector('[data-msgs]')!.textContent).toContain('Done. I added both to your list');
    await vi.advanceTimersByTimeAsync(6000);
    const dana = root.querySelector('[data-rows] li.done')!;
    expect(dana.textContent).toContain('Email Dana the Q4 budget draft');
    expect(root.querySelector('[data-msgs]')!.lastElementChild!.textContent).toBe(
      'Yes. You checked it off a moment ago.',
    );
  });

  it('starts over on Replay, and the run it replaced writes nothing more', async () => {
    undo = enhance(root);
    await vi.advanceTimersByTimeAsync(3000);
    root.querySelector<HTMLButtonElement>('[data-replay]')!.click();
    expect(rows()).toHaveLength(2);
    await vi.advanceTimersByTimeAsync(3000);
    expect(rows()).toHaveLength(4);
  });

  it('waits until it is on screen, and plays once', async () => {
    watchable();
    undo = enhance(root);
    expect(rows()).toEqual([]);
    const demo = root.querySelector('[data-ai-demo]')!;
    watching.get(demo)!(true);
    await vi.advanceTimersByTimeAsync(3000);
    watching.get(demo)!(true);
    expect(rows()).toHaveLength(4);
  });

  it('stops when undone', async () => {
    undo = enhance(root);
    undo();
    await vi.advanceTimersByTimeAsync(10000);
    expect(rows()).toHaveLength(2);
    expect(root.querySelector('[data-msgs]')!.textContent).toBe('');
  });
});

describe('the recording', () => {
  it('plays while on screen, pauses off it, and lights the caption for the part showing', () => {
    watchable();
    undo = enhance(root);
    expect(video.controls).toBe(false);
    expect(lit()).toEqual([true, false, false]);
    watching.get(video)!(true);
    expect(video.play).toHaveBeenCalledTimes(1);
    video.currentTime = 9;
    video.dispatchEvent(new Event('timeupdate'));
    expect(lit()).toEqual([false, true, false]);
    watching.get(video)!(false);
    expect(paused).toBe(true);
  });

  it('holds and resumes from the keyboard, and a held recording stays held when it scrolls back', () => {
    watchable();
    undo = enhance(root);
    const screen = root.querySelector<HTMLElement>('.screen')!;
    expect(screen.tabIndex).toBe(0);
    expect(screen.getAttribute('role')).toBe('button');
    watching.get(video)!(true);
    key(screen, 'Enter');
    expect(paused).toBe(true);
    watching.get(video)!(true);
    expect(paused).toBe(true);
    key(screen, 'a');
    expect(paused).toBe(true);
    key(screen, ' ');
    expect(paused).toBe(false);
    screen.click();
    expect(paused).toBe(true);
  });

  it('jumps to a caption’s part and plays', () => {
    watchable();
    undo = enhance(root);
    root.querySelectorAll<HTMLButtonElement>('[data-captions] button')[2].click();
    expect(video.currentTime).toBe(17.2);
    expect(paused).toBe(false);
  });

  it('with reduced motion, waits with the browser’s own controls, and captions still jump', () => {
    watchable();
    vi.stubGlobal('matchMedia', (q: string) => ({ matches: q.includes('reduced-motion') }));
    undo = enhance(root);
    expect(video.controls).toBe(true);
    expect(video.loop).toBe(false);
    expect(watching.has(video)).toBe(false);
    expect(root.querySelector('.screen')!.hasAttribute('role')).toBe(false);
    root.querySelectorAll<HTMLButtonElement>('[data-captions] button')[1].click();
    expect(video.currentTime).toBe(7.1);
    expect(root.querySelector<HTMLElement>('[data-pop]')!.style.getPropertyValue('--p')).toBe('');
  });

  it('does nothing after it is undone', () => {
    watchable();
    undo = enhance(root);
    undo();
    key(root.querySelector('.screen')!, 'Enter');
    root.querySelectorAll<HTMLButtonElement>('[data-captions] button')[1].click();
    expect(video.play).not.toHaveBeenCalled();
    expect(video.currentTime).toBe(0);
  });
});

it('tilts a screenshot up as it scrolls in', () => {
  const pop = root.querySelector<HTMLElement>('[data-pop]')!;
  pop.getBoundingClientRect = () => ({ top: window.innerHeight / 2, bottom: window.innerHeight }) as DOMRect;
  undo = enhance(root);
  const p = Number(pop.style.getPropertyValue('--p'));
  expect(p).toBeGreaterThan(0.5);
  expect(p).toBeLessThan(1);
});
