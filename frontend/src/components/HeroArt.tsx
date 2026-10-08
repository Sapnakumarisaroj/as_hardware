/**
 * The home hero's picture: an original vector illustration (a pegboard of hand tools, a hinge and a
 * stack of boards) in the shop's colours. No photo or brand artwork is used; swap in a licensed photo
 * here when one is available.
 */
export function HeroArt({ className = '' }: { className?: string }) {
  return (
    <svg viewBox="0 0 520 440" role="img" aria-label="Hand tools, a cabinet hinge and a stack of plywood boards" className={className}>
      <defs>
        <linearGradient id="hero-board" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#ffb81f" />
          <stop offset="1" stopColor="#f5a300" />
        </linearGradient>
        <pattern id="hero-pegs" width="26" height="26" patternUnits="userSpaceOnUse">
          <circle cx="13" cy="13" r="3" fill="#121417" opacity="0.14" />
        </pattern>
        <linearGradient id="hero-steel" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="#eceef1" />
          <stop offset="1" stopColor="#b9bfc7" />
        </linearGradient>
        <filter id="hero-shadow" x="-20%" y="-20%" width="140%" height="140%">
          <feDropShadow dx="0" dy="8" stdDeviation="8" floodColor="#121417" floodOpacity="0.28" />
        </filter>
      </defs>

      {/* Pegboard */}
      <rect x="20" y="10" width="480" height="330" rx="28" fill="url(#hero-board)" />
      <rect x="20" y="10" width="480" height="330" rx="28" fill="url(#hero-pegs)" />

      {/* Hammer */}
      <g filter="url(#hero-shadow)" transform="rotate(-28 150 150)">
        <rect x="138" y="70" width="22" height="190" rx="10" fill="#1c1f24" />
        <rect x="138" y="190" width="22" height="70" rx="10" fill="#2a2e35" />
        <path d="M96 52 h96 a10 10 0 0 1 10 10 v20 a10 10 0 0 1 -10 10 h-96 l-22 -14 a8 8 0 0 1 0 -12 z" fill="url(#hero-steel)" />
        <path d="M192 56 q28 6 36 30 q-14 -10 -36 -8 z" fill="#8a929d" />
      </g>

      {/* Wrench */}
      <g filter="url(#hero-shadow)" transform="rotate(32 330 150)">
        <rect x="318" y="88" width="26" height="170" rx="13" fill="url(#hero-steel)" />
        <path d="M331 34 a38 38 0 1 1 -0.1 0 z M321 34 h20 v30 h-20 z" fill="url(#hero-steel)" fillRule="evenodd" />
        <circle cx="331" cy="268" r="26" fill="url(#hero-steel)" />
        <circle cx="331" cy="268" r="11" fill="#f5a300" />
      </g>

      {/* Screwdriver */}
      <g filter="url(#hero-shadow)">
        <rect x="420" y="46" width="34" height="96" rx="15" fill="#1c1f24" />
        <rect x="428" y="54" width="6" height="80" rx="3" fill="#4b525c" />
        <rect x="433" y="140" width="8" height="120" rx="3" fill="url(#hero-steel)" />
        <path d="M433 258 h8 l-2 16 h-4 z" fill="#8a929d" />
      </g>

      {/* Tape measure */}
      <g filter="url(#hero-shadow)">
        <rect x="56" y="232" width="98" height="92" rx="24" fill="#1c1f24" />
        <circle cx="105" cy="278" r="26" fill="#2a2e35" />
        <circle cx="105" cy="278" r="10" fill="#f5a300" />
        <rect x="150" y="296" width="120" height="16" rx="3" fill="#ffd25e" />
        <g stroke="#121417" strokeWidth="2" opacity="0.55">
          {[160, 172, 184, 196, 208, 220, 232, 244, 256].map((x, i) => (
            <line key={x} x1={x} y1="296" x2={x} y2={i % 2 ? 302 : 306} />
          ))}
        </g>
      </g>

      {/* Hinge */}
      <g filter="url(#hero-shadow)" transform="translate(372 196)">
        <rect x="0" y="0" width="52" height="96" rx="8" fill="url(#hero-steel)" />
        <rect x="56" y="0" width="52" height="96" rx="8" fill="url(#hero-steel)" />
        <rect x="48" y="-4" width="12" height="104" rx="6" fill="#8a929d" />
        {[18, 48, 78].map((y) => (
          <g key={y} fill="#4b525c">
            <circle cx="26" cy={y} r="6" />
            <circle cx="82" cy={y} r="6" />
          </g>
        ))}
      </g>

      {/* Plywood stack */}
      <g filter="url(#hero-shadow)">
        {[0, 1, 2, 3].map((i) => (
          <g key={i} transform={`translate(${170 - i * 6} ${372 - i * 18})`}>
            <rect width="250" height="20" rx="4" fill={i % 2 ? '#d9ad6b' : '#e8c48a'} />
            <g stroke="#a4783c" strokeWidth="1.5" opacity="0.7">
              <line x1="6" y1="7" x2="244" y2="7" />
              <line x1="6" y1="13" x2="244" y2="13" />
            </g>
          </g>
        ))}
      </g>
    </svg>
  )
}
