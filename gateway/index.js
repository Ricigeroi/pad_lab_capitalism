'use strict';

const http = require('http');
const httpProxy = require('http-proxy');
const express = require('express');
const morgan = require('morgan');

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
      { host: 'user_management_service', port: 8001 },
      { host: 'user_management_service', port: 8001 },
      { host: 'user_management_service', port: 8001 },
    ],
    counter: 0,
  },
  enterprise: {
    targets: [
      { host: 'enterprise_management_service', port: 8002 },
      { host: 'enterprise_management_service', port: 8002 },
      { host: 'enterprise_management_service', port: 8002 },
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
const proxy = httpProxy.createProxyServer({ changeOrigin: true });

proxy.on('error', (err, req, res) => {
  console.error(`[gateway] proxy error: ${err.message}`);
  if (!res.headersSent) {
    res.writeHead(502, { 'Content-Type': 'application/json' });
  }
  res.end(JSON.stringify({ detail: 'Bad gateway – upstream unreachable' }));
});

// ── Express app ───────────────────────────────────────────────────────────────
const app = express();
app.use(morgan(':method :url :status :res[content-length] - :response-time ms → :req[x-forwarded-host]'));

// ── Status endpoint ───────────────────────────────────────────────────────────
app.get('/status', (_req, res) => {
  res.json({
    status: 'ok',
    service: 'gateway',
    pools: {
      user:       { replicas: POOLS.user.targets.length,       requests: POOLS.user.counter },
      enterprise: { replicas: POOLS.enterprise.targets.length, requests: POOLS.enterprise.counter },
    },
  });
});

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

    // req.url has already been stripped of the mount prefix by Express.
    // Re-prepend the upstream's own base path when needed.
    const originalUrl = req.url;
    req.url = (upstreamPrefix + req.url).replace(/\/+/g, '/') || '/';

    console.log(
      `[gateway] ${req.method} ${originalPrefix}${originalUrl} → ${upstream}${req.url}  (pool[${(pool.counter === 0 ? pool.targets.length : pool.counter) - 1}])`
    );

    proxy.web(req, res, { target: upstream });
  };
}

// /api/users/**      → user_management_service:8001/**         (no prefix needed)
// /api/enterprise/** → enterprise_management_service:8002/enterprise/**
app.use('/api/users',      makeRouter(POOLS.user,       '',              '/api/users'));
app.use('/api/enterprise', makeRouter(POOLS.enterprise, '/enterprise',   '/api/enterprise'));

// Catch-all for unknown routes
app.use((_req, res) => {
  res.status(404).json({ detail: 'Route not found on gateway' });
});

// ── Start ─────────────────────────────────────────────────────────────────────
const PORT = process.env.PORT || 8000;
const server = http.createServer(app);

server.listen(PORT, () => {
  console.log(`[gateway] listening on port ${PORT}`);
  console.log(`[gateway] user pool        → ${POOLS.user.targets.length} replica(s) at user_management_service:8001`);
  console.log(`[gateway] enterprise pool  → ${POOLS.enterprise.targets.length} replica(s) at enterprise_management_service:8002`);
});
