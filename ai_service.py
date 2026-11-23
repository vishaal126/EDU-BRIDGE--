"""AI learning assistant backend (Anthropic Messages API, key read from the environment)."""
import requests

import config

API_URL = "https://api.anthropic.com/v1/messages"

MODES = {
    "Explain a concept": "Explain the topic clearly for a student. Start with the core idea in plain language, then give a concrete example, then a short recap.",
    "Programming help": "Help with the programming question. Explain the concept, show short, correct, well-commented code, and mention common mistakes.",
    "Study plan": "Create a realistic, step-by-step study plan with milestones, practice tasks and ways to check progress.",
    "Summarize text": "Summarize the text the student provides: key points as short bullets, then a one-paragraph overview.",
}
BASE_SYSTEM = (
    "You are EduBridge AI, a patient, accurate learning assistant for students on an educational platform. "
    "Be concise and well structured, check your reasoning, say so when you are unsure, and encourage the "
    "student to try problems themselves. Never invent facts or sources."
)


class AIError(Exception):
    """Error whose message is safe to show to the user."""


def is_configured() -> bool:
    return bool(config.get("ANTHROPIC_API_KEY"))


def ask(history: list, mode: str = "Explain a concept") -> str:
    """history: [{'role': 'user'|'assistant', 'content': str}, ...] ending with a user turn."""
    key = config.get("ANTHROPIC_API_KEY")
    if not key:
        raise AIError("The AI assistant isn't configured yet. Add ANTHROPIC_API_KEY to the server settings.")
    payload = {
        "model": config.get("AI_MODEL", "claude-sonnet-5-5"),
        "max_tokens": 1500,
        "system": BASE_SYSTEM + " " + MODES.get(mode, ""),
        "messages": history[-20:],
    }
    try:
        resp = requests.post(
            API_URL,
            json=payload,
            headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
            timeout=60,
        )
    except requests.Timeout:
        raise AIError("The AI took too long to respond. Please try again.")
    except requests.RequestException:
        raise AIError("Couldn't reach the AI service. Check your connection and try again.")
    if resp.status_code == 401:
        raise AIError("The AI API key was rejected. Please contact the site admin.")
    if resp.status_code == 429:
        raise AIError("The AI service is busy right now. Please wait a moment and retry.")
    if resp.status_code >= 400:
        raise AIError(f"The AI service returned an error ({resp.status_code}). Please try again.")
    try:
        text = "".join(b.get("text", "") for b in resp.json().get("content", []) if b.get("type") == "text").strip()
    except ValueError:
        text = ""
    if not text:
        raise AIError("The AI returned an empty answer. Please rephrase and try again.")
    return text
