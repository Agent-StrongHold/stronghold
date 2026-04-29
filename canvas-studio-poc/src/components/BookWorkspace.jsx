import { useState, useEffect, useRef, useCallback } from "react";
import { decomposeBook } from "../lib/storyApi";
import { generateScenePlan } from "../lib/templateEngine";
import {
  renderStoryboardOverview,
  renderCharacterReferences,
  renderStyleSample,
  renderLayerDraft,
  renderLayerFinal,
  compositeScene,
} from "../lib/renderingPipeline";
import { refineScene } from "../lib/refinementPass";
import { saveState, loadState, clearState } from "../lib/persistence";

const S = {
  loading: "loading",
  reviewStory: "reviewStory",
  reviewStyle: "reviewStyle",
  reviewCharacter: "reviewCharacter",
  storyboard: "storyboard",
  pages: "pages",
  done: "done",
};

function buildPageLayers(sp) {
  const layers = [];
  layers.push({ id: `${sp.id}-bg`, name: "Background", type: "background", prompt: sp.bg_prompt, image_url: null, quality: "draft", z_index: 0, slot: "full_page" });
  if (sp.character_prompt) {
    layers.push({ id: `${sp.id}-char`, name: "Character", type: "character", prompt: sp.character_prompt, image_url: null, quality: "draft", z_index: 10, slot: sp.character_slot?.slot_bounds || sp.composition?.character_slot, pose: sp.character_slot?.pose });
  }
  for (let i = 0; i < (sp.prop_prompts || []).length; i++) {
    const p = sp.prop_prompts[i];
    layers.push({ id: `${sp.id}-prop${i}`, name: p.name, type: "prop", prompt: p.prompt, image_url: null, quality: "draft", z_index: 5 + i, placement: p.placement });
  }
  return layers;
}

function Editable({ value, onChange, multiline, style }) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || "");
  if (editing) {
    const commit = () => { onChange(draft); setEditing(false); };
    const Tag = multiline ? "textarea" : "input";
    return <Tag autoFocus value={draft} onChange={(e) => setDraft(e.target.value)} onBlur={commit} onKeyDown={(e) => { if (!multiline && e.key === "Enter") commit(); if (e.key === "Escape") { setDraft(value); setEditing(false); } }} style={{ width: "100%", fontSize: 12, padding: "2px 6px", minHeight: multiline ? 60 : undefined, ...style }} />;
  }
  return <span onClick={() => { setDraft(value || ""); setEditing(true); }} style={{ cursor: "pointer", ...style }}>{value || <em style={{ color: "var(--text-dim)" }}>click to edit</em>}</span>;
}

function VersionPicker({ versions, selectedIdx, onSelect, label }) {
  if (!versions || versions.length === 0) return null;
  return (
    <div style={{ display: "flex", gap: 4, flexWrap: "wrap", marginTop: 8 }}>
      {versions.map((v, i) => (
        <div key={i} onClick={() => onSelect(i)} style={{
          width: 48, height: 48, borderRadius: 4, overflow: "hidden", cursor: "pointer",
          border: i === selectedIdx ? "2px solid var(--phosphor)" : "2px solid var(--border)",
          opacity: i === selectedIdx ? 1 : 0.6,
        }}>
          <img src={v} alt={`${label} v${i + 1}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
        </div>
      ))}
    </div>
  );
}

export default function BookWorkspace({ bookSpec, onReset }) {
  const [step, setStep] = useState(S.loading);
  const [bookPlan, setBookPlan] = useState(null);
  const [rawDecomp, setRawDecomp] = useState(null);
  const [styleVersions, setStyleVersions] = useState([]);
  const [styleIdx, setStyleIdx] = useState(0);
  const [charVersions, setCharVersions] = useState([]);
  const [charIdx, setCharIdx] = useState(0);
  const [sbVersions, setSbVersions] = useState([]);
  const [sbIdx, setSbIdx] = useState(0);
  const [pageLayers, setPageLayers] = useState([]);
  const [currentScene, setCurrentScene] = useState(0);
  const [log, setLog] = useState([]);
  const [selectedLayer, setSelectedLayer] = useState(null);
  const [transformingLayer, setTransformingLayer] = useState(null);
  const [transformText, setTransformText] = useState("");
  const [generating, setGenerating] = useState("");
  const busyRef = useRef(false);
  const saveTimerRef = useRef(null);

  const addLog = useCallback((msg) => setLog((p) => [...p.slice(-100), msg]), []);

  const curStyle = styleVersions[styleIdx] || null;
  const curChar = charVersions[charIdx] || null;
  const curSb = sbVersions[sbIdx] || null;

  const scheduleSave = useCallback((overrides = {}) => {
    if (saveTimerRef.current) clearTimeout(saveTimerRef.current);
    saveTimerRef.current = setTimeout(() => {
      const title = bookSpec?.title || bookSpec?.premise?.slice(0, 30) || bookSpec?._storageKey;
      if (!title) return;
      saveState(title, { step, bookSpec, rawDecomp, bookPlan, styleVersions, styleIdx, charVersions, charIdx, sbVersions, sbIdx, pageLayers, currentScene, log: log.slice(-50), savedAt: new Date().toISOString(), ...overrides });
    }, 3000);
  }, [step, bookSpec, rawDecomp, bookPlan, styleVersions, styleIdx, charVersions, charIdx, sbVersions, sbIdx, pageLayers, currentScene, log]);

  const persist = scheduleSave;

  useEffect(() => { scheduleSave(); }, [step, styleVersions, charVersions, sbVersions, pageLayers, currentScene]);

  useEffect(() => {
    (async () => {
      const title = bookSpec?._storageKey || bookSpec?.title || bookSpec?.premise?.slice(0, 30);
      if (!title) { doDecompose(); return; }
      try {
        const saved = await loadState(title);
        if (saved && saved.step && saved.step !== S.loading) {
          if (saved.rawDecomp) setRawDecomp(saved.rawDecomp);
          if (saved.bookPlan) setBookPlan(saved.bookPlan);
          if (saved.styleVersions?.length) { setStyleVersions(saved.styleVersions); setStyleIdx(saved.styleIdx || 0); }
          else if (saved.styleSample) { setStyleVersions([saved.styleSample]); }
          if (saved.charVersions?.length) { setCharVersions(saved.charVersions); setCharIdx(saved.charIdx || 0); }
          else if (saved.characterSheet) { setCharVersions([saved.characterSheet]); }
          if (saved.sbVersions?.length) { setSbVersions(saved.sbVersions); setSbIdx(saved.sbIdx || 0); }
          else if (saved.storyboardImg) { setSbVersions([saved.storyboardImg]); }
          if (saved.pageLayers?.length) setPageLayers(saved.pageLayers);
          if (saved.currentScene != null) setCurrentScene(saved.currentScene);
          if (saved.log) setLog(saved.log);
          addLog("Resumed saved session.");
          setStep(saved.step);
          return;
        }
      } catch {}
      doDecompose();
    })();
  }, []);

  const doDecompose = async () => {
    if (busyRef.current) return;
    busyRef.current = true;
    setGenerating("Decomposing story...");
    try {
      addLog("Decomposing story...");
      const raw = await decomposeBook(bookSpec);
      setRawDecomp(raw);
      addLog(`"${raw.title}" — ${raw.scenes?.length || 0} scenes`);
      const plan = generateScenePlan(raw, bookSpec);
      setBookPlan(plan);
      addLog(`Plan ready: ${plan.scenes.length} scenes`);
      setStep(S.reviewStory);
    } catch (err) {
      addLog(`Decompose failed: ${err.message}`);
      setStep(S.reviewStory);
    } finally { busyRef.current = false; setGenerating(""); }
  };

  const genStyle = async () => {
    setGenerating("Generating style sample...");
    addLog("Generating style sample...");
    try {
      const img = await renderStyleSample(bookPlan.style_token, bookSpec.setting, (m) => { addLog(m); setGenerating(m); });
      setStyleVersions((prev) => { const n = [...prev, img]; setStyleIdx(n.length - 1); return n; });
      addLog("Style sample ready.");
    } catch (err) { addLog(`Style failed: ${err.message}`); }
    finally { setGenerating(""); }
  };

  const mainCharPhotos = bookSpec?.characters?.find((c) => c.role === "main character")?.reference_photos
    || bookSpec?.reference_photos || [];

  const genChar = async () => {
    setGenerating("Generating character sheet...");
    addLog("Generating character sheet...");
    try {
      const refs = mainCharPhotos.length > 0
        ? [...mainCharPhotos, ...(curStyle ? [curStyle] : [])]
        : curStyle ? [curStyle] : undefined;
      const img = await renderCharacterReferences(bookPlan.character_design, bookPlan.style_token, (m) => { addLog(m); setGenerating(m); }, refs);
      setCharVersions((prev) => { const n = [...prev, img]; setCharIdx(n.length - 1); return n; });
      addLog("Character sheet ready.");
    } catch (err) { addLog(`Character failed: ${err.message}`); }
    finally { setGenerating(""); }
  };

  const genStoryboard = async () => {
    setGenerating("Generating storyboard...");
    addLog("Generating storyboard overview...");
    try {
      const img = await renderStoryboardOverview(bookPlan, (m) => { addLog(m); setGenerating(m); });
      setSbVersions((prev) => { const n = [...prev, img]; setSbIdx(n.length - 1); return n; });
      addLog("Storyboard ready.");
    } catch (err) { addLog(`Storyboard failed: ${err.message}`); }
    finally { setGenerating(""); }
  };

  const startPages = async () => {
    const initial = bookPlan.scenes.map((scene) => ({
      scene_id: scene.id, title: scene.title, scene_type: scene.scene_type, page_text: scene.page_text,
      layers: buildPageLayers(scene), composite: null, approved: false,
    }));
    setPageLayers(initial);
    setCurrentScene(0);
    setStep(S.pages);
    addLog("Starting page drafts...");
    await genPageDrafts(0, initial);
  };

  const genPageDrafts = async (idx, layers) => {
    if (idx >= bookPlan.scenes.length || !layers[idx]) return;
    const page = layers[idx];
    setGenerating(`Page ${idx + 1}: generating layers...`);
    addLog(`Page ${idx + 1}: generating ${page.layers.length} draft layers...`);
    const updated = [...page.layers];
    for (let li = 0; li < updated.length; li++) {
      if (updated[li].image_url && updated[li].quality !== "draft") continue;
      const label = `${updated[li].name} (page ${idx + 1})`;
      setGenerating(label + "...");
      addLog(`  ${label}...`);
      try {
        const url = await renderLayerDraft(updated[li].prompt, (m) => { addLog(m); setGenerating(m); });
        updated[li] = { ...updated[li], image_url: url, quality: "draft" };
      } catch (err) { addLog(`  ${updated[li].name} failed: ${err.message}`); }
    }
    const up = { ...page, layers: updated };
    const comp = await compositeScene(up, bookPlan.page_dims);
    setPageLayers((prev) => { const n = [...prev]; n[idx] = { ...up, composite: comp }; return n; });
    addLog(`Page ${idx + 1} drafts done.`);
    setGenerating("");
  };

  const retryLayer = async (pi, li) => {
    const page = pageLayers[pi]; if (!page) return;
    const layer = page.layers[li];
    setGenerating(`Retrying "${layer.name}"...`);
    addLog(`Retrying "${layer.name}"...`);
    try {
      const url = await renderLayerDraft(layer.prompt, (m) => { addLog(m); setGenerating(m); });
      const history = [...(layer.history || []), layer.image_url].filter(Boolean);
      const layers = [...page.layers]; layers[li] = { ...layer, image_url: url, quality: "draft", history, historyIdx: history.length };
      const comp = await compositeScene({ ...page, layers }, bookPlan.page_dims);
      setPageLayers((prev) => { const n = [...prev]; n[pi] = { ...page, layers, composite: comp }; return n; });
    } catch (err) { addLog(`Retry failed: ${err.message}`); }
    finally { setGenerating(""); }
  };

  const upgradeLayer = async (pi, li) => {
    const page = pageLayers[pi]; if (!page) return;
    const layer = page.layers[li];
    setGenerating(`Upgrading "${layer.name}" to HQ...`);
    addLog(`Upgrading "${layer.name}" to final...`);
    try {
      const url = await renderLayerFinal(layer.prompt, (m) => { addLog(m); setGenerating(m); }, layer.image_url);
      const history = [...(layer.history || []), layer.image_url].filter(Boolean);
      const layers = [...page.layers]; layers[li] = { ...layer, image_url: url, quality: "final", history, historyIdx: history.length };
      const comp = await compositeScene({ ...page, layers }, bookPlan.page_dims);
      setPageLayers((prev) => { const n = [...prev]; n[pi] = { ...page, layers, composite: comp }; return n; });
    } catch (err) { addLog(`Upgrade failed: ${err.message}`); }
    finally { setGenerating(""); }
  };

  const applyTransform = async () => {
    if (!transformingLayer) return;
    const { page: pi, layer: li } = transformingLayer;
    const page = pageLayers[pi]; const layer = page.layers[li];
    setGenerating(`Transforming "${layer.name}"...`);
    addLog(`Transforming "${layer.name}"...`);
    const history = [...(layer.history || []), layer.image_url].filter(Boolean);
    const layers = [...page.layers]; layers[li] = { ...layer, prompt: transformText, quality: "draft", history, historyIdx: history.length };
    try {
      const url = await renderLayerDraft(transformText, (m) => { addLog(m); setGenerating(m); });
      layers[li] = { ...layers[li], image_url: url };
    } catch (err) { addLog(`Transform failed: ${err.message}`); }
    const comp = await compositeScene({ ...page, layers }, bookPlan.page_dims);
    setPageLayers((prev) => { const n = [...prev]; n[pi] = { ...page, layers, composite: comp }; return n; });
    setTransformingLayer(null); setTransformText("");
    setGenerating("");
  };

  const revertLayer = (pi, li, versionIdx) => {
    const page = pageLayers[pi]; if (!page) return;
    const layer = page.layers[li];
    const history = layer.history || [];
    if (versionIdx < 0 || versionIdx >= history.length) return;
    const url = history[versionIdx];
    const layers = [...page.layers];
    layers[li] = { ...layer, image_url: url, historyIdx: versionIdx };
    compositeScene({ ...page, layers }, bookPlan.page_dims).then((comp) => {
      setPageLayers((prev) => { const n = [...prev]; n[pi] = { ...page, layers, composite: comp }; return n; });
    });
  };

  const approvePage = async (pi) => {
    const page = pageLayers[pi];
    let up = { ...page, approved: true };
    if (page.layers.every((l) => l.quality === "final") && !page.refined) {
      addLog("Running refinement...");
      try { const r = await refineScene(up, bookPlan.style_token, (m) => addLog(m)); up = { ...r, approved: true }; } catch {}
    }
    setPageLayers((prev) => { const n = [...prev]; n[pi] = up; return n; });
    const next = pi + 1;
    if (next < bookPlan.scenes.length) {
      setCurrentScene(next);
      addLog(`Page ${pi + 1} approved. Next: page ${next + 1}.`);
      await genPageDrafts(next, pageLayers.map((p, i) => i === pi ? up : p));
    } else {
      setStep(S.done);
      addLog("All pages approved!");
    }
  };

  const updateBookPlan = (path, value) => {
    setBookPlan((prev) => {
      const n = { ...prev };
      const keys = path.split(".");
      let obj = n;
      for (let i = 0; i < keys.length - 1; i++) { obj[keys[i]] = { ...obj[keys[i]] }; obj = obj[keys[i]]; }
      obj[keys[keys.length - 1]] = value;
      return n;
    });
  };

  const updateScene = (idx, field, value) => {
    setRawDecomp((prev) => { const n = { ...prev }; n.scenes = [...n.scenes]; n.scenes[idx] = { ...n.scenes[idx], [field]: value }; return n; });
    if (bookPlan) {
      setBookPlan((prev) => { const n = { ...prev }; n.scenes = [...n.scenes]; if (n.scenes[idx]) n.scenes[idx] = { ...n.scenes[idx], [field]: value }; return n; });
    }
  };

  const handleReset = async () => {
    const title = bookSpec?._storageKey || bookSpec?.title || bookSpec?.premise?.slice(0, 30);
    if (title) await clearState(title);
    onReset();
  };

  const curPage = pageLayers[currentScene];

  const STEP_ORDER = [S.reviewStory, S.reviewStyle, S.reviewCharacter, S.storyboard, S.pages];
  const STEP_LABELS = { [S.reviewStory]: "Story", [S.reviewStyle]: "Style", [S.reviewCharacter]: "Character", [S.storyboard]: "Board", [S.pages]: "Pages" };
  const stepIdx = STEP_ORDER.indexOf(step);
  const reachedStep = Math.max(stepIdx, pageLayers.length > 0 ? 4 : stepIdx);

  const stepNav = (
    <div style={{ display: "flex", gap: 2, padding: "6px 12px", background: "var(--ink-1)", borderBottom: "1px solid var(--border)", flexShrink: 0 }}>
      {STEP_ORDER.map((s, i) => {
        const active = s === step;
        const reachable = i <= reachedStep;
        return (
          <button key={s} onClick={() => reachable && setStep(s)} disabled={!reachable}
            style={{ flex: 1, padding: "6px 4px", fontSize: 11, fontFamily: "var(--font)", textTransform: "uppercase", letterSpacing: 1,
              background: active ? "var(--phosphor-bg)" : "transparent", borderColor: active ? "var(--phosphor)" : "transparent",
              color: active ? "var(--phosphor)" : reachable ? "var(--text-dim)" : "var(--ink-5)", borderRadius: 3, cursor: reachable ? "pointer" : "default" }}>
            {STEP_LABELS[s]}
          </button>
        );
      })}
    </div>
  );

  const genOverlay = generating ? (
    <div style={{ position: "fixed", bottom: 0, left: 0, right: 0, zIndex: 200, background: "linear-gradient(to right, var(--ink-1), var(--ink-2))", borderTop: "2px solid var(--phosphor)", padding: "10px 24px", display: "flex", alignItems: "center", gap: 12 }}>
      <div className="status-dot generating" style={{ width: 12, height: 12, flexShrink: 0 }} />
      <div style={{ flex: 1 }}><div style={{ fontSize: 12, color: "var(--phosphor)", fontWeight: 600 }}>{generating}</div></div>
      <div style={{ fontSize: 10, color: "var(--text-dim)", fontFamily: "var(--font)" }}>generating...</div>
    </div>
  ) : null;

  const panel = (title, subtitle, content, actions) => (
    <div className="main-layout">
      {genOverlay}{stepNav}
      <div className="left-panel">
        <div className="panel-section"><h3>{title}</h3><div style={{ fontSize: 11, color: "var(--phosphor)" }}>{subtitle}</div></div>
        <div className="scroll-area" style={{ padding: 12 }}>{content}</div>
        <div className="panel-section" style={{ display: "flex", gap: 8 }}>{actions}</div>
      </div>
      <div className="viewport-area">
        <img src="" alt="" style={{ display: "none" }} />
      </div>
      <div className="right-panel"><div className="panel-section scroll-area"><h3>Log</h3>
        {log.slice(-20).map((m, i) => <div key={i} className="log-line">{m}</div>)}
      </div></div>
    </div>
  );

  // ── Loading ──────────────────────────────────────────────────────────────
  if (step === S.loading) {
    return <div className="main-layout">{genOverlay}<div className="viewport-area"><div className="empty-state">
      <div className="status-dot generating" style={{ width: 16, height: 16 }} />
      <div style={{ color: "var(--phosphor)", fontSize: 13 }}>Loading...</div>
    </div></div></div>;
  }

  // ── Step 1: Story ───────────────────────────────────────────────────────
  if (step === S.reviewStory && rawDecomp) {
    return (
      <div className="main-layout">
        {genOverlay}{stepNav}
        <div className="left-panel">
          <div className="panel-section"><h3>Story</h3><div style={{ fontSize: 11, color: "var(--phosphor)" }}>Click any field to edit</div></div>
          <div className="scroll-area">
            {rawDecomp.scenes?.map((s, i) => (
              <div key={i} style={{ padding: "8px 12px", borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
                  <span style={{ fontSize: 11, color: "var(--phosphor)", fontFamily: "var(--font)", width: 18 }}>{i + 1}</span>
                  <Editable value={s.title} onChange={(v) => updateScene(i, "title", v)} style={{ fontSize: 12, color: "var(--text)", flex: 1 }} />
                  <span style={{ color: "var(--text-dim)", fontSize: 9 }}>{s.type || s.scene_type}</span>
                </div>
                <Editable value={s.page_text} onChange={(v) => updateScene(i, "page_text", v)} multiline style={{ fontSize: 12, color: "var(--text)", marginTop: 2, lineHeight: 1.4 }} />
                <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 2, display: "flex", gap: 8 }}>
                  <span>pose: <Editable value={s.pose} onChange={(v) => updateScene(i, "pose", v)} style={{ fontSize: 10 }} /></span>
                  <span>comp: <Editable value={s.composition} onChange={(v) => updateScene(i, "composition", v)} style={{ fontSize: 10 }} /></span>
                </div>
              </div>
            ))}
          </div>
          <div className="panel-section" style={{ display: "flex", gap: 8 }}>
            <button style={{ flex: 1 }} onClick={handleReset}>Start Over</button>
            <button style={{ flex: 1 }} onClick={doDecompose}>Regenerate</button>
            <button className="primary" style={{ flex: 1 }} onClick={() => setStep(S.reviewStyle)}>Continue</button>
          </div>
        </div>
        <div className="viewport-area" style={{ overflow: "auto" }}>
          <div style={{ maxWidth: 600, margin: "0 auto", padding: 32 }}>
            <h2 style={{ color: "var(--text)", fontSize: 22, marginBottom: 8 }}>{rawDecomp.title}</h2>
            {rawDecomp.dedication && <div style={{ color: "var(--text-dim)", fontSize: 13, fontStyle: "italic", marginBottom: 16 }}>For {rawDecomp.dedication}</div>}
            <div style={{ background: "var(--ink-2)", borderRadius: 6, padding: 16 }}>
              {(rawDecomp.scenes || []).map((s, i) => (
                <div key={i} style={{ padding: "6px 0", borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                  <span style={{ fontSize: 11, color: "var(--phosphor)", fontFamily: "var(--font)" }}>{i + 1}.</span>{" "}
                  <span style={{ fontSize: 13 }}>{s.title}</span>
                  {s.page_text && <div style={{ fontSize: 12, color: "var(--text-dim)", marginTop: 2 }}>"{s.page_text}"</div>}
                </div>
              ))}
            </div>
          </div>
        </div>
        <div className="right-panel"><div className="panel-section scroll-area"><h3>Log</h3>
          {log.slice(-20).map((m, i) => <div key={i} className="log-line">{m}</div>)}
        </div></div>
      </div>
    );
  }

  // ── Step 2: Style ───────────────────────────────────────────────────────
  if (step === S.reviewStyle) {
    return (
      <div className="main-layout">
        {genOverlay}{stepNav}
        <div className="left-panel">
          <div className="panel-section"><h3>Style</h3><div style={{ fontSize: 11, color: "var(--phosphor)" }}>Click any field to edit</div></div>
          <div className="scroll-area" style={{ padding: 12 }}>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Art style</b><Editable value={bookPlan?.style_token?.technique} onChange={(v) => updateBookPlan("style_token.technique", v)} multiline style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Edge</b><Editable value={bookPlan?.style_token?.edge_softness} onChange={(v) => updateBookPlan("style_token.edge_softness", v)} style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Contrast</b><Editable value={bookPlan?.style_token?.contrast} onChange={(v) => updateBookPlan("style_token.contrast", v)} style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Detail</b><Editable value={bookPlan?.style_token?.detail_level} onChange={(v) => updateBookPlan("style_token.detail_level", v)} style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Mood</b><Editable value={bookSpec?.mood} onChange={(v) => { bookSpec.mood = v; }} style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Lighting</b><Editable value={bookSpec?.lighting} onChange={(v) => { bookSpec.lighting = v; }} style={{ fontSize: 12, color: "var(--text)" }} /></div>
            <div style={{ marginBottom: 10 }}>
              <b style={{ fontSize: 11, color: "var(--text-dim)" }}>Character design</b>
              <Editable value={bookPlan?.character_design} onChange={(v) => updateBookPlan("character_design", v)} multiline style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.4 }} />
            </div>
            {styleVersions.length > 1 && (
              <div><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Versions ({styleVersions.length})</b>
              <VersionPicker versions={styleVersions} selectedIdx={styleIdx} onSelect={setStyleIdx} label="Style" /></div>
            )}
          </div>
          <div className="panel-section" style={{ display: "flex", gap: 8 }}>
            <button style={{ flex: 1 }} onClick={genStyle}>Generate New</button>
            <button className="primary" style={{ flex: 1 }} onClick={() => setStep(S.reviewCharacter)}>Continue</button>
          </div>
        </div>
        <div className="viewport-area">
          {curStyle ? (
            <img src={curStyle} alt="Style sample" style={{ maxWidth: "90%", maxHeight: "90%", borderRadius: 6, boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }} />
          ) : (
            <div className="empty-state">
              <div style={{ color: "var(--text-dim)", fontSize: 13 }}>No style sample yet. Click "Generate New".</div>
            </div>
          )}
        </div>
        <div className="right-panel"><div className="panel-section scroll-area"><h3>Log</h3>
          {log.slice(-20).map((m, i) => <div key={i} className="log-line">{m}</div>)}
        </div></div>
      </div>
    );
  }

  // ── Step 3: Character ───────────────────────────────────────────────────
  if (step === S.reviewCharacter) {
    return (
      <div className="main-layout">
        {genOverlay}{stepNav}
        <div className="left-panel">
          <div className="panel-section"><h3>Character</h3><div style={{ fontSize: 11, color: "var(--phosphor)" }}>Click to edit description</div></div>
          <div className="scroll-area" style={{ padding: 12 }}>
            <b style={{ fontSize: 11, color: "var(--text-dim)" }}>Character description</b>
            <Editable value={bookPlan?.character_design} onChange={(v) => updateBookPlan("character_design", v)} multiline style={{ fontSize: 12, color: "var(--text)", lineHeight: 1.5, marginTop: 4 }} />
            {charVersions.length > 1 && (
              <div style={{ marginTop: 8 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Versions ({charVersions.length})</b>
              <VersionPicker versions={charVersions} selectedIdx={charIdx} onSelect={setCharIdx} label="Character" /></div>
            )}
          </div>
          <div className="panel-section" style={{ display: "flex", gap: 8 }}>
            <button style={{ flex: 1 }} onClick={genChar}>Generate New</button>
            <button className="primary" style={{ flex: 1 }} onClick={() => setStep(S.storyboard)}>Continue</button>
          </div>
        </div>
        <div className="viewport-area">
          {curChar ? (
            <img src={curChar} alt="Character sheet" style={{ maxWidth: "90%", maxHeight: "90%", borderRadius: 6, boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }} />
          ) : (
            <div className="empty-state"><div style={{ color: "var(--text-dim)", fontSize: 13 }}>No character sheet yet. Click "Generate New".</div></div>
          )}
        </div>
        <div className="right-panel"><div className="panel-section scroll-area"><h3>Log</h3>
          {log.slice(-20).map((m, i) => <div key={i} className="log-line">{m}</div>)}
        </div></div>
      </div>
    );
  }

  // ── Step 4: Storyboard ──────────────────────────────────────────────────
  if (step === S.storyboard) {
    return (
      <div className="main-layout">
        {genOverlay}{stepNav}
        <div className="left-panel">
          <div className="panel-section"><h3>Storyboard</h3><div style={{ fontSize: 11, color: "var(--phosphor)" }}>All scenes at a glance</div></div>
          <div className="scroll-area" style={{ padding: "8px 12px" }}>
            {bookPlan?.scenes.map((s, i) => (
              <div key={i} style={{ padding: "6px 0", borderTop: i > 0 ? "1px solid var(--border)" : "none" }}>
                <span style={{ fontSize: 11, color: "var(--phosphor)", fontFamily: "var(--font)" }}>{i + 1}. {s.title}</span>
                <div style={{ fontSize: 10, color: "var(--text-dim)" }}>{s.scene_type}</div>
              </div>
            ))}
            {sbVersions.length > 1 && (
              <div style={{ marginTop: 8 }}><b style={{ fontSize: 11, color: "var(--text-dim)" }}>Versions ({sbVersions.length})</b>
              <VersionPicker versions={sbVersions} selectedIdx={sbIdx} onSelect={setSbIdx} label="Storyboard" /></div>
            )}
          </div>
          <div className="panel-section" style={{ display: "flex", gap: 8 }}>
            <button style={{ flex: 1 }} onClick={genStoryboard}>Generate New</button>
            <button className="primary" style={{ flex: 1 }} onClick={startPages}>Start Pages</button>
          </div>
        </div>
        <div className="viewport-area">
          {curSb ? (
            <img src={curSb} alt="Storyboard" style={{ maxWidth: "90%", maxHeight: "90%", borderRadius: 6, boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }} />
          ) : (
            <div className="empty-state"><div style={{ color: "var(--text-dim)", fontSize: 13 }}>No storyboard yet. Click "Generate New".</div></div>
          )}
        </div>
        <div className="right-panel"><div className="panel-section scroll-area"><h3>Log</h3>
          {log.slice(-20).map((m, i) => <div key={i} className="log-line">{m}</div>)}
        </div></div>
      </div>
    );
  }

  // ── Step 5: Pages ───────────────────────────────────────────────────────
  if (step === S.pages || step === S.done) {
    return (
      <div className="main-layout">
        {genOverlay}{stepNav}
        <div className="left-panel">
          <div className="panel-section">
            <h3>Pages</h3>
            <div style={{ fontSize: 12, color: "var(--text)", marginBottom: 4 }}>{bookPlan?.title}</div>
            <div style={{ fontSize: 11, color: "var(--text-dim)" }}>{pageLayers.filter((p) => p.approved).length}/{pageLayers.length} approved</div>
            <div style={{ marginTop: 6, width: "100%", height: 3, background: "var(--ink-3)", borderRadius: 2, overflow: "hidden" }}>
              <div style={{ width: `${pageLayers.length ? (pageLayers.filter((p) => p.approved).length / pageLayers.length) * 100 : 0}%`, height: "100%", background: "var(--phosphor)", borderRadius: 2, transition: "width 0.3s" }} />
            </div>
          </div>
          <div className="scroll-area">
            {pageLayers.map((page, idx) => (
              <div key={idx} className={`layer-item ${idx === currentScene ? "selected" : ""}`} onClick={() => setCurrentScene(idx)} style={{ opacity: page.approved ? 0.7 : 1 }}>
                <div className="thumb" style={{ background: page.composite ? undefined : "var(--ink-3)" }}>
                  {page.composite ? <img src={page.composite} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} /> : <span>{idx + 1}</span>}
                </div>
                <div className="info">
                  <div className="name">{idx + 1}. {page.title}</div>
                  <div style={{ fontSize: 10, color: "var(--text-dim)", display: "flex", gap: 4 }}>
                    <span>{page.scene_type}</span>
                    {page.approved && <span style={{ color: "var(--phosphor)" }}>ok</span>}
                  </div>
                </div>
              </div>
            ))}
          </div>
          <div className="panel-section"><button style={{ width: "100%" }} onClick={handleReset}>Start Over</button></div>
        </div>
        <div className="viewport-area">
          {curPage?.composite ? (
            <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", padding: 24 }}>
              <img src={curPage.composite} alt={curPage.title} style={{ maxWidth: "100%", maxHeight: "100%", borderRadius: 6, boxShadow: "0 8px 32px rgba(0,0,0,0.5)" }} />
            </div>
          ) : (
            <div className="empty-state"><div className="status-dot generating" style={{ width: 16, height: 16 }} /><div style={{ color: "var(--phosphor)", fontSize: 13 }}>Rendering...</div></div>
          )}
          {curPage?.page_text && (
            <div style={{ position: "absolute", bottom: 24, left: "50%", transform: "translateX(-50%)", maxWidth: "80%", background: "rgba(0,0,0,0.7)", backdropFilter: "blur(8px)", padding: "12px 20px", borderRadius: 8, textAlign: "center", fontSize: 15, lineHeight: 1.6, color: "var(--text)" }}>{curPage.page_text}</div>
          )}
          <div style={{ position: "absolute", top: 12, right: 12, background: "var(--ink-2)", padding: "4px 10px", borderRadius: 4, fontSize: 11, fontFamily: "var(--font)", color: "var(--text-dim)" }}>Page {currentScene + 1} / {pageLayers.length}</div>
        </div>
        <div className="right-panel">
          <div className="panel-section scroll-area" style={{ flex: 1 }}>
            <h3>Layers</h3>
            {curPage ? (
              <div>
                <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{curPage.title}</div>
                <span style={{ fontSize: 10, padding: "2px 6px", borderRadius: 3, background: "var(--ink-3)", color: "var(--phosphor)", fontFamily: "var(--font)" }}>{curPage.scene_type}</span>
                <div style={{ marginTop: 12 }}>
                  {(curPage.layers || []).map((layer, li) => (
                    <div key={layer.id} style={{ display: "flex", alignItems: "center", gap: 8, padding: "6px 4px", background: selectedLayer === li ? "var(--phosphor-bg)" : "transparent", borderRadius: 4, marginBottom: 2, cursor: "pointer" }} onClick={() => setSelectedLayer(li)}>
                      <div style={{ width: 8, height: 8, borderRadius: "50%", flexShrink: 0, background: layer.quality === "final" ? "var(--phosphor)" : layer.image_url ? "var(--amber)" : "var(--ink-5)" }} />
                      <div style={{ flex: 1, minWidth: 0 }}><div style={{ fontSize: 12 }}>{layer.name}</div><div style={{ fontSize: 10, color: "var(--text-dim)" }}>{layer.quality}</div></div>
                      <div style={{ display: "flex", gap: 2 }}>
                        <button style={{ fontSize: 9, padding: "1px 4px" }} onClick={(e) => { e.stopPropagation(); retryLayer(currentScene, li); }}>Retry</button>
                        <button style={{ fontSize: 9, padding: "1px 4px" }} onClick={(e) => { e.stopPropagation(); setTransformingLayer({ page: currentScene, layer: li }); setTransformText(layer.prompt); }}>Edit</button>
                        {layer.quality !== "final" && layer.image_url && (
                          <button style={{ fontSize: 9, padding: "1px 4px", color: "var(--phosphor)" }} onClick={(e) => { e.stopPropagation(); upgradeLayer(currentScene, li); }}>HQ</button>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
                {selectedLayer != null && curPage.layers?.[selectedLayer] && (
                  <div style={{ marginTop: 8, padding: 8, background: "var(--ink-2)", borderRadius: 4 }}>
                    <div style={{ fontSize: 10, color: "var(--text-dim)", marginBottom: 4 }}>PROMPT</div>
                    <div style={{ fontSize: 11, lineHeight: 1.4, maxHeight: 80, overflow: "auto" }}>{curPage.layers[selectedLayer].prompt}</div>
                    {curPage.layers[selectedLayer].image_url && <img src={curPage.layers[selectedLayer].image_url} alt="" style={{ width: "100%", marginTop: 6, borderRadius: 4 }} />}
                    {(curPage.layers[selectedLayer].history?.length > 0) && (
                      <div style={{ marginTop: 6 }}>
                        <div style={{ fontSize: 10, color: "var(--text-dim)", marginBottom: 3 }}>VERSIONS ({curPage.layers[selectedLayer].history.length} prior)</div>
                        <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                          {curPage.layers[selectedLayer].history.map((hUrl, vi) => (
                            <div key={vi} onClick={() => revertLayer(currentScene, selectedLayer, vi)} style={{
                              width: 36, height: 36, borderRadius: 3, overflow: "hidden", cursor: "pointer",
                              border: "1px solid var(--border)", opacity: 0.7,
                            }}>
                              <img src={hUrl} alt={`v${vi}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </div>
                )}
                {transformingLayer && transformingLayer.page === currentScene && (
                  <div style={{ marginTop: 8, padding: 8, background: "var(--ink-2)", borderRadius: 4, border: "1px solid var(--phosphor)" }}>
                    <div style={{ fontSize: 10, color: "var(--phosphor)", marginBottom: 4 }}>EDIT PROMPT</div>
                    <textarea autoFocus value={transformText} onChange={(e) => setTransformText(e.target.value)} style={{ width: "100%", fontSize: 11, minHeight: 60, marginBottom: 6 }} />
                    <div style={{ display: "flex", gap: 4 }}>
                      <button className="primary" style={{ flex: 1, fontSize: 11 }} onClick={applyTransform}>Apply</button>
                      <button style={{ flex: 1, fontSize: 11 }} onClick={() => setTransformingLayer(null)}>Cancel</button>
                    </div>
                  </div>
                )}
                {!curPage.approved && (
                  <button className="primary" style={{ width: "100%", fontSize: 12, marginTop: 12 }} onClick={() => approvePage(currentScene)}>
                    {currentScene < pageLayers.length - 1 ? "Approve & Next" : "Approve Final Page"}
                  </button>
                )}
                {curPage.approved && <div style={{ marginTop: 8, fontSize: 11, color: "var(--phosphor)", textAlign: "center" }}>Approved</div>}
              </div>
            ) : <p style={{ color: "var(--text-dim)", fontSize: 13 }}>No page selected</p>}
          </div>
          <div className="panel-section" style={{ flexShrink: 0, maxHeight: "30vh", overflowY: "auto", borderTop: "2px solid var(--phosphor)" }}>
            <h3>Log</h3>
            {log.slice(-15).map((m, i) => <div key={i} className="log-line" style={{ color: i === log.slice(-15).length - 1 ? "var(--phosphor)" : undefined }}>{m}</div>)}
          </div>
        </div>
      </div>
    );
  }

  // fallback
  return (
    <div className="main-layout">
      {genOverlay}
      <div className="viewport-area"><div className="empty-state">
        <div style={{ color: "var(--text-dim)", fontSize: 13 }}>Unexpected state: {step}</div>
        <button className="primary" onClick={handleReset}>Start Over</button>
        <button onClick={() => { if (rawDecomp) setStep(S.reviewStory); else doDecompose(); }}>Retry</button>
      </div></div>
    </div>
  );
}
