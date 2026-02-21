'use strict';

const http = require('http');
const httpProxy = require('http-proxy');
const express = require('express');
const morgan = require('morgan');
const Redis = require('ioredis');

// ── Config ────────────────────────────────────────────────────────────────────
const PORT       = process.env.PORT       || 8000;
const REDIS_URL  = process.env.REDIS_URL  || 'redis://redis:6379';
const CACHE_TTL  = parseInt(process.env.CACHE_TTL || '30', 10); // seconds

// ── Redis client ──────────────────────────────────────────────────────────────
const redis = new Redis(REDIS_URL, { lazyConnect: true });

redis.on('connect',  () => console.log('[gateway] Redis connected'));
redis.on('error',    (e) => console.error(`[gateway] Redis error: ${e.message}`));

redis.connect().catch((e) => console.error(`[gateway] Redis initial connect failed: ${e.message}`));

// ── Cache stats ───────────────────────────────────────────────────────────────
const cacheStats = { hits: 0, misses: 0, bypassed: 0 };

// ── Target pools ──────────────────────────────────────────────────────────────
// Docker Compose replicas are reachable via the service name as the hostname.
// With `deploy.replicas: 3`, Docker's internal DNS returns all 3 task IPs when
// the service name is resolved, but to implement explicit round-robin here we
// list the tasks by their Compose-assigned hostnames (tasks.<service>.<index>
// are not guaranteed; Docker Swarm uses them but plain Compose does not).
//
// For plain `docker compose up --scale`, replicas share one DNS name and Docker
// load-balances at the network level. We still implement our own round-robin on
// top by tracking a counter per pool – this gives us visible, deterministic
// balancing and lets us add health-aware skipping later.
//
// The hostnames below match the service names declared in docker-compose.yml.
// Each replica is identical, so we point all slots at the same hostname and let
// our counter cycle through them – in practice Docker will map each connection
// to a different container via its internal IPVS load-balancer.
//
// If you switch to Docker Swarm, replace the entries with:
//   "tasks.user_management_service" (resolves to all task IPs via DNS round-robin)

const POOLS = {
  user: {
    targets: [
      { host: 'user_management_service_1', port: 8001 },
      { host: 'user_management_service_2', port: 8001 },
      { host: 'user_management_service_3', port: 8001 },
    ],
    counter: 0,
  },
  enterprise: {
    targets: [
      { host: 'enterprise_management_service_1', port: 8002 },
      { host: 'enterprise_management_service_2', port: 8002 },
      { host: 'enterprise_management_service_3', port: 8002 },
    ],
    counter: 0,
  },
};

// ── Round-robin picker ────────────────────────────────────────────────────────
function nextTarget(pool) {
  const target = pool.targets[pool.counter % pool.targets.length];
  pool.counter = (pool.counter + 1) % pool.targets.length;
  return target;
}

// ── Proxy ─────────────────────────────────────────────────────────────────────
const proxy = httpProxy.createProxyServer({ changeOrigin: true, selfHandleResponse: true });

proxy.on('error', (err, req, res) => {
  console.error(`[gateway] proxy error: ${err.message}`);
  if (!res.headersSent) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
  }
  res.end(JSON.stringify({ detail: 'Bad gateway – upstream unreachable' }));
});

// Intercept upstream response to buffer body, cache it, then forward to client
proxy.on('proxyRes', (proxyRes, req, res) => {
  const chunks = [];
  proxyRes.on('data', (chunk) => chunks.push(chunk));
  proxyRes.on('end', async () => {
    const body = Buffer.concat(chunks);
    const statusCode = proxyRes.statusCode;

    // Forward status + headers to client
    res.writeHead(statusCode, proxyRes.headers);
    res.end(body);

    // Only cache successful GET responses
    if (req.method === 'GET' && statusCode >= 200 && statusCode < 300 && req._cacheKey) {
      try {
        const payload = JSON.stringify({
          status:  statusCode,
          headers: proxyRes.headers,
          body:    body.toString('utf8'),
        });
        await redis.set(req._cacheKey, payload, 'EX', CACHE_TTL);
        console.log(`[cache] SET  ${req._cacheKey}  (TTL ${CACHE_TTL}s)`);
      } catch (e) {
        console.error(`[cache] SET error: ${e.message}`);
      }
    }
  });
});

// ── Express app ───────────────────────────────────────────────────────────────
const app = express();
app.use(morgan(':method :url :status :res[content-length] - :response-time ms'));

// ── Status endpoint ───────────────────────────────────────────────────────────
app.get('/status', (_req, res) => {
  res.json({
    status: 'ok',
    service: 'gateway',
    cache: {
      redis_url: REDIS_URL,
      ttl_seconds: CACHE_TTL,
      ...cacheStats,
      ratio: cacheStats.hits + cacheStats.misses === 0
        ? 'n/a'
        : `${((cacheStats.hits / (cacheStats.hits + cacheStats.misses)) * 100).toFixed(1)}% hit rate`,
    },
    pools: {
      user:       { replicas: POOLS.user.targets.length,       requests: POOLS.user.counter },
      enterprise: { replicas: POOLS.enterprise.targets.length, requests: POOLS.enterprise.counter },
    },
  });
});

// ── Cache middleware (GET only) ───────────────────────────────────────────────
async function cacheMiddleware(req, res, next) {
  // Never cache non-GET requests (mutations must always hit upstream)
  if (req.method !== 'GET') {
    cacheStats.bypassed++;
    return next();
  }

  const cacheKey = `gw:${req.originalUrl}`;
  req._cacheKey = cacheKey; // pass key to proxyRes handler for SET

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

// ── Routing rules ─────────────────────────────────────────────────────────────
// Express strips the mount prefix from req.url before our handler runs, so:
//   incoming: /api/users/register       → req.url inside handler: /register
//   incoming: /api/enterprise/1/roles   → req.url inside handler: /1/roles
//
// The enterprise service owns the /enterprise/* namespace, so we must
// re-prepend "/enterprise" to every request routed there.
// The user service owns routes at the root (/, /register, /login, /user/…),
// so no rewrite is needed.

function makeRouter(pool, upstreamPrefix, originalPrefix) {
  return (req, res) => {
    const target = nextTarget(pool);
    const upstream = `http://${target.host}:${target.port}`;

    const originalUrl = req.url;
    req.url = (upstreamPrefix + req.url).replace(/\/+/g, '/') || '/';

    console.log(
      `[gateway] ${req.method} ${originalPrefix}${originalUrl} → ${upstream}${req.url}  (pool[${(pool.counter === 0 ? pool.targets.length : pool.counter) - 1}])`
    );

    proxy.web(req, res, { target: upstream });
  };
}

// Apply cache middleware then proxy
// /api/users/**      → user_management_service:8001/**
// /api/enterprise/** → enterprise_management_service:8002/enterprise/**
app.use('/api/users',      cacheMiddleware, makeRouter(POOLS.user,       '',            '/api/users'));
app.use('/api/enterprise', cacheMiddleware, makeRouter(POOLS.enterprise, '/enterprise', '/api/enterprise'));

// Catch-all for unknown routes
app.use((_req, res) => {
  res.status(404).json({ detail: 'Route not found on gateway' });
});

// ── Start ─────────────────────────────────────────────────────────────────────
const server = http.createServer(app);

server.listen(PORT, () => {
  console.log(`[gateway] listening on port ${PORT}`);
  console.log(`[gateway] Redis cache       → ${REDIS_URL}  (TTL ${CACHE_TTL}s)`);
  console.log(`[gateway] user pool         → ${POOLS.user.targets.map(t => t.host).join(', ')}`);
  console.log(`[gateway] enterprise pool   → ${POOLS.enterprise.targets.map(t => t.host).join(', ')}`);
});
