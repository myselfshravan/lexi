"""
Lexi — self-hosted Alexa skill backend (Flask + Groq).

Runs your Echo skill on your own machine instead of Amazon's (broken) hosted
Lambda. A Cloudflare tunnel exposes this over HTTPS; Alexa POSTs signed requests
to it, this app verifies the signature, runs the skill, and calls Groq.

Logs (clean, per-turn):
  logs/lexi.log     rotating human log — one tidy block per turn
  logs/turns.jsonl  one JSON line per turn: latency, tokens, tools, query, answer
    tail -f logs/lexi.log
    tail -f logs/turns.jsonl | jq .

Env vars:
  GROQ_API_KEY   (required) your Groq key from console.groq.com
  ALEXA_SKILL_ID (required) skill id (amzn1.ask.skill.xxxx) — rejects other skills
  GROQ_MODEL     (optional) default openai/gpt-oss-120b  (gpt-oss-20b for speed)
  PORT           (optional) default 8080
  LOG_LEVEL      (optional) INFO | DEBUG   (DEBUG just adds slot detail — still tidy)
  RELOAD         (optional) 1 to auto-restart on code edits
  SSL_CERT_FILE  certifi CA bundle so urllib can verify Alexa's signature cert chain
"""
import os
import sys
import json
import time
import logging
import warnings
from logging.handlers import RotatingFileHandler
from datetime import datetime

import requests
from flask import Flask, jsonify, request, g, has_request_context

from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import (
    AbstractRequestHandler,
    AbstractExceptionHandler,
    AbstractRequestInterceptor,
    AbstractResponseInterceptor,
)
import ask_sdk_core.utils as ask_utils
from flask_ask_sdk.skill_adapter import SkillAdapter

# --------------------------------------------------------------------------- #
#  Logging — clean: only our "lexi" logger talks; everything else is hushed    #
# --------------------------------------------------------------------------- #
warnings.filterwarnings("ignore")  # hush CryptographyDeprecationWarning etc.

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
RELOAD = os.environ.get("RELOAD", "0") == "1"
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
os.makedirs(LOG_DIR, exist_ok=True)
TURNS_LOG = os.path.join(LOG_DIR, "turns.jsonl")

_console = logging.StreamHandler(sys.stdout)
_console.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%H:%M:%S"))
_file = RotatingFileHandler(os.path.join(LOG_DIR, "lexi.log"),
                            maxBytes=2_000_000, backupCount=5)
_file.setFormatter(logging.Formatter("%(asctime)s  %(message)s", "%Y-%m-%d %H:%M:%S"))

log = logging.getLogger("lexi")
log.setLevel(LOG_LEVEL)
log.handlers[:] = [_console, _file]
log.propagate = False

# keep third-party libraries out of the log entirely
logging.getLogger().setLevel(logging.ERROR)
for noisy in ("werkzeug", "urllib3", "requests", "ask_sdk",
              "ask_sdk_core", "ask_sdk_webservice_support", "asyncio"):
    logging.getLogger(noisy).setLevel(logging.ERROR)

# --------------------------------------------------------------------------- #
#  Config                                                                      #
# --------------------------------------------------------------------------- #
GROQ_KEY = os.environ.get("GROQ_API_KEY", "").strip()
SKILL_ID = os.environ.get("ALEXA_SKILL_ID", "").strip()
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b").strip()
PORT = int(os.environ.get("PORT", "8080"))

PERSONA = (
    "You are Lexi, a witty, warm voice assistant living in an Amazon Echo. "
    "You're sharp, a little playful, never robotic. Answer in at most 3 short "
    "spoken sentences. Plain words only - no markdown, lists, emoji, or code, "
    "since everything you say is read aloud. If you don't know, say so briefly."
)


def _clip(s, n=90):
    s = str(s or "")
    return s if len(s) <= n else s[:n - 1] + "…"


# --------------------------------------------------------------------------- #
#  Per-turn metrics (shared across interceptors within one request via flask.g)#
# --------------------------------------------------------------------------- #
def turn():
    if has_request_context():
        if not hasattr(g, "turn"):
            g.turn = {"groq_ms": 0.0, "tokens_in": 0, "tokens_out": 0, "tools": []}
        return g.turn
    return {"groq_ms": 0.0, "tokens_in": 0, "tokens_out": 0, "tools": []}


# --------------------------------------------------------------------------- #
#  Tools (Groq function-calling)                                              #
# --------------------------------------------------------------------------- #
TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": "Get the current weather for a city.",
        "parameters": {
            "type": "object",
            "properties": {"city": {"type": "string", "description": "City name"}},
            "required": ["city"],
        },
    },
}]
# Add your own tools above; register them in dispatch_tool below.


def get_weather(city):
    gc = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": city, "count": 1}, timeout=5,
    ).json()
    if not gc.get("results"):
        return f"I couldn't find a place called {city}."
    loc = gc["results"][0]
    w = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        params={
            "latitude": loc["latitude"], "longitude": loc["longitude"],
            "current": "temperature_2m,wind_speed_10m",
        }, timeout=5,
    ).json()
    c = w["current"]
    return (f"In {loc['name']} it's {round(c['temperature_2m'])} degrees "
            f"with wind at {round(c['wind_speed_10m'])} kilometers per hour.")


def dispatch_tool(name, args):
    log.info("   · tool  %s(%s)", name, args)
    turn()["tools"].append(name)
    if name == "get_weather":
        return get_weather(**args)
    return "That tool isn't available."


# --------------------------------------------------------------------------- #
#  Groq call (with tool loop)                                                  #
# --------------------------------------------------------------------------- #
def ask_groq(question, history):
    t = turn()
    t["query"] = question
    messages = [{"role": "system", "content": PERSONA}] + history + \
               [{"role": "user", "content": question}]
    for _ in range(3):  # allow a couple of tool rounds
        t0 = time.time()
        r = requests.post(
            GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": MODEL, "messages": messages, "tools": TOOLS,
                  "tool_choice": "auto", "max_tokens": 220, "temperature": 0.7},
            timeout=8,
        )
        dt = (time.time() - t0) * 1000
        t["groq_ms"] += dt
        if r.status_code != 200:
            log.error("   · groq ERROR %s: %s", r.status_code, _clip(r.text, 200))
            r.raise_for_status()
        body = r.json()
        usage = body.get("usage", {})
        t["tokens_in"] += usage.get("prompt_tokens", 0) or 0
        t["tokens_out"] += usage.get("completion_tokens", 0) or 0
        msg = body["choices"][0]["message"]
        if msg.get("tool_calls"):
            messages.append(msg)
            for tc in msg["tool_calls"]:
                out = dispatch_tool(tc["function"]["name"],
                                    json.loads(tc["function"]["arguments"] or "{}"))
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
            continue
        answer = (msg.get("content") or "Hmm, I blanked on that one.").strip()
        t["answer"] = answer
        return answer
    return "That got complicated - ask me again?"


# --------------------------------------------------------------------------- #
#  Alexa handlers  (param names MUST be handler_input / exception)             #
# --------------------------------------------------------------------------- #
class LaunchHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("LaunchRequest")(handler_input)

    def handle(self, handler_input):
        handler_input.attributes_manager.session_attributes["history"] = []
        return (handler_input.response_builder
                .speak("Hey, Lexi here. What's on your mind?")
                .ask("I'm listening.").response)


class AskLexiHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AskLexiIntent")(handler_input)

    def handle(self, handler_input):
        slots = handler_input.request_envelope.request.intent.slots
        query = slots["query"].value if slots and slots.get("query") else ""
        hist = handler_input.attributes_manager.session_attributes.get("history", [])
        try:
            answer = ask_groq(query, hist)
        except Exception as e:
            log.error("   · groq failed: %s", e)
            answer = "My brain hiccuped. Try that again?"
        hist += [{"role": "user", "content": query},
                 {"role": "assistant", "content": answer}]
        handler_input.attributes_manager.session_attributes["history"] = hist[-8:]
        return handler_input.response_builder.speak(answer).ask("Anything else?").response


class HelpHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.HelpIntent")(handler_input)

    def handle(self, handler_input):
        return (handler_input.response_builder
                .speak("Just ask me anything, like the weather or a question.")
                .ask("What do you want to know?").response)


class CancelStopHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return (ask_utils.is_intent_name("AMAZON.CancelIntent")(handler_input) or
                ask_utils.is_intent_name("AMAZON.StopIntent")(handler_input))

    def handle(self, handler_input):
        return (handler_input.response_builder.speak("Catch you later.")
                .set_should_end_session(True).response)


class FallbackHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_intent_name("AMAZON.FallbackIntent")(handler_input)

    def handle(self, handler_input):
        return (handler_input.response_builder
                .speak("Didn't catch that. Try starting with what, how, or why.")
                .ask("What's your question?").response)


class SessionEndedHandler(AbstractRequestHandler):
    def can_handle(self, handler_input):
        return ask_utils.is_request_type("SessionEndedRequest")(handler_input)

    def handle(self, handler_input):
        return handler_input.response_builder.response


class CatchAll(AbstractExceptionHandler):
    def can_handle(self, handler_input, exception):
        return True

    def handle(self, handler_input, exception):
        log.error("   · unhandled: %s", exception)
        turn()["error"] = str(exception)
        return (handler_input.response_builder
                .speak("Something broke on my end. Try again.").ask("?").response)


# --------------------------------------------------------------------------- #
#  Interceptors — record request into the turn (concise, no raw JSON/secrets)  #
# --------------------------------------------------------------------------- #
class LogRequest(AbstractRequestInterceptor):
    def process(self, handler_input):
        req = handler_input.request_envelope.request
        t = turn()
        t["request_type"] = req.object_type
        t["intent"] = getattr(getattr(req, "intent", None), "name", None)
        slots = getattr(getattr(req, "intent", None), "slots", None) or {}
        t["slots"] = {k: v.value for k, v in slots.items() if getattr(v, "value", None)}
        extra = ""
        if LOG_LEVEL == "DEBUG" and t["slots"]:
            extra = "  slots=" + json.dumps(t["slots"], ensure_ascii=False)
        log.info("▶ %s%s%s", t["request_type"],
                 f"  [{t['intent']}]" if t["intent"] else "", extra)


class LogResponse(AbstractResponseInterceptor):
    def process(self, handler_input, response):
        speech = ""
        if response and response.output_speech is not None:
            speech = getattr(response.output_speech, "ssml", "") or ""
            speech = speech.replace("<speak>", "").replace("</speak>", "").strip()
        turn().setdefault("answer", speech)


# --------------------------------------------------------------------------- #
#  Skill + Flask wiring                                                        #
# --------------------------------------------------------------------------- #
sb = SkillBuilder()
for h in (LaunchHandler(), AskLexiHandler(), HelpHandler(),
          CancelStopHandler(), FallbackHandler(), SessionEndedHandler()):
    sb.add_request_handler(h)
sb.add_exception_handler(CatchAll())
sb.add_global_request_interceptor(LogRequest())
sb.add_global_response_interceptor(LogResponse())

app = Flask(__name__)


@app.route("/health")
def health():
    return jsonify(status="ok", model=MODEL,
                   groq_key_set=bool(GROQ_KEY), skill_id_set=bool(SKILL_ID))


@app.before_request
def _start_turn():
    if request.path == "/" and request.method == "POST":
        g.t_start = time.time()
        t = turn()
        t["ts"] = datetime.now().isoformat(timespec="seconds")
        t["model"] = MODEL


@app.after_request
def _end_turn(response):
    if request.path == "/" and request.method == "POST":
        t = turn()
        if not t.get("request_type"):
            return response  # rejected before dispatch (bad signature) — stay quiet
        t["total_ms"] = round((time.time() - getattr(g, "t_start", time.time())) * 1000, 1)
        t["groq_ms"] = round(t.get("groq_ms", 0.0), 1)
        t["status"] = response.status_code
        # one tidy summary line per turn
        bits = [f"{t['total_ms']:.0f}ms"]
        if t["groq_ms"]:
            bits.append(f"groq {t['groq_ms']:.0f}ms")
            bits.append(f"{t['tokens_in']}/{t['tokens_out']} tok")
        if t["tools"]:
            bits.append("tools " + ",".join(t["tools"]))
        log.info("✓ %s%s  ·  %s", t["request_type"],
                 f"[{t['intent']}]" if t.get("intent") else "", "  ·  ".join(bits))
        if t.get("answer"):
            log.info('   “%s”', _clip(t["answer"], 110))
        try:
            with open(TURNS_LOG, "a") as fh:
                fh.write(json.dumps(t, ensure_ascii=False) + "\n")
        except Exception as e:
            log.error("could not write turns.jsonl: %s", e)
    return response


# SkillAdapter verifies Alexa's request signature + timestamp and dispatches.
skill_adapter = SkillAdapter(skill=sb.create(), skill_id=SKILL_ID, app=app)
skill_adapter.register(app=app, route="/")


def _banner():
    ok = lambda b: "OK" if b else "MISSING"
    log.info("─" * 56)
    log.info("  Lexi backend  ·  :%s  ·  %s", PORT, MODEL)
    log.info("  GROQ_API_KEY %s   ALEXA_SKILL_ID %s   log=%s%s",
             ok(GROQ_KEY), ok(SKILL_ID), LOG_LEVEL, "  reload" if RELOAD else "")
    log.info("  human log  : %s", os.path.join(LOG_DIR, "lexi.log"))
    log.info("  metrics log: %s", TURNS_LOG)
    log.info("─" * 56)
    if not GROQ_KEY:
        log.info("  !! GROQ_API_KEY not set — answers will fail")
    if not SKILL_ID:
        log.info("  !! ALEXA_SKILL_ID not set — Alexa requests will be REJECTED")


if __name__ == "__main__":
    # avoid double banner when the reloader spawns its child
    if not RELOAD or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
        _banner()
    app.run(host="0.0.0.0", port=PORT, threaded=True,
            debug=False, use_reloader=RELOAD)
