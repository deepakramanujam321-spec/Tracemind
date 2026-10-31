# TraceMind Deployment Plan (Cloudways, subject to runtime compatibility)

Research date: 2026-10-31. Read-only web research; nothing deployed or signed up.
Tags: **[D]** documented (URL given), **[A]** assumption/unknown, **[S]** secondary source (Cloudways blog, forum or search snippet; not core docs).

## 1. What Cloudways is

- Managed cloud hosting on VMs at DigitalOcean, AWS, Google Cloud, Vultr and Linode. **[D]** https://support.cloudways.com/en/articles/11721533-what-types-of-databases-does-cloudways-support
- Two products:
  - **Flexible** is the classic PHP/WordPress-style stack.
    - Debian 12, Nginx 1.25 on ports 80/443, Apache 2.4, Varnish, Memcached, Redis, PHP 7.4 to 8.4, Git, Composer, and MySQL 8.4 or MariaDB 10.11. **[D]** https://support.cloudways.com/en/articles/5116170-which-base-packages-are-deployed-with-a-cloudways-server
    - Optional add-ons: Supervisor, Elasticsearch/OpenSearch, and **RabbitMQ (Beta, servers with 4 GB RAM or more)**. **[D]** same URL.
  - **Velocity** is managed Node.js hosting.
    - The app is imported from a GitHub, GitLab or Bitbucket repo (required). It has Node version and framework presets, a build command and output folder, env vars (can be marked sensitive), PM2 start/stop/restart, and custom domains via A/CNAME records. **[D]** https://support.cloudways.com/en/articles/15550368-how-to-launch-a-velocity-application-on-cloudways and https://support.cloudways.com/en/articles/15550860-cloudways-velocity-application-overview-guide
    - The overview guide says a Velocity app can use "PostgreSQL or Supabase" and shows DB credentials plus a Database Manager. **[D]** (overview URL above). The launch guide does not mention databases. How that database is provisioned, and whether it is reachable from outside, is **[A]**.
    - Pricing starts at $20/mo (2 vCPU, 2 GB, 5 apps). **[D]** (launch URL above).

## 2. Capability matrix

| Question | Finding |
|---|---|
| Docker / Compose | No documented support. A Cloudways feedback-forum reply (June 2022) said "We don't have a plan to offer Docker support" **[S]** https://feedback.cloudways.com/forums/203824-service-improvement/suggestions/6754845-add-docker-support (the page returned 403 to me; this is from a search snippet). Treat as unsupported. |
| Root / sudo | Not granted: "We can not give root access to your servers." **[D]** https://support.cloudways.com/en/articles/5134090-why-can-t-i-have-root-access-to-my-server. The same article says that without root you cannot deploy new software packages. Sudo is not mentioned **[A]**. A marketing page (https://www.cloudways.com/en/dev-hosting.php) mentions root access for developers; this conflicts with the support article **[A]**. |
| SSH | SSH/SFTP on all Flexible and Autonomous plans. **[D]** https://support.cloudways.com/en/articles/5119485-guide-to-connecting-to-your-application-using-ssh-sftp |
| System packages | Only through the dashboard Packages tab (Supervisor, RabbitMQ Beta, etc.). Arbitrary apt installs are undocumented **[A]**. |
| Python | Cloudways marketing says Python, Java, .NET and Ruby apps are not supported **[S]** https://www.cloudways.com/en/digital-ocean-cloud-hosting.php. I could not fetch the full page text to quote it. The backend and demo app are Python, so this is a blocker. |
| Long-lived processes | Flexible: Supervisor is an optional package **[D]**. Whether customers can run arbitrary Supervisor programs is **[A]**. Velocity: PM2 controls for the Node process **[D]**. |
| Custom ports / reverse proxy | Flexible runs Nginx on 80/443 with Apache behind it. One Cloudways blog proxies to a Node port via `.htaccess` mod_proxy rules and says mod_proxy may need to be enabled by support **[S]** https://www.cloudways.com/blog/how-to-host-a-node-js-application/. Custom Nginx location blocks are undocumented **[A]**. |
| Firewall / inbound ports | The firewall page only covers IP allow/block lists with TTL, country blocking, DoS and bot settings. It documents no arbitrary port opening. **[D]** https://support.cloudways.com/en/articles/9979437-a-brief-guide-to-server-security-management. Cloudways will not open MySQL 3306 remotely; it suggests SSH tunnels. **[D]** https://support.cloudways.com/en/articles/5124817-how-to-whitelist-ip-addresses-for-remote-mysql-connections |
| Databases | Managed RDBMS are MySQL 8.4 and MariaDB 10.11 only. NoSQL cannot be deployed on Cloudways, but external ones (e.g. MongoDB) can be connected. **[D]** https://support.cloudways.com/en/articles/11721533-what-types-of-databases-does-cloudways-support. PostgreSQL on Flexible is not documented **[A]**; Velocity mentions it (see section 1). |
| Static hosting | Not a dedicated documented feature. Flexible can serve static files from a PHP-type app **[A]**. Velocity builds React/Vite from Git, and Cloudways has a React deploy guide **[S]** https://www.cloudways.com/blog/deploy-react-app/. |
| SSL | Velocity: custom domains with automatic SSL are marketed **[S]** https://www.cloudways.com/en/velocity.php. Let's Encrypt on Flexible is common but I did not verify it in this pass **[A]**. |
| Env vars / secrets | Velocity: env vars with a sensitive flag **[D]** (launch URL above). Flexible: **[A]**. |

## 3. Component fit

| Component | On Cloudways? |
|---|---|
| React+Vite frontend | **Possible** on Velocity (Node build to static output). Its `/api` proxy would have to become an absolute backend URL or an edge rewrite **[A]**. |
| FastAPI backend (Python, long-lived, OTLP protobuf endpoints) | **No** (Python unsupported **[S]**, no Docker). Host elsewhere. |
| Postgres 16 | **No** on Flexible (MySQL/MariaDB only **[D]**). Velocity DB is **[A]**: confirm that it is PostgreSQL 16, has external access, and has the extensions TraceMind needs (check the backend migrations). Safer to use external managed Postgres. |
| RabbitMQ 3.13 | Flexible Beta package exists **[D]**, but it needs a Flexible server and only Python-hosting hosts could use it remotely, which needs an open AMQP port **[A]**. Use a hosted broker such as CloudAMQP instead. |
| OTel Collector | **No.** It is a custom binary or container. Run it beside the backend. |
| Demo app (FastAPI + aio-pika worker) | **No** (Python, worker). Run beside the backend. |
| Remediation sandbox (`docker run --network none`) | **No.** It needs a Docker daemon. |

Conclusion: Cloudways can at best host the static/Node frontend. The rest must live elsewhere, so a Cloudways deployment is mostly a front door.

## 4. Recommended minimal hackathon topology

```
Browser -> Cloudways Velocity (React/Vite static, optional) ----HTTPS /api----> VPS (Docker host)
                                                                     |  Caddy/Nginx :443 (only public ports 80/443)
                                                                     |  backend, collector, demo app (compose, internal network)
                                                                     |  sandbox runner (see below)
                                                     managed Postgres 16 (private/allowlisted) + CloudAMQP (TLS AMQPS)
```

Simplest and recommended: put everything, including the frontend, on one small Docker VPS (2 vCPU, 4 GB or more) using the existing compose stack, with TLS from Caddy or Let's Encrypt. Add Cloudways only for the frontend if the hackathon requires it. This is a design suggestion **[A]**. Nothing here has been tested.

**Sandbox safety (the key decision).** Do not mount `/var/run/docker.sock` into the public-facing backend. Options, safest first:
1. A separate sandbox VM or host. The backend submits jobs over a private, authenticated channel (queue message or an internal-only HTTP service with a shared token). The runner on that host holds the Docker socket and is not internet-reachable. Containers use `--network none`, read-only root filesystem, `--cap-drop ALL`, `no-new-privileges`, pids/memory/CPU limits, a timeout, and a non-root user.
2. Rootless Docker or Podman for the runner user on the same VPS, behind a small internal service.
3. Demo-only fallback: the sandbox is disabled and remediation shows a precomputed result. Say so honestly in the demo.

## 5. Secrets and configuration

Provide these through the host's secret store or a `.env` with `chmod 600`, never committed. Exact names must be matched against the repo's compose file and config, which I did not review:
- Postgres URL (with `sslmode=require`) and its credentials.
- RabbitMQ AMQPS URL.
- LLM provider API key(s).
- OTLP ingest token or auth for `/v1/traces` and `/v1/logs` **[A]**: confirm the backend can enforce this, because those endpoints will be public.
- Sandbox runner shared token.
- Public frontend and API origins (CORS), and the collector's exporter endpoint.

## 6. Security notes

- Expose only 80/443. Keep Postgres, RabbitMQ, the collector's 4318 and the Docker daemon off the public internet, or allowlist by IP.
- Rate-limit and authenticate the OTLP endpoints and the investigation/remediation triggers. A public "run code" feature is the highest risk.
- Cloudways rule: do not share MySQL or SSH ports broadly. Use its IP allowlist **[D]** (security guide URL above).

## 7. Step-by-step plan with checks

1. **Ask Cloudways support (section 9) first.** Check: written answers on Python/Docker/ports. Stop here if any answer is no.
2. Provision the VPS, install Docker, set up a firewall (allow 22 from your IP, 80, 443). Check: `nmap` from outside shows only 80/443 (and 22).
3. Create managed Postgres 16 and a CloudAMQP instance. Check: `psql` and an AMQPS test from the VPS succeed; they are not reachable from random IPs.
4. Deploy compose (backend, collector, demo app) on an internal network behind Caddy. Check: `GET /api/health` over HTTPS returns 200; migrations ran.
5. Send demo OTLP data. Check: traces and logs appear and an incident is created.
6. Deploy the sandbox runner per section 4. Check: a job runs, the container has no network (`curl` fails inside), and the backend has no socket access.
7. (Optional) Deploy the frontend to Velocity and set the API base URL, CORS and TLS. Check: a browser loads the UI, with no mixed content or CORS errors.
8. End-to-end demo script run, then snapshot DB and compose files. Check: a clean redeploy reproduces the result.

## 8. Risks

- Cloudways cannot run the core stack (high; documented/likely).
- Python and Docker support statements come from marketing and a 2022 forum reply, not a current runtime doc.
- A public sandbox is a remote-code-execution surface. Mitigate as in section 4.
- Hosted-service free tiers may sleep or have connection limits (verify per provider).
- Time cost of splitting hosts; a single VPS keeps this small.

## 9. Owner should confirm with Cloudways support (in writing)

1. Is Python (FastAPI/uvicorn) supported on Velocity or Flexible? Can arbitrary long-lived processes run?
2. Is Docker/Compose permitted or technically possible on any plan, or on a Cloudways-provisioned Vultr/DO VM with real root?
3. Is sudo or any package installation (apt) allowed, and is the "root access" claim on the dev-hosting page accurate?
4. Can customers open inbound ports (e.g. 4318, 5672) or add Nginx location/proxy rules?
5. What does the Velocity "PostgreSQL" database include (version, extensions, external access)?
6. Does Velocity allow a custom backend (non-Express) or workers?
7. Does the hackathon accept "Cloudways frontend + external backend" as satisfying the requirement?

## 10. Go / no-go

- **No-go** for deploying the full TraceMind stack on Cloudways as documented: Python, Docker, Postgres (on Flexible), arbitrary ports and root are all undocumented or unsupported.
- **Conditional go** for a hybrid: frontend on Cloudways Velocity (if organisers accept it), backend and sandbox on a separate Docker VPS with managed Postgres and RabbitMQ. If Cloudways support answers 1 to 4 positively, re-evaluate.
