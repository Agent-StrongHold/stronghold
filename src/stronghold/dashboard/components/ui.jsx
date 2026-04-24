/* Shared UI kit primitives for Agent Turing */

const UI = {};

UI.Shell = function Shell({ children, style }) {
  return <div style={{ minHeight: '100%', background: 'var(--ink-1)', color: 'var(--fg)', fontFamily: 'var(--font-sans)', position: 'relative', overflow: 'hidden', ...style }}>{children}</div>;
};

UI.TopBar = function TopBar({ caseId = 'CASE-0041', status = 'ENCRYPTED', timestamp = '1961-08-14  02:47:11 UTC' }) {
  return (
    <div style={{
      height: 42, display: 'flex', alignItems: 'center', gap: 20, padding: '0 16px',
      borderBottom: '1px solid var(--line-1)', fontFamily: 'var(--font-mono)', fontSize: 11,
      letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--grey-2)',
      background: 'var(--ink-2)', position: 'relative', zIndex: 10
    }}>
      <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>◆ PROJECT·TURING</span>
      <span>/</span>
      <span>{caseId}</span>
      <span style={{ marginLeft: 'auto' }}>{timestamp}</span>
      <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>● {status}</span>
    </div>
  );
};

UI.BottomBar = function BottomBar({ left = 'WIRE · OPEN', right = 'AT-01 · AUTH' }) {
  return (
    <div style={{
      height: 28, display: 'flex', alignItems: 'center', padding: '0 16px', gap: 16,
      borderTop: '1px solid var(--line-1)', fontFamily: 'var(--font-mono)', fontSize: 10,
      letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--grey-1)',
      background: 'var(--ink-2)'
    }}>
      <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>{left}</span>
      <span style={{ marginLeft: 'auto' }}>{right}</span>
    </div>
  );
};

UI.Label = function Label({ children, color = 'var(--grey-2)', glow = false, style }) {
  return <div style={{
    fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.22em',
    textTransform: 'uppercase', color, textShadow: glow ? 'var(--phosphor-glow-soft)' : 'none', ...style
  }}>{children}</div>;
};

UI.PhLabel = function PhLabel(props) { return <UI.Label {...props} color="var(--phosphor)" glow={true} />; };

UI.Brackets = function Brackets({ children, color = 'var(--phosphor)', pad = 10, style }) {
  const line = { position: 'absolute', width: 14, height: 14, borderColor: color, borderStyle: 'solid', borderWidth: 1, filter: 'drop-shadow(0 0 4px rgba(94,232,140,0.4))' };
  return (
    <div style={{ position: 'relative', padding: pad, ...style }}>
      <span style={{ ...line, top: 0, left: 0, borderRightWidth: 0, borderBottomWidth: 0 }} />
      <span style={{ ...line, top: 0, right: 0, borderLeftWidth: 0, borderBottomWidth: 0 }} />
      <span style={{ ...line, bottom: 0, left: 0, borderRightWidth: 0, borderTopWidth: 0 }} />
      <span style={{ ...line, bottom: 0, right: 0, borderLeftWidth: 0, borderTopWidth: 0 }} />
      {children}
    </div>
  );
};

UI.Chip = function Chip({ children, tone = 'live', style }) {
  const tones = {
    live:       { color: 'var(--phosphor)', glow: 'var(--phosphor-glow-soft)' },
    classified: { color: 'var(--amber)', glow: 'var(--amber-glow)' },
    burn:       { color: 'var(--burn)', glow: 'var(--burn-glow)' },
    cold:       { color: 'var(--grey-2)', glow: 'none' },
  };
  const t = tones[tone] || tones.live;
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, padding: '3px 10px',
      borderRadius: 9999, border: `1px solid ${t.color}`, color: t.color, textShadow: t.glow,
      fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.18em', textTransform: 'uppercase', ...style
    }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: t.color, boxShadow: `0 0 6px ${t.color}` }} />
      {children}
    </span>
  );
};

UI.Button = function Button({ children, variant = 'outline', onClick, style, glyph }) {
  const base = {
    fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.22em',
    textTransform: 'uppercase', padding: '9px 16px', cursor: 'pointer',
    border: '1px solid var(--phosphor)', color: 'var(--phosphor)', background: 'transparent',
    textShadow: 'var(--phosphor-glow-soft)', display: 'inline-flex', alignItems: 'center', gap: 8,
    transition: 'all 120ms var(--ease-ui)'
  };
  const variants = {
    solid:   { background: 'var(--phosphor)', color: 'var(--ink-0)', textShadow: 'none', boxShadow: 'var(--phosphor-glow-med)' },
    outline: {},
    ghost:   { border: '1px solid var(--line-2)', color: 'var(--grey-3)', textShadow: 'none' },
    burn:    { border: '1px solid var(--burn)', color: 'var(--burn)', textShadow: 'var(--burn-glow)' },
  };
  return (
    <button onClick={onClick} style={{ ...base, ...(variants[variant] || {}), ...style }}>
      {glyph && <span>{glyph}</span>}
      {children}
    </button>
  );
};

UI.Card = function Card({ title, meta, children, style, brackets = false, headerColor = 'var(--phosphor)' }) {
  const body = (
    <div style={{ border: '1px solid var(--line-2)', background: 'var(--panel-recessed)', padding: '14px 16px', position: 'relative', ...style }}>
      {(title || meta) && (
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--line-1)', paddingBottom: 8, marginBottom: 10 }}>
          {title && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.22em', textTransform: 'uppercase', color: headerColor, textShadow: headerColor === 'var(--phosphor)' ? 'var(--phosphor-glow-soft)' : 'none' }}>{title}</span>}
          {meta && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-2)', letterSpacing: '0.12em' }}>{meta}</span>}
        </div>
      )}
      {children}
    </div>
  );
  return brackets ? <UI.Brackets>{body}</UI.Brackets> : body;
};

UI.Divider = function Divider({ label, dashed = true }) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, margin: '14px 0' }}>
      <span style={{ flex: 1, borderTop: dashed ? '1px dashed var(--line-2)' : '1px solid var(--line-1)' }} />
      {label && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-2)', letterSpacing: '0.22em', textTransform: 'uppercase' }}>{label}</span>}
      <span style={{ flex: 1, borderTop: dashed ? '1px dashed var(--line-2)' : '1px solid var(--line-1)' }} />
    </div>
  );
};

UI.Stat = function Stat({ label, value, tone = 'phosphor' }) {
  const color = tone === 'phosphor' ? 'var(--phosphor)' : tone === 'amber' ? 'var(--amber)' : 'var(--fg)';
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, padding: 10, border: '1px solid var(--line-1)' }}>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-2)', letterSpacing: '0.2em', textTransform: 'uppercase' }}>{label}</span>
      <span style={{ fontFamily: 'var(--font-display)', fontSize: 28, color, textShadow: tone === 'phosphor' ? 'var(--phosphor-glow-med)' : 'none', lineHeight: 1 }}>{value}</span>
    </div>
  );
};

UI.Cursor = function Cursor({ inline = true }) {
  return <span className="cursor" style={{ display: inline ? 'inline-block' : 'block' }} />;
};

// Typewriter that reveals text progressively
UI.Typewriter = function Typewriter({ text, speed = 28, start = 0, onDone, style }) {
  const [n, setN] = React.useState(0);
  React.useEffect(() => {
    const t0 = setTimeout(() => {
      let i = 0;
      const iv = setInterval(() => {
        i += 1;
        setN(i);
        if (i >= text.length) { clearInterval(iv); onDone && onDone(); }
      }, speed);
      return () => clearInterval(iv);
    }, start);
    return () => clearTimeout(t0);
  }, [text, speed, start]);
  return <span style={style}>{text.slice(0, n)}{n < text.length && <UI.Cursor />}</span>;
};

Object.assign(window, { UI });
