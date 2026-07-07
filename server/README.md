# Lexi — self-hosted backend (Flask + Groq + Cloudflare tunnel)

Runs the Alexa skill on your own machine instead of Amazon's hosted Lambda
(which is broken account-wide — the runtime Lambda is never invoked). Alexa POSTs
signed HTTPS requests through a Cloudflare tunnel to this Flask app, which verifies
the signature and calls Groq.

```
Echo ──speech──> Alexa ──HTTPS(signed)──> cloudflared ──> Flask (app.py) ──> Groq
```

## What you need
- This folder, Python 3.9+
- A Groq key: console.groq.com → API Keys
- `cloudflared` installed (you have it)
- An Alexa skill with **"Provision your own"** hosting (Alexa-hosted can't point
  at a custom endpoint). See "Create the skill" below.

## 1. Configure
```bash
cd ~/alexa-lexi/server
cp .env.example .env
# edit .env: set GROQ_API_KEY and ALEXA_SKILL_ID (the amzn1.ask.skill.xxx id)
```

## 2. Run the backend
```bash
./run.sh
```
First run makes a venv + installs deps, then starts on http://localhost:8080.
Health check: `curl http://localhost:8080/health`

## 3. Expose it over HTTPS (Cloudflare tunnel)

**Quick test** (random URL, no setup):
```bash
cloudflared tunnel --url http://localhost:8080
# prints https://<random>.trycloudflare.com
```

**Permanent** (own domain, survives reboots) — a dedicated named tunnel run as a
user LaunchAgent, so it never touches your other tunnels:
```bash
cloudflared tunnel create lexi
cloudflared tunnel route dns lexi lexi.yourdomain.dev
```
`~/.cloudflared/lexi.yml`:
```yaml
tunnel: <lexi-tunnel-id>
credentials-file: /Users/you/.cloudflared/<lexi-tunnel-id>.json
ingress:
  - hostname: lexi.yourdomain.dev
    service: http://localhost:8080
  - service: http_status:404
```
Run it permanently via a LaunchAgent (`~/Library/LaunchAgents/com.lexi.tunnel.plist`
with `ProgramArguments` = `cloudflared tunnel --config ~/.cloudflared/lexi.yml run lexi`,
`RunAtLoad` + `KeepAlive` true), then:
```bash
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.lexi.tunnel.plist
```
The tunnel is now permanent; you only run the backend (step 2) when you want Lexi
answering. When the backend is down, the URL returns 502 — harmless.

## 4. Point Alexa at it
Alexa console → your skill → **Build → Endpoint**:
- Service Endpoint Type: **HTTPS**
- Default Region: `https://<your-tunnel-host>/`  (the tunnel URL, with trailing `/`)
- SSL cert dropdown:
  - `*.trycloudflare.com` → **"sub-domain of a domain that has a wildcard
    certificate from a certificate authority"**
  - your own domain → **"has a certificate from a trusted certificate authority"**
- **Save Endpoints**, then **Build → Build skill**.

## 5. Test
Alexa console **Test** tab (Development) or the Echo: *"open hey lexi"*.
Watch `./run.sh`'s console — every turn logs the request, Groq call, tools, and
the spoken reply.

## Notes
- The free `trycloudflare.com` URL changes each time you restart cloudflared —
  re-paste it into the Endpoint and rebuild. A named tunnel avoids this.
- Keep both the server and cloudflared running for the skill to work.
- Add tools: extend `TOOLS` + `dispatch_tool` in `app.py`. Because this runs on
  your machine, tools here CAN reach your home LAN (dashcam, Home Assistant, etc.) —
  unlike the cloud-hosted version.
