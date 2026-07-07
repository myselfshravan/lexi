# Meet Lexi: I gave my Echo Dot a Groq brain for free — and found Amazon's skill hosting is silently broken

> TL;DR — I wanted my Amazon Echo Dot to answer like a real LLM instead of "Hmm, I don't know that." I ended up (1) discovering that Amazon's own "Alexa‑hosted" backend never actually runs your code on my account, (2) self‑hosting my Echo's brain on my MacBook behind a Cloudflare tunnel, and (3) wiring in **Groq** so it replies in **~0.8 seconds**, for **₹0**. This is the whole journey — including the six walls I face‑planted into so you don't have to.

Everyone doing "ChatGPT on Alexa" uses OpenAI on Amazon's Lambda or a throwaway ngrok URL. Lexi is different on three counts: it runs on **Groq** (sub‑second, free tier), it's **self‑hosted on my own machine + domain** (permanent Cloudflare named tunnel), and it exists because Amazon's hosting **quietly didn't work** — which turned out to be the most interesting part.

---

## The goal

An Echo Dot is a great microphone + speaker with a mediocre brain. I wanted to keep the hardware and swap the brain:

> "Alexa, open my lexi" → *"Hey, Lexi here. What's on your mind?"* → ask anything → get a fast, witty, LLM answer.

Why Groq? Because Alexa gives your skill roughly **8 seconds** to respond before it gives up, and Groq's whole thing is blazing inference. `openai/gpt-oss-120b` on Groq answers in well under a second — perfect for voice.

## How an Alexa skill actually works (the 60‑second version)

You don't flash the Echo. You build a **custom skill**: the Echo stays the voice front‑end, and it forwards your speech to a **backend you control**.

```
You speak → Alexa cloud (speech→intent) → your endpoint (JSON in, JSON out) → Alexa speaks the text
```

Two things nobody tells you up front:
- A skill in **"Development"** stage is automatically live on every Echo signed into **the same Amazon account**. No publishing, no certification.
- Your backend can be an **AWS Lambda** *or* **any HTTPS endpoint**. Remember that second option. We're going to need it.

## Attempt #1: the "easy" path (Alexa‑hosted) — and the wall

Amazon offers **Alexa‑hosted**: a free Lambda + in‑browser editor. I built the skill, pasted my Python (ASK SDK → Groq), deployed. Clean. Then in the simulator:

```
open lexi
→ "There was a problem with the requested skill's response"
```

Fine, a code bug. Except… it happened even on the bare `LaunchRequest`, which just returns a greeting and never touches Groq. So I went to the logs.

## The investigation (the good part)

CloudWatch for an Alexa‑hosted skill lives under `/aws/lambda/<skill-id>`. I opened it:

> **"Log group does not exist."**

If a Lambda runs — even to crash on a bad import — AWS creates its log group and writes a traceback. No log group means **the function was never invoked at all**. The whole account had only two shared *builder* Lambdas (they just package your code on deploy) and **zero** per‑skill runtime log groups.

I didn't trust it. So I deleted everything and created a **brand‑new, from‑scratch Alexa‑hosted skill**. Same code, same result: *"There was a problem…"*, and again **no runtime log group ever created**.

**Conclusion: on my developer account, Amazon's Alexa‑hosted runtime Lambda is never invoked.** The endpoint wiring is broken upstream — nothing you write in the code editor can fix it, because your code never runs. (If you've hit the same silent failure: check CloudWatch. If `/aws/lambda/<skill-id>` doesn't exist after you test, it's not your code.)

Time to stop fighting Amazon's black box.

## The pivot: host my Echo's brain myself

Remember "your endpoint can be any HTTPS server"? I made a new skill with **"Provision your own"** hosting and pointed it at a Flask app on my Mac:

```
Echo → Alexa cloud → https://lexi.mydomain.dev (Cloudflare tunnel) → Mac:8080 → Flask → Groq → spoken reply
```

Three deliberate choices:
- **Flask + `flask-ask-sdk`** so Alexa's mandatory **request‑signature verification** happens for real (only genuinely Alexa‑signed requests get through — everything else is a 400).
- **Groq** as the brain (`openai/gpt-oss-120b`), with a tool‑calling loop (it can call `get_weather`, and because it runs on *my* machine it could reach my LAN — dashcam, home stuff — which a cloud Lambda never could).
- **A permanent Cloudflare *named* tunnel** on my own domain, run as a `launchctl` agent — not ngrok's ephemeral URL that changes on every restart. Reboot‑proof.

The handler is boring in the best way:

```python
class AskLexiHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AskLexiIntent")(handler_input)
    def handle(self, handler_input):
        query = ...  # the AMAZON.SearchQuery slot
        answer = ask_groq(query, history)   # ~0.8s
        return handler_input.response_builder.speak(answer).ask("Anything else?").response
```

## The gotcha gauntlet 🥊

Getting from "Provision your own" to a working Echo took **six** separate walls. Individually small; together, a day. Here they are so your day is shorter:

**1. Invocation names must be 2+ words.** `lexi` is rejected outright. Had to pick a two‑word name.

**2. Duplicate invocation names route randomly.** I had three test skills all answering the same phrase; the simulator non‑deterministically picked a (broken) one. Symptom: it works, then it doesn't, with no code change. Fix: one invocation name, disable the others.

**3. macOS python.org Python ships with no CA bundle.** Alexa signs each request and includes a `SignatureCertChainUrl`; the SDK downloads that cert over HTTPS to verify the signature. On a python.org build, `urllib` can't verify Amazon's S3 cert → `CERTIFICATE_VERIFY_FAILED`. Fix: point it at certifi —
```bash
export SSL_CERT_FILE=/path/to/.venv/.../certifi/cacert.pem
```

**4. The ASK SDK calls your handlers with keyword arguments.** If you write `def can_handle(self, h)` it explodes with `unexpected keyword argument 'handler_input'`. Param names must be exactly `handler_input` / `exception`. (Never caught this earlier because on Alexa‑hosted the handlers never ran!)

**5. Endpoint changes need a rebuild.** After switching the HTTPS endpoint, the simulator kept hitting the old target until I rebuilt the model.

**6. "hey" is a terrible spoken invocation word.** I named it `hey lexi`. Typed in the simulator: works. Spoken to the physical Echo: *"I'm not quite sure how to help you with that,"* and **nothing reached my server**. Alexa hears the leading "hey" as filler and never matches the skill. Renamed to `my lexi` → instant match.

Bonus boss fight: **locale.** My skill was built for **English (US)** only, but my Echo is set to **English (India)**. A dev skill only appears on a device whose language matches a *built* locale — so an en‑IN Echo literally can't see an en‑US‑only skill, even on the right account. Added the en‑IN locale, rebuilt. (Then Amazon's "Sync Locales" helpfully cloned my model across five English locales and wiped the invocation name in the process — a fun little extra build failure. Set it on the *primary* locale and it propagates.)

## The payoff

```
17:41:26  ▶ IntentRequest  [AskLexiIntent]
17:41:26  ✓ IntentRequest[AskLexiIntent]  ·  812ms  ·  groq 783ms  ·  199/85 tok
17:41:26     "You're spot-on — the sky's usually blue, but it loves to dress up at sunrise and sunset."
```

Speak to the Dot → the request streams into my terminal in real time → Groq answers → the Echo speaks it back. Every turn is logged to a rotating human log **and** a `turns.jsonl` metrics file (latency, tokens, tools) so I can graph how fast it is, for fun.

**Cost:** ₹0. Groq's free tier is generous, the skill is private/dev‑stage, and the tunnel rides my existing Cloudflare setup. Compare with Alexa+ at $19.99/month.

## Build your own

Everything's in the repo — the Flask backend, the interaction model, the Cloudflare tunnel setup, and the exact fixes for all six gotchas. Start with the [README](./README.md).

The meta‑lesson: **the Echo is just a mic and a speaker with an API.** Once you own the endpoint, the brain is yours — and it can be as fast, as weird, and as personal as you want.

*Built with a lot of CloudWatch spelunking and one very patient terminal. — Shravan*
