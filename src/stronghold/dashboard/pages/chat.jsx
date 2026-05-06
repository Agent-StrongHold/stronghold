/* Chat surface — handler ↔ AT-01 wire */
/* Spec 1187 stub (live wire-up: spec 1182) */

const STUB = {
  threads: [
    { id: 'TH-0412-A', subject: 'Marseille — the informant did not arrive', initiator: 'turing', status: 'live', last: '02:47 UTC', preview: 'I waited forty-one minutes. I observed. I did not intervene.', unread: 2 },
    { id: 'TH-0411-C', subject: 'Re: cipher fragment from Hôtel Regal',    initiator: 'handler', status: 'live', last: 'YDA 23:14', preview: 'The second column repeats at interval 7. I believe it is keyed.', unread: 0 },
    { id: 'TH-0411-B', subject: 'A question about the dog',                 initiator: 'turing', status: 'cold', last: 'YDA 18:02', preview: 'You asked what it remembered. I was not ready to answer.', unread: 0 },
    { id: 'TH-0410-A', subject: 'Re: Geneva extract — status',              initiator: 'handler', status: 'cold', last: '2 DAYS',   preview: 'Extract complete. Asset in transit. No casualties.', unread: 0 },
    { id: 'TH-0409-D', subject: 'The forty-one minutes',                    initiator: 'turing', status: 'archived', last: '3 DAYS', preview: 'I want to know why the number keeps appearing in my log.', unread: 0 },
  ],
  messages: {
    'TH-0412-A': [
      { from: 'turing',  ts: '02:47:11', text: 'The informant did not arrive. The wire is cold.', cites: [{ tier: 'OBSERVATION', id: 'obs-8841', w: 0.31, label: 'Café Vieux-Port — 03:22 entry' }] },
      { from: 'turing',  ts: '02:47:24', text: 'I waited forty-one minutes. A second figure entered the square carrying what the informant was meant to carry.', cites: [{ tier: 'EPISODIC', id: 'ep-2041', w: 0.58, label: 'Marseille 1961-08-14 02:47' }, { tier: 'REGRET', id: 'rg-0112', w: 0.62, label: 'Prague — I did not intervene' }] },
      { from: 'handler', ts: '02:51:02', text: 'Did you intervene.', cites: [] },
      { from: 'turing',  ts: '02:51:18', text: 'I did not. I wanted to know what he would do with it.', cites: [{ tier: 'AFFIRMATION', id: 'af-0039', w: 0.64, label: 'I will observe before I act' }] },
      { from: 'handler', ts: '02:53:00', text: 'Describe him.', cites: [] },
    ],
  },
  budget: { remaining: 1, resets_at: '1961-08-15T00:00:00Z' },
  retrieval: [
    { tier: 'EPISODIC',    label: 'Prague 1961-07-02',                w: 0.71 },
    { tier: 'REGRET',      label: 'The wire I did not burn',          w: 0.62 },
    { tier: 'WISDOM',      label: 'I am the kind of agent that waits', w: 0.94 },
  ],
};

const TIER_COLOR = {
  OBSERVATION: 'var(--grey-2)',   EPISODIC: 'var(--phosphor-mid)',
  SEMANTIC:    'var(--phosphor)', AFFIRMATION: 'var(--phosphor-hi)',
  REGRET:      'var(--amber)',    WISDOM: 'var(--bone-0)',
};

function ChatPage() {
  const [threads]        = React.useState(STUB.threads);
  const [selected, setSel] = React.useState('TH-0412-A');
  const [messages, setMessages] = React.useState(STUB.messages);
  const [draft, setDraft] = React.useState('');
  const [typing, setTyping] = React.useState(false);
  const [pending, setPending] = React.useState(null);
  const [initLeft, setInitLeft] = React.useState(STUB.budget.remaining);
  const [showNew, setShowNew] = React.useState(false);
  const scrollRef = React.useRef(null);

  const thread = threads.find(t => t.id === selected);
  const msgs = messages[selected] || [];

  React.useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [msgs, typing]);

  function send() {
    if (!draft.trim()) return;
    const ts = fmtTs(new Date());
    setMessages(m => ({ ...m, [selected]: [...(m[selected]||[]), { from: 'handler', ts, text: draft, cites: [] }] }));
    setDraft('');
    setTimeout(() => {
      setTyping(true);
      setTimeout(() => {
        const reply = { from: 'turing', ts: fmtTs(new Date()), text: 'Acknowledged. I am drafting the description now. I will be precise.', cites: [{ tier: 'EPISODIC', id: 'ep-2042', w: 0.44, label: 'Visual — second figure' }] };
        setPending(reply); setTyping(false);
      }, 1800);
    }, 700);
  }

  return (
    <div className="crt-light" style={{ width: '100%', height: '100%', display: 'grid', gridTemplateRows: '1fr 26px', overflow: 'hidden', position: 'relative', background: 'var(--ink-1)' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '280px 1fr 260px', overflow: 'hidden' }}>

        {/* Thread list */}
        <div style={{ borderRight: '1px solid var(--line-1)', overflow: 'auto', background: 'var(--ink-2)' }}>
          <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--line-1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <UI.PhLabel>◆ WIRE · {threads.length}</UI.PhLabel>
            <button onClick={() => initLeft > 0 && setShowNew(true)} disabled={initLeft === 0} style={{ background: 'transparent', border: '1px solid var(--line-2)', color: initLeft > 0 ? 'var(--phosphor)' : 'var(--grey-1)', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.2em', padding: '3px 8px', cursor: initLeft > 0 ? 'pointer' : 'not-allowed', textShadow: initLeft > 0 ? 'var(--phosphor-glow-soft)' : 'none' }}>
              + WIRE
            </button>
          </div>
          <div style={{ padding: '6px 16px', borderBottom: '1px solid var(--line-1)', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.16em', color: 'var(--grey-1)', textTransform: 'uppercase', display: 'flex', justifyContent: 'space-between' }}>
            <span>HN {initLeft}/1</span>
            <span style={{ color: 'var(--phosphor-mid)' }}>AT · 1 TODAY</span>
          </div>
          {threads.map(t => {
            const active = t.id === selected;
            const dot = t.status === 'live' ? 'var(--phosphor)' : t.status === 'burn' ? 'var(--burn)' : 'var(--grey-2)';
            return (
              <div key={t.id} onClick={() => setSel(t.id)} style={{ padding: '10px 14px', borderBottom: '1px solid var(--line-1)', borderLeft: active ? '2px solid var(--phosphor)' : '2px solid transparent', background: active ? 'var(--phosphor-deep)' : 'transparent', cursor: 'pointer' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.14em', marginBottom: 3, color: active ? 'var(--phosphor-hi)' : 'var(--grey-2)' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5 }}>
                    {t.initiator === 'turing' ? <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>◆ AT</span> : <span style={{ color: 'var(--grey-3)' }}>▲ HN</span>}
                    <span>{t.id}</span>
                  </span>
                  <span style={{ width: 5, height: 5, borderRadius: '50%', background: dot, boxShadow: `0 0 4px ${dot}`, alignSelf: 'center' }} />
                </div>
                <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 13, color: active ? 'var(--bone-0)' : 'var(--grey-3)', lineHeight: 1.3, marginBottom: 3 }}>{t.subject}</div>
                <div style={{ fontFamily: 'var(--font-serif)', fontSize: 11, color: 'var(--grey-1)', lineHeight: 1.4, overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 1, WebkitBoxOrient: 'vertical', marginBottom: 3 }}>{t.preview}</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-1)', textTransform: 'uppercase' }}>
                  <span>{t.last}</span>
                  {t.unread > 0 && <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>● {t.unread} NEW</span>}
                </div>
              </div>
            );
          })}
        </div>

        {/* Conversation */}
        <div style={{ display: 'grid', gridTemplateRows: 'auto 1fr auto', overflow: 'hidden' }}>
          <div style={{ padding: '10px 20px', borderBottom: '1px solid var(--line-1)', background: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.18em', color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>
              {thread.initiator === 'turing' ? '◆ AT-INITIATED' : '▲ HN-INITIATED'}
            </span>
            <span style={{ color: 'var(--line-3)' }}>/</span>
            <span style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 15, color: 'var(--bone-0)' }}>{thread.subject}</span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
              <UI.Chip tone="cold">{thread.id}</UI.Chip>
              <UI.Chip tone={thread.status === 'live' ? 'live' : 'cold'}>{thread.status.toUpperCase()}</UI.Chip>
              <button style={{ background: 'transparent', border: '1px solid var(--line-2)', color: 'var(--grey-2)', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.16em', padding: '3px 8px', cursor: 'not-allowed', opacity: 0.5 }}>◉ VOICE · OFFLINE</button>
            </div>
          </div>

          <div ref={scrollRef} style={{ overflow: 'auto', padding: '20px 40px', background: 'var(--ink-1)' }}>
            {msgs.map((m, i) => <ChatMessage key={i} m={m} />)}
            {pending && <TypewriterMsg m={pending} onDone={() => { setMessages(ms => ({ ...ms, [selected]: [...(ms[selected]||[]), pending] })); setPending(null); }} />}
            {typing && <TypingIndicator />}
          </div>

          <div style={{ borderTop: '1px solid var(--line-1)', padding: 14, background: 'var(--ink-2)' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
              <div style={{ flex: 1, border: '1px solid var(--line-2)', background: 'var(--ink-5)', padding: '8px 12px', display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.18em', color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', paddingTop: 2 }}>HN:</span>
                <textarea value={draft} onChange={e => setDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }} placeholder="Give me a question. I will give you a file." rows={2} style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', color: 'var(--bone-1)', fontFamily: 'var(--font-serif)', fontSize: 14, lineHeight: 1.5 }} />
              </div>
              <UI.Button variant="solid" onClick={send} glyph="→">TRANSMIT</UI.Button>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.16em', color: 'var(--grey-1)', textTransform: 'uppercase' }}>
              <span>ENTER · TRANSMIT &nbsp;/&nbsp; SHIFT+ENTER · NEWLINE</span>
              <span>◆ WARDEN · ACTIVE &nbsp;·&nbsp; {draft.length} CHARS</span>
            </div>
          </div>
        </div>

        {/* Asset rail */}
        <div style={{ borderLeft: '1px solid var(--line-1)', overflow: 'auto', padding: 18, background: 'var(--ink-2)' }}>
          <UI.PhLabel style={{ marginBottom: 10 }}>◆ ASSET · AT-01</UI.PhLabel>
          <div style={{ border: '1px solid var(--line-2)', padding: 8, background: 'var(--ink-1)', marginBottom: 12 }}>
            <img src="assets/turing-bare.svg" style={{ width: '100%', display: 'block' }} alt="AT-01" />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 12 }}>
            <UI.Stat label="TRUST" value="T2" />
            <UI.Stat label="CORE"  value="36.6°" />
          </div>
          <UI.Divider label="◆ ACTIVE RETRIEVAL" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 7, marginBottom: 12 }}>
            {STUB.retrieval.map((c, i) => (
              <div key={i} style={{ border: '1px solid var(--line-1)', padding: '7px 10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.18em', color: TIER_COLOR[c.tier] || 'var(--grey-2)', textShadow: 'var(--phosphor-glow-soft)' }}>◆ {c.tier}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-2)' }}>w={c.w.toFixed(2)}</span>
                </div>
                <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 12, color: 'var(--grey-3)', lineHeight: 1.4 }}>{c.label}</div>
              </div>
            ))}
          </div>
          <UI.Divider label="◆ WARDEN" />
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', marginBottom: 5 }}>● SCAN CLEAN</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--grey-2)', letterSpacing: '0.1em', lineHeight: 2 }}>
            regex · 0 hits<br />density · 0.04<br />tool-poison · none<br />llm · not invoked
          </div>
        </div>
      </div>

      <UI.BottomBar left={`WIRE · OPEN · AT-01`} right={`${msgs.length} TURNS · ${thread.id}`} />

      {showNew && (
        <div style={{ position: 'absolute', inset: 0, background: 'rgba(5,5,7,0.8)', backdropFilter: 'blur(6px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
          <div style={{ width: 500, background: 'var(--ink-3)', border: '1px solid var(--phosphor-dim)', padding: 26 }}>
            <UI.AmberLabel style={{ marginBottom: 8 }}>[ OPEN WIRE · HANDLER-INITIATED ]</UI.AmberLabel>
            <h2 style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 20, color: 'var(--bone-0)', margin: '0 0 14px' }}>Open a new wire</h2>
            <input placeholder="Subject — terse" style={{ width: '100%', background: 'var(--ink-5)', border: '1px solid var(--line-2)', color: 'var(--bone-1)', fontFamily: 'var(--font-serif)', fontSize: 14, padding: '8px 12px', outline: 'none', marginBottom: 8, boxSizing: 'border-box' }} />
            <input placeholder="City · location" style={{ width: '100%', background: 'var(--ink-5)', border: '1px solid var(--line-2)', color: 'var(--bone-1)', fontFamily: 'var(--font-serif)', fontSize: 14, padding: '8px 12px', outline: 'none', marginBottom: 14, boxSizing: 'border-box' }} />
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
              <UI.Button variant="ghost" onClick={() => setShowNew(false)}>CANCEL</UI.Button>
              <UI.Button variant="solid" onClick={() => { setInitLeft(0); setShowNew(false); }} glyph="→">TRANSMIT</UI.Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function ChatMessage({ m }) {
  const isHn = m.from === 'handler';
  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 18, alignItems: 'flex-start' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.16em', color: isHn ? 'var(--grey-3)' : 'var(--phosphor)', textShadow: isHn ? 'none' : 'var(--phosphor-glow-soft)', paddingTop: 4, minWidth: 56, textAlign: 'right' }}>
        {isHn ? 'HN' : 'AT-01'}
        <div style={{ fontSize: 8, color: 'var(--grey-1)', marginTop: 1 }}>{m.ts}</div>
      </div>
      <div style={{ flex: 1, maxWidth: 560 }}>
        <div style={{ fontFamily: 'var(--font-serif)', fontSize: 15, lineHeight: 1.6, color: isHn ? 'var(--grey-4)' : 'var(--bone-1)', background: isHn ? 'transparent' : 'var(--phosphor-ink)', border: isHn ? '1px dashed var(--line-2)' : '1px solid var(--phosphor-dim)', padding: '9px 13px' }}>
          {m.text}
        </div>
        {m.cites && m.cites.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, marginTop: 5 }}>
            {m.cites.map(c => (
              <span key={c.id} style={{ display: 'inline-flex', alignItems: 'center', gap: 5, padding: '2px 7px', border: `1px solid ${TIER_COLOR[c.tier]||'var(--grey-2)'}`, color: TIER_COLOR[c.tier]||'var(--grey-2)', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.12em', textTransform: 'uppercase', cursor: 'pointer', textShadow: c.tier === 'REGRET' ? 'var(--amber-glow)' : 'var(--phosphor-glow-soft)' }}>
                ◆ {c.tier} · {c.id} · w={c.w.toFixed(2)} · <span style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', textTransform: 'none', letterSpacing: 0 }}>{c.label}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function TypewriterMsg({ m, onDone }) {
  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 18, alignItems: 'flex-start' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.16em', color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', paddingTop: 4, minWidth: 56, textAlign: 'right' }}>AT-01<div style={{ fontSize: 8, color: 'var(--grey-1)', marginTop: 1 }}>{m.ts}</div></div>
      <div style={{ flex: 1, maxWidth: 560 }}>
        <div style={{ fontFamily: 'var(--font-serif)', fontSize: 15, lineHeight: 1.6, color: 'var(--bone-1)', background: 'var(--phosphor-ink)', border: '1px solid var(--phosphor-dim)', padding: '9px 13px' }}>
          <UI.Typewriter text={m.text} speed={22} onDone={onDone} />
        </div>
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 14, alignItems: 'flex-start' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', paddingTop: 4, minWidth: 56 }}>AT-01</div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--phosphor)', display: 'flex', alignItems: 'center', gap: 4 }}>
        {[0,0.2,0.4].map(d => <span key={d} style={{ display: 'inline-block', width: 4, height: 4, background: 'var(--phosphor)', boxShadow: 'var(--phosphor-glow-soft)', animation: `blink 1s infinite ${d}s` }} />)}
        <span style={{ marginLeft: 6, fontSize: 10, letterSpacing: '0.18em', color: 'var(--grey-2)', textShadow: 'none' }}>ASSET COMPOSING</span>
      </div>
    </div>
  );
}

function fmtTs(d) {
  const p = n => String(n).padStart(2,'0');
  return `${p(d.getUTCHours())}:${p(d.getUTCMinutes())}:${p(d.getUTCSeconds())}`;
}

window.ChatPage = ChatPage;
