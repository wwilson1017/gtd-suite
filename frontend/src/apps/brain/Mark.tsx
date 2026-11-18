// Common Brain's mark, "Linked": a glowing center dot inside a whole ring, an outer
// ring of two arcs, and four dots riding them (the AIs). `live` turns the rings and
// sends light rippling out from the center, for the big sizes and while AIs work.
// `small` (40 px and under) draws the favicon's version instead (public/icon-brain.svg):
// one bold ring of two arcs with a dot in each gap and no glow, so it stays sharp. The
// light dots are currentColor, so they turn navy on a light background.
import { useId, type CSSProperties } from 'react';

const OUTER = ['M40.52 55.5A25 25 0 0 1 15.9 12.87', 'M23.48 8.5A25 25 0 0 1 48.1 51.13'];
const SMALL = ['M54.62 25.62A23.5 23.5 0 0 1 25.62 54.62', 'M9.38 38.38A23.5 23.5 0 0 1 38.38 9.38'];
const CYAN = '#7FE7FF';

export function Mark({
  className = '',
  live = false,
  small = false,
  title,
}: {
  className?: string;
  live?: boolean;
  small?: boolean;
  title?: string;
}) {
  const id = useId().replace(/:/g, '');
  const line = `url(#cbl${id})`;
  const core = small ? 10 : 8.5;
  const dot = (cx: number, cy: number, r: number, fill: string) => <circle cx={cx} cy={cy} r={r} fill={fill} />;
  return (
    <svg
      viewBox="0 0 64 64"
      className={`cb-mark${live ? ' cb-live' : ''} ${className}`}
      role={title ? 'img' : undefined}
      aria-label={title}
      aria-hidden={title ? undefined : true}
    >
      <defs>
        <linearGradient id={`cbl${id}`} gradientUnits="userSpaceOnUse" x1="6" y1="6" x2="58" y2="58">
          <stop offset="0" stopColor="#9B82FF" />
          <stop offset="1" stopColor="#22D3EE" />
        </linearGradient>
        <linearGradient id={`cbc${id}`} x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#A28BFF" />
          <stop offset="1" stopColor="#22D3EE" />
        </linearGradient>
        <radialGradient id={`cbg${id}`}>
          <stop offset="0" stopColor="#7C5CFF" stopOpacity=".7" />
          <stop offset=".45" stopColor="#7C5CFF" stopOpacity=".26" />
          <stop offset="1" stopColor="#7C5CFF" stopOpacity="0" />
        </radialGradient>
      </defs>
      {small ? (
        <g className="cb-ring" fill="none" strokeLinecap="round" style={{ '--spd': '14s' } as CSSProperties}>
          {SMALL.map((d) => (
            <path key={d} d={d} stroke={line} strokeWidth={6} />
          ))}
          {dot(48.62, 15.38, 5.6, CYAN)}
          {dot(15.38, 48.62, 5.6, 'currentColor')}
        </g>
      ) : (
        <>
          <g fill="none" strokeLinecap="round">
            <g className="cb-ring cb-ccw" style={{ '--spd': '18s' } as CSSProperties}>
              {OUTER.map((d) => (
                <path key={d} d={d} stroke={line} strokeWidth={2.6} />
              ))}
              {dot(44.5, 53.65, 2.7, CYAN)}
              {dot(19.5, 10.35, 2.7, 'currentColor')}
            </g>
            <circle cx="32" cy="32" r="14.5" stroke={line} strokeWidth={3.3} />
            <g className="cb-ring" style={{ '--spd': '12s' } as CSSProperties}>
              {dot(43.11, 22.68, 3.5, CYAN)}
              {dot(20.89, 41.32, 3.5, 'currentColor')}
            </g>
          </g>
          <circle cx="32" cy="32" r="22" fill={`url(#cbg${id})`} />
        </>
      )}
      {live &&
        [0, -1.6].map((begin) => (
          <circle
            key={begin}
            className="cb-rip"
            cx="32"
            cy="32"
            r={core}
            opacity="0"
            fill="none"
            stroke={CYAN}
            strokeWidth=".7"
          >
            <animate attributeName="r" values={`${core};30`} dur="3.2s" begin={`${begin}s`} repeatCount="indefinite" />
            <animate attributeName="opacity" values=".75;0" dur="3.2s" begin={`${begin}s`} repeatCount="indefinite" />
          </circle>
        ))}
      <circle cx="32" cy="32" r={core} fill={`url(#cbc${id})`} />
      <circle cx={32 - core * 0.3} cy={32 - core * 0.3} r={core * 0.32} fill="#fff" opacity=".85" />
    </svg>
  );
}
