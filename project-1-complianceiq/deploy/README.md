# Deploying ComplianceIQ to AWS (free plan)

One EC2 server runs everything in Docker: Caddy (HTTPS) → Next.js UI + FastAPI (search models on CPU) →
Postgres/pgvector + Redis. Answers are written by a hosted LLM (Groq free tier; Bedrock supported).

**Cost:** an AWS account on the **Free plan** gets $100 in credits (up to $200 with onboarding activities),
for 6 months, and is never charged. `m7i-flex.large` (2 vCPU, 8 GB) uses about $70 of credit per month if it
runs 24/7. **Stop the instance when you're not demoing** and the credits last for months (stopped = only the
small disk is billed).

## 1. Launch the server (AWS console, ~10 min)
1. Region: **Asia Pacific (Mumbai) ap-south-1** (top right).
2. **Billing → Budgets → Create budget** → "Zero spend" or a $20 monthly budget, with your email. (Alerts early.)
3. **EC2 → Launch instance**
   - Name `complianceiq`; image **Ubuntu Server 24.04 LTS**; type **m7i-flex.large** (marked Free tier eligible)
   - Key pair: **Create new** → `complianceiq` → RSA, `.pem` → it downloads. Keep it safe; it's the server's key.
   - Network: allow **SSH from My IP**, **HTTPS** and **HTTP** from anywhere
   - Storage: **30 GB gp3**
   - Advanced details → **User data**: paste the whole of `deploy/setup-ec2.sh`
4. Launch, wait ~3 min, copy the **Public IPv4 address** (e.g. `13.233.10.20`).
   Optional: **Elastic IPs → Allocate → Associate** with the instance so the address survives stop/start.

## 2. Connect and configure (your laptop terminal)
```bash
mv ~/Downloads/complianceiq.pem ~/.ssh/ && chmod 400 ~/.ssh/complianceiq.pem
ssh -i ~/.ssh/complianceiq.pem ubuntu@13.233.10.20        # your IP
```
On the server, create the secrets file (nano: paste, then Ctrl+O, Enter, Ctrl+X):
```bash
cd ~/ai-engineer-portfolio/project-1-complianceiq
nano .env
```
```
POSTGRES_USER=complianceiq
POSTGRES_PASSWORD=<long random string>
POSTGRES_DB=complianceiq
SITE_ADDRESS=13-233-10-20.sslip.io
LLM_PROVIDERS=openai_compat
OPENAI_COMPAT_BASE_URL=https://api.groq.com/openai/v1
OPENAI_COMPAT_MODEL=llama-3.1-8b-instant
OPENAI_COMPAT_API_KEY=<your Groq key>
JWT_SECRET=<long random string>
AUTH_REQUIRED=false
RATE_LIMIT_PER_MINUTE=5
```
Random strings: `python3 -c "import secrets; print(secrets.token_urlsafe(32))"`. `SITE_ADDRESS` is your IP
with dashes + `.sslip.io`: a free hostname that points to your IP, so Caddy can get a real HTTPS certificate.

## 3. Copy the database from the laptop (no re-ingestion on the server)
Laptop:
```bash
cd ~/projects/ai-engineer-portfolio/project-1-complianceiq
make up && make db-dump
scp -i ~/.ssh/complianceiq.pem data/complianceiq.dump ubuntu@13.233.10.20:~/ai-engineer-portfolio/project-1-complianceiq/data/
```

## 4. Start it (server)
```bash
cd ~/ai-engineer-portfolio/project-1-complianceiq/deploy
make up            # first build ~10 min; first start downloads the models (~4.5 GB)
make logs          # wait for "startup complete", then Ctrl+C
make restore       # load the database
make user EMAIL=you@example.com ROLE=admin     # for the Usage & cost page
make health
```
Open `https://13-233-10-20.sslip.io` 🎉

## 5. Automatic deploys (optional)
GitHub repo → **Settings → Secrets and variables → Actions**:
- Secrets: `EC2_HOST` = the IP, `EC2_SSH_KEY` = the whole content of `complianceiq.pem`
- Variables: `DEPLOY_ENABLED` = `true`

Every push to `main` then runs the checks, SSHes in, pulls, rebuilds and smoke-tests `/api/health`.
(SSH must then be open to GitHub's runners: set the SSH rule to 0.0.0.0/0. Key-only login keeps it safe.)

## Daily use
- **Stop** the instance after a demo: EC2 → Instances → Instance state → Stop. **Start** it before the next one
  (everything comes back by itself; with no Elastic IP the IP changes, so update `SITE_ADDRESS` and `make up`).
- Logs: `make logs` · status: `make ps` · update by hand: `git pull && make up`
