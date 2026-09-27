'use strict';

const path = require('path');
const express = require('express');
const { Pool } = require('pg');

const PORT = process.env.PORT || 8080;
const ROLES = new Set(['seller', 'supplier', 'carrier']);

// Field lengths mirror the columns below, so an oversized payload is rejected
// before it reaches the database rather than being silently truncated.
const LIMITS = { full_name: 120, email: 180, company: 160, categories: 400, message: 2000 };

const app = express();
app.disable('x-powered-by');
app.set('trust proxy', true);
app.use(express.json({ limit: '16kb' }));

const pool = process.env.DATABASE_URL
  ? new Pool({
      connectionString: process.env.DATABASE_URL,
      // Railway's internal Postgres presents a self-signed certificate.
      ssl: process.env.DATABASE_URL.includes('railway.internal')
        ? false
        : { rejectUnauthorized: false },
      max: 4,
      idleTimeoutMillis: 30_000,
    })
  : null;

async function ensureSchema() {
  if (!pool) return;
  await pool.query(`
    CREATE TABLE IF NOT EXISTS registrations (
      id          BIGSERIAL PRIMARY KEY,
      role        TEXT        NOT NULL,
      full_name   TEXT        NOT NULL,
      email       TEXT        NOT NULL,
      company     TEXT        NOT NULL,
      categories  TEXT,
      message     TEXT,
      accepted    BOOLEAN     NOT NULL,
      lang        TEXT,
      source      TEXT,
      user_agent  TEXT,
      created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
    )
  `);
  await pool.query(
    `CREATE INDEX IF NOT EXISTS registrations_created_at_idx ON registrations (created_at DESC)`
  );
  await pool.query(
    `CREATE INDEX IF NOT EXISTS registrations_role_idx ON registrations (role)`
  );
}

// Two in-memory buckets. The address bucket stops a bored script; the e-mail
// bucket still catches it when the address rotates, which it does behind some
// proxies. Neither substitutes for a real WAF, and both reset on restart.
const buckets = new Map();
function overLimit(key, max, windowMs) {
  const now = Date.now();
  const rec = buckets.get(key);
  if (!rec || now - rec.start > windowMs) {
    buckets.set(key, { start: now, count: 1 });
    return false;
  }
  rec.count += 1;
  if (buckets.size > 8000) buckets.clear();
  return rec.count > max;
}
function rateLimited(ip, email) {
  const byIp = overLimit(`ip:${ip}`, 5, 60_000);
  const byEmail = overLimit(`em:${email}`, 3, 3_600_000);
  return byIp || byEmail;
}

function clean(value, max) {
  if (typeof value !== 'string') return '';
  return value.replace(/\s+/g, ' ').trim().slice(0, max);
}

// Deliberately permissive: the goal is to catch typos, not to adjudicate which
// addresses RFC 5322 allows.
const EMAIL = /^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/;

app.post('/api/registro', async (req, res) => {
  const body = req.body || {};
  const role = String(body.role || '');
  if (!ROLES.has(role)) return res.status(400).json({ error: 'role' });

  const full_name = clean(body.full_name, LIMITS.full_name);
  const email = clean(body.email, LIMITS.email).toLowerCase();
  const company = clean(body.company, LIMITS.company);
  const categories = clean(body.categories, LIMITS.categories);
  const message = clean(body.message, LIMITS.message);
  const accepted = body.accept === true || body.accept === 'true';

  const missing = [];
  if (full_name.length < 2) missing.push('full_name');
  if (!EMAIL.test(email)) missing.push('email');
  if (company.length < 2) missing.push('company');
  if (!accepted) missing.push('accept');
  if (missing.length) return res.status(422).json({ error: 'fields', fields: missing });

  // Honeypot: a field no human sees, so anything in it is a bot. Answer 200 so
  // the sender learns nothing from the response.
  if (clean(body.website, 80)) return res.json({ ok: true });

  if (rateLimited(req.ip || 'unknown', email)) return res.status(429).json({ error: 'rate' });

  if (!pool) {
    console.error('[registro] DATABASE_URL is not set; submission not stored');
    return res.status(503).json({ error: 'storage' });
  }

  try {
    const { rows } = await pool.query(
      `INSERT INTO registrations
         (role, full_name, email, company, categories, message, accepted, lang, source, user_agent)
       VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10)
       RETURNING id`,
      [
        role,
        full_name,
        email,
        company,
        categories || null,
        message || null,
        accepted,
        clean(body.lang, 8) || null,
        clean(body.source, 80) || null,
        clean(req.get('user-agent'), 300) || null,
      ]
    );
    // No personal data in the logs: the id is enough to find the row.
    console.log(`[registro] stored id=${rows[0].id} role=${role}`);
    return res.json({ ok: true });
  } catch (err) {
    console.error('[registro] insert failed:', err.message);
    return res.status(500).json({ error: 'server' });
  }
});

app.get('/health', async (_req, res) => {
  if (!pool) return res.type('text').send('ok (sin base de datos)');
  try {
    await pool.query('SELECT 1');
    res.type('text').send('ok');
  } catch {
    res.status(503).type('text').send('sin base de datos');
  }
});

const STATIC = __dirname;
app.use(
  express.static(STATIC, {
    extensions: ['html'], // /suppliers resolves to suppliers.html
    setHeaders(res, filePath) {
      if (/\.(html|css|js)$/.test(filePath)) {
        res.setHeader('Cache-Control', 'no-cache');
      } else {
        res.setHeader('Cache-Control', 'public, max-age=2592000');
      }
      res.setHeader('X-Content-Type-Options', 'nosniff');
      res.setHeader('X-Frame-Options', 'SAMEORIGIN');
      res.setHeader('Referrer-Policy', 'strict-origin-when-cross-origin');
    },
  })
);

app.use((_req, res) => res.status(404).sendFile(path.join(STATIC, '404.html'), (err) => {
  if (err) res.type('text').send('No encontrado');
}));

ensureSchema()
  .catch((err) => console.error('[schema]', err.message))
  .finally(() => {
    app.listen(PORT, () => console.log(`landing-ventu escuchando en :${PORT}`));
  });
