# Lexi 🎙️ — give your Echo Dot a Groq brain

Turn a plain Amazon Echo into a fast, witty LLM assistant. Say **"Alexa, open my lexi"**, ask anything, get an answer from **Groq** in **~0.8 seconds** — self‑hosted on your own machine, for **free**.

Unlike the usual "ChatGPT on Alexa" tutorials, Lexi runs on **Groq** (sub‑second inference), is **self‑hosted behind your own Cloudflare tunnel** (permanent, not ephemeral ngrok), and was born out of discovering that Amazon's own *Alexa‑hosted* backend silently never ran my code.

📖 **Read the full story:** [BLOG.md](./BLOG.md) — *"I gave my Echo Dot a Groq brain for free (and found Amazon's hosting is broken)."*

---

## Demo

Say it, and it answers in under a second — every turn logged with latency and tokens:

```
▶ IntentRequest  [AskLexiIntent]
✓ IntentRequest[AskLexiIntent]  ·  812ms  ·  groq 783ms  ·  199/85 tok
   "You're spot-on — the sky's usually blue, but it loves to dress up at sunrise and sunset."
```

> 🎥 A video of the Echo answering live + the terminal streaming is in [`docs/`](./docs/) — see [docs/CAPTURE.md](./docs/CAPTURE.md).

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
  Flask app on your machine  :8080
        │   • verifies Alexa's signature
        │   • runs the skill
        ▼
  Groq  (openai/gpt-oss-120b)  ~0.8s
        │
        ▼
  spoken reply on your Echo
```

- **Echo** = mic + speaker. The brain is yours.
- **Groq** = the fast LLM (free tier). Swap `gpt-oss-20b` for even lower latency.
- **Cloudflare named tunnel** = a permanent public HTTPS URL to your localhost, reboot‑proof.
- **Signature verification** = only genuinely Alexa‑signed requests are processed.

## Features

- ⚡ ~0.8s end‑to‑end responses (well under Alexa's ~8s timeout)
- 🧠 Groq LLM with a **tool‑calling loop** (`get_weather` included; add your own — and because it runs on *your* box, tools can reach your LAN)
- 🔁 Multi‑turn memory within a session
- 🔊 Custom persona ("Lexi" — witty, concise, spoken‑friendly)
- 📊 Clean per‑turn logs + a `turns.jsonl` metrics file (latency, tokens, tools) for graphing
- 🔒 Alexa request‑signature + timestamp verification
- 💸 Free (Groq free tier + your own machine)

## Quickstart (self‑hosted)

**1. Backend**
```bash
cd server
cp .env.example .env      # add your GROQ_API_KEY and ALEXA_SKILL_ID
./run.sh                  # Flask on :8080
```

**2. Expose it** (any HTTPS tunnel works; a Cloudflare named tunnel is permanent)
```bash
cloudflared tunnel --url http://localhost:8080     # quick test URL
# or a named tunnel on your domain -> https://lexi.yourdomain.dev
```

**3. Create the Alexa skill** (developer.amazon.com → Create Skill)
- Custom model, **Provision your own** hosting
- Invocation name: **`my lexi`** (2+ words; avoid a leading "hey" — Alexa mishears it)
- Import the interaction model from [`skill-package/`](./skill-package/)
- **Build → Endpoint → HTTPS** → your tunnel URL → cert type "wildcard sub‑domain / trusted CA"
- **Build Model**
- Add the **locale that matches your Echo's language** (e.g. English (India)) — a dev skill only shows on devices whose language you've built

**4. Talk to it:** *"Alexa, open my lexi"* — watch requests stream into `server/logs/lexi.log`.

Full setup + all the gotchas: [`server/README.md`](./server/README.md).

## Repo layout

```
lexi/
├── README.md            # you are here
├── BLOG.md              # the full story
├── server/              # the working self-hosted backend (Flask + Groq)  ← run this
├── skill-package/       # Alexa interaction model (invocation + intents)
└── lambda/              # reference: the Alexa-hosted version Amazon never ran
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

Plus: your skill must be built for the **locale your Echo is set to**.

## Why not just Alexa‑hosted?

On my account, the Alexa‑hosted runtime Lambda was **never invoked** (proven via CloudWatch — no `/aws/lambda/<skill-id>` log group ever created, on both converted and fresh skills). Self‑hosting sidesteps it entirely. Details in [BLOG.md](./BLOG.md).

---

Built by [@myselfshravan](https://github.com/myselfshravan). PRs and stars welcome ⭐
