import { useState, useEffect } from "react";
import { listTemplates, saveTemplate, deleteTemplate } from "../lib/templates";

const CHAR_FIELDS = [
  { key: "name", label: "Name", placeholder: "e.g. Emma" },
  { key: "age", label: "Age range", type: "select", options: ["3-4", "5-6", "7-8", "9-10"] },
  { key: "pronouns", label: "Pronouns", type: "select", options: ["she/her", "he/him", "they/them"] },
  { key: "nickname", label: "Nickname (optional)", placeholder: "e.g. Em" },
  { key: "hair", label: "Hair", placeholder: "e.g. curly brown, shoulder length" },
  { key: "skin_tone", label: "Skin tone", placeholder: "e.g. warm brown, fair with freckles" },
  { key: "eye_color", label: "Eye color", placeholder: "e.g. hazel, dark brown" },
  { key: "face_shape", label: "Face shape", type: "select", options: ["round", "oval", "heart-shaped", "square"] },
  { key: "signature_features", label: "Distinctive features", placeholder: "e.g. gap tooth, dimple, glasses" },
  { key: "build", label: "Build", placeholder: "e.g. tall for age, petite" },
  { key: "role", label: "Role in story", type: "select", options: ["main character", "best friend / sidekick", "sibling", "pet / companion", "other"] },
];

const STEPS = [
  { key: "characters", title: "Who is in the story?", helper: "Add your recurring characters. Save them as a template to reuse." },
  { key: "style", title: "Illustration style", helper: "Sets the visual look for the entire book",
    fields: [
      { key: "art_style", label: "Art style", type: "select", options: ["Warm watercolor childrens book", "Soft pastel digital illustration", "Bold gouache with visible brushstrokes", "Gentle colored pencil sketch", "Clean flat vector illustration", "Whimsical ink and wash", "Dreamy airbrushed fantasy"] },
      { key: "mood", label: "Overall mood", type: "select", options: ["warm and cozy", "bright and adventurous", "dreamy and magical", "playful and silly", "calm and gentle", "exciting and energetic"] },
      { key: "palette_preference", label: "Color preference", type: "select", options: ["warm earth tones (browns, oranges, golds)", "soft pastels (pinks, lavenders, mint)", "bright and saturated (reds, blues, greens)", "cool ocean tones (teals, blues, silver)", "nature greens and woodland tones", "let the AI choose"] },
      { key: "lighting", label: "Lighting feel", type: "select", options: ["soft golden hour warmth", "bright cheerful daylight", "moonlit and sparkly", "dappled forest light", "cozy lamplight glow", "natural and neutral"] },
    ],
  },
  { key: "story", title: "What is the story?", helper: "Describe the adventure",
    fields: [
      { key: "premise", label: "Story premise (1-3 sentences)", type: "textarea", required: true, placeholder: "e.g. A girl discovers a hidden door in her grandmother's garden..." },
      { key: "setting", label: "Where does it take place?", placeholder: "e.g. A magical forest, a castle in the clouds" },
      { key: "lessons", label: "Lesson or theme (optional)", placeholder: "e.g. Courage, friendship, it's okay to be different" },
      { key: "ending", label: "How should it end?", type: "select", options: ["happy and triumphant", "cozy and heartwarming", "surprise twist", "open-ended", "let the AI decide"] },
    ],
  },
  { key: "book", title: "Book details", helper: "Final settings",
    fields: [
      { key: "page_count", label: "Pages/spreads", type: "select", options: ["8 (short)", "12 (standard)", "16 (long)", "20 (epic)"] },
      { key: "orientation", label: "Orientation", type: "select", options: ["landscape (wide)", "portrait (tall)", "square"] },
      { key: "title", label: "Book title (or let AI create one)", placeholder: "e.g. Emma and the Whispering Woods" },
      { key: "dedication", label: "Dedication (optional)", placeholder: "e.g. For Emma, who always looks for magic" },
    ],
  },
];

function CharacterCard({ char, onChange, onRemove, index }) {
  const [expanded, setExpanded] = useState(index === 0);

  const handlePhotoUpload = (e) => {
    const files = Array.from(e.target.files || []);
    if (files.length === 0) return;
    const maxPhotos = 5;
    const currentPhotos = char.reference_photos || [];
    const toProcess = files.slice(0, maxPhotos - currentPhotos.length);
    let loaded = 0;
    const newPhotos = [];
    toProcess.forEach((file) => {
      const reader = new FileReader();
      reader.onload = (ev) => {
        newPhotos.push(ev.target.result);
        loaded++;
        if (loaded === toProcess.length) {
          onChange("reference_photos", [...currentPhotos, ...newPhotos]);
        }
      };
      reader.readAsDataURL(file);
    });
  };

  const removePhoto = (photoIdx) => {
    const photos = [...(char.reference_photos || [])];
    photos.splice(photoIdx, 1);
    onChange("reference_photos", photos);
  };

  return (
    <div style={{ background: "var(--ink-1)", border: "1px solid var(--border)", borderRadius: 6, marginBottom: 8 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "8px 12px", cursor: "pointer" }} onClick={() => setExpanded(!expanded)}>
        <div style={{ width: 28, height: 28, borderRadius: "50%", background: "var(--ink-3)", display: "flex", alignItems: "center", justifyContent: "center", fontSize: 12, color: "var(--phosphor)", fontFamily: "var(--font)", flexShrink: 0, overflow: "hidden" }}>
          {(char.reference_photos || []).length > 0 ? (
            <img src={char.reference_photos[0]} alt="" style={{ width: "100%", height: "100%", objectFit: "cover" }} />
          ) : (
            index + 1
          )}
        </div>
        <div style={{ flex: 1, fontSize: 14, fontWeight: 600 }}>{char.name || `Character ${index + 1}`}</div>
        <span style={{ fontSize: 10, color: "var(--text-dim)" }}>{char.role || "main character"}</span>
        {(char.reference_photos || []).length > 0 && <span style={{ fontSize: 10, color: "var(--phosphor)" }}>{char.reference_photos.length} photo{char.reference_photos.length > 1 ? "s" : ""}</span>}
        <button style={{ fontSize: 10, padding: "2px 8px", border: "none", background: "transparent", color: "var(--text-dim)" }} onClick={(e) => { e.stopPropagation(); setExpanded(!expanded); }}>{expanded ? "collapse" : "expand"}</button>
        {onRemove && <button className="danger" style={{ fontSize: 10, padding: "2px 8px" }} onClick={(e) => { e.stopPropagation(); onRemove(); }}>Remove</button>}
      </div>
      {expanded && (
        <div style={{ padding: "4px 12px 12px" }}>
          <div style={{ marginBottom: 10, padding: 8, background: "var(--ink-2)", borderRadius: 4 }}>
            <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 4 }}>Reference photos (3-5 photos of the child for personalized character)</div>
            <div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center" }}>
              {(char.reference_photos || []).map((photo, pi) => (
                <div key={pi} style={{ width: 56, height: 56, borderRadius: 4, overflow: "hidden", position: "relative", border: "1px solid var(--border)" }}>
                  <img src={photo} alt={`ref ${pi + 1}`} style={{ width: "100%", height: "100%", objectFit: "cover" }} />
                  <button onClick={() => removePhoto(pi)} style={{ position: "absolute", top: 1, right: 1, width: 14, height: 14, fontSize: 8, padding: 0, background: "rgba(0,0,0,0.7)", color: "var(--text)", border: "none", borderRadius: 2, cursor: "pointer", lineHeight: "14px" }}>x</button>
                </div>
              ))}
              {(char.reference_photos || []).length < 5 && (
                <label style={{ width: 56, height: 56, borderRadius: 4, border: "2px dashed var(--border)", display: "flex", alignItems: "center", justifyContent: "center", cursor: "pointer", fontSize: 18, color: "var(--text-dim)" }}>
                  +
                  <input type="file" accept="image/*" multiple onChange={handlePhotoUpload} style={{ display: "none" }} />
                </label>
              )}
            </div>
            <div style={{ fontSize: 10, color: "var(--text-dim)", marginTop: 4 }}>
              {(char.reference_photos || []).length === 0
                ? "No photos — character will be text-described only"
                : `${(char.reference_photos || []).length}/5 uploaded`}
            </div>
          </div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
            {CHAR_FIELDS.map((f) => (
              <div key={f.key} style={{ gridColumn: f.type === "select" || f.key === "name" ? "span 1" : "span 2" }}>
                <label style={{ display: "block", fontSize: 11, color: "var(--text-dim)", marginBottom: 2 }}>{f.label}</label>
                {f.type === "select" ? (
                  <select value={char[f.key] || ""} onChange={(e) => onChange(f.key, e.target.value)} style={{ width: "100%", fontSize: 12 }}>
                    <option value="">Choose...</option>
                    {f.options.map((o) => <option key={o} value={o}>{o}</option>)}
                  </select>
                ) : (
                  <input value={char[f.key] || ""} onChange={(e) => onChange(f.key, e.target.value)} placeholder={f.placeholder} style={{ width: "100%", fontSize: 12 }} />
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function BookWizard({ onComplete }) {
  const [step, setStep] = useState(0);
  const [characters, setCharacters] = useState([{ name: "", role: "main character" }]);
  const [styleData, setStyleData] = useState({});
  const [storyData, setStoryData] = useState({});
  const [bookData, setBookData] = useState({});
  const [templates, setTemplates] = useState([]);
  const [templateName, setTemplateName] = useState("");
  const [showTemplates, setShowTemplates] = useState(false);

  useEffect(() => { listTemplates().then(setTemplates); }, []);

  const current = STEPS[step];
  const isLast = step === STEPS.length - 1;
  const stepData = step === 0 ? {} : step === 1 ? styleData : step === 2 ? storyData : bookData;
  const setStepData = step === 1 ? setStyleData : step === 2 ? setStoryData : setBookData;

  const setField = (key, value) => setStepData((d) => ({ ...d, [key]: value }));

  const allFilled = (current.fields || []).filter((f) => f.required).every((f) => stepData[f.key]?.toString().trim());

  const addCharacter = () => setCharacters((p) => [...p, { name: "", role: "sidekick" }]);

  const updateCharacter = (idx, key, value) => {
    setCharacters((p) => { const n = [...p]; n[idx] = { ...n[idx], [key]: value }; return n; });
  };

  const removeCharacter = (idx) => setCharacters((p) => p.filter((_, i) => i !== idx));

  const handleSaveTemplate = async () => {
    if (!templateName.trim()) return;
    const tmpl = { name: templateName, characters, style: styleData, savedAt: new Date().toISOString() };
    await saveTemplate(tmpl);
    setTemplates(await listTemplates());
    setTemplateName("");
  };

  const loadTemplate = (tmpl) => {
    setCharacters(tmpl.characters || [{ name: "", role: "main character" }]);
    if (tmpl.style) setStyleData((d) => ({ ...d, ...tmpl.style }));
    setShowTemplates(false);
  };

  const handleComplete = () => {
    const mainChar = characters.find((c) => c.role === "main character") || characters[0] || {};
    onComplete({
      ...mainChar,
      characters,
      ...styleData,
      ...storyData,
      ...bookData,
    });
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", maxWidth: 640, margin: "0 auto", padding: "24px 16px" }}>
      <div style={{ display: "flex", gap: 4, marginBottom: 24 }}>
        {STEPS.map((_, i) => (
          <div key={i} style={{ flex: 1, height: 3, borderRadius: 2, background: i <= step ? "var(--phosphor)" : "var(--ink-3)" }} />
        ))}
      </div>

      <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 4 }}>Step {step + 1} of {STEPS.length}</div>
      <h2 style={{ fontFamily: "var(--font)", fontSize: 20, color: "var(--phosphor)", marginBottom: 4 }}>{current.title}</h2>
      <p style={{ color: "var(--text-dim)", fontSize: 13, marginBottom: 20 }}>{current.helper}</p>

      <div style={{ flex: 1, overflow: "auto" }}>
        {step === 0 ? (
          <>
            {templates.length > 0 && (
              <div style={{ marginBottom: 16 }}>
                <button onClick={() => setShowTemplates(!showTemplates)} style={{ fontSize: 12, width: "100%", marginBottom: 4 }}>
                  {showTemplates ? "Hide Templates" : `Load from Template (${templates.length})`}
                </button>
                {showTemplates && (
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 8 }}>
                    {templates.map((t) => (
                      <div key={t.key} style={{ display: "flex", alignItems: "center", gap: 4, background: "var(--ink-2)", padding: "4px 8px", borderRadius: 4, border: "1px solid var(--border)" }}>
                        <span style={{ fontSize: 12, cursor: "pointer", color: "var(--phosphor)" }} onClick={() => loadTemplate(t)}>{t.name}</span>
                        <span style={{ fontSize: 10, color: "var(--text-dim)" }}>({(t.characters || []).length} chars)</span>
                        <button className="danger" style={{ fontSize: 9, padding: "1px 4px" }} onClick={async () => { await deleteTemplate(t.key); setTemplates(await listTemplates()); }}>x</button>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}
            {characters.map((char, idx) => (
              <CharacterCard key={idx} char={char} index={idx}
                onChange={(key, val) => updateCharacter(idx, key, val)}
                onRemove={characters.length > 1 ? () => removeCharacter(idx) : null}
              />
            ))}
            <button onClick={addCharacter} style={{ width: "100%", marginTop: 4, marginBottom: 16 }}>+ Add Character</button>
            <div style={{ borderTop: "1px solid var(--border)", paddingTop: 12, marginBottom: 16 }}>
              <div style={{ fontSize: 11, color: "var(--text-dim)", marginBottom: 6 }}>Save these characters as a template for reuse:</div>
              <div style={{ display: "flex", gap: 8 }}>
                <input value={templateName} onChange={(e) => setTemplateName(e.target.value)} placeholder="Template name" style={{ flex: 1, fontSize: 12 }} />
                <button onClick={handleSaveTemplate} disabled={!templateName.trim()}>Save Template</button>
              </div>
            </div>
          </>
        ) : (
          (current.fields || []).map((field) => (
            <div key={field.key} style={{ marginBottom: 16 }}>
              <label style={{ display: "block", fontSize: 12, color: "var(--text-dim)", marginBottom: 4 }}>
                {field.label}{field.required ? " *" : ""}
              </label>
              {field.type === "textarea" ? (
                <textarea value={stepData[field.key] || ""} onChange={(e) => setField(field.key, e.target.value)} placeholder={field.placeholder} rows={4} style={{ width: "100%" }} />
              ) : field.type === "select" ? (
                <select value={stepData[field.key] || ""} onChange={(e) => setField(field.key, e.target.value)} style={{ width: "100%" }}>
                  <option value="">Choose...</option>
                  {field.options.map((opt) => <option key={opt} value={opt}>{opt}</option>)}
                </select>
              ) : (
                <input value={stepData[field.key] || ""} onChange={(e) => setField(field.key, e.target.value)} placeholder={field.placeholder} style={{ width: "100%" }} />
              )}
            </div>
          ))
        )}
      </div>

      <div style={{ display: "flex", gap: 8, marginTop: 16, paddingTop: 16, borderTop: "1px solid var(--border)" }}>
        {step > 0 && <button onClick={() => setStep(step - 1)}>Back</button>}
        <div style={{ flex: 1 }} />
        {isLast ? (
          <button className="primary" onClick={handleComplete}>Build My Book</button>
        ) : (
          <button className="primary" onClick={() => setStep(step + 1)}>Next</button>
        )}
      </div>
    </div>
  );
}
