import { useEffect, useId, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { brainName, selectBrain, useBrainSelection } from '../todo-gtd/brainSelection';

export function BrainSwitcher() {
  const { brains, id } = useBrainSelection();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useId();
  const navigate = useNavigate();
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        setOpen(false);
        button.current?.focus();
      }
    };
    const outside = (e: Event) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener('keydown', key);
    document.addEventListener('pointerdown', outside);
    document.addEventListener('focusin', outside);
    return () => {
      document.removeEventListener('keydown', key);
      document.removeEventListener('pointerdown', outside);
      document.removeEventListener('focusin', outside);
    };
  }, [open]);
  return (
    <div ref={wrap} className="relative w-full min-w-0 max-w-full sm:w-auto">
      <button
        ref={button}
        type="button"
        aria-label="Switch brain"
        aria-expanded={open}
        aria-controls={panel}
        onClick={() => setOpen(!open)}
        className="cb-btn-ghost max-w-full truncate sm:max-w-[14rem]"
      >
        {brains.find((b) => b.id === id) ? brainName(brains.find((b) => b.id === id)!) : 'Brain'} ▾
      </button>
      {open && (
        <div
          id={panel}
          className="absolute left-0 top-full z-50 mt-1 w-64 max-w-[calc(100vw-2rem)] rounded-xl border border-line bg-cream p-2 text-charcoal shadow-xl"
        >
          {brains
            .filter((b) => b.status === 'active')
            .map((b) => (
              <button
                type="button"
                key={b.id}
                aria-current={id === b.id ? 'true' : undefined}
                className="block w-full break-words rounded-lg px-3 py-2 text-left hover:bg-sand"
                onClick={() => {
                  navigate('/');
                  selectBrain(b.id);
                }}
              >
                {brainName(b)}
                {id === b.id ? ' ✓' : ''}
              </button>
            ))}
          <Link to="/brains/new" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 hover:bg-sand">
            New brain
          </Link>
          <Link to="/brains" onClick={() => setOpen(false)} className="block rounded-lg px-3 py-2 hover:bg-sand">
            Brain settings
          </Link>
        </div>
      )}
    </div>
  );
}
