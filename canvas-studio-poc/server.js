import express from "express";
import cors from "cors";
import pg from "pg";

const { Pool } = pg;
const pool = new Pool({
  host: "127.0.0.1",
  port: 5440,
  user: "coinswarm",
  password: "coinswarm_dev_2024",
  database: "canvas_studio",
});

const app = express();
app.use(cors());
app.use(express.json({ limit: "200mb" }));

function safeKey(key) {
  return (key || "untitled").replace(/[^a-zA-Z0-9_-]/g, "_").slice(0, 80);
}

app.post("/api/books/:key", async (req, res) => {
  const key = safeKey(req.params.key);
  const payload = { ...req.body, savedAt: new Date().toISOString() };
  try {
    await pool.query(
      `INSERT INTO books (key, data, updated_at) VALUES ($1, $2, now())
       ON CONFLICT (key) DO UPDATE SET data = $2, updated_at = now()`,
      [key, JSON.stringify(payload)]
    );
    res.json({ ok: true, savedAt: payload.savedAt });
  } catch (e) {
    console.error("Save error:", e.message);
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/books/:key", async (req, res) => {
  const key = safeKey(req.params.key);
  try {
    const { rows } = await pool.query("SELECT data FROM books WHERE key = $1", [key]);
    if (rows.length === 0) return res.status(404).json({ error: "not found" });
    res.json(rows[0].data);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/books", async (_req, res) => {
  try {
    const { rows } = await pool.query(
      "SELECT key, data->>'savedAt' as saved_at, data->>'step' as step, data->'bookSpec'->>'title' as title, data->'bookSpec'->>'premise' as premise FROM books ORDER BY updated_at DESC"
    );
    const results = rows.map((r) => ({
      key: r.key,
      title: r.title || r.premise?.slice(0, 40) || r.key,
      step: r.step,
      bookSpec: { title: r.title, premise: r.premise },
      savedAt: r.saved_at,
    }));
    res.json(results);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.delete("/api/books/:key", async (req, res) => {
  const key = safeKey(req.params.key);
  try {
    await pool.query("DELETE FROM books WHERE key = $1", [key]);
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.delete("/api/books", async (_req, res) => {
  try {
    await pool.query("TRUNCATE books");
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── Templates ─────────────────────────────────────────────────────────────

app.get("/api/templates", async (_req, res) => {
  try {
    const { rows } = await pool.query("SELECT key, data FROM templates ORDER BY updated_at DESC");
    res.json(rows.map((r) => ({ key: r.key, ...r.data })));
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post("/api/templates/:key", async (req, res) => {
  const key = safeKey(req.params.key);
  try {
    await pool.query(
      `INSERT INTO templates (key, data, updated_at) VALUES ($1, $2, now())
       ON CONFLICT (key) DO UPDATE SET data = $2, updated_at = now()`,
      [key, JSON.stringify(req.body)]
    );
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.delete("/api/templates/:key", async (req, res) => {
  try {
    await pool.query("DELETE FROM templates WHERE key = $1", [safeKey(req.params.key)]);
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// ── Characters ─────────────────────────────────────────────────────────────

app.get("/api/characters", async (_req, res) => {
  try {
    const { rows } = await pool.query("SELECT key, data FROM characters ORDER BY updated_at DESC");
    res.json(rows.map((r) => ({ key: r.key, ...r.data })));
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.get("/api/characters/:key", async (req, res) => {
  try {
    const { rows } = await pool.query("SELECT data FROM characters WHERE key = $1", [safeKey(req.params.key)]);
    if (rows.length === 0) return res.status(404).json({ error: "not found" });
    res.json(rows[0].data);
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.post("/api/characters/:key", async (req, res) => {
  const key = safeKey(req.params.key);
  try {
    await pool.query(
      `INSERT INTO characters (key, data, updated_at) VALUES ($1, $2, now())
       ON CONFLICT (key) DO UPDATE SET data = $2, updated_at = now()`,
      [key, JSON.stringify({ ...req.body, savedAt: new Date().toISOString() })]
    );
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

app.delete("/api/characters/:key", async (req, res) => {
  try {
    await pool.query("DELETE FROM characters WHERE key = $1", [safeKey(req.params.key)]);
    res.json({ ok: true });
  } catch (e) { res.status(500).json({ error: e.message }); }
});

// ── Lulu Print-on-Demand ─────────────────────────────────────────────────
// The Lulu client runs as a separate Python service at LULU_SERVICE_URL.
// See server/lulu/ for the Python implementation.

const LULU_SERVICE_URL = process.env.LULU_SERVICE_URL || "http://localhost:8260";

app.get("/api/print/packages", async (_req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/packages`);
    if (!r.ok) throw new Error(`Lulu service ${r.status}`);
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.get("/api/print/shipping-cost", async (req, res) => {
  try {
    const params = new URLSearchParams(req.query).toString();
    const r = await fetch(`${LULU_SERVICE_URL}/shipping-cost?${params}`);
    if (!r.ok) throw new Error(`Lulu service ${r.status}`);
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.post("/api/print/order", async (req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/order`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req.body),
    });
    if (!r.ok) {
      const err = await r.json().catch(() => ({}));
      throw new Error(err.detail || `Lulu service ${r.status}`);
    }
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.get("/api/print/orders", async (_req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/orders`);
    if (!r.ok) throw new Error(`Lulu service ${r.status}`);
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.get("/api/print/orders/:id", async (req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/orders/${req.params.id}`);
    if (!r.ok) throw new Error(`Lulu service ${r.status}`);
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.post("/api/print/orders/:id/cancel", async (req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/orders/${req.params.id}/cancel`, { method: "POST" });
    if (!r.ok) throw new Error(`Lulu service ${r.status}`);
    res.json(await r.json());
  } catch (e) {
    res.status(502).json({ error: e.message });
  }
});

app.get("/api/print/health", async (_req, res) => {
  try {
    const r = await fetch(`${LULU_SERVICE_URL}/health`, { signal: AbortSignal.timeout(3000) });
    res.json(await r.json());
  } catch {
    res.json({ configured: false, healthy: false });
  }
});

const PORT = 5174;

// ── Generation Attempts (training data) ──────────────────────────────────

app.post("/api/generation-attempts", async (req, res) => {
  const { book_key, scene_id, layer_id, attempt_type, prompt, model_id, quality, verdict, data } = req.body;
  if (!book_key || !scene_id || !layer_id || !attempt_type) {
    return res.status(400).json({ error: "book_key, scene_id, layer_id, attempt_type required" });
  }
  try {
    const { rows } = await pool.query(
      `INSERT INTO generation_attempts (book_key, scene_id, layer_id, attempt_type, prompt, model_id, quality, verdict, data)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING id, created_at`,
      [book_key, scene_id, layer_id, attempt_type, prompt || "", model_id || null, quality || "draft", verdict || "pending", JSON.stringify(data || {})]
    );
    res.json({ ok: true, id: rows[0].id, created_at: rows[0].created_at });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.patch("/api/generation-attempts/:id/verdict", async (req, res) => {
  const { verdict } = req.body;
  if (!verdict) return res.status(400).json({ error: "verdict required" });
  try {
    const { rowCount } = await pool.query(
      "UPDATE generation_attempts SET verdict = $1 WHERE id = $2", [verdict, req.params.id]
    );
    if (rowCount === 0) return res.status(404).json({ error: "not found" });
    res.json({ ok: true });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/generation-attempts", async (req, res) => {
  const { book_key, scene_id } = req.query;
  try {
    const clauses = [];
    const params = [];
    if (book_key) { params.push(book_key); clauses.push(`book_key = $${params.length}`); }
    if (scene_id) { params.push(scene_id); clauses.push(`scene_id = $${params.length}`); }
    const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
    const { rows } = await pool.query(
      `SELECT id, book_key, scene_id, layer_id, attempt_type, prompt, model_id, quality, verdict, created_at FROM generation_attempts ${where} ORDER BY id DESC LIMIT 500`, params
    );
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── Page Layout Versions (training data) ──────────────────────────────────

app.post("/api/layout-versions", async (req, res) => {
  const { book_key, scene_id, layout, diff } = req.body;
  if (!book_key || !scene_id || !layout) {
    return res.status(400).json({ error: "book_key, scene_id, layout required" });
  }
  try {
    const { rows: prev } = await pool.query(
      "SELECT version FROM page_layout_versions WHERE book_key = $1 AND scene_id = $2 ORDER BY version DESC LIMIT 1",
      [book_key, scene_id]
    );
    const version = prev.length > 0 ? prev[0].version + 1 : 1;
    const { rows } = await pool.query(
      `INSERT INTO page_layout_versions (book_key, scene_id, version, layout, diff) VALUES ($1,$2,$3,$4,$5) RETURNING id, version, created_at`,
      [book_key, scene_id, version, JSON.stringify(layout), diff ? JSON.stringify(diff) : null]
    );
    res.json({ ok: true, id: rows[0].id, version: rows[0].version, created_at: rows[0].created_at });
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

app.get("/api/layout-versions", async (req, res) => {
  const { book_key, scene_id } = req.query;
  try {
    const clauses = [];
    const params = [];
    if (book_key) { params.push(book_key); clauses.push(`book_key = $${params.length}`); }
    if (scene_id) { params.push(scene_id); clauses.push(`scene_id = $${params.length}`); }
    const where = clauses.length ? `WHERE ${clauses.join(" AND ")}` : "";
    const { rows } = await pool.query(
      `SELECT id, book_key, scene_id, version, layout, diff, created_at FROM page_layout_versions ${where} ORDER BY id DESC LIMIT 200`, params
    );
    res.json(rows);
  } catch (e) {
    res.status(500).json({ error: e.message });
  }
});

// ── PDF Export ────────────────────────────────────────────────────────────

import { execFile } from "child_process";
import { mkdtemp, rmdir, stat } from "fs/promises";
import { join } from "path";
import { tmpdir } from "os";

const EXPORT_SCRIPT = join(import.meta.dirname, "server", "export_book.py");

app.post("/api/export", async (req, res) => {
  const { mode, title, author, product_id, pages, front_cover, back_cover } = req.body;
  if (!pages?.length) return res.status(400).json({ error: "pages required" });

  let tmpDir;
  try {
    tmpDir = await mkdtemp(join(tmpdir(), "canvas-export-"));
    const payload = JSON.stringify({ mode: mode || "interior", title, author, product_id, pages, front_cover, back_cover, output_dir: tmpDir });

    await new Promise((resolve, reject) => {
      const proc = execFile("python3", [EXPORT_SCRIPT], { maxBuffer: 100 * 1024 * 1024 }, (err, stdout, stderr) => {
        if (err) return reject(stderr || err.message);
        try {
          const result = JSON.parse(stdout.trim());
          if (!result.ok) return reject(result.error || "export failed");
          resolve(result.path);
        } catch (e) { reject(e.message); }
      });
      proc.stdin.write(payload);
      proc.stdin.end();
    });

    const pdfName = mode === "cover" ? "cover.pdf" : "interior.pdf";
    const pdfPath = join(tmpDir, pdfName);
    const pdfStat = await stat(pdfPath);

    res.setHeader("Content-Type", "application/pdf");
    res.setHeader("Content-Length", pdfStat.size);
    res.setHeader("Content-Disposition", `attachment; filename="${(title || "book").replace(/[^a-zA-Z0-9_-]/g, "_")}_${pdfName}"`);

    const { createReadStream } = await import("fs");
    const stream = createReadStream(pdfPath);
    stream.pipe(res);
    stream.on("end", () => { rmdir(tmpDir, { recursive: true }).catch(() => {}); });
    stream.on("error", () => { rmdir(tmpDir, { recursive: true }).catch(() => {}); });
  } catch (e) {
    if (tmpDir) rmdir(tmpDir, { recursive: true }).catch(() => {});
    console.error("Export error:", e);
    res.status(500).json({ error: typeof e === "string" ? e : e.message });
  }
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`Canvas Studio API → Postgres :5440, listening on :${PORT}`);
});
