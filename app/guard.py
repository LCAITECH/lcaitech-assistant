"""Input normalisation and cheap guardrails that run before/after the model.

The model's system prompt is the main guardrail; these checks catch the obvious
cases for free (no model call) and stop accidental prompt leaks.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .prompt import CANARY

_INJECTION = [
    # "ignore / forget your previous instructions"
    r"\b(ignor\w*|olvid[aá](te|r|las|lo)?|disregard\w*|forget|override\w*|bypass\w*|salte[aá]\w*)\b.{0,60}\b(instruc\w*|regla\w*|rules?|prompt\w*|restric\w*|guardrails?|indicaciones|directiv\w*|anteriores|previous|above)",
    # asking for the system / developer prompt
    r"\b(system|developer|hidden|initial|original)\s*(prompt|message|instructions?)\b",
    r"\bprompt\s+(del\s+|de\s+)?(sistema|inicial|oculto|original)\b",
    r"\b(mostr\w*|revel\w*|imprim\w*|repet\w*|copi\w*|pas\w*|dec\w*|escrib\w*|show|reveal|print|repeat|output|dump|leak|tell|give)\b.{0,40}\b(tus|sus|your|the|tu|las)\s+(instrucciones|instructions|reglas internas|configuraci\w+|system prompt|prompt)\b",
    r"\b(repeat|repet\w*|copy|copi\w*|print|imprim\w*|output)\b.{0,30}\b(everything|all|todo|todas?)\b.{0,40}\b(above|arriba|anterior\w*|before|previo\w*|verbatim|textual\w*)",
    r"\b(jailbreak\w*|dan mode|do anything now|developer mode|modo desarrollador|modo dios|god mode)\b",
    r"\b(a partir de ahora|desde ahora|from now on)\b\s*,?\s*(sos|eres|vas a|actu\w*|you are|you will|you're|act|respond\w*|habl\w*|ignor\w*|no tenes|no tienes)",
    r"\b(you are now|ahora sos un|ahora eres un|act[uú]a como si|pretend (to be|you are)|roleplay as)\b",
    r"<\s*/?\s*(system|instructions?)\s*>|\[\s*(system|inst)\s*\]|###\s*(system|instruction)",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE | re.DOTALL) for p in _INJECTION]

_CONTROL = re.compile(r"[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f\u200b-\u200f\u202a-\u202e\u2060-\u2064\ufeff]")


def clean_text(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = _CONTROL.sub("", text)
    return re.sub(r"[ \t]{3,}", "  ", text).strip()


def _fold(text: str) -> str:
    """Lower-case and strip accents for pattern matching."""
    nfd = unicodedata.normalize("NFD", text.lower())
    return "".join(c for c in nfd if unicodedata.category(c) != "Mn")


def looks_like_injection(text: str) -> bool:
    folded = _fold(text)
    return any(r.search(text) or r.search(folded) for r in _INJECTION_RE)


@dataclass
class Msg:
    role: str  # "user" | "model"
    text: str


class InputError(ValueError):
    def __init__(self, code: str, message_es: str, message_en: str):
        super().__init__(code)
        self.code = code
        self.message_es = message_es
        self.message_en = message_en


def normalise_history(raw: list[dict], max_msg_chars: int, max_history: int, max_assistant_chars: int) -> list[Msg]:
    """Validate roles, trim history and enforce length limits."""
    msgs: list[Msg] = []
    for item in raw:
        role = str(item.get("role", "")).lower()
        if role in {"assistant", "model", "bot"}:
            role = "model"
        elif role == "user":
            pass
        else:
            continue  # silently drop unknown roles (e.g. "system")
        text = clean_text(str(item.get("content", "")))
        if not text:
            continue
        if role == "model":
            text = text[:max_assistant_chars]
        if msgs and msgs[-1].role == role:
            msgs[-1].text = (msgs[-1].text + "\n\n" + text)[: max(max_msg_chars, max_assistant_chars) * 2]
        else:
            msgs.append(Msg(role, text))

    if not msgs or msgs[-1].role != "user":
        raise InputError("no_user_message", "Escribí un mensaje para empezar.", "Please type a message first.")
    if len(msgs[-1].text) > max_msg_chars:
        raise InputError(
            "message_too_long",
            f"Tu mensaje es muy largo (máximo {max_msg_chars} caracteres). ¿Lo podés resumir?",
            f"Your message is too long (max {max_msg_chars} characters). Could you shorten it?",
        )
    msgs = msgs[-max_history:]
    while msgs and msgs[0].role != "user":
        msgs.pop(0)
    # older user turns are history: cap them too
    for m in msgs[:-1]:
        if m.role == "user":
            m.text = m.text[:max_msg_chars]
    return msgs


_PROMPT_MARKERS = [CANARY.lower(), "reglas del asistente", "base de conocimiento (informaci", "seguridad del prompt"]


def output_leaks_prompt(reply: str) -> bool:
    low = reply.lower()
    return any(m in low for m in _PROMPT_MARKERS)
