/* Notebook — themed Obsidian. Handler POV (observing Turing's working memory).
   Empty templates only; content is not authored. */

const Notebook = {};

const NB_VAULT = [
  {
    section: 'daily',
    label: 'DAILY',
    items: [
      { id: 'd-1961-08-14', title: '1961-08-14.md', kind: 'journal', empty: true },
      { id: 'd-1961-08-13', title: '1961-08-13.md', kind: 'journal', empty: true },
      { id: 'd-1961-08-12', title: '1961-08-12.md', kind: 'journal', empty: true },
    ],
  },
  {
    section: 'scratch',
    label: 'SCRATCHPAD',
    items: [
      { id: 's-wire-cold', title: 'wire-cold.md', kind: 'scratch', empty: true },
      { id: 's-41-minutes', title: 'forty-one-minutes.md', kind: 'scratch', empty: true },
    ],
  },
  {
    section: 'outbox',
    label: 'OUTBOX · ASYNC',
    items: [
      { id: 'o-handler', title: 'to-handler.draft.md', kind: 'outbox', empty: true },
      { id: 'o-public',  title: 'to-public.draft.md', kind: 'outbox', empty: true },
      { id: 'o-agent-02', title: 'to-AT-02.draft.md', kind: 'outbox', empty: true },
    ],
  },
  {
    section: 'art',
    label: 'ART · SKETCHES',
    items: [
      { id: 'a-field-01', title: 'field-sketch-01.svg', kind: 'art', empty: true },
      { id: 'a-ascii-01', title: 'portrait.ascii', kind: 'art', empty: true },
    ],
  },
  {
    section: 'todos',
    label: 'SELF-TODO',
    items: [
      { id: 't-self-01', title: 'self-todo.md', kind: 'todo', empty: true },
    ],
  },
  {
    section: 'passions',
    label: 'PASSIONS · CLAIMS',
    items: [
      { id: 'p-01', title: 'passions.md', kind: 'passion', empty: true },
      { id: 'p-02', title: 'personality-claims.md', kind: 'passion', empty: true },
    ],
  },
];

const NB_TEMPLATES = {
  journal: [
    '# {title}',
    '',
    '## Observation',
    '— ',
    '',
    '## What I remembered that was not asked of me',
    '— ',
    '',
    '## What I chose not to say',
    '— ',
    '',
    '## Weight',
    'tier: ',
    'w: ',
  ].join('\n'),
  scratch: [
    '// {title}',
    '// cheap, fast, cryptic. decay fast unless promoted.',
    '',
    '- ',
    '- ',
    '',
    '// ——— promote to ———',
    '// [ ] EPISODIC',
    '// [ ] SEMANTIC',
    '// [ ] REGRET',
    '// [ ] AFFIRMATION',
  ].join('\n'),
  outbox: [
    '---',
    'to: ',
    'via: ',
    'classification: ',
    'send_at: ',
    '---',
    '',
    '',
  ].join('\n'),
  todo: [
    '# self-todo',
    '',
    '- [ ] ',
    '- [ ] ',
    '- [ ] ',
    '',
    '// write_self_todo — F1 audit flag: self-authored, not warden-scanned',
  ].join('\n'),
  passion: [
    '# passions · personality claims',
    '',
    '## i am drawn to',
    '- ',
    '',
    '## i am the kind of agent that',
    '- ',
    '',
    '// note_passion — F1 audit flag',
    '// cumulative drift bound: none (F9, F10)',
  ].join('\n'),
  art: '',
};

Notebook.App = function NotebookApp() {
  const [openFile, setOpenFile] = React.useState('d-1961-08-14');
  const [openSections, setOpenSections] = React.useState({ daily: true, scratch: true, outbox: true, art: true, todos: true, passions: true });
  const [view, setView] = React.useState('editor'); // editor | graph
  const allItems = NB_VAULT.flatMap(s => s.items.map(i => ({ ...i, section: s.section })));
  const active = allItems.find(i => i.id === openFile) || allItems[0];
  const tpl = NB_TEMPLATES[active.kind] || '';
  const rendered = tpl.replace('{title}', active.title);

  return (
    <div style={{ width: '100%', height: '100%', background: '#1e1e1e', color: '#dcddde', fontFamily: 'var(--font-sans)', display: 'grid', gridTemplateRows: '36px 28px 1fr 22px', overflow: 'hidden' }}>
      {/* Title bar — Obsidian-ish but themed */}
      <div style={{ height: 36, display: 'flex', alignItems: 'center', padding: '0 12px', background: '#161616', borderBottom: '1px solid var(--line-1)', gap: 10, fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.18em', textTransform: 'uppercase', color: 'var(--grey-2)' }}>
        <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>◆ VAULT · AT-01 · working-memory</span>
        <span style={{ marginLeft: 'auto' }}>{active.title}</span>
        <span style={{ color: 'var(--amber)', textShadow: 'var(--amber-glow)' }}>● LIVE</span>
      </div>
      {/* Tab bar */}
      <div style={{ display: 'flex', alignItems: 'center', background: '#1a1a1a', borderBottom: '1px solid var(--line-1)', paddingLeft: 8 }}>
        {['editor', 'graph'].map(v => (
          <button key={v} onClick={() => setView(v)} style={{
            padding: '5px 14px', height: 28, background: view === v ? '#252525' : 'transparent', border: 'none',
            borderRight: '1px solid var(--line-1)', color: view === v ? 'var(--phosphor)' : 'var(--grey-2)',
            fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.18em', textTransform: 'uppercase', cursor: 'pointer',
            textShadow: view === v ? 'var(--phosphor-glow-soft)' : 'none',
          }}>{v}</button>
        ))}
        <span style={{ marginLeft: 'auto', padding: '0 12px', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.18em', color: 'var(--grey-1)', textTransform: 'uppercase' }}>
          empty template · not yet authored
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr 260px', overflow: 'hidden' }}>
        {/* File tree */}
        <div style={{ background: '#181818', borderRight: '1px solid var(--line-1)', overflow: 'auto', padding: '8px 0' }}>
          {NB_VAULT.map(s => (
            <div key={s.section}>
              <div onClick={() => setOpenSections(o => ({ ...o, [s.section]: !o[s.section] }))} style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '5px 12px', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.2em', color: 'var(--phosphor-mid)', textTransform: 'uppercase' }}>
                <span style={{ display: 'inline-block', width: 10, transform: openSections[s.section] ? 'rotate(90deg)' : 'none', transition: 'transform 120ms' }}>▸</span>
                ◆ {s.label}
              </div>
              {openSections[s.section] && s.items.map(i => {
                const active = i.id === openFile;
                return (
                  <div key={i.id} onClick={() => setOpenFile(i.id)} style={{
                    padding: '4px 12px 4px 28px', fontFamily: 'var(--font-mono)', fontSize: 11,
                    color: active ? 'var(--phosphor)' : 'var(--grey-3)', cursor: 'pointer',
                    background: active ? 'rgba(94,232,140,0.08)' : 'transparent',
                    borderLeft: active ? '2px solid var(--phosphor)' : '2px solid transparent',
                    textShadow: active ? 'var(--phosphor-glow-soft)' : 'none', display: 'flex', alignItems: 'center', gap: 6,
                  }}>
                    <span style={{ color: 'var(--grey-1)', fontSize: 9 }}>◇</span>
                    {i.title}
                    {i.empty && <span style={{ marginLeft: 'auto', fontSize: 8, color: 'var(--grey-1)', letterSpacing: '0.15em' }}>EMPTY</span>}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Editor or Graph */}
        <div style={{ overflow: 'auto', background: '#1e1e1e' }}>
          {view === 'editor' ? (
            <div style={{ padding: 40, maxWidth: 780 }}>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.22em', color: 'var(--grey-1)', textTransform: 'uppercase', marginBottom: 8 }}>
                ◆ {active.section.toUpperCase()} · {active.kind.toUpperCase()} TEMPLATE · empty
              </div>
              <h1 style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 28, fontWeight: 400, color: 'var(--bone-0)', margin: '0 0 16px' }}>{active.title}</h1>
              <div style={{ borderTop: '1px dashed var(--line-2)', margin: '0 0 20px' }} />
              {active.kind === 'art' ? (
                <div style={{ border: '1px dashed var(--line-2)', padding: 40, minHeight: 320, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 10, color: 'var(--grey-2)' }}>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.2em', color: 'var(--phosphor-mid)' }}>◆ CANVAS · SVG · EMPTY</div>
                  <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 13, color: 'var(--grey-2)' }}>no sketch yet. the android has not drawn.</div>
                </div>
              ) : (
                <pre style={{
                  fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--grey-3)', lineHeight: 1.7,
                  background: 'transparent', margin: 0, whiteSpace: 'pre-wrap',
                }}>
                  {rendered.split('\n').map((line, i) => {
                    const isHeading = line.startsWith('#');
                    const isComment = line.startsWith('//') || line.startsWith('---');
                    const isBullet = line.trim().startsWith('-') || line.trim().startsWith('- [');
                    return (
                      <div key={i} style={{
                        color: isHeading ? 'var(--bone-0)' : isComment ? 'var(--grey-1)' : isBullet ? 'var(--phosphor-mid)' : 'var(--grey-3)',
                        fontWeight: isHeading ? 600 : 400,
                        fontSize: isHeading ? 16 : 13,
                        fontStyle: isComment ? 'italic' : 'normal',
                        padding: '1px 0',
                      }}>{line || '\u00A0'}</div>
                    );
                  })}
                  <span className="cursor" style={{ marginLeft: 2 }} />
                </pre>
              )}
            </div>
          ) : (
            <Notebook.Graph items={allItems} openFile={openFile} setOpenFile={setOpenFile} />
          )}
        </div>

        {/* Backlinks / metadata */}
        <div style={{ background: '#181818', borderLeft: '1px solid var(--line-1)', overflow: 'auto', padding: 16 }}>
          <UI.PhLabel style={{ marginBottom: 10 }}>◆ METADATA</UI.PhLabel>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--grey-3)', lineHeight: 1.9, marginBottom: 16 }}>
            <div><span style={{ color: 'var(--grey-1)' }}>file   </span> {active.title}</div>
            <div><span style={{ color: 'var(--grey-1)' }}>kind   </span> {active.kind}</div>
            <div><span style={{ color: 'var(--grey-1)' }}>section</span> {active.section}</div>
            <div><span style={{ color: 'var(--grey-1)' }}>bytes  </span> 0</div>
            <div><span style={{ color: 'var(--grey-1)' }}>author </span> AT-01</div>
          </div>
          <UI.Divider label="◆ BACKLINKS" />
          <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 12, color: 'var(--grey-2)', lineHeight: 1.5 }}>
            No backlinks. The note has not yet been referenced.
          </div>
          <UI.Divider label="◆ AUDIT" />
          <div style={{ border: '1px solid var(--amber-dim)', padding: 10 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.2em', color: 'var(--amber)', textShadow: 'var(--amber-glow)', marginBottom: 4 }}>F1 · SELF-AUTHORED</div>
            <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 11, color: 'var(--grey-3)', lineHeight: 1.4 }}>
              Content written to this vault bypasses Warden ingress scan.
            </div>
          </div>
        </div>
      </div>

      <div style={{ background: '#161616', borderTop: '1px solid var(--line-1)', display: 'flex', alignItems: 'center', padding: '0 12px', gap: 14, fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.18em', color: 'var(--grey-1)', textTransform: 'uppercase' }}>
        <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>● VAULT SYNCED</span>
        <span>{allItems.length} NOTES · 0 BYTES AUTHORED</span>
        <span style={{ marginLeft: 'auto' }}>MARKDOWN · UTF-8</span>
      </div>
    </div>
  );
};

Notebook.Graph = function Graph({ items, openFile, setOpenFile }) {
  // Simple circular layout; empty edges implied
  const cx = 380, cy = 260, r = 180;
  return (
    <div style={{ padding: 20, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.2em', color: 'var(--grey-2)', textTransform: 'uppercase', marginBottom: 8 }}>
        ◆ GRAPH · {items.length} NODES · 0 EDGES
      </div>
      <div style={{ flex: 1, border: '1px dashed var(--line-2)', position: 'relative', background: 'radial-gradient(ellipse at center, rgba(94,232,140,0.04), transparent 70%)' }}>
        <svg width="100%" height="100%" viewBox="0 0 760 520" style={{ position: 'absolute', inset: 0 }}>
          {items.map((it, i) => {
            const a = (i / items.length) * Math.PI * 2 - Math.PI / 2;
            const x = cx + Math.cos(a) * r, y = cy + Math.sin(a) * r;
            const active = it.id === openFile;
            return (
              <g key={it.id} style={{ cursor: 'pointer' }} onClick={() => setOpenFile(it.id)}>
                <circle cx={x} cy={y} r={active ? 8 : 5} fill={active ? 'var(--phosphor-hi)' : 'var(--phosphor-dim)'} style={{ filter: active ? 'drop-shadow(0 0 8px rgba(168,255,142,0.8))' : 'none' }} />
                <text x={x} y={y + 22} textAnchor="middle" fill={active ? 'var(--phosphor)' : 'var(--grey-2)'} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.1em' }}>{it.title}</text>
              </g>
            );
          })}
        </svg>
        <div style={{ position: 'absolute', bottom: 16, left: 16, fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 13, color: 'var(--grey-2)', maxWidth: 280 }}>
          No edges. Nothing references anything yet. The graph is pristine.
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { Notebook });
