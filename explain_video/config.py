import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_TTS_INSTRUCTIONS = "Говори по-русски тепло, дружелюбно и чуть бодрее, как коллега, которая с удовольствием помогает разобраться. Лёгкая улыбка в голосе, живая естественная интонация и мягкие смысловые акценты. Темп разговорный, с короткими естественными паузами. Сохрани естественный тембр выбранного голоса. Без театральности, сюсюканья и рекламного энтузиазма. Не добавляй слов, прочитай только данный текст."


@dataclass(frozen=True)
class Config:
    api_key: str = field(default="", repr=False)
    transcription_model: str = "gpt-4o-mini-transcribe"
    rewrite_model: str = "gpt-4.1-mini"
    tts_provider: str = "openai"
    voice: str = "marin"
    tts_model: str = "gpt-4o-mini-tts"
    tts_instructions: str | None = DEFAULT_TTS_INSTRUCTIONS


def load_config(path: Path = Path(".env"), voice: str | None = None) -> Config:
    values = {}
    if path.exists():
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, sep, value = line.partition("=")
            if not sep:
                raise ValueError(f"Invalid config line {number}: expected KEY=value")
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            values[key.strip()] = value
    values.update(os.environ)
    provider = values.get("EXPLAIN_TTS_PROVIDER", "openai")
    if provider not in {"edge", "openai"}:
        raise ValueError("EXPLAIN_TTS_PROVIDER must be edge or openai")
    return Config(
        api_key=values.get("OPENAI_API_KEY", ""),
        transcription_model=values.get("EXPLAIN_TRANSCRIPTION_MODEL", "gpt-4o-mini-transcribe"),
        rewrite_model=values.get("EXPLAIN_REWRITE_MODEL", "gpt-4.1-mini"),
        tts_provider=provider,
        voice=voice or values.get("EXPLAIN_VOICE") or ("marin" if provider == "openai" else "ru-RU-SvetlanaNeural"),
        tts_model=values.get("EXPLAIN_TTS_MODEL", "gpt-4o-mini-tts"),
        tts_instructions=values.get("EXPLAIN_TTS_INSTRUCTIONS") or DEFAULT_TTS_INSTRUCTIONS,
    )
