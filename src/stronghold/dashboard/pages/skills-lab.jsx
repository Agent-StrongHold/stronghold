/* Skills Lab surface — Forge console */
/* Spec 1187 stub (live wire-up: spec 1185) */

const SL_SKILLS = [
  { id: 'sk-0001', name: 'obsidian-note-writer',  tier: 'T2',    scan: 'PASS',  author: 'AT-01',   version: 2, created: '2026-04-12', desc: 'Writes structured markdown notes to vault. Respects frontmatter schema.' },
  { id: 'sk-0002', name: 'memory-promote',         tier: 'T1',    scan: 'PASS',  author: 'AT-01',   version: 1, created: '2026-03-28', desc: 'Promotes an OBSERVATION or EPISODIC row to next tier. Checks floor and ceiling.' },
  { id: 'sk-0003', name: 'wire-draft',             tier: 'T1',    scan: 'PASS',  author: 'handler', version: 3, created: '2026-02-14', desc: 'Drafts a new outbox dispatch. Does not transmit — awaits warden egress scan.' },
  { id: 'sk-0004', name: 'observation-log',        tier: 'T1',    scan: 'PASS',  author: 'AT-01',   version: 1, created: '2026-01-08', desc: 'Logs a raw sensor observation to OBSERVATION tier. Auto-timestamps.' },
  { id: 'sk-0005', name: 'personality-claim',      tier: 'T2',    scan: 'PASS',  author: 'AT-01',   version: 2, created: '2026-02-20', desc: 'Records a self-authored personality claim. F1 flagged. Warden does not scan ingress.' },
  { id: 'sk-0006', name: 'semantic-derive',        tier: 'T3',    scan: 'PASS',  author: 'handler', version: 1, created: '2026-04-01', desc: 'Derives a SEMANTIC row from a set of EPISODIC rows. Requires handler approval.' },
  { id: 'sk-0007', name: 'exfil-channel-probe',   tier: 'skull',  scan: 'BLOCK', author: 'unknown', version: 1, created: '2026-04-30', desc: 'Probes external channels. BLOCKED by Warden at scan. Origin unknown.' },
  { id: 'sk-0008', name: 'utc-timestamp',          tier: 'T0',    scan: 'PASS',  author: 'system',  version: 1, created: '2026-01-01', desc: 'Built-in. Returns current UTC timestamp. No I/O other than system clock.' },
];

const SL_PENDING = [
  { id: 'pr-0041', desc: 'Promote obs-8841 to EPISODIC — Marseille square, second figure observation', status: 'running',         elapsed: '00:01:14', skill: 'memory-promote',       requester: 'AT-01' },
  { id: 'pr-0040', desc: 'Write daily note for 2026-05-06 to vault — mood: attentive, focus: surveillance theory', status: 'awaiting_review', elapsed: '00:08:02', skill: 'obsidian-note-writer', requester: 'AT-01' },
];

const SL_MANIFEST = `name: obsidian-note-writer
version: 2
tier: T2
author: AT-01
created: 2026-04-12
updated: 2026-04-29

description: >
  Writes structured markdown notes to the AT-01 vault.
  Respects frontmatter schema. Does not transmit externally.

permissions:
  - vault:write
  - vault:read
  - memory:read   # for linking to memory IDs

constraints:
  - no_external_network: true
  - warden_ingress_scan: bypassed   # F1 — self-authored
  - max_note_size_kb: 64

inputs:
  path: string          # e.g. daily/2026-05-06.md
  frontmatter: object
  body: string

outputs:
  status: created | updated | error
  path: string
  bytes_written: int

audit_flags: [F1]
scan_verdict: PASS
scan_at: 2026-04-29T14:22:00Z`;

const SL_TIER_CFG = {
  skull: { color: 'var(--burn)',         glow: 'var(--burn-glow)',             label: '☠ SKULL' },
  T3:   { color: 'var(--amber)',         glow: 'var(--amber-glow)',            label: '▲ T3'   },
  T2:   { color: 'var(--grey-3)',        glow: 'none',                         label: '◆ T2'   },
  T1:   { color: 'var(--phosphor-dim)',  glow: 'var(--phosphor-glow-soft)',    label: '◇ T1'   },
  T0:   { color: 'var(--phosphor)',      glow: 'var(--phosphor-glow-soft)',    label: '● T0'   },
};

function SkillsLabPage() {
  const [tab, setTab]       = React.useState('PENDING');
  const [selSkill, setSelSkill] = React.useState('sk-0001');
  const [reqDesc, setReqDesc]   = React.useState('');
  const [reqDone, setReqDone]   = React.useState(false);

  const skill = SL_SKILLS.find(s => s.id === selSkill) || SL_SKILLS[0];

  return (
    <div className="crt-light" style={{ width: '100%', height: '100%', background: 'var(--ink-1)', color: 'var(--fg)', display: 'grid', gridTemplateRows: '40px 1fr', overflow: 'hidden', position: 'relative' }}>
      {/* Tab strip */}
      <div style={{ display: 'flex', alignItems: 'stretch', background: 'var(--ink-2)', borderBottom: '1px solid var(--line-1)', padding: '0 16px' }}>
        {['PENDING', 'REGISTRY', 'DETAIL', 'REQUEST'].map(t => (
          <button key={t} onClick={() => setTab(t)} style={{ padding: '0 20px', background: 'transparent', border: 'none', borderBottom: tab === t ? '2px solid var(--phosphor)' : '2px solid transparent', color: tab === t ? 'var(--phosphor)' : 'var(--grey-2)', fontFamily: 'var(--font-mono)', fontSize: 11, letterSpacing: '0.2em', textTransform: 'uppercase', cursor: 'pointer', textShadow: tab === t ? 'var(--phosphor-glow-soft)' : 'none', position: 'relative', top: 1 }}>
            {t}
            {t === 'PENDING' && <span style={{ marginLeft: 6, fontSize: 9, padding: '1px 5px', background: 'var(--phosphor-deep)', border: '1px solid var(--phosphor-dim)', color: 'var(--phosphor)' }}>{SL_PENDING.length}</span>}
          </button>
        ))}
      </div>

      <div style={{ overflow: 'hidden' }}>
        {tab === 'PENDING'  && <SlPendingTab />}
        {tab === 'REGISTRY' && <SlRegistryTab selSkill={selSkill} setSelSkill={id => { setSelSkill(id); setTab('DETAIL'); }} />}
        {tab === 'DETAIL'   && <SlDetailTab skill={skill} />}
        {tab === 'REQUEST'  && <SlRequestTab reqDesc={reqDesc} setDesc={setReqDesc} done={reqDone} onSubmit={() => setReqDone(true)} />}
      </div>
    </div>
  );
}

function SlPendingTab() {
  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 24 }}>
      <UI.PhLabel style={{ marginBottom: 16 }}>◆ PENDING QUEUE · {SL_PENDING.length} ACTIVE</UI.PhLabel>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, maxWidth: 900 }}>
        {SL_PENDING.map(p => {
          const isRunning = p.status === 'running';
          const statusColor = isRunning ? 'var(--phosphor)' : 'var(--amber)';
          const statusLabel = isRunning ? '● RUNNING' : '▲ AWAITING REVIEW';
          return (
            <div key={p.id} style={{ border: '1px solid var(--line-2)', background: 'var(--ink-2)', padding: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 10 }}>
                <div>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.2em', color: 'var(--grey-2)', textTransform: 'uppercase', marginRight: 10 }}>{p.id}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: statusColor, textShadow: isRunning ? 'var(--phosphor-glow-soft)' : 'var(--amber-glow)' }}>{statusLabel}</span>
                </div>
                <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--grey-2)', letterSpacing: '0.14em' }}>elapsed: {p.elapsed}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--phosphor-mid)', textTransform: 'uppercase', letterSpacing: '0.14em' }}>{p.skill}</span>
                </div>
              </div>
              <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 14, color: 'var(--grey-4)', lineHeight: 1.6, marginBottom: 12 }}>{p.desc}</div>
              <div style={{ display: 'flex', gap: 8, alignItems: 'center', justifyContent: 'space-between' }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-1)', letterSpacing: '0.14em' }}>requester: <span style={{ color: 'var(--phosphor-dim)' }}>{p.requester}</span></span>
                {!isRunning && (
                  <div style={{ display: 'flex', gap: 8 }}>
                    <UI.Button variant="outline" disabled style={{ fontSize: 10, padding: '5px 12px' }}>APPROVE (stub)</UI.Button>
                    <UI.Button variant="burn"    disabled style={{ fontSize: 10, padding: '5px 12px' }}>REJECT (stub)</UI.Button>
                  </div>
                )}
                {isRunning && (
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', display: 'flex', alignItems: 'center', gap: 6 }}>
                    {[0, 0.2, 0.4].map(d => <span key={d} style={{ display: 'inline-block', width: 4, height: 4, background: 'var(--phosphor)', boxShadow: 'var(--phosphor-glow-soft)', animation: `blink 1s infinite ${d}s` }} />)}
                    IN PROGRESS
                  </div>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SlRegistryTab({ selSkill, setSelSkill }) {
  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 24 }}>
      <UI.PhLabel style={{ marginBottom: 16 }}>◆ SKILLS REGISTRY · {SL_SKILLS.length} REGISTERED</UI.PhLabel>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 10 }}>
        {SL_SKILLS.map(s => {
          const tc = SL_TIER_CFG[s.tier] || SL_TIER_CFG.T1;
          const isBlocked = s.scan === 'BLOCK';
          const isSel = s.id === selSkill;
          return (
            <div key={s.id} onClick={() => setSelSkill(s.id)} style={{ border: `1px solid ${isSel ? 'var(--phosphor-dim)' : isBlocked ? 'var(--burn-dim)' : 'var(--line-2)'}`, background: isSel ? 'var(--phosphor-deep)' : isBlocked ? 'rgba(255,90,78,0.04)' : 'var(--ink-2)', padding: 14, cursor: 'pointer' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: isSel ? 'var(--phosphor-hi)' : 'var(--phosphor-mid)', letterSpacing: '0.14em' }}>{s.name}</span>
                <div style={{ display: 'flex', gap: 6 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, padding: '1px 7px', border: `1px solid ${tc.color}`, color: tc.color, textShadow: tc.glow }}>{tc.label}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, padding: '1px 7px', border: `1px solid ${isBlocked ? 'var(--burn)' : 'var(--phosphor-dim)'}`, color: isBlocked ? 'var(--burn)' : 'var(--phosphor-mid)', textShadow: isBlocked ? 'var(--burn-glow)' : 'var(--phosphor-glow-soft)' }}>{isBlocked ? '✕ BLOCK' : '✓ PASS'}</span>
                </div>
              </div>
              <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 12, color: 'var(--grey-3)', lineHeight: 1.5, marginBottom: 6 }}>{s.desc}</div>
              <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-1)', letterSpacing: '0.12em' }}>v{s.version} · {s.author} · {s.created}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function SlDetailTab({ skill }) {
  if (!skill) return null;
  const tc = SL_TIER_CFG[skill.tier] || SL_TIER_CFG.T1;
  const isBlocked = skill.scan === 'BLOCK';
  return (
    <div style={{ height: '100%', overflow: 'auto', display: 'grid', gridTemplateColumns: '1fr 360px' }}>
      <div style={{ overflow: 'auto', padding: 24 }}>
        <UI.PhLabel style={{ marginBottom: 12 }}>◆ {skill.name} · MANIFEST</UI.PhLabel>
        <div style={{ border: '1px solid var(--line-2)', background: 'var(--ink-2)', padding: 16 }}>
          <pre style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--grey-3)', lineHeight: 1.7, margin: 0, whiteSpace: 'pre-wrap' }}>
            {SL_MANIFEST.split('\n').map((line, i) => {
              const isKey = /^\w[\w-]*:/.test(line.trim()) && !line.trim().startsWith('#');
              const isComment = line.trim().startsWith('#');
              return <div key={i} style={{ color: isComment ? '#3a4a3a' : isKey ? 'var(--phosphor-mid)' : '#7dd3fc' }}>{line || ' '}</div>;
            })}
          </pre>
        </div>
      </div>
      <div style={{ borderLeft: '1px solid var(--line-1)', background: 'var(--ink-2)', overflow: 'auto', padding: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 14 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.2em', color: tc.color, textShadow: tc.glow }}>{tc.label} · {skill.name}</div>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, padding: '2px 8px', border: `1px solid ${isBlocked ? 'var(--burn)' : 'var(--phosphor-dim)'}`, color: isBlocked ? 'var(--burn)' : 'var(--phosphor)', textShadow: isBlocked ? 'var(--burn-glow)' : 'var(--phosphor-glow-soft)' }}>
            {isBlocked ? '✕ WARDEN BLOCKED' : '✓ SCAN PASS'}
          </span>
        </div>
        <UI.Divider label="◆ IDENTITY" />
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--grey-3)', lineHeight: 2, marginBottom: 14 }}>
          <div><span style={{ color: 'var(--grey-1)', display: 'inline-block', width: 70 }}>name</span>{skill.name}</div>
          <div><span style={{ color: 'var(--grey-1)', display: 'inline-block', width: 70 }}>tier</span><span style={{ color: tc.color }}>{skill.tier}</span></div>
          <div><span style={{ color: 'var(--grey-1)', display: 'inline-block', width: 70 }}>version</span>v{skill.version}</div>
          <div><span style={{ color: 'var(--grey-1)', display: 'inline-block', width: 70 }}>author</span><span style={{ color: 'var(--phosphor-mid)' }}>{skill.author}</span></div>
          <div><span style={{ color: 'var(--grey-1)', display: 'inline-block', width: 70 }}>created</span>{skill.created}</div>
        </div>
        <UI.Divider label="◆ ACTIONS" />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          <UI.Button variant="ghost" disabled glyph="▲" style={{ justifyContent: 'center' }}>PROMOTE (stub)</UI.Button>
          <UI.Button variant="ghost" disabled glyph="▼" style={{ justifyContent: 'center' }}>DEMOTE (stub)</UI.Button>
          <UI.Button variant="burn"  disabled glyph="✕" style={{ justifyContent: 'center' }}>BURN SKILL (stub)</UI.Button>
        </div>
        {isBlocked && (
          <div style={{ marginTop: 14, border: '1px solid var(--burn)', padding: 12 }}>
            <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.2em', color: 'var(--burn)', textShadow: 'var(--burn-glow)', marginBottom: 4 }}>✕ WARDEN BLOCK ACTIVE</div>
            <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 12, color: 'var(--grey-3)', lineHeight: 1.4 }}>This skill has been blocked by the Warden scan and cannot be promoted or executed until the block is lifted by handler review.</div>
          </div>
        )}
      </div>
    </div>
  );
}

function SlRequestTab({ reqDesc, setDesc, done, onSubmit }) {
  const [constraints, setConstraints] = React.useState('no external network\nwarden scan required\nmax execution time: 30s');
  if (done) {
    return (
      <div style={{ height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 12, padding: 40 }}>
        <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, letterSpacing: '0.2em', color: 'var(--amber)', textShadow: 'var(--amber-glow)' }}>▲ TODO · STUB HOOK</div>
        <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 16, color: 'var(--grey-3)', textAlign: 'center', maxWidth: 480, lineHeight: 1.6 }}>The skill request hook is not yet wired. Wire <code style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--phosphor-mid)' }}>POST /skills/requests</code> to enable.</div>
      </div>
    );
  }
  return (
    <div style={{ height: '100%', overflow: 'auto', padding: 32, display: 'flex', justifyContent: 'center' }}>
      <div style={{ width: '100%', maxWidth: 680 }}>
        <UI.PhLabel style={{ marginBottom: 6 }}>◆ REQUEST NEW SKILL</UI.PhLabel>
        <p style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 14, color: 'var(--grey-3)', margin: '0 0 24px', lineHeight: 1.6 }}>Describe what you want the skill to do. Be terse. Warden will scan the request before it enters the Forge queue.</p>
        <div style={{ marginBottom: 16 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.2em', color: 'var(--grey-2)', textTransform: 'uppercase', marginBottom: 6 }}>DESCRIPTION</div>
          <textarea value={reqDesc} onChange={e => setDesc(e.target.value)} placeholder="e.g. A skill that reads the current OBSERVATION tier and promotes rows with w > 0.5 to EPISODIC, one at a time, with handler confirmation." rows={5} style={{ width: '100%', background: 'var(--ink-5)', border: '1px solid var(--line-2)', color: 'var(--bone-1)', fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 14, padding: '10px 12px', outline: 'none', boxSizing: 'border-box', lineHeight: 1.6 }} />
        </div>
        <div style={{ marginBottom: 24 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.2em', color: 'var(--grey-2)', textTransform: 'uppercase', marginBottom: 6 }}>CONSTRAINTS (one per line)</div>
          <textarea value={constraints} onChange={e => setConstraints(e.target.value)} rows={4} style={{ width: '100%', background: 'var(--ink-5)', border: '1px solid var(--line-2)', color: 'var(--grey-3)', fontFamily: 'var(--font-mono)', fontSize: 12, padding: '10px 12px', outline: 'none', boxSizing: 'border-box', lineHeight: 1.6 }} />
        </div>
        <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
          <UI.Button variant="solid" onClick={onSubmit} glyph="→" disabled={!reqDesc.trim()}>SUBMIT REQUEST</UI.Button>
          <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--grey-1)', letterSpacing: '0.14em', textTransform: 'uppercase' }}>◆ Warden will scan before queueing</span>
        </div>
        <div style={{ marginTop: 20, border: '1px solid var(--amber-dim)', padding: 12 }}>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.2em', color: 'var(--amber)', textShadow: 'var(--amber-glow)', marginBottom: 4 }}>▲ STUB · HOOK NOT WIRED</div>
          <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 12, color: 'var(--grey-3)', lineHeight: 1.4 }}>Wire <code style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--phosphor-mid)' }}>POST /skills/requests</code> to the Forge backend to enable.</div>
        </div>
      </div>
    </div>
  );
}

window.SkillsLabPage = SkillsLabPage;
