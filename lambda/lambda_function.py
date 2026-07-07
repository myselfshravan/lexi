import os, json, logging, requests
from ask_sdk_core.skill_builder import SkillBuilder
from ask_sdk_core.dispatch_components import AbstractRequestHandler, AbstractExceptionHandler
from ask_sdk_core.handler_input import HandlerInput
import ask_sdk_core.utils as ask_utils

logger = logging.getLogger(__name__); logger.setLevel(logging.INFO)

GROQ_KEY = os.environ.get("GROQ_API_KEY", "gsk_PUT_YOUR_KEY_HERE")
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
MODEL    = "openai/gpt-oss-120b"   # good at tool-calls; use gpt-oss-20b for max speed

PERSONA = (
    "You are Lexi, a witty, warm voice assistant living in an Amazon Echo. "
    "You're sharp, a little playful, never robotic. Answer in at most 3 short "
    "spoken sentences. Plain words only - no markdown, lists, emoji, or code, "
    "since everything you say is read aloud. If you don't know, say so briefly."
)

# ---- TOOLS -----------------------------------------------------------------
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
    g = requests.get("https://geocoding-api.open-meteo.com/v1/search",
                     params={"name": city, "count": 1}, timeout=5).json()
    if not g.get("results"):
        return f"I couldn't find a place called {city}."
    loc = g["results"][0]
    w = requests.get("https://api.open-meteo.com/v1/forecast",
        params={"latitude": loc["latitude"], "longitude": loc["longitude"],
                "current": "temperature_2m,wind_speed_10m"}, timeout=5).json()
    c = w["current"]
    return (f"In {loc['name']} it's {round(c['temperature_2m'])} degrees "
            f"with wind at {round(c['wind_speed_10m'])} kilometers per hour.")

def dispatch_tool(name, args):
    if name == "get_weather":
        return get_weather(**args)
    return "That tool isn't available."

# ---- GROQ CALL (with tool loop) -------------------------------------------
def ask_groq(question, history):
    messages = [{"role": "system", "content": PERSONA}] + history + \
               [{"role": "user", "content": question}]
    for _ in range(3):  # allow a couple of tool rounds
        r = requests.post(GROQ_URL,
            headers={"Authorization": f"Bearer {GROQ_KEY}"},
            json={"model": MODEL, "messages": messages, "tools": TOOLS,
                  "tool_choice": "auto", "max_tokens": 220, "temperature": 0.7},
            timeout=6)
        r.raise_for_status()
        msg = r.json()["choices"][0]["message"]
        if msg.get("tool_calls"):
            messages.append(msg)
            for tc in msg["tool_calls"]:
                out = dispatch_tool(tc["function"]["name"],
                                    json.loads(tc["function"]["arguments"] or "{}"))
                messages.append({"role": "tool", "tool_call_id": tc["id"], "content": out})
            continue
        return (msg.get("content") or "Hmm, I blanked on that one.").strip()
    return "That got complicated - ask me again?"

# ---- ALEXA HANDLERS --------------------------------------------------------
class LaunchHandler(AbstractRequestHandler):
    def can_handle(self, h): return ask_utils.is_request_type("LaunchRequest")(h)
    def handle(self, h):
        h.attributes_manager.session_attributes["history"] = []
        return h.response_builder.speak("Hey, Lexi here. What's on your mind?") \
                .ask("I'm listening.").response

class AskLexiHandler(AbstractRequestHandler):
    def can_handle(self, h): return ask_utils.is_intent_name("AskLexiIntent")(h)
    def handle(self, h):
        slots = h.request_envelope.request.intent.slots
        query = slots["query"].value if slots and slots.get("query") else ""
        hist  = h.attributes_manager.session_attributes.get("history", [])
        try:
            answer = ask_groq(query, hist)
        except Exception as e:
            logger.exception(e); answer = "My brain hiccuped. Try that again?"
        hist += [{"role": "user", "content": query},
                 {"role": "assistant", "content": answer}]
        h.attributes_manager.session_attributes["history"] = hist[-8:]
        return h.response_builder.speak(answer).ask("Anything else?").response

class HelpHandler(AbstractRequestHandler):
    def can_handle(self, h): return ask_utils.is_intent_name("AMAZON.HelpIntent")(h)
    def handle(self, h):
        return h.response_builder.speak("Just ask me anything, like the weather or a question.") \
                .ask("What do you want to know?").response

class CancelStopHandler(AbstractRequestHandler):
    def can_handle(self, h):
        return (ask_utils.is_intent_name("AMAZON.CancelIntent")(h) or
                ask_utils.is_intent_name("AMAZON.StopIntent")(h))
    def handle(self, h):
        return h.response_builder.speak("Catch you later.").set_should_end_session(True).response

class FallbackHandler(AbstractRequestHandler):
    def can_handle(self, h): return ask_utils.is_intent_name("AMAZON.FallbackIntent")(h)
    def handle(self, h):
        return h.response_builder.speak("Didn't catch that. Try starting with what, how, or why.") \
                .ask("What's your question?").response

class SessionEndedHandler(AbstractRequestHandler):
    def can_handle(self, h): return ask_utils.is_request_type("SessionEndedRequest")(h)
    def handle(self, h): return h.response_builder.response

class CatchAll(AbstractExceptionHandler):
    def can_handle(self, h, e): return True
    def handle(self, h, e):
        logger.exception(e)
        return h.response_builder.speak("Something broke on my end. Try again.").ask("?").response

sb = SkillBuilder()
sb.add_request_handler(LaunchHandler())
sb.add_request_handler(AskLexiHandler())
sb.add_request_handler(HelpHandler())
sb.add_request_handler(CancelStopHandler())
sb.add_request_handler(FallbackHandler())
sb.add_request_handler(SessionEndedHandler())
sb.add_exception_handler(CatchAll())
lambda_handler = sb.lambda_handler()
