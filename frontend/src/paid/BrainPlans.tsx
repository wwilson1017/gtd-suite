import { useEffect } from 'react';
import type { AppConfig } from '../apps/todo-gtd/api';
import { answered } from '../apps/todo-gtd/useConfig';
import './brain.css';

/** The prices are the hosted service's: a self-hosted (one-list) server shows none,
 *  nor does a free suite (nothing is sold), nor a server whose config failed to load. */
function offered(config: AppConfig | null) {
  return answered(config) && config.open_signup && !config.free;
}

export function BrainPlans({ config }: { config: AppConfig | null }) {
  return offered(config) ? <Prices /> : null;
}

function Prices() {
  // The section mounts once the server has answered, after the browser looked for the
  // address's #pricing, so a link straight to the prices is taken there now.
  useEffect(() => {
    if (window.location.hash === '#pricing') document.getElementById('pricing')?.scrollIntoView();
  }, []);
  return (
    <section id="pricing">
      <h2>Pricing</h2>
      <p className="sub2">One plan covers every app. Free covers most people; Pro and Max are for big brains.</p>
      <div className="grid3">
        <div className="glass price">
          <div className="lbl mono">FREE</div>
          <div className="amt">$0</div>
          <div className="per">forever</div>
          <ul>
            <li>Every AI you use</li>
            <li>2,000 memories · 2,000 pages</li>
            <li>
              500 MB of files <i>soon</i>
            </li>
            <li>500 pages and 500 short links on Simple Sites</li>
            <li>Full history, export and forget</li>
            <li>The free curator skill</li>
          </ul>
        </div>
        <div className="glass price pro">
          <div className="lbl mono">PRO</div>
          <div className="amt">
            $5<small>/mo</small>
          </div>
          <div className="per">or $36 a year</div>
          <ul>
            <li>Everything in Free</li>
            <li>10,000 memories · 25,000 pages</li>
            <li>
              10 GB of files <i>soon</i>
            </li>
            <li>2,500 pages and 2,500 short links on Simple Sites</li>
            <li>Higher limits on Todo, Notes and Projects</li>
          </ul>
        </div>
        <div className="glass price">
          <div className="lbl mono">
            MAX <i>coming soon</i>
          </div>
          <div className="amt">
            $10<small>/mo</small>
          </div>
          <div className="per">or $96 a year</div>
          <ul>
            <li>Everything in Pro</li>
            <li>Unlimited memories and pages</li>
            <li>100 GB of files</li>
            <li>Unlimited Simple Sites pages and links</li>
            <li>No limits on Todo, Notes and Projects</li>
          </ul>
        </div>
      </div>
      <p className="fine center">
        Files and Max arrive with the next version. Simple Sites includes 5 GB of page traffic a month on Free, 25 GB on
        Pro and 100 GB on Max.
      </p>
    </section>
  );
}

export function BrainPlansLink({ config }: { config: AppConfig | null }) {
  if (!offered(config)) return null;
  return <a href="#pricing">Pricing</a>;
}
