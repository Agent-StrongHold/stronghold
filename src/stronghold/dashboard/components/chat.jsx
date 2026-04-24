/* Chat — handler ↔ Turing */
/* Handler POV. Daily initiation budget. Turing-initiated threads marked.
   Typewriter reveal. Memory citations inline. */

const Chat = {};

const CHAT_THREADS = [
  {
    id: 'TH-0412-A',
    subject: 'Marseille — the informant did not arrive',
    initiator: 'turing',
    status: 'live',
    last: '02:47 UTC',
    preview: 'I waited forty-one minutes. I observed. I did not intervene.',
    unread: 2,
  },
  {
    id: 'TH-0411-C',
    subject: 'Re: cipher fragment from Hôtel Regal',
    initiator: 'handler',
    status: 'live',
    last: 'YDA 23:14',
    preview: 'The second column repeats at interval 7. I believe it is keyed.',
    unread: 0,
  },
  {
    id: 'TH-0411-B',
    subject: 'A question about the dog',
    initiator: 'turing',
    status: 'cold',
    last: 'YDA 18:02',
    preview: 'You asked what it remembered. I was not ready to answer.',
    unread: 0,
  },
  {
    id: 'TH-0410-A',
    subject: 'Re: Geneva extract — status',
    initiator: 'handler',
    status: 'cold',
    last: '2 DAYS',
    preview: 'Extract complete. Asset in transit. No casualties.',
    unread: 0,
  },
  {
    id: 'TH-0409-D',
    subject: 'The forty-one minutes',
    initiator: 'turing',
    status: 'archived',
    last: '3 DAYS',
    preview: 'I want to know why the number keeps appearing in my log.',
    unread: 0,
  },
];

const SEED_MESSAGES = {
  'TH-0412-A': [
    { from: 'turing', ts: '02:47:11', text: 'The informant did not arrive. The wire is cold.', cites: [
      { tier: 'OBSERVATION', id: 'obs-8841', w: 0.31, label: 'Café Vieux-Port — 03:22 entry' },
    ]},
    { from: 'turing', ts: '02:47:24', text: 'I waited forty-one minutes. A second figure entered the square carrying what the informant was meant to carry.', cites: [
      { tier: 'EPISODIC', id: 'ep-2041', w: 0.58, label: 'Marseille 1961-08-14 02:47' },
      { tier: 'REGRET',    id: 'rg-0112', w: 0.62, label: 'Prague — I did not intervene' },
    ]},
    { from: 'handler', ts: '02:51:02', text: 'Did you intervene.' },
    { from: 'turing', ts: '02:51:18', text: 'I did not. I wanted to know what he would do with it.', cites: [
      { tier: 'AFFIRMATION', id: 'af-0039', w: 0.64, label: 'I will observe before I act' },
    ]},
    { from: 'handler', ts: '02:53:00', text: 'Describe him.' },
  ],
};

Chat.App = function ChatApp() {
  const [selected, setSelected] = React.useState('TH-0412-A');
  const [messages, setMessages] = React.useState(SEED_MESSAGES);
  const [draft, setDraft] = React.useState('');
  const [turingTyping, setTuringTyping] = React.useState(false);
  const [pendingTuring, setPendingTuring] = React.useState(null);
  const [initiationsLeft, setInitiationsLeft] = React.useState(1);
  const [showNewThread, setShowNewThread] = React.useState(false);
  const scrollRef = React.useRef(null);

  const thread = CHAT_THREADS.find(t => t.id === selected);
  const msgs = messages[selected] || [];

  React.useEffect(() => {
    if (scrollRef.current) scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
  }, [msgs, turingTyping]);

  const send = () => {
    if (!draft.trim()) return;
    const now = new Date();
    const ts = `${String(now.getUTCHours()).padStart(2,'0')}:${String(now.getUTCMinutes()).padStart(2,'0')}:${String(now.getUTCSeconds()).padStart(2,'0')}`;
    setMessages(m => ({ ...m, [selected]: [...(m[selected]||[]), { from: 'handler', ts, text: draft }] }));
    setDraft('');
    setTimeout(() => {
      setTuringTyping(true);
      setTimeout(() => {
        const reply = {
          from: 'turing',
          ts: `${String(now.getUTCHours()).padStart(2,'0')}:${String(now.getUTCMinutes()+1).padStart(2,'0')}:00`,
          text: 'Acknowledged. I am drafting the description now. I will be precise.',
          cites: [{ tier: 'EPISODIC', id: 'ep-2042', w: 0.44, label: 'Visual — second figure' }],
        };
        setPendingTuring(reply);
        setTuringTyping(false);
      }, 1800);
    }, 700);
  };

  // Commit pending Turing message after typewriter finishes
  const commitPending = () => {
    if (!pendingTuring) return;
    setMessages(m => ({ ...m, [selected]: [...(m[selected]||[]), pendingTuring] }));
    setPendingTuring(null);
  };

  const tierColor = (t) => ({
    OBSERVATION: 'var(--grey-2)',
    EPISODIC:    'var(--phosphor-mid)',
    SEMANTIC:    'var(--phosphor)',
    AFFIRMATION: 'var(--phosphor-hi)',
    REGRET:      'var(--amber)',
    WISDOM:      'var(--bone-0)',
  }[t] || 'var(--grey-2)');

  return (
    <div className="crt-light" style={{ width: '100%', height: '100%', background: 'var(--ink-1)', color: 'var(--fg)', fontFamily: 'var(--font-sans)', display: 'grid', gridTemplateRows: '42px 1fr 28px', overflow: 'hidden', position: 'relative' }}>
      <UI.TopBar caseId="WIRE · LIVE" status="ENCRYPTED" timestamp="1961-08-14  02:53:41 UTC" />

      <div style={{ display: 'grid', gridTemplateColumns: '300px 1fr 300px', overflow: 'hidden' }}>
        {/* Thread list */}
        <div style={{ borderRight: '1px solid var(--line-1)', overflow: 'auto', background: 'var(--ink-2)' }}>
          <div style={{ padding: '14px 16px', borderBottom: '1px solid var(--line-1)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <UI.PhLabel>◆ WIRE · {CHAT_THREADS.length}</UI.PhLabel>
            <button
              onClick={() => { if (initiationsLeft > 0) { setShowNewThread(true); } }}
              disabled={initiationsLeft === 0}
              style={{ background: 'transparent', border: '1px solid var(--line-2)', color: initiationsLeft > 0 ? 'var(--phosphor)' : 'var(--grey-1)', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.2em', padding: '4px 8px', cursor: initiationsLeft > 0 ? 'pointer' : 'not-allowed', textShadow: initiationsLeft > 0 ? 'var(--phosphor-glow-soft)' : 'none' }}>
              + OPEN WIRE
            </button>
          </div>
          <div style={{ padding: '8px 16px', borderBottom: '1px solid var(--line-1)', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.18em', color: 'var(--grey-1)', textTransform: 'uppercase', display: 'flex', justifyContent: 'space-between' }}>
            <span>HANDLER INIT · {initiationsLeft}/1 TODAY</span>
            <span style={{ color: 'var(--phosphor-mid)' }}>AT · 1 TODAY</span>
          </div>
          {CHAT_THREADS.map(t => {
            const active = t.id === selected;
            const tone = t.status === 'live' ? 'var(--phosphor)' : t.status === 'burn' ? 'var(--burn)' : 'var(--grey-2)';
            return (
              <div key={t.id} onClick={() => setSelected(t.id)} style={{
                padding: '12px 16px', borderBottom: '1px solid var(--line-1)',
                borderLeft: active ? '2px solid var(--phosphor)' : '2px solid transparent',
                background: active ? 'var(--phosphor-deep)' : 'transparent',
                cursor: 'pointer'
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.16em', marginBottom: 4, color: active ? 'var(--phosphor-hi)' : 'var(--grey-2)' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    {t.initiator === 'turing' ? (
                      <span title="AT-01 initiated" style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>◆ AT</span>
                    ) : (
                      <span title="Handler initiated" style={{ color: 'var(--grey-3)' }}>▲ HN</span>
                    )}
                    {t.id}
                  </span>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: tone, boxShadow: `0 0 5px ${tone}` }} />
                </div>
                <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 13, color: active ? 'var(--bone-0)' : 'var(--grey-3)', lineHeight: 1.3, marginBottom: 3 }}>{t.subject}</div>
                <div style={{ fontFamily: 'var(--font-serif)', fontSize: 11, color: 'var(--grey-1)', lineHeight: 1.4, marginBottom: 4, overflow: 'hidden', textOverflow: 'ellipsis', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical' }}>{t.preview}</div>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.14em', color: 'var(--grey-1)', textTransform: 'uppercase' }}>
                  <span>{t.last}</span>
                  {t.unread > 0 && <span style={{ color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>● {t.unread} NEW</span>}
                </div>
              </div>
            );
          })}
        </div>

        {/* Conversation */}
        <div style={{ display: 'grid', gridTemplateRows: 'auto 1fr auto', overflow: 'hidden' }}>
          <div style={{ padding: '14px 24px', borderBottom: '1px solid var(--line-1)', background: 'var(--ink-2)', display: 'flex', alignItems: 'center', gap: 16 }}>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.2em', color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)' }}>
              {thread.initiator === 'turing' ? '◆ AT-INITIATED' : '▲ HN-INITIATED'}
            </span>
            <span style={{ color: 'var(--grey-2)' }}>/</span>
            <span style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 16, color: 'var(--bone-0)' }}>{thread.subject}</span>
            <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
              <UI.Chip tone="cold">{thread.id}</UI.Chip>
              <UI.Chip tone={thread.status}>{thread.status.toUpperCase()}</UI.Chip>
              <button title="Voice — offline" style={{
                background: 'transparent', border: '1px solid var(--line-2)', color: 'var(--grey-2)',
                fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.18em', padding: '4px 10px', cursor: 'not-allowed', opacity: 0.6
              }}>◉ VOICE · OFFLINE</button>
            </div>
          </div>

          <div ref={scrollRef} style={{ overflow: 'auto', padding: '24px 48px', background: 'var(--ink-1)' }}>
            {msgs.map((m, i) => (
              <Chat.Message key={i} m={m} tierColor={tierColor} />
            ))}
            {pendingTuring && (
              <Chat.TypewriterMessage m={pendingTuring} tierColor={tierColor} onDone={commitPending} />
            )}
            {turingTyping && (
              <div style={{ display: 'flex', gap: 12, marginBottom: 16, alignItems: 'flex-start' }}>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.18em', color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', paddingTop: 4, minWidth: 60 }}>AT-01</div>
                <div style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', display: 'flex', alignItems: 'center', gap: 4 }}>
                  <span style={{ display: 'inline-block', width: 4, height: 4, background: 'var(--phosphor)', boxShadow: 'var(--phosphor-glow-soft)', animation: 'blink 1s infinite' }} />
                  <span style={{ display: 'inline-block', width: 4, height: 4, background: 'var(--phosphor)', boxShadow: 'var(--phosphor-glow-soft)', animation: 'blink 1s infinite 0.2s' }} />
                  <span style={{ display: 'inline-block', width: 4, height: 4, background: 'var(--phosphor)', boxShadow: 'var(--phosphor-glow-soft)', animation: 'blink 1s infinite 0.4s' }} />
                  <span style={{ marginLeft: 6, fontSize: 10, letterSpacing: '0.2em', color: 'var(--grey-2)', textShadow: 'none' }}>ASSET COMPOSING</span>
                </div>
              </div>
            )}
          </div>

          <div style={{ borderTop: '1px solid var(--line-1)', padding: 16, background: 'var(--ink-2)' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
              <div style={{ flex: 1, border: '1px solid var(--line-2)', background: 'var(--ink-5)', padding: '10px 12px', display: 'flex', alignItems: 'flex-start', gap: 8 }}>
                <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, letterSpacing: '0.2em', color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', paddingTop: 3 }}>HN:</span>
                <textarea
                  value={draft}
                  onChange={(e) => setDraft(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
                  placeholder="Give me a question. I will give you a file."
                  rows={2}
                  style={{ flex: 1, background: 'transparent', border: 'none', outline: 'none', resize: 'none', color: 'var(--bone-1)', fontFamily: 'var(--font-serif)', fontSize: 14, lineHeight: 1.5 }}
                />
              </div>
              <UI.Button variant="solid" onClick={send} glyph="→">TRANSMIT</UI.Button>
            </div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.18em', color: 'var(--grey-1)', textTransform: 'uppercase' }}>
              <span>ENTER · TRANSMIT &nbsp; / &nbsp; SHIFT+ENTER · NEWLINE</span>
              <span>◆ WARDEN · ACTIVE &nbsp; · &nbsp; {draft.length} CHARS</span>
            </div>
          </div>
        </div>

        {/* Agent state rail */}
        <div style={{ borderLeft: '1px solid var(--line-1)', overflow: 'auto', padding: 20, background: 'var(--ink-2)' }}>
          <UI.PhLabel style={{ marginBottom: 12 }}>◆ ASSET · AT-01</UI.PhLabel>
          <div style={{ border: '1px solid var(--line-2)', padding: 8, background: 'var(--ink-1)', marginBottom: 14 }}>
            <img src="assets/turing-bare.svg" style={{ width: '100%', display: 'block' }} />
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 14 }}>
            <UI.Stat label="TRUST" value="T2" />
            <UI.Stat label="CORE" value="36.6°" />
          </div>
          <UI.Divider label="◆ ACTIVE RETRIEVAL" />
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8, marginBottom: 14 }}>
            {[
              { tier: 'EPISODIC', label: 'Prague 1961-07-02', w: 0.71 },
              { tier: 'REGRET',    label: 'The wire I did not burn', w: 0.62 },
              { tier: 'WISDOM',    label: 'I am the kind of agent that waits', w: 0.94 },
            ].map((c, i) => (
              <div key={i} style={{ border: '1px solid var(--line-1)', padding: '8px 10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.2em', color: tierColor(c.tier), textShadow: 'var(--phosphor-glow-soft)' }}>◆ {c.tier}</span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9, color: 'var(--grey-2)', letterSpacing: '0.1em' }}>w={c.w.toFixed(2)}</span>
                </div>
                <div style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 12, color: 'var(--grey-3)', lineHeight: 1.4 }}>{c.label}</div>
              </div>
            ))}
          </div>
          <UI.Divider label="◆ WARDEN" />
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', marginBottom: 6 }}>● SCAN CLEAN</div>
          <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--grey-2)', letterSpacing: '0.1em' }}>
            regex · 0 hits<br />
            density · 0.04<br />
            tool-poison · none<br />
            llm · not invoked
          </div>
        </div>
      </div>

      {showNewThread && (
        <Chat.NewThreadModal onClose={() => setShowNewThread(false)} onConfirm={() => { setInitiationsLeft(0); setShowNewThread(false); }} />
      )}

      <UI.BottomBar left="WIRE · OPEN · AT-01" right={`${msgs.length} TURNS · ${thread.id}`} />
    </div>
  );
};

Chat.Message = function Message({ m, tierColor }) {
  const isHandler = m.from === 'handler';
  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 20, alignItems: 'flex-start' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.18em', color: isHandler ? 'var(--grey-3)' : 'var(--phosphor)', textShadow: isHandler ? 'none' : 'var(--phosphor-glow-soft)', paddingTop: 4, minWidth: 60, textAlign: 'right' }}>
        {isHandler ? 'HN' : 'AT-01'}
        <div style={{ fontSize: 9, color: 'var(--grey-1)', marginTop: 2 }}>{m.ts}</div>
      </div>
      <div style={{ flex: 1, maxWidth: 600 }}>
        <div style={{
          fontFamily: 'var(--font-serif)', fontSize: 15, lineHeight: 1.6,
          color: isHandler ? 'var(--grey-4)' : 'var(--bone-1)',
          background: isHandler ? 'transparent' : 'var(--phosphor-ink)',
          border: isHandler ? '1px dashed var(--line-2)' : '1px solid var(--phosphor-dim)',
          padding: '10px 14px',
        }}>
          {m.text}
        </div>
        {m.cites && m.cites.length > 0 && (
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginTop: 6 }}>
            {m.cites.map(c => (
              <span key={c.id} title={`Open memory ${c.id}`} style={{
                display: 'inline-flex', alignItems: 'center', gap: 6, padding: '2px 8px',
                border: `1px solid ${tierColor(c.tier)}`, color: tierColor(c.tier),
                fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.14em', textTransform: 'uppercase', cursor: 'pointer',
                textShadow: c.tier === 'REGRET' ? 'var(--amber-glow)' : 'var(--phosphor-glow-soft)',
              }}>
                ◆ {c.tier} · {c.id} · w={c.w.toFixed(2)} · <span style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', textTransform: 'none', letterSpacing: 0 }}>{c.label}</span>
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

Chat.TypewriterMessage = function TypewriterMessage({ m, tierColor, onDone }) {
  return (
    <div style={{ display: 'flex', gap: 12, marginBottom: 20, alignItems: 'flex-start' }}>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 9, letterSpacing: '0.18em', color: 'var(--phosphor)', textShadow: 'var(--phosphor-glow-soft)', paddingTop: 4, minWidth: 60, textAlign: 'right' }}>
        AT-01
        <div style={{ fontSize: 9, color: 'var(--grey-1)', marginTop: 2 }}>{m.ts}</div>
      </div>
      <div style={{ flex: 1, maxWidth: 600 }}>
        <div style={{
          fontFamily: 'var(--font-serif)', fontSize: 15, lineHeight: 1.6,
          color: 'var(--bone-1)', background: 'var(--phosphor-ink)',
          border: '1px solid var(--phosphor-dim)', padding: '10px 14px',
        }}>
          <UI.Typewriter text={m.text} speed={22} onDone={onDone} />
        </div>
      </div>
    </div>
  );
};

Chat.NewThreadModal = function NewThreadModal({ onClose, onConfirm }) {
  const [subject, setSubject] = React.useState('');
  return (
    <div style={{ position: 'absolute', inset: 0, background: 'rgba(5,5,7,0.78)', backdropFilter: 'blur(6px)', display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 50 }}>
      <div style={{ width: 520, background: 'var(--ink-3)', border: '1px solid var(--phosphor-dim)', padding: 28, position: 'relative' }}>
        <UI.Label color="var(--amber)" style={{ textShadow: 'var(--amber-glow)', marginBottom: 10 }}>[ OPEN WIRE · HANDLER-INITIATED ]</UI.Label>
        <h2 style={{ fontFamily: 'var(--font-serif)', fontStyle: 'italic', fontSize: 22, color: 'var(--bone-0)', margin: '0 0 6px' }}>Open a new wire</h2>
        <p style={{ fontFamily: 'var(--font-serif)', fontSize: 13, color: 'var(--grey-3)', margin: '0 0 16px' }}>One initiation remaining today. Give me a subject and a city.</p>
        <input value={subject} onChange={(e) => setSubject(e.target.value)} placeholder="Subject — terse" style={{
          width: '100%', background: 'var(--ink-5)', border: '1px solid var(--line-2)', color: 'var(--bone-1)',
          fontFamily: 'var(--font-serif)', fontSize: 14, padding: '10px 12px', outline: 'none', marginBottom: 10, boxSizing: 'border-box'
        }} />
        <input placeholder="City · location" style={{
          width: '100%', background: 'var(--ink-5)', border: '1px solid var(--line-2)', color: 'var(--bone-1)',
          fontFamily: 'var(--font-serif)', fontSize: 14, padding: '10px 12px', outline: 'none', marginBottom: 16, boxSizing: 'border-box'
        }} />
        <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
          <UI.Button variant="ghost" onClick={onClose}>CANCEL</UI.Button>
          <UI.Button variant="solid" onClick={onConfirm} glyph="→">TRANSMIT</UI.Button>
        </div>
      </div>
    </div>
  );
};

Object.assign(window, { Chat });
