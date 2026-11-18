// Common Brain — forget something for good. The one place in the suite where real
// content is deleted, and only the signed-in person can do it: an AI that is asked to
// forget something hands over a link to this page (brain_forget_link), which asks first.
import { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { apiErrorMessage } from '../../core/api/client';
import { forget, getMemory, getPage } from './api';
import { BrainShell } from './BrainShell';

export function ForgetPage() {
  const { kind: rawKind, id: rawId } = useParams();
  const kind = rawKind === 'page' ? 'page' : 'memory';
  const id = Number(rawId);
  const [what, setWhat] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();
  useEffect(() => {
    (kind === 'memory' ? getMemory(id).then((m) => m.text) : getPage(id).then((p) => `${p.title} (${p.path})`)).then(
      setWhat,
      (e) => setError(apiErrorMessage(e, 'It is not in your brain: it may be forgotten already.')),
    );
  }, [kind, id]);
  const go = async () => {
    setBusy(true);
    try {
      await forget(kind, id);
      navigate('/', { replace: true });
    } catch (e) {
      setError(apiErrorMessage(e, 'Could not forget it.'));
      setBusy(false);
    }
  };
  return (
    <BrainShell title="Forget">
      <div className="cb-glow mx-auto mt-6 max-w-lg rounded-2xl p-6">
        <h1 className="font-heading text-2xl font-bold text-white">Forget this for good?</h1>
        {what !== null && (
          <blockquote className="mt-4 rounded-xl border border-white/10 bg-white/5 p-3 text-charcoal">
            {what}
          </blockquote>
        )}
        <p className="mt-4 text-sm text-muted">
          This removes the {kind} and every earlier version of it. No AI can bring it back, and your AIs will not see it
          again. Backups age out on their own within a few weeks. To keep it but stop using it, archive it instead.
        </p>
        {error && (
          <p role="alert" className="mt-3 text-sm text-[#ff9db0]">
            {error}
          </p>
        )}
        <div className="mt-5 flex gap-2">
          <button
            type="button"
            disabled={busy || what === null}
            onClick={() => void go()}
            className="cb-btn bg-none"
            style={{ background: '#d4385a', boxShadow: 'none' }}
          >
            {busy ? 'Forgetting…' : 'Forget it for good'}
          </button>
          <Link to="/" className="cb-btn-ghost">
            Keep it
          </Link>
        </div>
      </div>
    </BrainShell>
  );
}
