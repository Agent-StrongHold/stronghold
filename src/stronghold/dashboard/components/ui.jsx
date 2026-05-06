/* Shared UI kit — Phosphor/Noir design system */
/* Spec 1187: Frontend port                    */

const UI = {};

/* ── TopBar ── */
UI.TopBar = function TopBar({ surface = 'CONSOLE', sub = '', status = 'ENCRYPTED' }) {
  const [ts, setTs] = React.useState(utcNow());
  React.useEffect(() => {
    const iv = setInterval(() => setTs(utcNow()), 1000);
    return () => clearInterval(iv);
  }, []);
  return (
    <div style={{
      height: 42, display: 'flex', alignItems: 'center', gap: 20, padding: '0 20px',
      borderBottom: '1px solid var(--line-1)', fontFamily: 'var(--font-mono)', fontSize: 11,
      letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--grey-2)',
      background: 'var(--ink-2)', flexShrink: 0, zIndex: 10,
    }}>
      <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 16, lineHeight: 1 }}>◆</span>
        <span style={{ fontFamily: 'var(--font-display)', fontSize: 18, letterSpacing: '0.04em' }}>AT-01</span>
      </span>
      <span style={{ color: 'var(--line-3)' }}>/</span>
      <span style={{ color: 'var(--grey-3)' }}>{surface}</span>
      {sub && <>
        <span style={{ color: 'var(--line-3)' }}>/</span>
        <span style={{ color: 'var(--grey-2)' }}>{sub}</span>
      </>}
      <span style={{ marginLeft: 'auto', color: 'var(--grey-1)' }}>{ts}</span>
      <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>● {status}</span>
    </div>
  );
};

/* ── BottomBar ── */
UI.BottomBar = function BottomBar({ left = '', right = '' }) {
  return (
    <div style={{
      height: 26, display: 'flex', alignItems: 'center', padding: '0 20px', gap: 16,
      borderTop: '1px solid var(--line-1)', fontFamily: 'var(--font-mono)', fontSize: 10,
      letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--grey-1)',
      background: 'var(--ink-2)', flexShrink: 0,
    }}>
      <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>{left}</span>
      <span style={{ marginLeft: 'auto' }}>{right}</span>
    </div>
  );
};

/* ── ClassificationBanner ── */
UI.ClassBanner = function ClassBanner({ text = 'CLASSIFIED · HANDLER EYES ONLY' }) {
  return (
    <div style={{
      height: 24, display: 'flex', alignItems: 'center', justifyContent: 'center',
      fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.32em', textTransform: 'uppercase',
      color: 'var(--amber)', textShadow: 'var(--amber-glow)', background: 'var(--ink-3)',
      borderBottom: '1px solid var(--amber-dim)', flexShrink: 0,
    }}>[ {text} ]</div>
  );
};

/* ── SectionLabel ── */
UI.SectionLabel = function SectionLabel({ children, style }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 12, margin: '18px 0 12px', ...style }}>
      <span style={{ flex: 1, borderTop: '1px dashed var(--line-2)' }} />
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--grey-2)', letterSpacing: '0.22em', textTransform: 'uppercase' }}>{children}</span>
      <span style={{ flex: 1, borderTop: '1px dashed var(--line-2)' }} />
    </div>
  );
};

/* ── Label / PhLabel ── */
UI.Label = function Label({ children, color = 'var(--grey-2)', glow, style }) {
  return (
    <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.22em', textTransform: 'uppercase', color, textShadow: glow ? 'var(--phosphor-glow-soft)' : 'none', ...style }}>
      {children}
    </div>
  );
};
UI.PhLabel = function PhLabel(props) {
  return <UI.Label {...props} color="var(--phosphor)" glow />;
};
UI.AmberLabel = function AmberLabel(props) {
  return <UI.Label {...props} color="var(--amber)" style={{ textShadow: 'var(--amber-glow)', ...(props.style||{}) }} />;
};

/* ── Chip ── */
UI.Chip = function Chip({ children, tone = 'live', style }) {
  const tones = {
    live:       { color: 'var(--phosphor)', glow: 'var(--phosphor-glow-soft)' },
    classified: { color: 'var(--amber)',    glow: 'var(--amber-glow)' },
    burn:       { color: 'var(--burn)',     glow: 'var(--burn-glow)' },
    cold:       { color: 'var(--grey-2)',   glow: 'none' },
    skull:      { color: 'var(--burn)',     glow: 'var(--burn-glow)' },
    t3:         { color: 'var(--amber)',    glow: 'var(--amber-glow)' },
    t2:         { color: 'var(--phosphor-mid)', glow: 'var(--phosphor-glow-soft)' },
    t1:         { color: 'var(--phosphor)', glow: 'var(--phosphor-glow-soft)' },
    t0:         { color: 'var(--phosphor-hi)', glow: 'var(--phosphor-glow-hot)' },
  };
  const t = tones[tone] || tones.live;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5, padding: '3px 9px',
      borderRadius: 9999, border: `1px solid ${t.color}`, color: t.color, textShadow: t.glow,
      fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.18em', textTransform: 'uppercase',
      ...style,
    }}>
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: t.color, boxShadow: `0 0 5px ${t.color}` }} />
      {children}
    </span>
  );
};

/* ── Button ── */
UI.Button = function Button({ children, variant = 'outline', onClick, style, glyph, disabled }) {
  const base = {
    fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.22em', textTransform: 'uppercase',
    padding: '8px 14px', cursor: disabled ? 'not-allowed' : 'pointer',
    border: '1px solid var(--phosphor)', color: 'var(--phosphor)', background: 'transparent',
    textShadow: 'var(--phosphor-glow-soft)', display: 'inline-flex', alignItems: 'center', gap: 7,
    transition: 'all 120ms var(--ease-ui)', opacity: disabled ? 0.4 : 1,
  };
  const variants = {
    solid:   { background: 'var(--phosphor)', color: 'var(--ink-0)', textShadow: 'none', boxShadow: 'var(--phosphor-glow-med)' },
    outline: {},
    ghost:   { border: '1px solid var(--line-2)', color: 'var(--grey-3)', textShadow: 'none' },
    burn:    { border: '1px solid var(--burn)', color: 'var(--burn)', textShadow: 'var(--burn-glow)' },
    amber:   { border: '1px solid var(--amber)', color: 'var(--amber)', textShadow: 'var(--amber-glow)' },
  };
  return (
    <button onClick={!disabled ? onClick : undefined} style={{ ...base, ...(variants[variant]||{}), ...style }}>
      {glyph && <span>{glyph}</span>}
      {children}
    </button>
  );
};

/* ── Card ── */
UI.Card = function Card({ title, meta, children, style, tone = 'default' }) {
  const borderColor = tone === 'amber' ? 'var(--amber-dim)' : tone === 'burn' ? 'var(--burn-dim)' : 'var(--line-2)';
  return (
    <div style={{ border: `1px solid ${borderColor}`, background: 'var(--panel-recessed)', padding: '14px 16px', ...style }}>
      {(title || meta) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--line-1)', paddingBottom: 8, marginBottom: 10 }}>
          {title && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.22em', textTransform: 'uppercase', color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>{title}</span>}
          {meta  && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-2)', letterSpacing: '0.12em' }}>{meta}</span>}
        </div>
      )}
      {children}
    </div>
  );
};

/* ── Divider ── */
UI.Divider = function Divider({ label, dashed = true }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '12px 0' }}>
      <span style={{ flex: 1, borderTop: dashed ? '1px dashed var(--line-2)' : '1px solid var(--line-1)' }} />
      {label && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-2)', letterSpacing: '0.22em', textTransform: 'uppercase' }}>{label}</span>}
      <span style={{ flex: 1, borderTop: dashed ? '1px dashed var(--line-2)' : '1px solid var(--line-1)' }} />
    </div>
  );
};

/* ── Stat ── */
UI.Stat = function Stat({ label, value, tone = 'phosphor' }) {
  const color = { phosphor: 'var(--phosphor)', amber: 'var(--amber)', burn: 'var(--burn)', bone: 'var(--bone-0)' }[tone] || 'var(--fg)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 10, border: '1px solid var(--line-1)' }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-2)', letterSpacing: '0.2em', textTransform: 'uppercase' }}>{label}</span>
      <span style={{ fontFamily: 'var(--font-display)', fontSize: 28, color, textShadow: tone === 'phosphor' ? 'var(--phosphor-glow-med)' : 'none', lineHeight: 1 }}>{value}</span>
    </div>
  );
};

/* ── Cursor + Typewriter ── */
UI.Cursor = function Cursor() {
  return <span className="cursor" />;
};

UI.Typewriter = function Typewriter({ text, speed = 24, onDone, style }) {
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    setN(0);
    let i = 0;
    const iv = setInterval(() => {
      i += 1; setN(i);
      if (i >= text.length) { clearInterval(iv); onDone && onDone(); }
    }, speed);
    return () => clearInterval(iv);
  }, [text]);
  return <span style={style}>{text.slice(0, n)}{n < text.length && <UI.Cursor />}</span>;
};

/* ── Inline helper ── */
function utcNow() {
  const d = new Date(), p = n => String(n).padStart(2, '0');
  return `${d.getUTCFullYear()}-${p(d.getUTCMonth()+1)}-${p(d.getUTCDate())}  ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())} UTC`;
}

Object.assign(window, { UI });
