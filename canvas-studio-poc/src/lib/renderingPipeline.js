// Rendering Pipeline — consumes structured scene plans, produces deterministic generation calls.
// The AI picks templates; this pipeline renders them.
// Characters are normalized after generation: silhouette detect → scale → anchor snap.

import {
  buildBackgroundPrompt,
  buildCharacterPrompt,
  buildPropPrompt,
  generateScenePlan,
} from "./templateEngine";
import { normalizeCharacter, buildFaceMask } from "./characterNormalizer";

const AZURE_KEY = import.meta.env.VITE_AZURE_KEY || "";
const AZURE_ENDPOINT = import.meta.env.VITE_AZURE_ENDPOINT || "";
const AZURE_DEPLOYMENTS = ["gpt-image-1-5", "gpt-image-2-1"];
const AZURE_API_VERSION = "2025-04-01-preview";
const AZURE_API_VERSION_FALLBACK = "2025-03-01-preview";
const GEMINI_KEY = import.meta.env.VITE_GEMINI_API_KEY || "";

async function azureImageGen(prompt, size = "1024x1024", quality = "medium") {
  if (!AZURE_KEY || !AZURE_ENDPOINT) throw new Error("No Azure config");
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000);
  try {
    const body = JSON.stringify({ prompt, n: 1, size, quality });
    for (const dep of AZURE_DEPLOYMENTS) {
      for (const apiVer of [AZURE_API_VERSION, AZURE_API_VERSION_FALLBACK]) {
        try {
          const res = await fetch(
            `${AZURE_ENDPOINT}/openai/deployments/${dep}/images/generations?api-version=${apiVer}`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json", "api-key": AZURE_KEY },
              body,
              signal: controller.signal,
            }
          );
          if (!res.ok) {
            const e = await res.json().catch(() => ({}));
            if (res.status === 404 || res.status === 400) continue;
            throw new Error(e.error?.message || `Azure ${res.status}`);
          }
          const data = await res.json();
          const img = data.data?.[0];
          if (!img) throw new Error("No image from Azure");
          if (img.b64_json) return `data:image/png;base64,${img.b64_json}`;
          if (img.url) return img.url;
          throw new Error("No image data");
        } catch (err) {
          if (err.name === "AbortError") throw err;
          continue;
        }
      }
    }
    throw new Error("All Azure deployments failed");
  } finally {
    clearTimeout(timeout);
  }
}

function dataUrlToBlob(dataUrl) {
  const match = dataUrl.match(/^data:([^;]+);base64,(.+)$/);
  if (!match) return null;
  const mime = match[1];
  const base64 = match[2];
  const binStr = atob(base64);
  const arr = new Uint8Array(binStr.length);
  for (let i = 0; i < binStr.length; i++) arr[i] = binStr.charCodeAt(i);
  return new Blob([arr], { type: mime });
}

export async function azureImageEdit(imageDataUrls, prompt, size = "1024x1024", quality = "medium", inputFidelity = 0.8) {
  if (!AZURE_KEY || !AZURE_ENDPOINT) throw new Error("No Azure config");

  const urls = Array.isArray(imageDataUrls) ? imageDataUrls : [imageDataUrls];
  const blobs = urls.map((u) => dataUrlToBlob(u)).filter(Boolean);
  if (blobs.length === 0) throw new Error("No valid images for edit");

  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 180000);

  const errors = [];

  try {
    for (const dep of AZURE_DEPLOYMENTS) {
      try {
        const form = new FormData();
        for (const blob of blobs) {
          const ext = blob.type.includes("png") ? "png" : "jpg";
          form.append("image[]", blob, `image.${ext}`);
        }
        form.append("prompt", prompt);
        form.append("size", size);
        form.append("n", "1");
        form.append("quality", quality);
        if (inputFidelity != null) {
          form.append("input_fidelity", inputFidelity >= 0.7 ? "high" : "low");
        }

        const res = await fetch(
          `${AZURE_ENDPOINT}/openai/deployments/${dep}/images/edits?api-version=${AZURE_API_VERSION}`,
          {
            method: "POST",
            headers: { "api-key": AZURE_KEY },
            body: form,
            signal: controller.signal,
          }
        );

        if (!res.ok) {
          const e = await res.json().catch(() => ({}));
          const msg = e.error?.message || `Azure edit ${res.status} on ${dep}`;
          errors.push(msg);
          if (res.status === 404 || res.status === 400) continue;
          if (res.status === 429) continue;
          throw new Error(msg);
        }
        const data = await res.json();
        const img = data.data?.[0];
        if (!img) throw new Error("No edited image");
        if (img.b64_json) return `data:image/png;base64,${img.b64_json}`;
        if (img.url) return img.url;
        throw new Error("No image data");
      } catch (err) {
        if (err.name === "AbortError") throw err;
        errors.push(err.message);
        continue;
      }
    }
    throw new Error(`All Azure edit deployments failed: ${errors.join("; ")}`);
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

function makePlaceholder(label) {
  const c = document.createElement("canvas");
  c.width = 512;
  c.height = 512;
  const ctx = c.getContext("2d");
  const h = [...label].reduce((a, ch) => a + ch.charCodeAt(0), 0) % 360;
  const g = ctx.createLinearGradient(0, 0, 512, 512);
  g.addColorStop(0, `hsl(${h},50%,20%)`);
  g.addColorStop(1, `hsl(${(h + 60) % 360},60%,35%)`);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 512, 512);
  ctx.fillStyle = "rgba(255,255,255,0.6)";
  ctx.font = "bold 14px monospace";
  ctx.textAlign = "center";
  ctx.fillText(label, 256, 256);
  return c.toDataURL("image/png");
}

async function generateImage(prompt, size, quality = "medium") {
  if (AZURE_KEY && AZURE_ENDPOINT) {
    try {
      return await azureImageGen(prompt, size, quality);
    } catch {}
  }
  if (GEMINI_KEY) {
    try {
      return await geminiImageGen(prompt);
    } catch {}
  }
  return makePlaceholder(prompt.slice(0, 40));
}

// ── Scene Renderer ───────────────────────────────────────────────────────────

export async function renderScene(scenePlan, pageDims, onProgress) {
  const { w, h } = pageDims || { w: 1536, h: 1024 };
  const imgSize = w >= h ? "1024x1024" : "1024x1536";
  const result = {
    scene_id: scenePlan.id,
    title: scenePlan.title,
    scene_type: scenePlan.scene_type,
    page_text: scenePlan.page_text,
    character_slot: scenePlan.character_slot,
    composition: scenePlan.composition,
    layers: [],
    composite: null,
  };

  // Step 1: Background
  onProgress?.(`Generating background for "${scenePlan.title}"...`);
  try {
    const bgUrl = await generateImage(scenePlan.bg_prompt, imgSize);
    result.layers.push({
      name: "Background",
      type: "background",
      image_url: bgUrl,
      z_index: 0,
      slot: "full_page",
    });
  } catch (err) {
    onProgress?.(`Background failed: ${err.message}`);
    result.layers.push({
      name: "Background",
      type: "background",
      image_url: makePlaceholder("background"),
      z_index: 0,
      slot: "full_page",
    });
  }

  // Step 2: Character (skip for title_page / dedication)
  if (scenePlan.character_prompt) {
    onProgress?.(`Generating character for "${scenePlan.title}"...`);
    try {
      const rawUrl = await generateImage(scenePlan.character_prompt, "1024x1024");

      // Normalize: detect silhouette → scale → align to pose geometry
      const poseGeo = scenePlan.character_slot?.pose?.geo;
      onProgress?.(`Normalizing character for "${scenePlan.title}"...`);
      const normResult = await normalizeCharacter(rawUrl, poseGeo, 1024, 1024);

      const faceMask = normResult.head_region
        ? buildFaceMask(normResult.head_region, 1024)
        : null;

      result.layers.push({
        name: "Character",
        type: "character",
        image_url: normResult.normalized_url,
        raw_url: rawUrl !== normResult.normalized_url ? rawUrl : null,
        z_index: 10,
        slot: scenePlan.character_slot?.slot_bounds || scenePlan.composition?.character_slot,
        pose: scenePlan.character_slot?.pose,
        normalization: normResult.normalization,
        silhouette: normResult.silhouette,
        head_region: normResult.head_region,
        face_mask: faceMask,
      });

      if (normResult.normalization?.needs_correction) {
        onProgress?.(`Character normalized (scale: ${normResult.normalization.scale.toFixed(2)}, alignment: ${(normResult.normalization.alignment_score || 0).toFixed(2)})`);
      }
    } catch (err) {
      onProgress?.(`Character failed: ${err.message}`);
      result.layers.push({
        name: "Character",
        type: "character",
        image_url: makePlaceholder("character"),
        z_index: 10,
        slot: scenePlan.composition?.character_slot,
        pose: scenePlan.character_slot?.pose,
      });
    }
  }

  // Step 3: Props
  for (let i = 0; i < (scenePlan.prop_prompts || []).length; i++) {
    const prop = scenePlan.prop_prompts[i];
    onProgress?.(`Generating prop "${prop.name}" for "${scenePlan.title}"...`);
    try {
      const propUrl = await generateImage(prop.prompt, "1024x1024");
      result.layers.push({
        name: prop.name,
        type: "prop",
        image_url: propUrl,
        z_index: 5 + i,
        placement: prop.placement,
      });
    } catch (err) {
      onProgress?.(`Prop "${prop.name}" failed: ${err.message}`);
    }
  }

  // Step 4: Composite
  onProgress?.(`Compositing "${scenePlan.title}"...`);
  result.composite = await compositeScene(result, pageDims);

  onProgress?.(`Scene "${scenePlan.title}" complete.`);
  return result;
}

// ── Compositor ───────────────────────────────────────────────────────────────
// Places layers using anchor snapping and composition zone geometry.

export async function compositeScene(renderedScene, pageDims) {
  const { w = 1536, h = 1024 } = pageDims || {};
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");

  const loadImage = (url) =>
    new Promise((resolve) => {
      const img = new Image();
      img.crossOrigin = "anonymous";
      img.onload = () => resolve(img);
      img.onerror = () => resolve(null);
      img.src = url;
    });

  const sorted = [...(renderedScene.layers || [])].sort(
    (a, b) => (a.z_index || 0) - (b.z_index || 0)
  );

  for (const layer of sorted) {
    const img = await loadImage(layer.image_url);
    if (!img) continue;

    if (layer.slot === "full_page") {
      // Background: stretch to fill entire page
      ctx.drawImage(img, 0, 0, w, h);
    } else if (layer.type === "character" && layer.pose?.geo) {
      // Character: anchor-snap using pose geometry
      await compositeAnchoredCharacter(ctx, img, layer, w, h);
    } else if (layer.slot && typeof layer.slot === "object") {
      // Generic slot-based placement
      await compositeSlotted(ctx, img, layer.slot, w, h);
    } else {
      // Fallback: centered
      const scale = Math.min(w / img.naturalWidth, h / img.naturalHeight) * 0.8;
      const dw = img.naturalWidth * scale;
      const dh = img.naturalHeight * scale;
      ctx.drawImage(img, (w - dw) / 2, (h - dh) / 2, dw, dh);
    }
  }

  return canvas.toDataURL("image/png");
}

async function compositeAnchoredCharacter(ctx, img, layer, pageW, pageH) {
  const geo = layer.pose.geo;
  const slot = layer.slot || { x: 0.3, y: 0.2, w: 0.4, h: 0.7 };

  const slotPx = {
    x: slot.x * pageW,
    y: slot.y * pageH,
    w: slot.w * pageW,
    h: slot.h * pageH,
  };

  // Character should fill slot height, maintain aspect ratio
  const targetH = slotPx.h;
  const imgAspect = img.naturalWidth / img.naturalHeight;
  const targetW = targetH * imgAspect;

  // Anchor: snap feet to bottom of slot (ground_contact) or seat to slot center (seat_contact)
  const anchorType = layer.pose.anchor || "ground_contact";
  let drawX, drawY;

  if (anchorType === "ground_contact") {
    drawX = slotPx.x + (slotPx.w - targetW) / 2;
    drawY = slotPx.y + slotPx.h - targetH;
  } else if (anchorType === "seat_contact") {
    drawX = slotPx.x + (slotPx.w - targetW) / 2;
    drawY = slotPx.y + slotPx.h * 0.4 - targetH * 0.5;
  } else {
    drawX = slotPx.x + (slotPx.w - targetW) / 2;
    drawY = slotPx.y;
  }

  ctx.drawImage(img, drawX, drawY, targetW, targetH);
}

async function compositeSlotted(ctx, img, slot, pageW, pageH) {
  const dx = Math.round(slot.x * pageW);
  const dy = Math.round(slot.y * pageH);
  const dw = Math.round(slot.w * pageW);
  const dh = Math.round(slot.h * pageH);

  const imgAspect = img.naturalWidth / img.naturalHeight;
  const slotAspect = dw / dh;
  let drawW, drawH, drawX, drawY;

  if (imgAspect > slotAspect) {
    drawH = dh;
    drawW = dh * imgAspect;
    drawX = dx - (drawW - dw) / 2;
    drawY = dy;
  } else {
    drawW = dw;
    drawH = dw / imgAspect;
    drawX = dx;
    drawY = dy - (drawH - dh) / 2;
  }

  ctx.drawImage(img, drawX, drawY, drawW, drawH);
}

// ── Full Book Renderer ───────────────────────────────────────────────────────

export async function renderBook(bookPlan, onSceneProgress, onSceneComplete) {
  const results = [];
  const totalScenes = bookPlan.scenes.length;

  for (let i = 0; i < totalScenes; i++) {
    const scenePlan = bookPlan.scenes[i];
    onSceneProgress?.(`Scene ${i + 1}/${totalScenes}: ${scenePlan.title}`, i, totalScenes);

    try {
      const rendered = await renderScene(
        scenePlan,
        bookPlan.page_dims,
        onSceneProgress
      );
      results.push(rendered);
      onSceneComplete?.(rendered, i, totalScenes);
    } catch (err) {
      onSceneProgress?.(`Scene ${i + 1} failed: ${err.message}`);
      results.push({
        scene_id: scenePlan.id,
        title: scenePlan.title,
        error: err.message,
        layers: [],
        composite: makePlaceholder(scenePlan.title),
      });
    }
  }

  return {
    ...bookPlan,
    rendered_scenes: results,
    rendered_at: new Date().toISOString(),
    status: "rendered",
  };
}

export { generateImage, makePlaceholder };

// ── Layer Draft Generator ────────────────────────────────────────────────────
// Generates a single layer at draft quality (512x512, quality "low").

export async function renderLayerDraft(prompt, onProgress, referenceImage) {
  onProgress?.("Generating layer draft...");
  if (referenceImage) {
    try {
      return await azureImageEdit(referenceImage, prompt, "512x512", "low", 0.5);
    } catch {}
  }
  try {
    return await generateImage(prompt, "512x512", "low");
  } catch (err) {
    onProgress?.(`Layer draft failed: ${err.message}`);
    return makePlaceholder(prompt.slice(0, 40));
  }
}

// ── Layer Final Upgrade ──────────────────────────────────────────────────────
// Upgrades a layer to final quality (1024x1024, quality "medium").

export async function renderLayerFinal(prompt, onProgress, referenceImage) {
  onProgress?.("Upgrading layer to final...");
  if (referenceImage) {
    try {
      return await azureImageEdit(referenceImage, prompt, "1024x1024", "medium", 0.7);
    } catch {}
  }
  try {
    return await generateImage(prompt, "1024x1024", "medium");
  } catch (err) {
    onProgress?.(`Layer upgrade failed: ${err.message}`);
    return makePlaceholder(prompt.slice(0, 40));
  }
}

// ── Storyboard Overview ──────────────────────────────────────────────────────

export async function renderStoryboardOverview(plan, onProgress) {
  const sceneDescs = plan.scenes
    .slice(0, 12)
    .map((s, i) => `${i + 1}. ${s.title}: ${s.description || s.page_text || ""}`)
    .join("\n");

  const prompt = [
    `Children's book storyboard overview showing ${plan.scenes.length} scenes in a grid layout.`,
    `Style: ${plan.style_token?.technique || "warm watercolor illustration"}`,
    `Title: "${plan.title}"`,
    `Scenes:\n${sceneDescs}`,
    "Show each scene as a small thumbnail in a grid, numbered.",
    "Grid layout, 3-4 rows, each cell is a different scene.",
  ].join("\n");

  onProgress?.("Generating storyboard overview...");
  try {
    return await generateImage(prompt, "1024x1024", "medium");
  } catch (err) {
    onProgress?.(`Storyboard overview failed: ${err.message}`);
    return makePlaceholder("Storyboard Overview");
  }
}

// ── Character Reference Sheet (11 images) ────────────────────────────────────

const CHARACTER_REFS = [
  // Turnaround (4 large, square layout)
  { id: "front", label: "Front View", category: "turnaround", angle: "facing directly forward, front view, full body" },
  { id: "3q_left", label: "3/4 Left View", category: "turnaround", angle: "three-quarter view from the left, full body" },
  { id: "isometric", label: "Isometric View", category: "turnaround", angle: "isometric view, slightly elevated angle showing depth, full body" },
  { id: "running", label: "Running", category: "turnaround", angle: "running, mid-stride, shown from the side to show full motion, full body" },
  // Action poses (4 bottom strip)
  { id: "sitting", label: "Sitting Cross-Legged", category: "pose", angle: "sitting cross-legged on the ground, three-quarter view to show leg position, full body" },
  { id: "walking", label: "Walking", category: "pose", angle: "walking naturally, shown from the side to show stride, full body" },
  { id: "wonder", label: "Looking Up in Wonder", category: "pose", angle: "standing and looking upward with wonder and awe, head tilted back, shown from a low angle looking up at the character, full body" },
  { id: "arms_raised", label: "Arms Raised", category: "pose", angle: "standing with both arms raised above head in joy or celebration, facing forward, full body" },
  // Resting/emotional (3 right side)
  { id: "sleeping", label: "Lying Down / Sleeping", category: "pose", angle: "lying down on their side, sleeping peacefully, shown from the side to show full horizontal body" },
  { id: "crouching", label: "Crouching", category: "pose", angle: "crouching down examining something on the ground, three-quarter view to show depth of crouch, full body" },
  { id: "hugging", label: "Hugging", category: "pose", angle: "standing with arms wrapped around an object as if hugging it tightly, facing forward to show arm wrap, full body" },
];

export { CHARACTER_REFS };

export async function renderCharacterReferences(characterDesign, styleToken, onProgress, referenceImages) {
  const technique = styleToken?.technique || "warm watercolor children's book illustration";
  const lighting = styleToken?.lighting || "soft warm light";
  const edgeSoftness = styleToken?.edge_softness ?? 0.7;
  const contrast = styleToken?.contrast || "low";
  const detailLevel = styleToken?.detail_level || "moderate";
  const palette = styleToken?.palette || "";

  const refImages = Array.isArray(referenceImages) ? referenceImages : referenceImages ? [referenceImages] : [];

  const prompt = [
    `Character turnaround reference sheet for a children's book character.`,
    `Art style: ${technique}.`,
    `Lighting: ${lighting}.`,
    edgeSoftness > 0.5 ? "Soft blended edges, painterly style." : "Clean defined edges with consistent line weight.",
    `Contrast: ${contrast}. Detail level: ${detailLevel}.`,
    palette ? `Color palette: ${palette}.` : "",
    refImages.length > 0 ? "Use the reference photos to match the child's REAL face, hair, skin tone, and build EXACTLY." : "",
    characterDesign,
    "Show the SAME character from multiple angles in a grid layout on ONE image:",
    "Top row: front view, 3/4 left view, side view, back view.",
    "Bottom row: sitting cross-legged, walking, running, arms raised in joy.",
    "Each view shows the full body from head to toes.",
    "Clean light grey background (NOT pure white, NOT pure black).",
    "Consistent character design across ALL views — same child, same clothes, same features.",
    "The character MUST match the art style exactly — same rendering technique, same color temperature, same line quality.",
    "CRITICAL: Preserve the child's exact facial features, hair, and skin tone from the reference photos.",
    "NO text, NO labels, NO watermarks, NO speech bubbles, NO borders between views.",
  ].filter(Boolean).join(" ");

  onProgress?.("Generating character reference sheet...");
  try {
    if (refImages.length > 0) {
      onProgress?.(`Using ${refImages.length} reference photo${refImages.length > 1 ? "s" : ""} for identity...`);
      try {
        const imageUrl = await azureImageEdit(
          refImages,
          prompt,
          "1024x1024",
          "medium",
          0.9
        );
        onProgress?.("Character reference sheet ready (photo-guided).");
        return imageUrl;
      } catch (editErr) {
        onProgress?.(`Photo-guided generation failed (${editErr.message}), trying text-only...`);
      }
    }
    const imageUrl = await generateImage(prompt, "1024x1024", "medium");
    onProgress?.("Character reference sheet ready.");
    return imageUrl;
  } catch (err) {
    onProgress?.(`Character sheet failed: ${err.message}`);
    return makePlaceholder("Character Reference Sheet");
  }
}

// ── Style Sample Generator ───────────────────────────────────────────────────

export async function renderStyleSample(styleToken, setting, onProgress) {
  const prompt = [
    "A sample illustration showing the art style for a children's book.",
    styleToken?.technique || "warm watercolor illustration",
    `Setting: ${setting || "a cozy scene with warm colors"}`,
    `Lighting: ${styleToken?.lighting || "soft warm light"}`,
    "Show a simple scene that demonstrates the color palette, line style, and mood.",
    "NO text, NO watermarks.",
  ].join(". ");

  onProgress?.("Generating style sample...");
  try {
    return await generateImage(prompt, "1024x1024", "medium");
  } catch (err) {
    onProgress?.(`Style sample failed: ${err.message}`);
    return makePlaceholder("Style Sample");
  }
}
