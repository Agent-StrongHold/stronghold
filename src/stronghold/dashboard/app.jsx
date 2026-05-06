/* AT-01 Field Console — App shell + left-rail nav + router */
/* Spec 1187: Frontend port                                  */

const SURFACES = [
  { id: 'chat',       label: 'Chat',       glyph: '◈', sub: 'WIRE · LIVE',      status: 'ENCRYPTED' },
  { id: 'notebook',   label: 'Notebook',   glyph: '◇', sub: 'VAULT · AT-01',    status: 'SYNCED' },
  { id: 'blog',       label: 'Blog',       glyph: '◉', sub: 'DISPATCH · PUBLIC', status: 'WARDEN · ACTIVE' },
  { id: 'dossier',    label: 'Dossier',    glyph: '▣', sub: 'ASSET · AT-01',    status: 'T2 · AUTH' },
  { id: 'synapse',    label: 'Synapse',    glyph: '◆', sub: 'MEMORY · RAW',     status: 'WRITE · AUTH' },
  { id: 'skills-lab', label: 'Skills Lab', glyph: '⬡', sub: 'FORGE · CONSOLE',  status: 'T3 · REVIEW' },
];

const PAGE_MAP = {
  'chat':       () => window.ChatPage       && React.createElement(window.ChatPage),
  'notebook':   () => window.NotebookPage   && React.createElement(window.NotebookPage),
  'blog':       () => window.BlogPage       && React.createElement(window.BlogPage),
  'dossier':    () => window.DossierPage    && React.createElement(window.DossierPage),
  'synapse':    () => window.SynapsePage    && React.createElement(window.SynapsePage),
  'skills-lab': () => window.SkillsLabPage  && React.createElement(window.SkillsLabPage),
};

function App() {
  const [surface, setSurface] = React.useState(() => {
    const hash = window.location.hash.replace('#', '') || 'chat';
    return SURFACES.find(s => s.id === hash) ? hash : 'chat';
  });

  React.useEffect(() => {
    const onHash = () => {
      const id = window.location.hash.replace('#', '');
      if (SURFACES.find(s => s.id === id)) setSurface(id);
    };
    window.addEventListener('hashchange', onHash);
    return () => window.removeEventListener('hashchange', onHash);
  }, []);

  const nav = (id) => { window.location.hash = id; setSurface(id); };
  const meta = SURFACES.find(s => s.id === surface);
  const PageEl = PAGE_MAP[surface] ? PAGE_MAP[surface]() : null;

  return (
    <div style={{ width: '100vw', height: '100vh', display: 'grid', gridTemplateRows: '42px 1fr', background: 'var(--ink-1)', overflow: 'hidden' }}>
      {/* ── Global topbar ── */}
      <UI.TopBar surface={meta.sub} status={meta.status} />

      {/* ── Body: left rail + content ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '200px 1fr', overflow: 'hidden' }}>

        {/* ── Left rail nav ── */}
        <div style={{ borderRight: '1px solid var(--line-1)', background: 'var(--ink-2)', display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Project mark */}
          <div style={{ padding: '20px 16px 14px', borderBottom: '1px solid var(--line-1)' }}>
            <div style={{ fontFamily: 'var(--font-display)', fontSize: 28, color: 'var(--phosphor-hi)', textShadow: 'var(--phosphor-glow-hot)', lineHeight: 1, letterSpacing: '0.04em' }}>AT-01</div>
            <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 11, color: 'var(--grey-2)', marginTop: 4 }}>Field Console</div>
          </div>

          {/* Classification */}
          <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--line-1)', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.24em', color: 'var(--amber)', textShadow: 'var(--amber-glow)', textTransform: 'uppercase' }}>
            [ HANDLER EYES ONLY ]
          </div>

          {/* Nav items */}
          <nav style={{ flex: 1, overflow: 'auto', padding: '8px 0' }}>
            {SURFACES.map(s => {
              const active = s.id === surface;
              return (
                <button key={s.id} onClick={() => nav(s.id)} style={{
                  display: 'flex', alignItems: 'center', gap: 10, width: '100%',
                  padding: '10px 16px', background: active ? 'var(--phosphor-deep)' : 'transparent',
                  border: 'none', borderLeft: active ? '2px solid var(--phosphor)' : '2px solid transparent',
                  cursor: 'pointer', textAlign: 'left',
                  transition: 'all 120ms var(--ease-ui)',
                }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: active ? 'var(--phosphor-hi)' : 'var(--grey-2)', textShadow: active ? 'var(--phosphor-glow-soft)' : 'none', lineHeight: 1, width: 16 }}>{s.glyph}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.18em', textTransform: 'uppercase', color: active ? 'var(--phosphor)' : 'var(--grey-2)', textShadow: active ? 'var(--phosphor-glow-soft)' : 'none' }}>{s.label}</span>
                </button>
              );
            })}
          </nav>

          {/* Footer */}
          <div style={{ padding: '12px 16px', borderTop: '1px solid var(--line-1)', fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-1)', letterSpacing: '0.16em' }}>
            <div>WARDEN · ACTIVE</div>
            <div style={{ color: 'var(--phosphor-mid)', marginTop: 4 }}>● WIRE · OPEN</div>
          </div>
        </div>

        {/* ── Page content ── */}
        <div style={{ overflow: 'hidden', position: 'relative' }}>
          {PageEl || (
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', fontFamily: 'var(--font-serif)', fontStyle: 'italic', color: 'var(--grey-2)' }}>
              Surface not loaded.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

ReactDOM.createRoot(document.getElementById('root')).render(<App />);
