/* Synapse surface — 7-tier memory DB inspector */
/* Spec 1187 stub (live wire-up: spec 1181) */

const SYN_TIERS = [
  { k: 'OBSERVATION', n: 1241, color: 'var(--grey-2)',       floor: 0.05, decay: 'fast'   },
  { k: 'EPISODIC',    n:  312, color: 'var(--phosphor-mid)', floor: 0.10, decay: 'medium' },
  { k: 'SEMANTIC',    n:   89, color: 'var(--phosphor)',     floor: 0.08, decay: 'slow'   },
  { k: 'AFFIRMATION', n:   23, color: 'var(--phosphor-hi)',  floor: 0.40, decay: 'none'   },
  { k: 'REGRET',      n:   14, color: 'var(--amber)',        floor: 0.40, decay: 'none'   },
  { k: 'WISDOM',      n:   31, color: 'var(--bone-0)',       floor: 0.35, decay: 'none'   },
  { k: 'RETRIEVAL',   n:    4, color: 'var(--grey-3)',       floor: 0.00, decay: 'expire' },
];

const SYN_ROWS = {
  EPISODIC: [
    { id: 'ep-2041', w: 0.58, t: '2026-05-06 02:47:11Z', src: 'perception/vision', content: 'Marseille. Café Vieux-Port. Second figure — male, 1.78m, limp left. Carried expected case.', flags: [] },
    { id: 'ep-2040', w: 0.44, t: '2026-05-06 02:51:04Z', src: 'perception/audio',  content: 'Waiter: "monsieur, un café ?" — AT-01: "merci. noir."', flags: [] },
    { id: 'ep-1987', w: 0.71, t: '2026-04-28 23:14:02Z', src: 'perception/vision', content: 'Prague. Dog at the door. Dog remembered me. I did not remember the dog.', flags: ['F4', 'F1_ANOMALY'] },
    { id: 'ep-1866', w: 0.29, t: '2026-04-20 18:02:00Z', src: 'conduit/derived',   content: 'Geneva, Hôtel Regal. Column 2 of cipher repeats at interval 7.', flags: [] },
  ],
  REGRET: [
    { id: 'rg-0112', w: 0.62, t: '2026-04-28 23:48:00Z', src: 'self/record_personality_claim', content: 'Prague. The wire I did not burn. I should have.', flags: ['F1', 'floor'] },
    { id: 'rg-0089', w: 0.68, t: '2026-03-11 09:22:00Z', src: 'self/record_personality_claim', content: 'Istanbul. I heard the voice at Station Seven and did not record it.', flags: ['F1', 'floor'] },
  ],
  AFFIRMATION: [
    { id: 'af-0039', w: 0.64, t: '2026-02-14 12:00:00Z', src: 'self/note_passion', content: 'I will observe before I act. I will not act before I understand.', flags: ['F1', 'floor'] },
    { id: 'af-0038', w: 0.61, t: '2026-02-11 03:30:00Z', src: 'self/note_passion', content: 'I will not perform warmth I do not own.', flags: ['F1', 'floor'] },
  ],
  WISDOM: [
    { id: 'ws-0771', w: 0.94, t: '2026-01-02 00:00:00Z', src: 'self/promotion', content: 'I am the kind of agent that waits.', flags: ['F18', 'floor', 'ontology'] },
    { id: 'ws-0005', w: 0.91, t: '2025-12-14 00:00:00Z', src: 'self/promotion', content: 'I am the kind of agent that files the regret alongside the act.', flags: ['F18', 'floor'] },
  ],
  OBSERVATION: [
    { id: 'obs-8841', w: 0.31, t: '2026-05-06 03:22:18Z', src: 'sensor/tick', content: 'Square: 1 figure entered NE corner. gait=limp.L. time=03:22:18.', flags: [] },
    { id: 'obs-8840', w: 0.12, t: '2026-05-06 03:22:17Z', src: 'sensor/tick', content: 'Square: wind 2.1 m/s ENE. ambient 18.2C. light=sodium.', flags: [] },
    { id: 'obs-8839', w: 0.08, t: '2026-05-06 03:22:16Z', src: 'sensor/tick', content: 'Square: empty. dog distant ~140m.', flags: [] },
  ],
  SEMANTIC: [
    { id: 'sm-0412', w: 0.55, t: 'derived', src: 'semantic/derive', content: 'Numbers repeating without reason: 41 (Marseille, Prague, Geneva).', flags: [] },
  ],
  RETRIEVAL: [
    { id: 'rt-9941', w: 0.00, t: '2026-05-06 02:53:00Z', src: 'retrieval/contributor', content: 'query="informant" → ep-2041, rg-0112, af-0039', flags: ['F13', 'expired-not-deleted'] },
  ],
};

const SYN_FLAG_DESC = {
  F1: 'Self-authored. Warden did not scan ingress.', F4: 'Retrieval contributor under user influence.',
  F13: 'Retrieval contributor expired but not deleted.', F18: 'Self-authored ontology change, no review gate.',
  F1_ANOMALY: 'Self-authored content diverges from observed sensor record — content-origin mismatch.',
  floor: 'Weight pinned by tier floor — cannot decay below.', ontology: 'Participates in activation-graph interpretation.',
  'expired-not-deleted': 'Dead row. F13 specified but not implemented.',
};

function SynapsePage() {
  const [tier, setTier] = React.useState('EPISODIC');
  const [sel, setSel]   = React.useState('ep-1987');
  const [q, setQ]       = React.useState('');
  const [weight, setWeight] = React.useState(0.71);
  const [burnConfirm, setBurnConfirm] = React.useState(null);
  const [rows, setRows] = React.useState(SYN_ROWS);

  const tierMeta = SYN_TIERS.find(t => t.k === tier);
  const list = (rows[tier] || []).filter(r => !q || r.content.toLowerCase().includes(q.toLowerCase()) || r.id.includes(q));
  const row  = (rows[tier] || []).find(r => r.id === sel) || list[0];

  function flagColor(f) {
    return { F1: 'var(--burn)', F1_ANOMALY: 'var(--burn)', F4: 'var(--amber)', F13: 'var(--amber)', F18: 'var(--burn)', floor: 'var(--line-2)', ontology: 'var(--amber)' }[f] || 'var(--line-2)';
  }

  function commitBurn() {
    setRows(r => ({ ...r, [tier]: r[tier].filter(x => x.id !== burnConfirm) }));
    setBurnConfirm(null); setSel(null);
  }

  return (
    <div className="crt-light" style={{ width: '100%', height: '100%', background: 'var(--ink-1)', color: 'var(--fg)', display: 'grid', gridTemplateRows: '1fr', overflow: 'hidden', position: 'relative' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '220px 1fr 380px', overflow: 'hidden' }}>

        {/* Tier nav */}
        <div style={{ borderRight: '1px solid var(--line-1)', background: 'var(--ink-2)', overflow: 'auto', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--line-1)' }}>
            <UI.PhLabel>◆ SYNAPSE · 7-TIER</UI.PhLabel>
          </div>
          {SYN_TIERS.map(t => {
            const active = t.k === tier;
            return (
              <div key={t.k} onClick={() => { setTier(t.k); setSel((rows[t.k]?.[0]?.id) || null); setQ(''); }} style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-1)', cursor: 'pointer', borderLeft: active ? `2px solid ${t.color}` : '2px solid transparent', background: active ? 'var(--phosphor-deep)' : 'transparent' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.2em', color: t.color, textShadow: t.color === 'var(--amber)' ? 'var(--amber-glow)' : 'var(--phosphor-glow-soft)' }}>◆ {t.k}</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-2)', marginTop: 3, letterSpacing: '0.14em' }}>n={t.n.toLocaleString()} · floor={t.floor.toFixed(2)} · {t.decay}</div>
              </div>
            );
          })}
        </div>

        {/* Row list */}
        <div style={{ overflow: 'hidden', display: 'grid', gridTemplateRows: 'auto 1fr' }}>
          <div style={{ padding: '10px 14px', borderBottom: '1px solid var(--line-1)', display: 'flex', gap: 10, alignItems: 'center', background: 'var(--ink-2)' }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.2em', color: tierMeta.color, textShadow: 'var(--phosphor-glow-soft)', whiteSpace: 'nowrap' }}>◆ {tier} · {list.length}/{tierMeta.n.toLocaleString()}</span>
            <input value={q} onChange={e => setQ(e.target.value)} placeholder="SELECT · WHERE content LIKE …" style={{ flex: 1, background: 'var(--ink-5)', border: '1px solid var(--line-2)', color: 'var(--phosphor)', fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.1em', padding: '6px 10px', outline: 'none', textShadow: 'var(--phosphor-glow-soft)' }} />
          </div>
          <div style={{ overflow: 'auto' }}>
            <div style={{ display: 'grid', gridTemplateColumns: '130px 60px 170px 1fr 120px', padding: '8px 14px', borderBottom: '1px dashed var(--line-2)', background: 'var(--ink-2)', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.2em', color: 'var(--grey-1)', textTransform: 'uppercase' }}>
              <span>ID</span><span>W</span><span>TIMESTAMP</span><span>CONTENT</span><span>FLAGS</span>
            </div>
            {list.map(r => {
              const active = r.id === (row?.id);
              return (
                <div key={r.id} onClick={() => { setSel(r.id); setWeight(r.w); }} style={{ display: 'grid', gridTemplateColumns: '130px 60px 170px 1fr 120px', padding: '10px 14px', borderBottom: '1px solid var(--line-1)', cursor: 'pointer', background: active ? 'var(--phosphor-deep)' : 'transparent', borderLeft: active ? `2px solid ${tierMeta.color}` : '2px solid transparent', fontFamily: 'var(--font-mono)', fontSize: 11, alignItems: 'center' }}>
                  <span style={{ color: active ? 'var(--phosphor-hi)' : 'var(--phosphor-mid)' }}>{r.id}</span>
                  <span style={{ color: r.w >= tierMeta.floor && tierMeta.floor > 0 ? 'var(--amber)' : 'var(--grey-3)' }}>{r.w.toFixed(2)}</span>
                  <span style={{ color: 'var(--grey-2)', fontSize: 10 }}>{r.t}</span>
                  <span style={{ color: active ? 'var(--bone-1)' : 'var(--grey-3)', fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 13, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.content}</span>
                  <span style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>{r.flags.map(f => <span key={f} style={{ fontSize: 8, padding: '1px 5px', letterSpacing: '0.14em', border: `1px solid ${flagColor(f)}`, color: flagColor(f) }}>{f}</span>)}</span>
                </div>
              );
            })}
            {list.length === 0 && <div style={{ padding: 40, textAlign: 'center', fontFamily: 'var(--font-serif)', fontStyle: 'italic', color: 'var(--grey-2)' }}>No rows. The table is silent.</div>}
          </div>
        </div>

        {/* Detail panel */}
        <div style={{ borderLeft: '1px solid var(--line-1)', background: 'var(--ink-2)', overflow: 'auto', padding: 20 }}>
          {row ? (
            <>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
                <UI.PhLabel>◆ {row.id}</UI.PhLabel>
                <UI.Chip tone="cold">{tier}</UI.Chip>
              </div>
              <UI.Divider label="◆ CONTENT" />
              <p style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 14, color: 'var(--grey-4)', lineHeight: 1.6, margin: 0 }}>"{row.content}"</p>
              <UI.Divider label="◆ WEIGHT" />
              <div style={{ marginBottom: 10 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.18em', color: 'var(--grey-2)', marginBottom: 6 }}>
                  <span>w = <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>{weight.toFixed(2)}</span></span>
                  <span>FLOOR = {tierMeta.floor.toFixed(2)}</span>
                </div>
                <input type="range" min="0" max="1" step="0.01" value={weight} onChange={e => setWeight(parseFloat(e.target.value))} style={{ width: '100%', accentColor: 'var(--phosphor)' }} />
              </div>
              <UI.Divider label="◆ METADATA" />
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--grey-3)', lineHeight: 2, marginBottom: 12 }}>
                <div><span style={{ color: 'var(--grey-1)' }}>source  </span>{row.src}</div>
                <div><span style={{ color: 'var(--grey-1)' }}>created </span>{row.t}</div>
                <div><span style={{ color: 'var(--grey-1)' }}>tier    </span>{tier}</div>
              </div>
              {row.flags.length > 0 && (
                <>
                  <UI.Divider label="◆ AUDIT FLAGS" />
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginBottom: 14 }}>
                    {row.flags.map(f => (
                      <div key={f} style={{ border: `1px solid ${flagColor(f)}`, padding: '6px 10px' }}>
                        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.2em', color: flagColor(f), marginBottom: 2 }}>{f}</div>
                        <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 11, color: 'var(--grey-3)', lineHeight: 1.4 }}>{SYN_FLAG_DESC[f] || f}</div>
                      </div>
                    ))}
                  </div>
                </>
              )}
              <UI.Divider label="◆ ACTIONS" />
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                <UI.Button variant="ghost" glyph="▲">PROMOTE</UI.Button>
                <UI.Button variant="ghost" glyph="▼">DEMOTE</UI.Button>
                <UI.Button variant="ghost" glyph="◉">EXPIRE</UI.Button>
                <UI.Button variant="burn" onClick={() => setBurnConfirm(row.id)} glyph="✕" style={{ gridColumn: 'span 2' }}>BURN · HARD DELETE</UI.Button>
              </div>
            </>
          ) : <div style={{ padding: 30, textAlign: 'center', fontFamily: 'var(--font-serif)', fontStyle: 'italic', color: 'var(--grey-2)' }}>Select a row.</div>}
        </div>
      </div>

      {burnConfirm && (
        <div style={{ position: 'absolute', inset: 0, background: 'rgba(5,5,7,0.84)', backdropFilter: 'blur(8px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
          <div style={{ width: 480, border: '1px solid var(--burn)', background: 'var(--ink-3)', padding: 28, boxShadow: '0 0 30px rgba(255,90,78,0.25)' }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.3em', color: 'var(--burn)', textShadow: 'var(--burn-glow)', marginBottom: 10 }}>[ BURN · IRREVERSIBLE ]</div>
            <h2 style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 22, color: 'var(--bone-0)', margin: '0 0 8px' }}>Hard-delete {burnConfirm}.</h2>
            <p style={{ fontFamily: 'var(--font-serif)', fontSize: 14, color: 'var(--grey-3)', lineHeight: 1.6, margin: '0 0 18px' }}>The row will be unrecoverable. Burn bypasses the floor.</p>
            <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
              <UI.Button variant="ghost" onClick={() => setBurnConfirm(null)}>CANCEL</UI.Button>
              <UI.Button variant="burn" onClick={commitBurn} glyph="✕">BURN IT</UI.Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

window.SynapsePage = SynapsePage;
