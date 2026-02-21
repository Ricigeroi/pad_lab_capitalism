# 🏭 Capitalism Simulation Table — Microservices Platform

A fully containerised microservice application built for the **Capitalism Simulation Table** board game.
Players register, manage enterprises (factories, research labs, transport systems), earn XP through achievements, build teams, and collaborate on industrial projects — all through a unified API gateway.

---

## 📑 Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Services Reference](#2-services-reference)
3. [Project Structure](#3-project-structure)
4. [Setup & Running with Docker Compose](#4-setup--running-with-docker-compose)
5. [API Reference](#5-api-reference)
6. [Testing with Swagger UI](#6-testing-with-swagger-ui)
7. [Testing with Postman](#7-testing-with-postman)
8. [pgAdmin — Querying the Databases](#8-pgadmin--querying-the-databases)
9. [How the API Gateway Works](#9-how-the-api-gateway-works)
10. [How Redis Caching Works](#10-how-redis-caching-works)
11. [Complete Demo Walk-through](#11-complete-demo-walk-through)
12. [Proving Round-Robin & Cache in Action](#12-proving-round-robin--cache-in-action)

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│                        Client (Browser / Postman / curl)        │
└───────────────────────────────┬─────────────────────────────────┘
                                │ :8000
                                ▼
                    ┌───────────────────────┐
                    │     API Gateway       │  Node.js + Express
                    │   (Round-Robin LB)    │  + Redis Cache
                    └────────┬──────┬───────┘
                             │      │
              ┌──────────────┘      └──────────────┐
              │  /api/users/**                      │  /api/enterprise/**
              ▼                                     ▼
  ┌─────────────────────────┐           ┌──────────────────────────────┐
  │  user_management        │           │  enterprise_management       │
  │  service_1  :8001       │           │  service_1  :8002            │
  │  service_2  :8001       │           │  service_2  :8002            │
  │  service_3  :8001       │           │  service_3  :8002            │
  └────────────┬────────────┘           └─────────────┬────────────────┘
               │                                      │
               ▼                                      ▼
  ┌────────────────────────┐           ┌──────────────────────────────┐
  │  postgres_user_mgmt    │           │  postgres_enterprise         │
  │  (PostgreSQL :5433)    │           │  (PostgreSQL :5434)          │
  └────────────────────────┘           └──────────────────────────────┘
               ▲
  ┌────────────┴───────────┐
  │  Redis Cache  :6379    │
  │  (used by Gateway)     │
  └────────────────────────┘
```

> **Key design decisions:**
> - Each microservice has its **own isolated PostgreSQL database** — no shared schemas, no cross-DB foreign keys.
> - The gateway is the **single public entry-point** (port `8000`). No service port is exposed except through it (except pgAdmin and Postgres for dev access).
> - JWT tokens are issued by `user_management_service` and **shared via the same `SECRET_KEY`**, so `enterprise_management_service` can validate them without calling back to the user service.
> - Enterprise replicas call `user_management_service_1` directly to fetch user profiles for the `/roles` enrichment — an intentional inter-service HTTP call.

---

## 2. Services Reference

| Container | Technology | Port | Purpose |
|---|---|---|---|
| `gateway` | Node.js 20, Express, ioredis | **8000** | Single public entry-point; round-robin load balancer; Redis cache |
| `user_management_service_1/2/3` | Python 3.12, FastAPI, SQLAlchemy | internal 8001 | User registration, login, profiles, XP, achievements, teams |
| `enterprise_management_service_1/2/3` | Python 3.12, FastAPI, SQLAlchemy | internal 8002 | Enterprise creation, project management, role assignment |
| `postgres_user_mgmt` | PostgreSQL 16 | 5433 | Dedicated database for user service |
| `postgres_enterprise` | PostgreSQL 16 | 5434 | Dedicated database for enterprise service |
| `redis` | Redis 7 | 6379 | Response cache for the gateway (GET requests only) |
| `pgadmin` | pgAdmin 4 | 5050 | Web UI for browsing both PostgreSQL databases |

### Why each service exists

**`gateway`** — Clients should never need to know how many replicas exist or on which port. The gateway provides a single stable URL, distributes load evenly across replicas using explicit round-robin, and reduces upstream traffic via Redis caching.

**`user_management_service` (×3)** — Handles everything identity-related: registration, JWT-based login, user profiles, XP, achievements, and team membership. Running 3 replicas ensures the most-called service (login, profile reads) stays responsive under load.

**`enterprise_management_service` (×3)** — Manages the game's productive ventures. Separated from the user service to respect the Single Responsibility Principle and allow independent scaling. Calls the user service only when it needs to enrich role data with human-readable usernames.

**`postgres_user_mgmt` / `postgres_enterprise`** — Separate database instances enforce data isolation. An outage or schema migration in one cannot affect the other. Each runs in its own named Docker volume so data persists across container restarts.

**`redis`** — Caching at the gateway level means repeated reads (e.g. `GET /api/users/user/1`) are served from memory in ~1ms instead of hitting FastAPI + PostgreSQL every time. This is especially valuable for achievement lists and enterprise role pages that change infrequently.

**`pgadmin`** — Developer convenience tool for inspecting both databases without needing a local PostgreSQL client.

---

## 3. Project Structure

```
pad_lab_capitalism/
├── docker-compose.yml
├── README.md
│
├── gateway/
│   ├── Dockerfile
│   ├── package.json
│   └── index.js                  # Round-robin + Redis cache logic
│
├── user_management_service/
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── main.py                   # FastAPI app entry-point + /status + /whoami
│   ├── core/
│   │   ├── config.py             # Pydantic settings (DATABASE_URL, SECRET_KEY…)
│   │   ├── security.py           # bcrypt hashing, JWT create/decode
│   │   └── dependencies.py       # get_db(), get_current_user() FastAPI deps
│   ├── db/
│   │   └── session.py            # Async SQLAlchemy engine + Base + init_db()
│   ├── models/                   # SQLAlchemy ORM models
│   │   ├── user.py
│   │   ├── achievement.py
│   │   ├── equipment.py
│   │   └── team.py
│   ├── schemas/                  # Pydantic request/response schemas
│   │   ├── user.py
│   │   ├── achievement.py
│   │   └── team.py
│   └── routers/                  # FastAPI route handlers
│       ├── auth.py               # POST /register, POST /login
│       ├── users.py              # GET/PUT /user/{id}, achievements
│       ├── achievements.py       # POST/GET /achievements
│       └── teams.py              # POST /teams, GET /teams/{id}, join
│
└── enterprise_management_service/
    ├── Dockerfile
    ├── requirements.txt
    ├── main.py
    ├── core/
    │   ├── config.py
    │   ├── security.py           # JWT decode only (tokens issued by user service)
    │   ├── dependencies.py       # get_db(), get_current_user_id()
    │   └── user_client.py        # Async HTTP client → user_management_service
    ├── db/
    │   └── session.py
    ├── models/
    │   ├── enterprise.py         # Enterprise (factory/lab/transport/bank…)
    │   ├── role.py               # EnterpriseRole (inventor/strategist…)
    │   └── project.py            # Project under an enterprise
    ├── schemas/
    │   ├── enterprise.py
    │   └── project.py
    └── routers/
        ├── enterprises.py        # /enterprise/create, /{id}, /roles
        └── projects.py           # /enterprise/{id}/projects
```

---

## 4. Setup & Running with Docker Compose

### Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) ≥ 24 (includes Compose v2)
- No local PostgreSQL or Redis needed — everything runs in containers.

### Step 1 — Clone / open the project

```bash
cd /path/to/pad_lab_capitalism
```

### Step 2 — Start all services

```bash
docker compose up -d
```

Docker will:
1. Pull base images (`postgres:16-alpine`, `redis:7-alpine`, `node:20-alpine`, `python:3.12-slim`, `dpage/pgadmin4`)
2. Build the three service images (`gateway`, `user_management_service`, `enterprise_management_service`)
3. Start containers in dependency order:
   - PostgreSQL instances first (with health-checks)
   - Redis (with health-check)
   - 3× user replicas + 3× enterprise replicas (after their DB is healthy)
   - Gateway (after Redis is healthy and all replicas are started)
   - pgAdmin

### Step 3 — Verify all 11 containers are running

```bash
docker compose ps
```

Expected output (all `running` or `healthy`):

```
NAME                             STATUS
gateway                          running
redis                            running (healthy)
postgres_user_mgmt               running (healthy)
postgres_enterprise              running (healthy)
user_management_service_1        running
user_management_service_2        running
user_management_service_3        running
enterprise_management_service_1  running
enterprise_management_service_2  running
enterprise_management_service_3  running
pgadmin                          running
```

### Step 4 — Confirm the gateway is up

```bash
curl http://localhost:8000/status
```

```json
{
  "status": "ok",
  "service": "gateway",
  "cache": { "hits": 0, "misses": 0, "bypassed": 0, "ratio": "n/a" },
  "pools": {
    "user":       { "replicas": 3, "requests": 0 },
    "enterprise": { "replicas": 3, "requests": 0 }
  }
}
```

### Stopping & cleaning up

```bash
# Stop all containers (data is preserved in volumes)
docker compose down

# Stop AND delete all volumes (wipes all data)
docker compose down -v
```

### Environment variables (reference)

All variables are set in `docker-compose.yml`. Key ones:

| Variable | Service | Default | Description |
|---|---|---|---|
| `DATABASE_URL` | user / enterprise | see compose | Async PostgreSQL DSN |
| `SECRET_KEY` | user / enterprise / gateway | `changeme_…` | JWT signing key — **change in production** |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | user | `30` | JWT lifetime in minutes |
| `REDIS_URL` | gateway | `redis://redis:6379` | Redis connection string |
| `CACHE_TTL` | gateway | `30` | Cache entry lifetime in seconds |
| `REPLICA_ID` | user / enterprise | `user-1` … | Human-readable replica identifier |
| `USER_SERVICE_URL` | enterprise | `http://user_management_service_1:8001` | Base URL for inter-service user profile calls |

---

## 5. API Reference

All requests go through the gateway on **`http://localhost:8000`**.

### URL mapping

| Public path prefix | Routes to | Internal port |
|---|---|---|
| `/api/users/**` | `user_management_service_1/2/3` | 8001 |
| `/api/enterprise/**` | `enterprise_management_service_1/2/3` | 8002 |
| `/status` | gateway itself | — |

> **Path rewriting:** `/api/users/register` → upstream `/register`  
> `/api/enterprise/1/roles` → upstream `/enterprise/1/roles`

### User Management endpoints

| Method | Gateway URL | Auth | Description |
|---|---|---|---|
| `POST` | `/api/users/register` | — | Register a new user |
| `POST` | `/api/users/login` | — | Login → returns JWT token |
| `GET` | `/api/users/user/{id}` | — | Get user profile |
| `PUT` | `/api/users/user/{id}` | ✅ JWT | Update email or password |
| `POST` | `/api/users/achievements` | — | Create an achievement definition |
| `GET` | `/api/users/achievements` | — | List all achievement definitions |
| `GET` | `/api/users/achievements/{id}` | — | Get a single achievement |
| `POST` | `/api/users/user/{id}/achievement` | ✅ JWT | Grant achievement to user (awards XP) |
| `GET` | `/api/users/user/{id}/achievements` | — | List achievements earned by user |
| `POST` | `/api/users/teams` | ✅ JWT | Create a team (caller becomes leader) |
| `GET` | `/api/users/teams/{id}` | — | Get team details + members |
| `POST` | `/api/users/teams/{id}/join` | ✅ JWT | Join a team |
| `GET` | `/api/users/whoami` | — | Returns which replica handled the request |
| `GET` | `/api/users/status` | — | Health check |

### Enterprise Management endpoints

| Method | Gateway URL | Auth | Description |
|---|---|---|---|
| `POST` | `/api/enterprise/enterprise/create` | ✅ JWT | Create a new enterprise (factory, lab…) |
| `GET` | `/api/enterprise/enterprise/{id}` | — | Get enterprise details + member roles |
| `GET` | `/api/enterprise/enterprises` | — | List all enterprises (filter by `?status_filter=active`) |
| `PUT` | `/api/enterprise/enterprise/{id}` | ✅ JWT | Update enterprise (owner only) |
| `POST` | `/api/enterprise/enterprise/{id}/roles` | ✅ JWT | Assign role to user (owner only) |
| `GET` | `/api/enterprise/enterprise/{id}/roles` | — | List roles, enriched with user profiles |
| `POST` | `/api/enterprise/enterprise/{id}/projects` | ✅ JWT | Create project under enterprise |
| `GET` | `/api/enterprise/enterprise/{id}/projects` | — | List projects |
| `GET` | `/api/enterprise/enterprise/{id}/projects/{pid}` | — | Get single project |
| `PUT` | `/api/enterprise/enterprise/{id}/projects/{pid}` | ✅ JWT | Update project status/budget |
| `GET` | `/api/enterprise/whoami` | — | Returns which replica handled the request |
| `GET` | `/api/enterprise/status` | — | Health check |

---

## 6. Testing with Swagger UI

Both services expose automatic interactive documentation powered by FastAPI's built-in Swagger UI.

> **Note:** Swagger accesses the services directly (bypassing the gateway), which is useful for development. For production-like testing use Postman or curl through the gateway.

### User Management Service Swagger

Open in your browser: **[http://localhost:8001/docs](http://localhost:8001/docs)**  
_(Direct access to replica 1 — or any replica by changing the port in docker-compose for dev purposes)_

### Enterprise Management Service Swagger

Open in your browser: **[http://localhost:8002/docs](http://localhost:8002/docs)**

### How to authenticate in Swagger

1. First use `POST /register` or `POST /login` to obtain a JWT token.
2. Copy the `access_token` value from the response.
3. Click the **"Authorize"** button (🔒 padlock icon) at the top right of the Swagger page.
4. In the dialog, paste the token into the **"Value"** field:
   ```
   Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...
   ```
5. Click **"Authorize"** then **"Close"**.
6. All subsequent requests from that session will include the `Authorization: Bearer <token>` header automatically.

---

## 7. Testing with Postman

### Import the collection

You can manually create requests or use the following setup:

**Base URL variable:** Set a Postman environment variable:
```
base_url = http://localhost:8000
```

### Setting up authentication

1. Send `POST {{base_url}}/api/users/login` with body:
   ```json
   { "username": "your_username", "password": "your_password" }
   ```
2. In the **Tests** tab of the login request, add this script to auto-save the token:
   ```javascript
   const resp = pm.response.json();
   pm.environment.set("token", resp.access_token);
   ```
3. On any protected request, go to the **Authorization** tab → Type: **Bearer Token** → Token: `{{token}}`

### Example requests

#### Register a user
- **Method:** `POST`
- **URL:** `{{base_url}}/api/users/register`
- **Body (JSON):**
  ```json
  {
    "username": "john_doe",
    "email": "john@example.com",
    "password": "secret123"
  }
  ```

#### Login
- **Method:** `POST`
- **URL:** `{{base_url}}/api/users/login`
- **Body (JSON):**
  ```json
  {
    "username": "john_doe",
    "password": "secret123"
  }
  ```
- **Response:**
  ```json
  { "access_token": "eyJ...", "token_type": "bearer" }
  ```

#### Create an enterprise (requires token)
- **Method:** `POST`
- **URL:** `{{base_url}}/api/enterprise/enterprise/create`
- **Authorization:** Bearer `{{token}}`
- **Body (JSON):**
  ```json
  {
    "name": "Iron Works",
    "description": "Heavy manufacturing plant",
    "enterprise_type": "factory",
    "capital_invested": 5000
  }
  ```

### Checking cache headers in Postman

After making any `GET` request, look in the response **Headers** tab for:
- `X-Cache: MISS` — served from upstream (first request)
- `X-Cache: HIT` — served from Redis cache (subsequent requests within TTL)
- `X-Cache-TTL: 30` — seconds until cache entry expires

---

## 8. pgAdmin — Querying the Databases

### Login to pgAdmin

1. Open **[http://localhost:5050](http://localhost:5050)** in your browser.
2. Log in with:
   - **Email:** `admin@example.com`
   - **Password:** `admin`

### Add the User Management database server

1. Right-click **"Servers"** in the left panel → **"Register" → "Server…"**
2. **General tab:**
   - Name: `User DB`
3. **Connection tab:**
   - Host: `postgres_user_mgmt`
   - Port: `5432`
   - Maintenance database: `user_management_db`
   - Username: `capitalism_user`
   - Password: `capitalism_pass`
4. Click **Save**.

### Add the Enterprise Management database server

1. Right-click **"Servers"** → **"Register" → "Server…"**
2. **General tab:**
   - Name: `Enterprise DB`
3. **Connection tab:**
   - Host: `postgres_enterprise`
   - Port: `5432`
   - Maintenance database: `enterprise_management_db`
   - Username: `capitalism_user`
   - Password: `capitalism_pass`
4. Click **Save**.

### Running queries

Navigate to: `Servers → User DB → Databases → user_management_db → Schemas → public → Tables`

Right-click any table → **"Query Tool"**, then run SQL:

```sql
-- List all registered users with XP
SELECT id, username, email, xp, capital, created_at
FROM users
ORDER BY xp DESC;

-- List all achievements with XP rewards
SELECT * FROM achievements;

-- List which users earned which achievements
SELECT u.username, a.name AS achievement, a.xp_reward, ua.earned_at
FROM user_achievements ua
JOIN users u ON u.id = ua.user_id
JOIN achievements a ON a.id = ua.achievement_id
ORDER BY ua.earned_at DESC;

-- List all teams and their members
SELECT t.name AS team, u.username, tm.role, tm.joined_at
FROM team_members tm
JOIN teams t ON t.id = tm.team_id
JOIN users u ON u.id = tm.user_id
ORDER BY t.name;
```

Switch to `Enterprise DB` and run:

```sql
-- All enterprises with status
SELECT id, name, enterprise_type, status, owner_id, capital_invested, created_at
FROM enterprises
ORDER BY created_at DESC;

-- All role assignments
SELECT e.name AS enterprise, er.user_id, er.role, er.assigned_at
FROM enterprise_roles er
JOIN enterprises e ON e.id = er.enterprise_id;

-- All projects with their status
SELECT e.name AS enterprise, p.name AS project, p.status, p.budget
FROM projects p
JOIN enterprises e ON e.id = p.enterprise_id;
```

---

## 9. How the API Gateway Works

The gateway is a **Node.js / Express** application (`gateway/index.js`) that acts as the single entry-point for all client requests.

### Routing

```
/api/users/**      ─→  strips /api/users  ─→  forwards to user pool    :8001/**
/api/enterprise/** ─→  strips /api/enterprise,
                        prepends /enterprise ─→  forwards to enterprise pool  :8002/enterprise/**
/status            ─→  handled locally (pool stats + cache stats)
```

> Express automatically strips the mount-prefix from `req.url`, so `/api/users/login` arrives in the handler as `/login`. The enterprise service needs the `/enterprise` namespace prepended back, which the gateway does before forwarding.

### Round-Robin Load Balancing

Each service pool is a JavaScript object holding:
- An array of `{ host, port }` targets — one per named replica
- A `counter` integer, starting at 0

```javascript
const POOLS = {
  user: {
    targets: [
      { host: 'user_management_service_1', port: 8001 },
      { host: 'user_management_service_2', port: 8001 },
      { host: 'user_management_service_3', port: 8001 },
    ],
    counter: 0,
  },
  // ...
};

function nextTarget(pool) {
  const target = pool.targets[pool.counter % pool.targets.length];
  pool.counter = (pool.counter + 1) % pool.targets.length;
  return target;
}
```

Every incoming request calls `nextTarget()`, which:
1. Reads `targets[counter % 3]` → selects replica 0, 1, or 2
2. Increments and wraps the counter

This is **explicit, deterministic round-robin**: request 1 → replica 1, request 2 → replica 2, request 3 → replica 3, request 4 → replica 1 again.

Because each replica has a **distinct hostname** in Docker Compose (`user_management_service_1`, `_2`, `_3`), the gateway truly targets different containers — not just the same service name resolved by Docker's internal DNS.

### Proxy

The gateway uses `http-proxy` (`node-http-proxy`) with `selfHandleResponse: true`, which means it intercepts the upstream response body, stores it in Redis if applicable, and then forwards it to the client. This is what enables transparent caching without the upstream services knowing anything about it.

### Gateway `/status` response

```json
{
  "status": "ok",
  "service": "gateway",
  "cache": {
    "redis_url": "redis://redis:6379",
    "ttl_seconds": 30,
    "hits": 42,
    "misses": 8,
    "bypassed": 15,
    "ratio": "84.0% hit rate"
  },
  "pools": {
    "user":       { "replicas": 3, "requests": 1 },
    "enterprise": { "replicas": 3, "requests": 0 }
  }
}
```

- `requests` is the **current counter value** (0–2), not the total number of requests.
- `bypassed` counts `POST`/`PUT`/`DELETE` requests that skipped the cache entirely.

---

## 10. How Redis Caching Works

### Why caching is needed

Without caching, every `GET /api/users/user/1` call travels:

```
Client → Gateway → FastAPI replica → PostgreSQL → back
```

That is at minimum 3 network hops and a DB query, typically **10–30ms**.

With Redis caching, repeat reads are:

```
Client → Gateway → Redis → back
```

That is a single in-memory lookup, typically **< 2ms** — a **10–15× speedup** for read-heavy workloads.

### What gets cached and what doesn't

| Request type | Cached? | Reason |
|---|---|---|
| `GET` (any route) | ✅ Yes (on 2xx response) | Safe to cache — reads don't change state |
| `POST` | ❌ No (bypassed) | Creates new data — must always hit upstream |
| `PUT` | ❌ No (bypassed) | Modifies data — must always hit upstream |
| `DELETE` | ❌ No (bypassed) | Deletes data — must always hit upstream |

### Cache key

The cache key is the **full request path including query string**:

```
gw:/api/users/user/1
gw:/api/users/achievements
gw:/api/enterprise/enterprise/1/roles
```

This means `/api/users/user/1` and `/api/users/user/2` are stored as separate entries.

### Cache flow

```
Incoming GET request
        │
        ▼
  Redis GET key
        │
   ┌────┴────┐
   │  HIT?   │
   └────┬────┘
        │
   YES ─┤─────────────────────────────────────────────┐
        │                                             │
   NO (MISS)                                 Serve from Redis
        │                                   Set X-Cache: HIT
        ▼                                   Return immediately
  Forward to upstream replica
        │
        ▼
  Receive response body
        │
        ▼
  Status 2xx?
        │
   YES ─┤──────────────────────────────────────────────┐
        │                                              │
   Forward to client                        Redis SET key
   Set X-Cache: MISS                        with TTL (30s)
```

### TTL (Time To Live)

The default TTL is **30 seconds** (configurable via `CACHE_TTL` env var in `docker-compose.yml`). After 30 seconds, the Redis key expires automatically and the next request will be a fresh MISS, fetching updated data from the database.

To change it:

```yaml
# docker-compose.yml
gateway:
  environment:
    CACHE_TTL: "60"   # cache entries live for 60 seconds
```

### Response headers

Every response from the gateway includes:
- `X-Cache: HIT` or `X-Cache: MISS`
- `X-Cache-TTL: 30`

These headers let you instantly see in Postman or curl whether a cached response was served.

---

## 11. Complete Demo Walk-through

This section walks through a complete end-to-end story for demonstrating all features. All requests go through the gateway at `http://localhost:8000`.

> You can use **Postman**, **Swagger UI**, or **curl** — examples use `curl` for clarity. In Postman, set `Authorization: Bearer {{token}}` after step 3.

---

### Step 1 — Try to login with a non-existent account

```bash
curl -s -X POST http://localhost:8000/api/users/login \
  -H "Content-Type: application/json" \
  -d '{"username": "john_doe", "password": "wrongpass"}'
```

**Expected response — 401 Unauthorized:**
```json
{ "detail": "Invalid username or password" }
```

This confirms the auth system correctly rejects unknown credentials.

---

### Step 2 — Register a new user

```bash
curl -s -X POST http://localhost:8000/api/users/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john_doe",
    "email": "john@example.com",
    "password": "secret123"
  }'
```

**Expected response — 201 Created:**
```json
{
  "id": 1,
  "username": "john_doe",
  "email": "john@example.com",
  "xp": 0,
  "capital": 1000,
  "created_at": "2026-02-21T12:00:00Z"
}
```

The user starts with `xp: 0` and `capital: 1000`.

---

### Step 3 — Login and get the JWT token

```bash
curl -s -X POST http://localhost:8000/api/users/login \
  -H "Content-Type: application/json" \
  -d '{"username": "john_doe", "password": "secret123"}'
```

**Expected response — 200 OK:**
```json
{ "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...", "token_type": "bearer" }
```

Save the token in a variable for the next steps:
```bash
TOKEN="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

---

### Step 4 — Create achievement definitions

Achievements must be created in the system before they can be granted to users.

```bash
# Achievement 1 — First Trade
curl -s -X POST http://localhost:8000/api/users/achievements \
  -H "Content-Type: application/json" \
  -d '{"name": "First Trade", "description": "Completed your first market trade", "xp_reward": 100}'

# Achievement 2 — Factory Baron
curl -s -X POST http://localhost:8000/api/users/achievements \
  -H "Content-Type: application/json" \
  -d '{"name": "Factory Baron", "description": "Opened your first factory", "xp_reward": 250}'

# Achievement 3 — Team Player
curl -s -X POST http://localhost:8000/api/users/achievements \
  -H "Content-Type: application/json" \
  -d '{"name": "Team Player", "description": "Joined your first team", "xp_reward": 50}'
```

List all available achievements:
```bash
curl -s http://localhost:8000/api/users/achievements
```

```json
[
  { "id": 1, "name": "First Trade",   "xp_reward": 100 },
  { "id": 2, "name": "Factory Baron", "xp_reward": 250 },
  { "id": 3, "name": "Team Player",   "xp_reward": 50  }
]
```

---

### Step 5 — Grant achievements to our user

Now award all three achievements to `john_doe` (user id `1`). Each grant automatically adds the XP reward to the user's total.

```bash
# Grant "First Trade" (achievement_id: 1)
curl -s -X POST http://localhost:8000/api/users/user/1/achievement \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"achievement_id": 1}'

# Grant "Factory Baron" (achievement_id: 2)
curl -s -X POST http://localhost:8000/api/users/user/1/achievement \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"achievement_id": 2}'

# Grant "Team Player" (achievement_id: 3)
curl -s -X POST http://localhost:8000/api/users/user/1/achievement \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"achievement_id": 3}'
```

Check the user's updated profile — XP should now be `400` (100 + 250 + 50):

```bash
curl -s http://localhost:8000/api/users/user/1
```

```json
{
  "id": 1,
  "username": "john_doe",
  "xp": 400,
  "capital": 1000,
  ...
}
```

List all earned achievements for the user:

```bash
curl -s http://localhost:8000/api/users/user/1/achievements
```

```json
[
  { "achievement_name": "First Trade",   "xp_reward": 100, "earned_at": "..." },
  { "achievement_name": "Factory Baron", "xp_reward": 250, "earned_at": "..." },
  { "achievement_name": "Team Player",   "xp_reward": 50,  "earned_at": "..." }
]
```

---

### Step 6 — Create an enterprise

Now switch to the enterprise service and create a factory:

```bash
curl -s -X POST http://localhost:8000/api/enterprise/enterprise/create \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{
    "name": "Iron Works",
    "description": "Heavy manufacturing plant producing steel components",
    "enterprise_type": "factory",
    "capital_invested": 5000
  }'
```

**Expected response — 201 Created:**
```json
{
  "id": 1,
  "name": "Iron Works",
  "enterprise_type": "factory",
  "status": "active",
  "owner_id": 1,
  "capital_invested": 5000,
  "members": [
    { "user_id": 1, "role": "strategist", "assigned_at": "..." }
  ]
}
```

The creator (`john_doe`, user id `1`) is automatically assigned the `strategist` role.

---

### Step 7 — Assign a role to the enterprise

Register a second user and assign them a role in our enterprise:

```bash
# Register a second user
curl -s -X POST http://localhost:8000/api/users/register \
  -H "Content-Type: application/json" \
  -d '{"username": "jane_smith", "email": "jane@example.com", "password": "pass456"}'
```

Now assign `jane_smith` (user id `2`) the role of `inventor` in Iron Works (enterprise id `1`):

```bash
curl -s -X POST http://localhost:8000/api/enterprise/enterprise/1/roles \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d '{"user_id": 2, "role": "inventor"}'
```

**Expected response — 201 Created (enriched with live user data from user service):**
```json
{
  "id": 2,
  "user_id": 2,
  "role": "inventor",
  "assigned_at": "...",
  "user": {
    "username": "jane_smith",
    "email": "jane@example.com",
    "xp": 0,
    "capital": 1000
  }
}
```

Notice the `user` object — the enterprise service fetched this **live from the user management service** to enrich the role response.

View all roles in the enterprise (all enriched with user profiles):

```bash
curl -s http://localhost:8000/api/enterprise/enterprise/1/roles
```

---

## 12. Proving Round-Robin & Cache in Action

### Proving Round-Robin

The `/whoami` endpoint on both services returns the `replica_id` and `hostname` of the specific container that handled the request. Hit it multiple times and watch the responses rotate:

**User service pool:**
```bash
python3 -c "
import urllib.request, json
for i in range(6):
    r = urllib.request.urlopen('http://localhost:8000/api/users/whoami')
    d = json.loads(r.read())
    print(f'Request {i+1}: replica_id={d[\"replica_id\"]}  hostname={d[\"hostname\"]}')
"
```

**Expected output — the replica rotates 1 → 2 → 3 → 1 → 2 → 3:**
```
Request 1: replica_id=user-1  hostname=user_management_service_1
Request 2: replica_id=user-2  hostname=user_management_service_2
Request 3: replica_id=user-3  hostname=user_management_service_3
Request 4: replica_id=user-1  hostname=user_management_service_1
Request 5: replica_id=user-2  hostname=user_management_service_2
Request 6: replica_id=user-3  hostname=user_management_service_3
```

**Enterprise service pool:**
```bash
python3 -c "
import urllib.request, json
for i in range(6):
    r = urllib.request.urlopen('http://localhost:8000/api/enterprise/whoami')
    d = json.loads(r.read())
    print(f'Request {i+1}: replica_id={d[\"replica_id\"]}  hostname={d[\"hostname\"]}')
"
```

You can also watch the gateway logs in real-time to see the `pool[0]` → `pool[1]` → `pool[2]` rotation on every request:

```bash
docker logs -f gateway 2>&1 | grep "\[gateway\]"
```

```
[gateway] GET /api/users/whoami → http://user_management_service_1:8001/whoami  (pool[0])
[gateway] GET /api/users/whoami → http://user_management_service_2:8001/whoami  (pool[1])
[gateway] GET /api/users/whoami → http://user_management_service_3:8001/whoami  (pool[2])
[gateway] GET /api/users/whoami → http://user_management_service_1:8001/whoami  (pool[0])
```

---

### Proving Redis Cache

#### Method 1 — Response headers (Postman / curl)

Make the same GET request twice and observe the `X-Cache` header:

```bash
# First request — MISS (hits upstream, stores in Redis)
python3 -c "
import urllib.request, json
req = urllib.request.Request('http://localhost:8000/api/users/user/1')
with urllib.request.urlopen(req) as r:
    print('X-Cache:', r.headers.get('X-Cache'))
    print('Response time: check gateway logs')
    print(json.dumps(json.loads(r.read()), indent=2))
"

# Second request — HIT (served from Redis, upstream never called)
python3 -c "
import urllib.request, json
req = urllib.request.Request('http://localhost:8000/api/users/user/1')
with urllib.request.urlopen(req) as r:
    print('X-Cache:', r.headers.get('X-Cache'))
"
```

Output:
```
# Request 1:
X-Cache: MISS

# Request 2:
X-Cache: HIT
```

#### Method 2 — Gateway logs

```bash
docker logs -f gateway 2>&1 | grep -E "\[cache\]"
```

```
[cache] MISS gw:/api/users/user/1          ← first request
[cache] SET  gw:/api/users/user/1  (TTL 30s)  ← stored in Redis
[cache] HIT  gw:/api/users/user/1          ← second request, NOT forwarded to upstream
[cache] HIT  gw:/api/users/user/1          ← third request, still cached
```

Notice: when a cache HIT occurs, you will **not** see a `[gateway]` proxy log line — the request never reached the upstream service.

#### Method 3 — Cache stats on /status

```bash
python3 -c "
import urllib.request, json
r = urllib.request.urlopen('http://localhost:8000/status')
d = json.loads(r.read())
print(json.dumps(d['cache'], indent=2))
"
```

```json
{
  "redis_url": "redis://redis:6379",
  "ttl_seconds": 30,
  "hits": 5,
  "misses": 2,
  "bypassed": 3,
  "ratio": "71.4% hit rate"
}
```

- `hits` — requests served from Redis (no upstream call)
- `misses` — requests that hit upstream (first time or after TTL expired)
- `bypassed` — `POST`/`PUT`/`DELETE` requests that skipped cache entirely

#### Method 4 — Inspect Redis directly

```bash
# Connect to the Redis CLI inside the container
docker exec -it redis redis-cli

# List all cached keys
KEYS gw:*

# See what's stored for a specific key
GET gw:/api/users/user/1

# Check the remaining TTL for a key (in seconds)
TTL gw:/api/users/user/1

# Manually flush all cache entries (forces all next requests to MISS)
FLUSHALL
```

#### Method 5 — Verify cache bypasses mutations

```bash
# POST /login — should be BYPASSED (not cached)
curl -s -X POST http://localhost:8000/api/users/login \
  -H "Content-Type: application/json" \
  -d '{"username":"john_doe","password":"secret123"}'
```

Then check the gateway logs — you'll see `[gateway] POST …` but no `[cache]` line, confirming POST requests are always forwarded directly to upstream without touching Redis.
