# Lexi 🎙️ — a self-hosted Groq brain for your Echo

A custom Alexa skill for the Echo Dot that **never rejects a question** *and* **controls your entire smart home in plain English** — powered by **Groq** (~0.8s replies), self-hosted on your own machine, for **free**. A Jarvis you own, running before Alexa+ shipped.

Say **"Alexa, open my lexi"** → ask it anything, or just tell it: *turn on the living room lights, set the bedroom AC to 22, open the gate, run movie night.* Because it runs on your LAN (not a cloud Lambda), it can talk to your home hub directly — something cloud Alexa can't.

📖 **Full story:** [BLOG.md](./BLOG.md) — *"I custom-built a skill for my Echo Dot that never rejects a question and controls my entire home — it runs on Groq now."*

---

## Demo

```
You: "Alexa, open my lexi"        →  "Hey, Lexi here. What's on your mind?"
You: "turn on the living room lights"
     ▶ IntentRequest [AskLexiIntent]
     · tool  control_home(area='living room', device='light', action='on')
     ✓ 640ms
     →  "Done — turned on the living room light."
You: "why is the sky blue"        →  (Groq answer in ~0.8s)
```

> 🎥 A clip of the Echo running the house + terminal is in [`docs/`](./docs/) — see [docs/CAPTURE.md](./docs/CAPTURE.md).

---

## How it works

```
You: "Alexa, open my lexi"
        │
        ▼
  Amazon Alexa cloud  (speech → intent)
        │  HTTPS, request-signed
        ▼
  Cloudflare tunnel  (https://lexi.yourdomain.dev)
        │
        ▼
  Flask app on your machine  :8080     ← verifies Alexa's signature
        │
        ├──► Groq (openai/gpt-oss-120b) ─ answers questions in ~0.8s
        └──► your home hub (LAN) ─ Schneider / Wiser / KNX / Home Assistant
```

Groq function-calling turns plain speech into the right action:

| You say | Groq calls |
|---|---|
| "turn on the living room lights" | `control_home(area="living room", device="light", action="on")` |
| "set the bedroom AC to 22" | `control_home(area="bedroom", device="ac", action="set", value="22")` |
| "open the main gate" | `control_home(area="entrance", device="gate", action="open")` |
| "movie night" | `run_scene(scene="movie night")` |
| "why is the sky blue" | *(no tool — just answers)* |

## Features

- 🏠 **Natural-language home control** — lights, fans, ACs, curtains, motor gates, scenes, via a pluggable hub adapter (`HOME_HUB_URL`). Ships in safe **dry-run** so you can demo before wiring your hub.
- 🧠 **Never says "I don't know"** — Groq answers anything, ~0.8s (well under Alexa's ~8s limit)
- 🔁 Multi-turn memory + a custom persona ("Lexi")
- 📊 Clean per-turn logs + a `turns.jsonl` metrics file (latency, tokens, tools)
- 🔒 Alexa request-signature + timestamp verification
- 💸 Free (Groq free tier + your own machine)

## Quickstart

**1. Backend**
```bash
cd server
cp .env.example .env      # add GROQ_API_KEY + ALEXA_SKILL_ID (HOME_HUB_URL optional)
./run.sh                  # Flask on :8080
```

**2. Expose it** (Cloudflare named tunnel = permanent; or `cloudflared tunnel --url http://localhost:8080` for a quick test)

**3. Create the Alexa skill** (developer.amazon.com → Create Skill)
- Custom model, **Provision your own** hosting
- Invocation: **`my lexi`** (2+ words; avoid a leading "hey")
- Import the model from [`skill-package/`](./skill-package/); set **Endpoint → HTTPS** to your tunnel URL; **Build Model**
- Add the **locale that matches your Echo's language** (e.g. English (India))

**4. Wire your home** (optional) — set `HOME_HUB_URL` / `HOME_HUB_TOKEN` to your Schneider/Wiser hub, KNX-IP gateway, or Home Assistant REST endpoint. Until then it runs in dry-run (understands + confirms + logs, doesn't fire).

Full setup + gotchas: [`server/README.md`](./server/README.md).

## Repo layout

```
lexi/
├── README.md            # you are here
├── BLOG.md              # the full story
├── server/              # Flask + Groq backend (home-control tools + Q&A)  ← run this
├── skill-package/       # Alexa interaction model
└── lambda/              # reference: Alexa-hosted version
```

## The 6 gotchas (that cost a day)

| # | Wall | Fix |
|---|------|-----|
| 1 | Invocation must be 2+ words | `my lexi`, not `lexi` |
| 2 | Duplicate invocation names route randomly | one name; disable dupes |
| 3 | macOS python.org has no CA bundle → signature cert fetch fails | `SSL_CERT_FILE=$(python -c "import certifi;print(certifi.where())")` |
| 4 | ASK SDK calls handlers with kwargs | params must be `handler_input` / `exception` |
| 5 | Endpoint change ignored | rebuild the model |
| 6 | "hey <name>" not recognized when spoken | pick a name without a leading "hey" |

Plus: build your skill for the **locale your Echo is set to**.

## Why self-hosted?

Self-hosting is what makes the home control possible — Lexi runs on your LAN, so it reaches your smart-home hub directly (a cloud Lambda can't). You also get real logs, any model, and full control. *(Amazon's one-click "Alexa-hosted" option also just didn't work on my account — no runtime logs ever appeared — but self-hosting is the better path regardless.)*

---

Built by [@myselfshravan](https://github.com/myselfshravan). PRs and stars welcome ⭐
