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
      "SELECT key, data->>'savedAt' as saved_at, data->>'step' as step, data->'bookSpec' as book_spec FROM books ORDER BY updated_at DESC"
    );
    const results = rows.map((r) => ({
      key: r.key,
      title: r.book_spec?.title || r.key,
      step: r.step,
      bookSpec: r.book_spec,
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

const PORT = 5174;
app.listen(PORT, "0.0.0.0", () => {
  console.log(`Canvas Studio API → Postgres :5440, listening on :${PORT}`);
});
