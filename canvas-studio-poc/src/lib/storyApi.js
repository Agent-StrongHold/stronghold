const LITELLM_URL =
  import.meta.env.VITE_LITELLM_URL || "/litellm";
const LITELLM_KEY =
  import.meta.env.VITE_LITELLM_KEY || "sk-conductor-litellm-2026";
const GEMINI_KEY = import.meta.env.VITE_GEMINI_API_KEY || "";
const AZURE_KEY = import.meta.env.VITE_AZURE_KEY || "";
const AZURE_ENDPOINT = import.meta.env.VITE_AZURE_ENDPOINT || "";
const AZURE_DEPLOYMENT = "gpt-image-2-1";

async function llm(messages, model = "gemini-flash") {
  const res = await fetch(`${LITELLM_URL}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${LITELLM_KEY}`,
    },
    body: JSON.stringify({
      model,
      messages,
      temperature: 0.7,
      max_tokens: 16000,
    }),
  });
  if (!res.ok) {
    const e = await res.json().catch(() => ({}));
    throw new Error(e.error?.message || `LLM ${res.status}`);
  }
  const data = await res.json();
  return data.choices?.[0]?.message?.content || "";
}

function extractJSON(text) {
  // Try code block first (greedy to avoid splitting on inner ```)
  const codeBlock = text.match(/```(?:json)?\s*([\s\S]*)```/);
  if (codeBlock) {
    try {
      return JSON.parse(codeBlock[1].trim());
    } catch {}
  }
  // Try to find outermost { ... }
  const firstBrace = text.indexOf("{");
  const lastBrace = text.lastIndexOf("}");
  if (firstBrace !== -1 && lastBrace > firstBrace) {
    let candidate = text.slice(firstBrace, lastBrace + 1);
    try {
      return JSON.parse(candidate);
    } catch {
      // Truncated JSON — try to fix by closing open brackets
      const opens = (candidate.match(/[\[\{]/g) || []).length;
      const closes = (candidate.match(/[\]\}]/g) || []).length;
      const missing = opens - closes;
      if (missing > 0 && missing < 20) {
        // Count which brackets are open
        const stack = [];
        for (const ch of candidate) {
          if (ch === "{" || ch === "[") stack.push(ch);
          else if (ch === "}" && stack[stack.length - 1] === "{") stack.pop();
          else if (ch === "]" && stack[stack.length - 1] === "[") stack.pop();
        }
        for (let i = stack.length - 1; i >= 0; i--) {
          candidate += stack[i] === "{" ? "}" : "]";
        }
        // Remove trailing partial entries (e.g. incomplete scene objects)
        candidate = candidate.replace(/,\s*\{[^}]*$/, "");
        try {
          return JSON.parse(candidate);
        } catch {}
      }
    }
  }
  throw new Error("AI did not return valid JSON. Response: " + text.slice(0, 200));
}

async function azureImageGen(prompt) {
  if (!AZURE_KEY || !AZURE_ENDPOINT) throw new Error("No Azure config");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 120000);
  try {
    const res = await fetch(
      `${AZURE_ENDPOINT}/openai/deployments/${AZURE_DEPLOYMENT}/images/generations?api-version=2025-03-01-preview`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json", "api-key": AZURE_KEY },
        body: JSON.stringify({ prompt, n: 1, size: "1024x1024", quality: "medium" }),
        signal: controller.signal,
      }
    );
    if (!res.ok) {
      const e = await res.json().catch(() => ({}));
      throw new Error(e.error?.message || `Azure ${res.status}`);
    }
    const data = await res.json();
    const img = data.data?.[0];
    if (!img) throw new Error("No image from Azure");
    if (img.b64_json) return `data:image/png;base64,${img.b64_json}`;
    if (img.url) return img.url;
    throw new Error("No image data");
  } finally {
    clearTimeout(timeout);
  }
}

async function geminiImageGen(prompt) {
  if (!GEMINI_KEY) throw new Error("No Gemini key");
  const res = await fetch(
    `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-image:generateContent`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        contents: [{ parts: [{ text: `Generate an image: ${prompt}` }] }],
        generationConfig: { responseModalities: ["TEXT", "IMAGE"] },
      }),
    }
  );
  if (!res.ok) throw new Error(`Gemini ${res.status}`);
  const data = await res.json();
  const part = data?.candidates?.[0]?.content?.parts?.find((p) => p.inlineData);
  if (!part) throw new Error("No image from Gemini");
  return `data:${part.inlineData.mimeType};base64,${part.inlineData.data}`;
}

async function generateImage(prompt) {
  if (AZURE_KEY && AZURE_ENDPOINT) {
    try { return await azureImageGen(prompt); } catch {}
  }
  if (GEMINI_KEY) {
    try { return await geminiImageGen(prompt); } catch {}
  }
  return makePlaceholder(prompt);
}

function makePlaceholder(prompt) {
  const c = document.createElement("canvas");
  c.width = 512; c.height = 512;
  const ctx = c.getContext("2d");
  const h = [...prompt].reduce((a, c) => a + c.charCodeAt(0), 0) % 360;
  const g = ctx.createLinearGradient(0, 0, 512, 512);
  g.addColorStop(0, `hsl(${h},60%,25%)`);
  g.addColorStop(1, `hsl(${(h+60)%360},70%,40%)`);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 512);
  ctx.fillStyle = "rgba(255,255,255,0.5)";
  ctx.font = "14px monospace";
  ctx.textAlign = "center";
  prompt.split(" ").slice(0, 8).forEach((w, i) => ctx.fillText(w, 256, 240 + i * 22));
  return c.toDataURL("image/png");
}

export const IMAGE_MODELS = {
  proof: [
    { id: "azure-gpt-image-2", name: "GPT-Image 2", provider: "azure" },
  ],
};

let _stories = {};
let _id = 0;
const uid = () => `s${++_id}`;

export async function decomposeBook(bookSpec) {
  const pageMatch = (bookSpec.page_count || "12").match(/(\d+)/);
  const numPages = pageMatch ? parseInt(pageMatch[1]) : 12;
  const orientation = bookSpec.orientation || "landscape (wide)";
  const dims = orientation.includes("portrait")
    ? { w: 1024, h: 1536 }
    : orientation.includes("square")
      ? { w: 1024, h: 1024 }
      : { w: 1536, h: 1024 };

  const resp = await llm([
    {
      role: "system",
      content: `You are a children's book storyboarding engine. You output STRUCTURED scene definitions — not prompts. A rendering pipeline consumes your output deterministically.

Return ONLY valid JSON:
{
  "title": "book title",
  "dedication": "dedication text or empty string",
  "style_contract": {
    "art_style": "exact art style name from spec",
    "color_palette": ["#hex", "#hex", "#hex", "#hex", "#hex"],
    "lighting": "lighting description",
    "mood": "mood description",
    "recurring_elements": ["elements across scenes"],
    "negative_prompts": "no text in images, no watermarks, no photorealism, no scary imagery"
  },
      "scenes": [
    {
      "id": 1,
      "title": "Scene title",
      "type": "title_page",
      "page_text": "",
      "description": "visual description of setting for this scene",
      "pose": "standing_3q_left",
      "composition": "center_focus",
      "character_action": "what the character is doing",
      "characters_present": ["Name1", "Name2"],
      "props": [
        {"name": "prop name", "description": "visual description", "scale": "handheld|environment", "placement": "right"}
      ]
    }
  ]
}

VALID scene types (pick exactly one per scene):
  title_page, dedication, story_beat, emotional_beat, action_beat, ending

VALID poses (pick exactly one per scene that has a character):
  standing_front, standing_3q_left, standing_3q_right,
  sitting_cross_legged, walking_left, walking_right,
  running_left, running_right, looking_up, crouching,
  arms_raised, hugging, sitting_edge, pointing

VALID compositions (pick exactly one per scene):
  center_focus, left_focus, right_focus, wide_establishing,
  close_up, bottom_center, top_text_wide

RULES:
- Exactly ${numPages} scenes
- Scene 1: type=title_page, no page_text, no character pose needed
- Scene 2 (if dedication provided): type=dedication, no page_text, no character
- Remaining scenes: story progression with page_text
- Last scene: type=ending
- Vary poses and compositions across scenes — avoid repeating the same combo
- Use action_beat for high-energy moments, emotional_beat for close-ups
- Page text: age-appropriate (${bookSpec.age || "5-6"}), 1-3 short sentences, simple vocabulary
- Props: 0-2 per scene, each with name, description, scale, and placement
- Prop scale "handheld" = small items the character holds/touches (toys, tools, food, wands, baskets, traps). These are GENERATED AS PART OF the character image.
- Prop scale "environment" = large objects the character stands near or inside (houses, boats, trees, castles, furniture, vehicles). These are SEPARATE layers.
- If no scale provided, default to "handheld"
- character_action should describe what ALL characters present are doing together — e.g. "Emma and Jack carefully placing gold coins in a tiny leprechaun trap" not just "standing"
- characters_present: list which named characters appear in this scene by their exact name. All listed characters will be generated together in a single image.
- Description: describe the SETTING/ENVIRONMENT only — the rendering pipeline handles character/prop generation
- Do NOT include any "prompt" fields — the rendering pipeline builds prompts from your structured data`,
    },
    {
      role: "user",
      content: `Create a ${numPages}-scene children's book storyboard.

CAST OF CHARACTERS:
${(bookSpec.characters || []).map((c, i) => {
  const appearance = [c.hair, c.skin_tone, c.eye_color, c.face_shape, c.signature_features, c.build].filter(Boolean).join(", ") || "generic child character";
  return `${i + 1}. ${c.name || "Unnamed"} (${c.age || "5-6"}, ${c.pronouns || "they/them"}, role: ${c.role || "main character"})${c.nickname ? ` — called "${c.nickname}"` : ""}
   Appearance: ${appearance}`;
}).join("\n")}

Story: ${bookSpec.premise}
Setting: ${bookSpec.setting || "not specified"}
${bookSpec.lessons ? `Theme: ${bookSpec.lessons}` : ""}
Ending: ${bookSpec.ending || "happy"}
${bookSpec.title ? `Title: ${bookSpec.title}` : "Generate an appropriate title"}
${bookSpec.dedication ? `Dedication: ${bookSpec.dedication}` : ""}

Remember: output structured scene data with type, pose, composition, characters_present, props — NOT freeform prompts.`,
    },
  ], "gemini-flash");

  const rawDecomp = extractJSON(resp);
  rawDecomp.page_dims = dims;
  rawDecomp.orientation = orientation;
  return rawDecomp;
}

export async function decomposeStory(storyText) {
  const resp = await llm([
    { role: "system", content: `You are a storyboard decomposition engine. Given a story or concept, produce:

1. A STYLE CONTRACT - the persistent visual rules for ALL scenes
2. A STORYBOARD - ordered list of scenes

Return ONLY valid JSON:
{
  "title": "story title",
  "style_contract": {
    "art_style": "e.g. Studio Ghibli, noir comic, oil painting, pixel art",
    "color_palette": ["#hex", "#hex", "#hex", "#hex", "#hex"],
    "lighting": "e.g. warm golden hour, cold fluorescent, dramatic chiaroscuro",
    "mood": "e.g. melancholic wonder, tense urgency, whimsical chaos",
    "camera_preference": "e.g. wide establishing shots, close-up intimacy, Dutch angles",
    "recurring_elements": ["element1", "element2"],
    "character_designs": {
      "CharacterName": "visual description for consistent generation"
    },
    "negative_prompts": "things to always avoid",
    "technique": "e.g. layered composition with separate BG/midground/FG, flat illustration with bold outlines"
  },
  "scenes": [
    {
      "id": 1,
      "title": "Scene title",
      "description": "What happens in this scene, composition notes",
      "layers": [
        {"name": "Background", "type": "background", "prompt": "detailed generation prompt for this layer ONLY, incorporating style contract"},
        {"name": "Element", "type": "object", "prompt": "detailed generation prompt for this element on transparent background"}
      ]
    }
  ]
}

Rules:
- 3-8 scenes that tell the story beat by beat
- Style contract must be specific enough that any scene generated from it looks like it belongs
- Each scene has 2-5 layers ordered back to front
- Layer prompts MUST incorporate the style contract's art style, lighting, mood, and color palette
- Character layers must reference the character_designs for consistency
- Backgrounds establish setting; characters/objects are generated separately for compositing` },
    { role: "user", content: storyText },
  ]);
  return extractJSON(resp);
}

export async function refineStyleContract(contract, feedback, sceneContext) {
  const resp = await llm([
    { role: "system", content: `You are a style contract editor. Given the current style contract, user feedback, and the scene context, return an UPDATED style contract JSON.

Current contract:
${JSON.stringify(contract, null, 2)}

Scene context: ${sceneContext || "general refinement"}

User feedback: ${feedback}

Return ONLY the updated style_contract JSON object (no wrapper, no explanation). Apply the user's feedback to the relevant fields. Keep unchanged fields intact.` },
    { role: "user", content: feedback },
  ]);
  return extractJSON(resp);
}

export async function refineScenePrompt(scene, contract, feedback) {
  const resp = await llm([
    { role: "system", content: `You are a scene refinement engine. Given the current scene, style contract, and user feedback, return updated layer prompts.

Style contract:
${JSON.stringify(contract, null, 2)}

Current scene:
${JSON.stringify(scene, null, 2)}

Return ONLY valid JSON - same scene structure but with updated prompts reflecting the feedback:
{"title":"...","description":"...","layers":[{"name":"...","type":"...","prompt":"updated prompt"}]}` },
    { role: "user", content: feedback },
  ]);
  return extractJSON(resp);
}

export function createStory(decomposition) {
  const storyId = uid();
  const story = {
    id: storyId,
    title: decomposition.title,
    style_contract: decomposition.style_contract,
    scenes: decomposition.scenes.map((s) => ({
      ...s,
      story_id: storyId,
      canvas: null,
      layers_data: [],
      status: "planned",
      thumbnail: null,
    })),
    created_at: new Date().toISOString(),
    current_scene_idx: 0,
  };
  _stories[storyId] = story;
  return story;
}

export function getStory(id) {
  return _stories[id] || null;
}

export function listStories() {
  return Object.values(_stories);
}

export function updateStyleContract(storyId, newContract) {
  const story = _stories[storyId];
  if (story) story.style_contract = newContract;
  return story;
}

export function updateScene(storyId, sceneId, updates) {
  const story = _stories[storyId];
  if (!story) return;
  const scene = story.scenes.find((s) => s.id === sceneId);
  if (scene) Object.assign(scene, updates);
  return scene;
}

export async function generateScene(storyId, sceneId, onProgress) {
  const story = _stories[storyId];
  if (!story) throw new Error("Story not found");
  const scene = story.scenes.find((s) => s.id === sceneId);
  if (!scene) throw new Error("Scene not found");

  const contract = story.style_contract;
  const aspect = "16:9";

  onProgress?.(`Creating canvas for "${scene.title}"...`);
  const canvas = {
    id: uid(),
    name: scene.title,
    width: 1824,
    height: 1024,
    background_color: contract.color_palette?.[0] || "#000000",
    layers: [],
  };

  scene.canvas = canvas;
  scene.status = "generating";

  const layers = [];
  for (let i = 0; i < scene.layers.length; i++) {
    const lp = scene.layers[i];
    onProgress?.(`Generating layer ${i + 1}/${scene.layers.length}: ${lp.name}`);

    const stylePrefix = [
      contract.art_style,
      contract.lighting,
      contract.mood,
      `palette: ${contract.color_palette?.join(", ")}`,
    ]
      .filter(Boolean)
      .join(". ");

    const fullPrompt = lp.prompt
      ? `${stylePrefix}. ${lp.prompt}`
      : `${stylePrefix}. ${lp.name}`;

    try {
      const imageUrl = await generateImage(fullPrompt);
      layers.push({
        id: uid(),
        name: lp.name,
        layer_type: lp.type || "object",
        z_index: i,
        image_url: imageUrl,
        width: 1024,
        height: 1024,
        x: 0,
        y: 0,
        scale: 1,
        rotation: 0,
        opacity: 1,
        visible: true,
        locked: false,
        prompt: fullPrompt,
      });
    } catch (err) {
      onProgress?.(`Warning: ${lp.name} failed: ${err.message}`);
      layers.push({
        id: uid(),
        name: lp.name,
        layer_type: lp.type || "object",
        z_index: i,
        image_url: makePlaceholder(lp.name),
        width: 512,
        height: 512,
        x: 0,
        y: 0,
        scale: 1,
        rotation: 0,
        opacity: 1,
        visible: true,
        locked: false,
        prompt: fullPrompt,
      });
    }
  }

  canvas.layers = layers;
  scene.layers_data = layers;
  scene.status = "done";
  scene.thumbnail = layers.length > 0 ? layers[0].image_url : null;
  onProgress?.(`Scene "${scene.title}" complete!`);
  return scene;
}

export { generateImage, llm };
export default {
  decomposeStory,
  refineStyleContract,
  refineScenePrompt,
  createStory,
  getStory,
  listStories,
  updateStyleContract,
  updateScene,
  generateScene,
  generateImage,
  IMAGE_MODELS,
};
