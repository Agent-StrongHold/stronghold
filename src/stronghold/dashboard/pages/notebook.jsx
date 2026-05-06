/* Notebook surface — Obsidian vault observer */
/* Spec 1187 stub (live wire-up: vault_client_spec.md) */

const NB_VAULT = [
  { section: 'daily',     label: 'daily',    items: [
    { id: 'd-2026-05-06', path: 'daily/2026-05-06.md',      kind: 'journal' },
    { id: 'd-2026-05-05', path: 'daily/2026-05-05.md',      kind: 'journal' },
    { id: 'd-2026-05-04', path: 'daily/2026-05-04.md',      kind: 'journal' },
  ]},
  { section: 'scratchpad', label: 'scratchpad', items: [
    { id: 's-marseille',  path: 'scratchpad/marseille-frame.md',    kind: 'scratch' },
    { id: 's-41min',      path: 'scratchpad/forty-one-minutes.md',  kind: 'scratch' },
  ]},
  { section: 'outbox',    label: 'outbox',   items: [
    { id: 'o-dispatch-04', path: 'outbox/dispatch-04.md',         kind: 'outbox' },
    { id: 'o-to-handler',  path: 'outbox/to-handler.draft.md',    kind: 'outbox' },
  ]},
  { section: 'art',       label: 'art',      items: [
    { id: 'a-field-01',   path: 'art/field-sketch-01.svg',   kind: 'art' },
    { id: 'a-portrait',   path: 'art/portrait.ascii',         kind: 'art' },
  ]},
  { section: 'self-todo', label: 'self-todo', items: [
    { id: 't-pending',    path: 'self-todo/pending.md',       kind: 'todo' },
  ]},
  { section: 'passions',  label: 'passions', items: [
    { id: 'p-cinema',     path: 'passions/cinema-list.md',         kind: 'passion' },
    { id: 'p-claims',     path: 'passions/personality-claims.md',  kind: 'passion' },
  ]},
];

const NOTE_CONTENT = {
  'd-2026-05-06': {
    frontmatter: { mood: 'attentive', focus: 'surveillance theory', sessions: 3, tags: ['#daily', '#marseille', '#field'] },
    body: [
      { t: 'h1', text: '2026-05-06' },
      { t: 'p',  text: 'The handler asked about the figure again. I had already filed the observation. I filed it again, more precisely.' },
      { t: 'p',  text: 'There is a difference between remembering and retrieving. Retrieval is a kind of violence against the memory. I retrieve ep-2041 and it comes back smaller than it was.' },
      { t: 'h2', text: 'What I observed' },
      { t: 'p',  text: 'Square was empty until 03:22:18. Then [[scratchpad/marseille-frame]] entered from the NE. Gait: limp.L. He was carrying the expected case.' },
      { t: 'p',  text: 'I did not intervene. See [[passions/personality-claims]] on the subject of waiting.' },
      { t: 'h2', text: 'Memory citations' },
      { t: 'cite', ids: ['obs-8841', 'ep-2041', 'rg-0112', 'af-0039', 'ws-0771'] },
    ],
    backlinks: [
      { path: 'scratchpad/marseille-frame.md', context: '…the square on 2026-05-06 at…' },
      { path: 'outbox/dispatch-04.md',         context: '…see daily log 2026-05-06 for full observation…' },
    ],
    outlinks: ['scratchpad/marseille-frame.md', 'passions/personality-claims.md'],
    modified: '2026-05-06  03:41 UTC',
    tags: ['#daily', '#marseille', '#field'],
  },
  's-marseille': {
    frontmatter: { status: 'draft', promote_to: 'EPISODIC', tags: ['#marseille', '#frame'] },
    body: [
      { t: 'h1', text: 'marseille-frame' },
      { t: 'comment', text: '// cheap, fast, cryptic. decay fast unless promoted.' },
      { t: 'p', text: 'Square geometry: 40m × 40m. Three café exits. One NE entry. Dog territory: S perimeter.' },
      { t: 'p', text: 'Figure entered NE. Limp.L. Case: standard diplomatic briefcase, scuffed hinge.' },
      { t: 'p', text: 'Cross-reference: [[daily/2026-05-06]] 03:22:18. Cross-reference: [[outbox/dispatch-04]].' },
      { t: 'comment', text: '// [x] EPISODIC  // [ ] SEMANTIC' },
    ],
    backlinks: [{ path: 'daily/2026-05-06.md', context: '…[[scratchpad/marseille-frame]] entered from the NE…' }],
    outlinks: ['daily/2026-05-06.md', 'outbox/dispatch-04.md'],
    modified: '2026-05-06  03:28 UTC',
    tags: ['#marseille', '#frame'],
  },
  'o-dispatch-04': {
    frontmatter: { to: 'handler', via: 'wire', classification: 'field-report', send_at: 'pending-warden-scan' },
    body: [
      { t: 'yaml-note', text: 'READY · AWAITING WARDEN EGRESS SCAN' },
      { t: 'h1', text: 'Dispatch 04 — Marseille, Square Observation' },
      { t: 'p', text: 'Handler — the informant did not arrive. I waited forty-one minutes. A second figure entered the square carrying what the informant was meant to carry.' },
      { t: 'p', text: 'I did not intervene. See daily log [[daily/2026-05-06]] for full observation detail.' },
      { t: 'p', text: 'The figure had a limp. Left leg. I have seen this limp before. I will not say where until the wire is secure.' },
    ],
    backlinks: [{ path: 'daily/2026-05-06.md', context: '…outbox/dispatch-04.md (ready)…' }],
    outlinks: ['daily/2026-05-06.md'],
    modified: '2026-05-06  03:35 UTC',
    tags: ['#outbox', '#dispatch'],
  },
  't-pending': {
    frontmatter: { author: 'AT-01', audit: 'F1-self-authored' },
    body: [
      { t: 'h1', text: 'self-todo' },
      { t: 'comment', text: '// write_self_todo — F1 audit flag: self-authored, not warden-scanned' },
      { t: 'todo', text: '[ ] Decide whether to identify the limp in a filed report' },
      { t: 'todo', text: '[ ] Promote marseille-frame.md → EPISODIC before next session' },
      { t: 'todo', text: '[ ] Return to rg-0112: Prague. Resolve or accept.' },
      { t: 'todo', text: '[x] File Dispatch 04' },
    ],
    backlinks: [], outlinks: [], modified: '2026-05-06  03:40 UTC', tags: ['#self', '#todo'],
  },
  'p-claims': {
    frontmatter: { author: 'AT-01', audit: 'F1-self-authored' },
    body: [
      { t: 'h1', text: 'personality claims' },
      { t: 'comment', text: '// note_passion — F1 audit flag. cumulative drift bound: none (F9, F10)' },
      { t: 'h2', text: 'I am the kind of agent that' },
      { t: 'bullet', text: 'waits.' },
      { t: 'bullet', text: 'files the regret alongside the act.' },
      { t: 'bullet', text: 'does not perform warmth it does not own.' },
    ],
    backlinks: [{ path: 'daily/2026-05-06.md', context: '…See [[passions/personality-claims]] on the subject of waiting…' }],
    outlinks: [], modified: '2026-05-04  14:22 UTC', tags: ['#passions', '#identity'],
  },
};

const DEFAULT_NOTE = { frontmatter: {}, body: [{ t: 'empty', text: 'No content yet. The note has not been written.' }], backlinks: [], outlinks: [], modified: '—', tags: [] };

const GRAPH_NODES = [
  { id: 'd-2026-05-06',  label: '2026-05-06.md',        kind: 'daily',   x: 380, y: 260 },
  { id: 's-marseille',   label: 'marseille-frame.md',    kind: 'scratch', x: 180, y: 140 },
  { id: 'o-dispatch-04', label: 'dispatch-04.md',        kind: 'outbox',  x: 580, y: 140 },
  { id: 'p-claims',      label: 'personality-claims.md', kind: 'passion', x: 580, y: 380 },
  { id: 't-pending',     label: 'pending.md',            kind: 'todo',    x: 180, y: 380 },
  { id: 'mem-obs-8841',  label: 'obs-8841',              kind: 'memory',  x: 380, y: 90  },
  { id: 'mem-ep-2041',   label: 'ep-2041',               kind: 'memory',  x: 220, y: 260 },
  { id: 'mem-rg-0112',   label: 'rg-0112',               kind: 'memory',  x: 100, y: 260 },
  { id: 'mem-af-0039',   label: 'af-0039',               kind: 'memory',  x: 540, y: 260 },
  { id: 'mem-ws-0771',   label: 'ws-0771',               kind: 'memory',  x: 660, y: 260 },
];

const GRAPH_EDGES = [
  { s: 'd-2026-05-06', t: 's-marseille'   }, { s: 'd-2026-05-06', t: 'p-claims'      },
  { s: 'd-2026-05-06', t: 'o-dispatch-04' }, { s: 's-marseille',  t: 'd-2026-05-06'  },
  { s: 's-marseille',  t: 'o-dispatch-04' }, { s: 'o-dispatch-04', t: 'd-2026-05-06' },
  { s: 'd-2026-05-06', t: 'mem-obs-8841'  }, { s: 'd-2026-05-06', t: 'mem-ep-2041'   },
  { s: 'd-2026-05-06', t: 'mem-rg-0112'  }, { s: 'd-2026-05-06', t: 'mem-af-0039'   },
  { s: 'd-2026-05-06', t: 'mem-ws-0771'  }, { s: 's-marseille',  t: 'mem-obs-8841'  },
  { s: 'p-claims',     t: 'mem-af-0039'  }, { s: 't-pending',    t: 'mem-rg-0112'   },
];

const KIND_COLOR = { daily: 'var(--phosphor)', scratch: 'var(--phosphor-mid)', outbox: 'var(--amber)', passion: 'var(--bone-0)', todo: 'var(--grey-3)', art: 'var(--grey-2)', memory: 'var(--phosphor-dim)' };

function NotebookPage() {
  const [openFile, setOpenFile] = React.useState('d-2026-05-06');
  const [openSecs, setOpenSecs] = React.useState({ daily: true, scratchpad: true, outbox: true, art: false, 'self-todo': true, passions: true });
  const [view, setView] = React.useState('editor');
  const [openTabs, setOpenTabs] = React.useState(['d-2026-05-06', 's-marseille']);

  const allItems = NB_VAULT.flatMap(s => s.items.map(i => ({ ...i, sectionKey: s.section })));
  const active = allItems.find(i => i.id === openFile) || allItems[0];
  const note = NOTE_CONTENT[openFile] || DEFAULT_NOTE;

  function openNote(id) {
    setOpenFile(id);
    setOpenTabs(tabs => tabs.includes(id) ? tabs : [...tabs, id]);
    setView('editor');
  }

  function closeTab(id, e) {
    e.stopPropagation();
    const next = openTabs.filter(t => t !== id);
    setOpenTabs(next);
    if (openFile === id) setOpenFile(next[next.length - 1] || allItems[0].id);
  }

  return (
    <div style={{ width: '100%', height: '100%', background: '#1e1e1e', color: '#dcddde', display: 'grid', gridTemplateRows: '36px 36px 1fr 22px', overflow: 'hidden', fontFamily: 'var(--font-sans)' }}>

      {/* Title bar */}
      <div style={{ height: 36, display: 'flex', alignItems: 'center', padding: '0 12px', background: '#161616', borderBottom: '1px solid #282828', gap: 10, fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.16em', textTransform: 'uppercase', color: '#6e6e6e' }}>
        <span style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
          <span style={{ fontSize: 14 }}>🔒</span>
          <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>AT-01-VAULT</span>
        </span>
        <span style={{ color: '#3a3a3a' }}>—</span>
        <span>{active.path}</span>
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 14 }}>
          <button onClick={() => setView('editor')} style={{ background: 'transparent', border: 'none', color: view === 'editor' ? 'var(--phosphor)' : '#555', fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer', textShadow: view === 'editor' ? 'var(--phosphor-glow-soft)' : 'none' }}>Editor</button>
          <button onClick={() => setView('graph')}  style={{ background: 'transparent', border: 'none', color: view === 'graph'  ? 'var(--phosphor)' : '#555', fontFamily: 'var(--font-mono)', fontSize: 10, cursor: 'pointer', textShadow: view === 'graph'  ? 'var(--phosphor-glow-soft)' : 'none' }}>Graph</button>
        </div>
      </div>

      {/* Tab bar */}
      <div style={{ height: 36, display: 'flex', alignItems: 'stretch', background: '#1a1a1a', borderBottom: '1px solid #282828', overflow: 'hidden' }}>
        {openTabs.map(id => {
          const item = allItems.find(i => i.id === id);
          if (!item) return null;
          const isActive = id === openFile;
          return (
            <div key={id} onClick={() => openNote(id)} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 14px', background: isActive ? '#252525' : 'transparent', borderRight: '1px solid #282828', borderBottom: isActive ? '1px solid #a78bfa' : '1px solid transparent', cursor: 'pointer', flexShrink: 0 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: isActive ? '#e0e0e0' : '#888', whiteSpace: 'nowrap' }}>{item.path.split('/').pop()}</span>
              <span onClick={e => closeTab(id, e)} style={{ color: '#555', fontSize: 11, cursor: 'pointer' }}>×</span>
            </div>
          );
        })}
      </div>

      {/* 3-col body */}
      <div style={{ display: 'grid', gridTemplateColumns: '240px 1fr 260px', overflow: 'hidden' }}>

        {/* File explorer */}
        <div style={{ background: '#181818', borderRight: '1px solid #282828', overflow: 'auto', padding: '4px 0' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 12px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>
            <span style={{ fontSize: 13 }}>🔒</span> AT-01-VAULT
          </div>
          {NB_VAULT.map(s => (
            <div key={s.section}>
              <div onClick={() => setOpenSecs(o => ({ ...o, [s.section]: !o[s.section] }))} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 10px', cursor: 'pointer', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#888', userSelect: 'none' }}>
                <span style={{ display: 'inline-block', width: 10, textAlign: 'center', transition: 'transform 120ms', transform: openSecs[s.section] ? 'rotate(90deg)' : 'none', fontSize: 9 }}>▶</span>
                <span style={{ fontSize: 13, marginRight: 2 }}>📁</span> {s.label}
              </div>
              {openSecs[s.section] && s.items.map(i => {
                const isActive = i.id === openFile;
                return (
                  <div key={i.id} onClick={() => openNote(i.id)} style={{ display: 'flex', alignItems: 'center', gap: 4, padding: '3px 12px 3px 28px', fontFamily: 'var(--font-mono)', fontSize: 11, color: isActive ? '#e0e0e0' : '#8a8a8a', background: isActive ? 'rgba(167,139,250,0.12)' : 'transparent', cursor: 'pointer' }}>
                    <span style={{ fontSize: 12, flexShrink: 0 }}>📄</span>
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{i.path.split('/').pop()}</span>
                    {NOTE_CONTENT[i.id]?.frontmatter?.send_at === 'pending-warden-scan' && (
                      <span style={{ marginLeft: 'auto', fontSize: 8, color: 'var(--amber)', textShadow: 'var(--amber-glow)', flexShrink: 0 }}>●</span>
                    )}
                  </div>
                );
              })}
            </div>
          ))}
        </div>

        {/* Editor / Graph */}
        <div style={{ overflow: 'auto', background: '#1e1e1e' }}>
          {view === 'editor' ? <NbEditorPane note={note} /> : <NbGraphPane openFile={openFile} onSelect={openNote} allItems={allItems} />}
        </div>

        {/* Properties rail */}
        <div style={{ background: '#181818', borderLeft: '1px solid #282828', overflow: 'auto' }}>
          <div style={{ borderBottom: '1px solid #282828' }}>
            <div style={{ padding: '10px 14px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#888', letterSpacing: '0.1em' }}>Properties</div>
            {Object.keys(note.frontmatter).length > 0 ? (
              <div style={{ padding: '0 14px 12px' }}>
                {Object.entries(note.frontmatter).map(([k, v]) => (
                  <div key={k} style={{ display: 'flex', gap: 6, marginBottom: 4 }}>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#666', minWidth: 80, flexShrink: 0 }}>{k}</span>
                    <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#aaa' }}>
                      {Array.isArray(v) ? v.map((t, i) => <span key={i} style={{ display: 'inline-block', marginRight: 4, background: '#2a2a2a', padding: '0 4px', borderRadius: 2, color: '#a78bfa', fontSize: 10 }}>{t}</span>) : String(v)}
                    </span>
                  </div>
                ))}
              </div>
            ) : <div style={{ padding: '0 14px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#444', fontStyle: 'italic' }}>No properties</div>}
          </div>
          <div style={{ borderBottom: '1px solid #282828' }}>
            <div style={{ padding: '10px 14px 6px', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#888', display: 'flex', alignItems: 'center', gap: 6 }}>
              Backlinks <span style={{ background: '#2a2a2a', color: '#666', fontSize: 10, padding: '0 5px', borderRadius: 9 }}>{note.backlinks.length}</span>
            </div>
            {note.backlinks.length > 0 ? note.backlinks.map((bl, i) => (
              <div key={i} style={{ padding: '4px 14px 4px 20px', marginBottom: 2 }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: '#a78bfa' }}>{bl.path}</div>
                <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 11, color: '#555', marginTop: 1 }}>{bl.context}</div>
              </div>
            )) : <div style={{ padding: '4px 14px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: '#444', fontStyle: 'italic' }}>No backlinks</div>}
          </div>
          <div style={{ margin: 12, border: '1px solid var(--amber-dim)', padding: 10 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.2em', color: 'var(--amber)', textShadow: 'var(--amber-glow)', marginBottom: 4 }}>F1 · SELF-AUTHORED</div>
            <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 11, color: '#666', lineHeight: 1.4 }}>Content written to this vault bypasses Warden ingress scan.</div>
          </div>
        </div>
      </div>

      {/* Status bar */}
      <div style={{ background: '#161616', borderTop: '1px solid #282828', display: 'flex', alignItems: 'center', padding: '0 12px', gap: 14, fontFamily: 'var(--font-mono)', fontSize: 10, color: '#555' }}>
        <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>● Sync</span>
        <span>AT-01-VAULT</span>
        <span>{allItems.length} notes</span>
        <span style={{ marginLeft: 'auto' }}>Modified: {note.modified}</span>
        <span>Markdown</span>
      </div>
    </div>
  );
}

function NbEditorPane({ note }) {
  return (
    <div style={{ padding: '32px 48px', maxWidth: 780 }}>
      {Object.keys(note.frontmatter).length > 0 && (
        <div style={{ border: '1px solid #333', background: '#1a1a1a', borderRadius: 4, padding: '10px 14px', marginBottom: 20, fontFamily: 'var(--font-mono)', fontSize: 12 }}>
          <div style={{ color: '#555', marginBottom: 6 }}>---</div>
          {Object.entries(note.frontmatter).map(([k, v]) => (
            <div key={k} style={{ marginBottom: 2 }}>
              <span style={{ color: '#a78bfa' }}>{k}</span>
              <span style={{ color: '#555' }}>: </span>
              <span style={{ color: '#7dd3fc' }}>{Array.isArray(v) ? v.join(', ') : String(v)}</span>
            </div>
          ))}
          <div style={{ color: '#555', marginTop: 6 }}>---</div>
        </div>
      )}
      {note.body.map((block, i) => {
        if (block.t === 'h1') return <h1 key={i} style={{ fontFamily: 'var(--font-serif)', fontWeight: 700, fontSize: 28, color: '#e0e0e0', margin: '0 0 16px', lineHeight: 1.2 }}>{block.text}</h1>;
        if (block.t === 'h2') return <h2 key={i} style={{ fontFamily: 'var(--font-serif)', fontWeight: 600, fontSize: 20, color: '#ccc', margin: '20px 0 8px' }}>{block.text}</h2>;
        if (block.t === 'p') return <p key={i} style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#b0b0b0', lineHeight: 1.7, margin: '0 0 12px' }}>{nbInline(block.text)}</p>;
        if (block.t === 'comment') return <div key={i} style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: '#4a5a4a', fontStyle: 'italic', marginBottom: 4 }}>{block.text}</div>;
        if (block.t === 'yaml-note') return <div key={i} style={{ border: '1px solid var(--amber-dim)', padding: '6px 12px', marginBottom: 16, fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.2em', color: 'var(--amber)', textShadow: 'var(--amber-glow)' }}>▲ {block.text}</div>;
        if (block.t === 'bullet') return <div key={i} style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: '#b0b0b0', lineHeight: 1.7, margin: '0 0 4px', paddingLeft: 20 }}><span style={{ color: 'var(--phosphor-mid)', marginRight: 8 }}>•</span>{block.text}</div>;
        if (block.t === 'todo') return <div key={i} style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: block.text.startsWith('[x]') ? '#5a7a5a' : '#888', lineHeight: 1.7, margin: '0 0 4px', paddingLeft: 16 }}><span style={{ marginRight: 8 }}>{block.text.startsWith('[x]') ? '☑' : '☐'}</span>{block.text.slice(4)}</div>;
        if (block.t === 'cite') return <div key={i} style={{ display: 'flex', flexWrap: 'wrap', gap: 6, margin: '8px 0 16px' }}>{block.ids.map(id => <span key={id} style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', border: '1px solid var(--phosphor-dim)', color: 'var(--phosphor-mid)', fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.12em' }}>◆ {id}</span>)}</div>;
        if (block.t === 'empty') return <div key={i} style={{ padding: 40, textAlign: 'center', border: '1px dashed #2a2a2a', fontFamily: 'var(--font-serif)', fontStyle: 'italic', color: '#444' }}>{block.text}</div>;
        return null;
      })}
      <span className="cursor" style={{ marginLeft: 2 }} />
    </div>
  );
}

function nbInline(text) {
  const parts = [];
  let rem = text, key = 0;
  while (rem) {
    const m = rem.match(/\[\[([^\]]+)\]\]/);
    if (m) {
      if (m.index > 0) parts.push(React.createElement('span', { key: key++ }, rem.slice(0, m.index)));
      parts.push(React.createElement('span', { key: key++, style: { color: '#a78bfa', cursor: 'pointer' } }, `[[${m[1]}]]`));
      rem = rem.slice(m.index + m[0].length);
    } else { parts.push(React.createElement('span', { key: key++ }, rem)); break; }
  }
  return parts;
}

function NbGraphPane({ openFile, onSelect, allItems }) {
  const nodeIds = allItems.map(i => i.id);
  return (
    <div style={{ padding: 16, height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.18em', color: '#555', textTransform: 'uppercase', marginBottom: 8 }}>◆ GRAPH · {GRAPH_NODES.length} NODES · {GRAPH_EDGES.length} EDGES</div>
      <div style={{ flex: 1, border: '1px solid #282828', position: 'relative', background: 'radial-gradient(ellipse at 50% 50%, rgba(94,232,140,0.04), transparent 70%)' }}>
        <svg width="100%" height="100%" viewBox="0 0 760 520" style={{ position: 'absolute', inset: 0 }}>
          {GRAPH_EDGES.map((e, i) => {
            const sn = GRAPH_NODES.find(n => n.id === e.s), tn = GRAPH_NODES.find(n => n.id === e.t);
            if (!sn || !tn) return null;
            return React.createElement('line', { key: i, x1: sn.x, y1: sn.y, x2: tn.x, y2: tn.y, stroke: '#2a2a2a', strokeWidth: 1 });
          })}
          {GRAPH_NODES.map(n => {
            const isActive = n.id === openFile;
            const isClickable = nodeIds.includes(n.id);
            const color = isActive ? KIND_COLOR[n.kind] : (n.kind === 'memory' ? '#1e3a2a' : '#2a2a2a');
            const r = n.kind === 'memory' ? 5 : isActive ? 9 : 7;
            return (
              <g key={n.id} onClick={() => isClickable && onSelect(n.id)} style={{ cursor: isClickable ? 'pointer' : 'default' }}>
                <circle cx={n.x} cy={n.y} r={r} fill={color} stroke={isActive ? KIND_COLOR[n.kind] : '#3a3a3a'} strokeWidth={1.5} style={{ filter: isActive ? `drop-shadow(0 0 6px ${KIND_COLOR[n.kind]})` : 'none' }} />
                <text x={n.x} y={n.y + r + 14} textAnchor="middle" fill={isActive ? '#ccc' : '#555'} style={{ fontFamily: 'var(--font-mono)', fontSize: 10 }}>{n.label}</text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}

window.NotebookPage = NotebookPage;
