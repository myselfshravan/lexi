# I custom-built a skill for my Echo Dot that never rejects a question and controls my entire home — it runs on Groq now

> TL;DR — Stock Alexa says *"Hmm, I don't know that"* constantly. So I built a custom skill that hands my questions to **Groq** and answers in **~0.8 seconds** — no more dead ends. And because it runs on a little server on *my* machine (not Amazon's), it also does what cloud Alexa can't: **control my entire home in plain English** — lights, fans, ACs, curtains, motor gates. For **₹0**, before Alexa+ even shipped. Here's how, plus the six walls I hit.

An Echo Dot is a fantastic microphone and speaker attached to a mediocre brain. So I kept the good part and swapped the brain for one I control.

The result never says "I don't know," talks back faster than stock Alexa, has a personality, remembers the conversation — and can flip any switch in my house because every word runs through code on my own laptop.

---

## Demo

```
You: "Alexa, open my lexi"  →  "Hey, Lexi here. What's on your mind?"
You: "why is the sky blue"  →  (answer in ~0.8s)

▶ IntentRequest  [AskLexiIntent]
✓ 812ms  ·  groq 783ms  ·  199/85 tok
   "You're spot-on — the sky's usually blue, but it loves to dress up at sunrise and sunset."
```

## The idea

Alexa skills aren't firmware hacks. A **custom skill** keeps the Echo as the voice front‑end and forwards your speech to a **backend you control**:

```
You speak → Alexa cloud (speech→intent) → your endpoint (JSON in, JSON out) → Alexa speaks the reply
```

Two facts that make this a proper hack:
1. A skill in **Development** stage is automatically live on every Echo on **your** Amazon account — no publishing.
2. That endpoint can be **any HTTPS server**. So it can be a Flask app on your own laptop.

Point #2 is the whole trick. I made the endpoint my machine, and put **Groq** behind it — chosen because Alexa gives a skill only ~8 seconds to reply, and Groq (`openai/gpt-oss-120b`) answers in well under one.

## The architecture

```
Echo → Alexa cloud → Cloudflare tunnel (https://lexi.mydomain.dev) → Flask on my Mac :8080 → Groq → spoken reply
```

- **Flask + flask-ask-sdk** — verifies Alexa's request signature, so only genuinely Alexa‑signed requests are processed.
- **Groq** — the brain, with a tool‑calling loop. Because it runs on *my* box, a tool can reach my LAN (dashcam, home stuff) — something a cloud function never could.
- **A permanent Cloudflare named tunnel** on my own domain, run as a `launchctl` agent — reboot‑proof, unlike a throwaway ngrok URL.

The handler is boringly small:

```python
class AskLexiHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AskLexiIntent")(handler_input)
    def handle(self, handler_input):
        query = ...  # the AMAZON.SearchQuery slot
        answer = ask_groq(query, history)   # ~0.8s
        return handler_input.response_builder.speak(answer).ask("Anything else?").response
```

> **Honest aside on hosting:** Amazon's one‑click "Alexa‑hosted" option (a managed Lambda) never actually ran my code — I got *"There was a problem with the requested skill's response"* and, digging into CloudWatch, the runtime Lambda's log group was never even created, on both a converted and a brand‑new skill. Might be an account/region quirk on my end; I didn't chase it, because **self‑hosting is the better move regardless** — you get real logs, any model you want, and LAN access. So that's what Lexi is.

## The gotcha gauntlet 🥊

Getting from "Provision your own" to a talking Echo took six small‑but‑real walls:

**1. Invocation names must be 2+ words.** `lexi` is rejected; you need e.g. `my lexi`.

**2. Duplicate invocation names route randomly.** Two test skills with the same phrase → the simulator non‑deterministically picks one. Symptom: works, then doesn't, with zero code change.

**3. macOS python.org Python ships with no CA bundle.** Alexa signs each request and includes a cert URL; the SDK downloads that cert to verify the signature. On a python.org build, `urllib` can't verify Amazon's S3 cert → `CERTIFICATE_VERIFY_FAILED`. Fix: point it at certifi via `SSL_CERT_FILE`.

**4. The ASK SDK calls your handlers with keyword args.** Write `def can_handle(self, h)` and it explodes; params must be exactly `handler_input` / `exception`.

**5. Endpoint changes need a rebuild** before the simulator uses the new target.

**6. "hey" is a terrible spoken invocation word.** I first named it `hey lexi`. Typed in the simulator: fine. Spoken to the Echo: *"I'm not quite sure how to help you with that,"* and nothing reached my server — Alexa hears the leading "hey" as filler and never matches. Renamed to `my lexi` → instant.

Bonus boss: **locale.** My skill was built for English (US), but my Echo is English (India). A dev skill only appears on a device whose language you've *built* — so an en‑IN Echo can't see an en‑US‑only skill. Add the matching locale, rebuild.

## The part cloud Alexa can't do: it runs my house

Because Lexi runs on my LAN, it can reach my home‑automation hub directly — something a cloud skill physically can't. I gave Groq two tools, `control_home` and `run_scene`, and let it map plain English to device commands:

> *"turn on the living room lights"* → `control_home(area="living room", device="light", action="on")`
> *"set the bedroom AC to 22"* → `control_home(area="bedroom", device="ac", action="set", value="22")`
> *"movie night"* → `run_scene(scene="movie night")`

No rigid phrases, no "Alexa, ask my-hub to turn on device 47." Just talk, and the right thing happens — lights, fans, ACs, curtains, motor gates, whole scenes. My house runs on **Control4**, and Lexi reaches it straight over the LAN through one pluggable bridge, mapping plain speech to the exact device command. Hundreds of switches across the house, all driven by natural language — a Jarvis I actually own, running in my home before Alexa+ even shipped.

## The payoff

- ~0.8s end‑to‑end, comfortably under Alexa's ~8s timeout
- Groq `gpt-oss-120b`, free tier (swap `gpt-oss-20b` for even faster)
- A persona, session memory, and tool‑calling that can hit my LAN
- Every turn logged with latency + tokens to a `turns.jsonl` I can graph

The meta‑lesson: **the Echo is just a mic and a speaker with an API.** Own the endpoint and the brain is yours — as fast, as weird, and as personal as you want.

Build your own: [README](./README.md). Code's all there.

*— Shravan*
