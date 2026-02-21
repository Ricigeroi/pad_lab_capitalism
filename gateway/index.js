'use strict';

const http    = require('http');
const express = require('express');
const morgan  = require('morgan');
const Redis   = require('ioredis');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT              = parseInt(process.env.PORT       || '8000', 10);
const REDIS_URL         = process.env.REDIS_URL           || 'redis://redis:6379';
const CACHE_TTL         = parseInt(process.env.CACHE_TTL  || '30',   10); // seconds
const MAX_RETRIES       = parseInt(process.env.MAX_RETRIES || '2',   10); // extra attempts after 1st failure
const UNAVAILABLE_TTL   = parseInt(process.env.UNAVAILABLE_TTL || '60', 10); // seconds a failed replica is excluded

// ── Redis client ──────────────────────────────────────────────────────────────
const redis = new Redis(REDIS_URL, { lazyConnect: true });
redis.on('connect', () => console.log('[gateway] Redis connected'));
redis.on('error',   (e) => console.error(`[gateway] Redis error: ${e.message}`));
redis.connect().catch((e) => console.error(`[gateway] Redis initial connect failed: ${e.message}`));

// ── Cache stats ───────────────────────────────────────────────────────────────
const cacheStats = { hits: 0, misses: 0, bypassed: 0 };

// ── Target pools ──────────────────────────────────────────────────────────────
// Each target carries its own health state:
//   unavailableUntil = 0          → healthy (in rotation)
//   unavailableUntil = <timestamp> → excluded until that epoch-ms passes
const POOLS = {
  user: {
    targets: [
      { host: 'user_management_service_1', port: 8001, unavailableUntil: 0, failures: 0 },
      { host: 'user_management_service_2', port: 8001, unavailableUntil: 0, failures: 0 },
      { host: 'user_management_service_3', port: 8001, unavailableUntil: 0, failures: 0 },
    ],
    counter: 0,
  },
  enterprise: {
    targets: [
      { host: 'enterprise_management_service_1', port: 8002, unavailableUntil: 0, failures: 0 },
      { host: 'enterprise_management_service_2', port: 8002, unavailableUntil: 0, failures: 0 },
      { host: 'enterprise_management_service_3', port: 8002, unavailableUntil: 0, failures: 0 },
    ],
    counter: 0,
  },
};

// ── Health helpers ────────────────────────────────────────────────────────────
function isAvailable(target) {
  if (target.unavailableUntil === 0) return true;
  if (Date.now() >= target.unavailableUntil) {
    // cooldown expired – bring back into rotation
    target.unavailableUntil = 0;
    target.failures = 0;
    console.log(`[circuit] RECOVERED  ${target.host}:${target.port} – back in rotation`);
    return true;
  }
  return false;
}

function markUnavailable(target) {
  target.unavailableUntil = Date.now() + UNAVAILABLE_TTL * 1000;
  target.failures++;
  const until = new Date(target.unavailableUntil).toISOString();
  console.warn(`[circuit] OPEN  ${target.host}:${target.port} – excluded for ${UNAVAILABLE_TTL}s (until ${until})`);
}

// ── Round-robin picker (skips unavailable targets) ────────────────────────────
// Returns the next available target, or null if the entire pool is down.
function nextTarget(pool) {
  const total = pool.targets.length;
  for (let i = 0; i < total; i++) {
    const candidate = pool.targets[pool.counter % total];
    pool.counter = (pool.counter + 1) % total;
    if (isAvailable(candidate)) return candidate;
  }
  return null; // all replicas unavailable
}

// ── Low-level HTTP forwarder (promise-based, no http-proxy dependency) ────────
function forwardRequest(target, req, bodyBuffer) {
  return new Promise((resolve, reject) => {
    const options = {
      hostname: target.host,
      port:     target.port,
      path:     req._upstreamPath,
      method:   req.method,
      headers:  { ...req.headers, host: `${target.host}:${target.port}` },
      timeout:  5000,
    };

    const proxyReq = http.request(options, (proxyRes) => {
      const chunks = [];
      proxyRes.on('data', (c) => chunks.push(c));
      proxyRes.on('end',  () => resolve({ proxyRes, body: Buffer.concat(chunks) }));
    });

    proxyReq.on('timeout', () => {
      proxyReq.destroy();
      reject(new Error(`timeout after 5000ms`));
    });
    proxyReq.on('error', reject);

    if (bodyBuffer && bodyBuffer.length) proxyReq.write(bodyBuffer);
    proxyReq.end();
  });
}

// ── Body reader (buffers the incoming request body once) ──────────────────────
function readBody(req) {
  return new Promise((resolve) => {
    const chunks = [];
    req.on('data', (c) => chunks.push(c));
    req.on('end',  () => resolve(Buffer.concat(chunks)));
  });
}

// ── Core dispatch: retry + circuit-breaker ────────────────────────────────────
async function dispatch(pool, req, res, upstreamPrefix) {
  // Build the upstream path once (reused across retries)
  req._upstreamPath = (upstreamPrefix + req.url).replace(/\/+/g, '/') || '/';

  // Buffer the request body so it can be replayed on retries
  const bodyBuffer = await readBody(req);

  const maxAttempts = MAX_RETRIES + 1; // e.g. 3 total: 1 original + 2 retries
  let lastError;

  for (let attempt = 1; attempt <= maxAttempts; attempt++) {
    const target = nextTarget(pool);

    if (!target) {
      console.error('[circuit] ALL replicas unavailable – returning 503');
      if (!res.headersSent) {
        res.writeHead(503, { 'Content-Type': 'application/json' });
        res.end(JSON.stringify({
          detail: 'Service temporarily unavailable – all replicas are down',
        }));
      }
      return;
    }

    console.log(
      `[gateway] attempt ${attempt}/${maxAttempts}  ${req.method} ${req._upstreamPath}` +
      ` → ${target.host}:${target.port}`
    );

    try {
      const { proxyRes, body } = await forwardRequest(target, req, bodyBuffer);

      // ── Success path ──────────────────────────────────────────────────────
      // Cache the response if applicable
      if (req.method === 'GET' && proxyRes.statusCode >= 200 && proxyRes.statusCode < 300 && req._cacheKey) {
        try {
          const payload = JSON.stringify({
            status:  proxyRes.statusCode,
            headers: proxyRes.headers,
            body:    body.toString('utf8'),
          });
          await redis.set(req._cacheKey, payload, 'EX', CACHE_TTL);
          console.log(`[cache] SET  ${req._cacheKey}  (TTL ${CACHE_TTL}s)`);
        } catch (e) {
          console.error(`[cache] SET error: ${e.message}`);
        }
      }

      if (!res.headersSent) {
        res.writeHead(proxyRes.statusCode, proxyRes.headers);
        res.end(body);
      }
      return; // done

    } catch (err) {
      lastError = err;
      console.warn(
        `[circuit] attempt ${attempt}/${maxAttempts} FAILED` +
        ` – ${target.host}:${target.port}: ${err.message}`
      );

      // Mark the target unavailable only after it has exhausted all retries
      // that were aimed at it (here each attempt targets a different replica
      // picked by round-robin, so one failure = mark that replica unavailable)
      markUnavailable(target);
    }
  }

  // All attempts exhausted
  console.error(`[circuit] all ${maxAttempts} attempts failed. Last error: ${lastError.message}`);
  if (!res.headersSent) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({
      detail: `Upstream unreachable after ${maxAttempts} attempts: ${lastError.message}`,
    }));
  }
}

// ── Express app ───────────────────────────────────────────────────────────────
const app = express();
app.use(morgan(':method :url :status :res[content-length] - :response-time ms'));

// ── Status endpoint ───────────────────────────────────────────────────────────
function poolStatus(pool) {
  const now = Date.now();
  return {
    replicas: pool.targets.map(t => ({
      host:      t.host,
      port:      t.port,
      status:    isAvailable(t) ? 'healthy' : 'unavailable',
      available_in_seconds: t.unavailableUntil > now
        ? Math.ceil((t.unavailableUntil - now) / 1000)
        : 0,
      total_failures: t.failures,
    })),
  };
}

app.get('/status', (_req, res) => {
  res.json({
    status:  'ok',
    service: 'gateway',
    fault_tolerance: {
      max_retries:      MAX_RETRIES,
      unavailable_ttl:  UNAVAILABLE_TTL,
    },
    cache: {
      redis_url:   REDIS_URL,
      ttl_seconds: CACHE_TTL,
      ...cacheStats,
      ratio: cacheStats.hits + cacheStats.misses === 0
        ? 'n/a'
        : `${((cacheStats.hits / (cacheStats.hits + cacheStats.misses)) * 100).toFixed(1)}% hit rate`,
    },
    pools: {
      user:       poolStatus(POOLS.user),
      enterprise: poolStatus(POOLS.enterprise),
    },
  });
});

// ── Cache middleware ───────────────────────────────────────────────────────────
const NO_CACHE_SUFFIXES = ['/whoami', '/status'];

async function cacheMiddleware(req, res, next) {
  if (req.method !== 'GET') {
    cacheStats.bypassed++;
    return next();
  }

  const path = req.originalUrl.split('?')[0];
  if (NO_CACHE_SUFFIXES.some(s => path.endsWith(s))) {
    cacheStats.bypassed++;
    console.log(`[cache] BYPASS (no-cache path) ${req.originalUrl}`);
    return next();
  }

  const cacheKey = `gw:${req.originalUrl}`;
  req._cacheKey = cacheKey;

  try {
    const cached = await redis.get(cacheKey);
    if (cached) {
      cacheStats.hits++;
      const { status, headers, body } = JSON.parse(cached);
      console.log(`[cache] HIT  ${cacheKey}`);
      res.set(headers);
      res.set('X-Cache', 'HIT');
      res.set('X-Cache-TTL', String(CACHE_TTL));
      return res.status(status).send(body);
    }
  } catch (e) {
    console.error(`[cache] GET error: ${e.message}`);
  }

  cacheStats.misses++;
  console.log(`[cache] MISS ${cacheKey}`);
  res.set('X-Cache', 'MISS');
  next();
}

// ── Routing ───────────────────────────────────────────────────────────────────
app.use('/api/users',      cacheMiddleware, (req, res) => dispatch(POOLS.user,       req, res, ''));
app.use('/api/enterprise', cacheMiddleware, (req, res) => dispatch(POOLS.enterprise, req, res, '/enterprise'));

app.use((_req, res) => res.status(404).json({ detail: 'Route not found on gateway' }));

// ── Start ─────────────────────────────────────────────────────────────────────
const server = http.createServer(app);
server.listen(PORT, () => {
  console.log(`[gateway] listening on port ${PORT}`);
  console.log(`[gateway] fault tolerance  → max_retries=${MAX_RETRIES}  unavailable_ttl=${UNAVAILABLE_TTL}s`);
  console.log(`[gateway] Redis cache      → ${REDIS_URL}  (TTL ${CACHE_TTL}s)`);
  console.log(`[gateway] user pool        → ${POOLS.user.targets.map(t => t.host).join(', ')}`);
  console.log(`[gateway] enterprise pool  → ${POOLS.enterprise.targets.map(t => t.host).join(', ')}`);
});
