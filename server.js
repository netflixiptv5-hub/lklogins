import express from "express";
import path from "path";
import { fileURLToPath } from "url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const app = express();
const PORT = process.env.PORT || 3000;
const WORKER_URL = "http://127.0.0.1:8787";

// === In-memory job store ===
const jobs = new Map();

function generateJobId() {
  return Math.random().toString(36).substring(2, 15) + Date.now().toString(36);
}

// Cleanup old jobs every 5 min
setInterval(() => {
  const now = Date.now();
  for (const [id, j] of jobs) {
    if (now - j.createdAt > 30 * 60 * 1000) jobs.delete(id);
  }
}, 5 * 60 * 1000);

// === API Routes ===
app.use(express.json());

app.post("/api/extract", (req, res) => {
  const { email, service } = req.body;
  if (!email || !service) return res.json({ ok: false, error: "Email e serviço são obrigatórios." });

  const validServices = ["password_reset", "household_update", "temp_code", "netflix_disconnect", "prime_code", "disney_code", "globo_reset"];
  if (!validServices.includes(service)) return res.json({ ok: false, error: "Serviço inválido." });

  const jobId = generateJobId();
  jobs.set(jobId, { status: "connecting", email, service, createdAt: Date.now() });

  // Fire-and-forget to Python worker
  fetch(`${WORKER_URL}/run`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ jobId, email, service }),
  }).catch(() => {});

  res.json({ ok: true, jobId });
});

app.get("/api/status/:jobId", (req, res) => {
  const job = jobs.get(req.params.jobId);
  if (!job) return res.json({ ok: false, error: "Job não encontrado." });
  res.json({
    ok: true,
    status: job.status,
    link: job.link,
    code: job.code,
    message: job.message,
    method: job.method,
    eta: job.eta,
    expired: job.expired || false,
  });
});

app.get("/api/logs/:jobId", async (req, res) => {
  try {
    const r = await fetch(`${WORKER_URL}/logs/${req.params.jobId}`);
    const data = await r.json();
    res.json(data);
  } catch (e) {
    res.json({ ok: false, error: "Worker indisponível." });
  }
});

app.post("/api/update", (req, res) => {
  const { jobId, status, link, code, message, method, eta, expired } = req.body;
  const job = jobs.get(jobId);
  if (!job) return res.json({ ok: false, error: "Job não encontrado." });
  
  if (status) job.status = status;
  if (link) job.link = link;
  if (code) job.code = code;
  if (message) job.message = message;
  if (method) job.method = method;
  if (eta !== undefined) job.eta = eta;
  if (expired !== undefined) job.expired = expired;

  res.json({ ok: true });
});

// === Serve static frontend ===
app.use(express.static(path.join(__dirname, "dist/public")));

// SPA fallback
app.get("/{*path}", (req, res) => {
  res.sendFile(path.join(__dirname, "dist/public", "index.html"));
});

app.listen(PORT, "0.0.0.0", () => {
  console.log(`Server running on port ${PORT}`);
});
