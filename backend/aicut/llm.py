"""LLM planning layer — Ollama only, no cloud, no API keys.

The LLM never invents timestamps: it emits an :class:`EditPlan` of typed actions
that reference transcript segment ids. This module builds the prompt, calls
Ollama's ``/api/chat`` with ``format:"json"``, validates the result with
pydantic, and retries once with the validation error fed back. Everything sits
behind ``Planner.plan()`` so tests can inject a fake chat function.
"""

from __future__ import annotations

from collections.abc import Callable

import httpx
from pydantic import ValidationError

from .config import Settings, get_settings
from .models import EditPlan, Transcript

# chat_fn(messages) -> assistant content string
ChatFn = Callable[[list[dict]], str]


class LLMUnavailable(RuntimeError):
    """Ollama isn't reachable — the caller should surface a helpful message."""


class PlanError(ValueError):
    """The model produced something that wouldn't validate, even after a retry."""

    def __init__(self, message: str, detail: str | None = None):
        super().__init__(message)
        self.detail = detail


ACTION_CATALOG = """\
You are the planning brain of a video editor. Convert the user's instruction into
a JSON EditPlan. Output ONLY JSON: {"actions": [...], "notes": "one line"}.

You NEVER invent timestamps. Reference transcript segments by their [id]. A
deterministic compiler resolves ids to exact times.

Available actions (discriminated by "type"):
- {"type":"remove_silences","min_gap_s":0.6,"pad_s":0.08}  # remove long dead-air gaps
- {"type":"remove_fillers","words":["um","uh",...]}         # omit words for defaults
- {"type":"tighten","max_gap_s":0.35}                       # cap ALL pauses, incl. within sentences (punchier than remove_silences)
- {"type":"remove_retakes","similarity":0.8}                # drop repeated attempts at a line, keep the last clean take
- {"type":"find_highlights","target_s":60,"max_fraction":0.6}  # auto-short: keep only the best moments up to a time budget
- {"type":"trim","mode":"before|after","anchor":{"kind":"segment_id","value":<id>}}
- {"type":"filter_topic","mode":"keep|remove","query":"<topic>","segment_ids":[<id>,...]}
    # ALWAYS include segment_ids you judge relevant to the query from the transcript.
- {"type":"cut_ranges","ranges":[[start_s,end_s]]}          # explicit times only if user gave them
- {"type":"keep_ranges","ranges":[[start_s,end_s]]}
- {"type":"set_captions","enabled":true,"granularity":"segment|word"}
- {"type":"set_aspect","aspect":"source|9:16|1:1"}
- {"type":"set_transition","kind":"none|crossfade|wipe","duration_s":0.5}  # dissolve/wipe between kept ranges

Rules:
- Prefer trim/filter_topic/remove_* over raw cut_ranges.
- For "tighten"/"punchier"/"snappier"/"remove all pauses" use tighten. For "remove mistakes"/"keep the last take"/"cut the retakes" use remove_retakes.
- For "vertical"/"shorts"/"reels" use set_aspect 9:16. For "subtitle"/"captions" use set_captions.
- For "highlights"/"best bits"/"make a short/teaser"/"cut it down to the good parts" use find_highlights.
- For "crossfade"/"dissolve"/"smooth the cuts"/"wipe between clips" use set_transition (kind wipe for "wipe", else crossfade).
- Keep "notes" to one short human sentence describing what you did.
"""

EXAMPLE_1_USER = (
    'Instruction: "trim everything before I actually start the demo, cut silences, subtitle it"\n'
    "Transcript:\n[6] 0:00–0:40  long rambling intro and hellos\n"
    "[7] 0:40–1:10  ok so let me show you the actual demo now"
)
EXAMPLE_1_ASSISTANT = (
    '{"actions": ['
    '{"type": "trim", "mode": "before", "anchor": {"kind": "segment_id", "value": 7}}, '
    '{"type": "remove_silences", "min_gap_s": 0.6}, '
    '{"type": "set_captions", "enabled": true, "granularity": "segment"}'
    '], "notes": "Demo starts at segment 7; trimming intro, tightening pauses, captions on."}'
)

EXAMPLE_2_USER = (
    'Instruction: "keep only the parts about pricing and make it vertical"\n'
    "Transcript:\n[0] 0:00–0:12  welcome everyone\n"
    "[1] 0:12–0:30  our pricing starts at ten dollars a month\n"
    "[2] 0:30–0:48  the pro tier is twenty five dollars\n"
    "[3] 0:48–1:04  anyway thanks for watching"
)
EXAMPLE_2_ASSISTANT = (
    '{"actions": ['
    '{"type": "filter_topic", "mode": "keep", "query": "pricing", "segment_ids": [1, 2]}, '
    '{"type": "set_aspect", "aspect": "9:16"}'
    '], "notes": "Keeping the two pricing segments and reframing to vertical 9:16."}'
)


def _fmt_ts(t: float) -> str:
    m, s = divmod(int(t), 60)
    return f"{m}:{s:02d}"


def compact_transcript(transcript: Transcript, max_chars: int = 24000) -> str:
    """`[id] mm:ss–mm:ss  text` per segment; truncate long segments if huge."""
    lines = []
    for seg in transcript.segments:
        text = seg.text.strip()
        lines.append(f"[{seg.id}] {_fmt_ts(seg.start)}–{_fmt_ts(seg.end)}  {text}")
    body = "\n".join(lines)
    if len(body) <= max_chars:
        return body
    # too big — truncate each segment to first ~15 words
    lines = []
    for seg in transcript.segments:
        words = seg.text.strip().split()
        text = " ".join(words[:15]) + ("…" if len(words) > 15 else "")
        lines.append(f"[{seg.id}] {_fmt_ts(seg.start)}–{_fmt_ts(seg.end)}  {text}")
    return "\n".join(lines)


def state_summary(source_dur: float, output_dur: float) -> str:
    return f"current cut: {_fmt_ts(source_dur)} → {_fmt_ts(output_dur)}"


def build_messages(instruction: str, transcript: Transcript, state: str) -> list[dict]:
    return [
        {"role": "system", "content": ACTION_CATALOG},
        {"role": "user", "content": EXAMPLE_1_USER},
        {"role": "assistant", "content": EXAMPLE_1_ASSISTANT},
        {"role": "user", "content": EXAMPLE_2_USER},
        {"role": "assistant", "content": EXAMPLE_2_ASSISTANT},
        {
            "role": "user",
            "content": (
                f"{state}\n"
                f'Instruction: "{instruction}"\n'
                f"Transcript:\n{compact_transcript(transcript)}"
            ),
        },
    ]


class Planner:
    def __init__(self, settings: Settings | None = None, chat_fn: ChatFn | None = None):
        self.settings = settings or get_settings()
        self._chat = chat_fn or self._ollama_chat

    def plan(self, instruction: str, transcript: Transcript, state: str) -> EditPlan:
        messages = build_messages(instruction, transcript, state)
        raw = self._chat(messages)
        try:
            return _validate(raw)
        except (ValidationError, ValueError) as first_err:
            # retry once, feeding the exact error back
            retry_messages = messages + [
                {"role": "assistant", "content": raw},
                {
                    "role": "user",
                    "content": (
                        "That did not validate. Error:\n"
                        f"{first_err}\n"
                        "Return corrected JSON only, matching the action schema exactly."
                    ),
                },
            ]
            raw2 = self._chat(retry_messages)
            try:
                return _validate(raw2)
            except (ValidationError, ValueError) as second_err:
                raise PlanError(
                    "Couldn't map that to an edit. Try rephrasing.",
                    detail=str(second_err),
                ) from second_err

    def _ollama_chat(self, messages: list[dict]) -> str:
        url = f"{self.settings.ollama_host}/api/chat"
        try:
            r = httpx.post(
                url,
                json={
                    "model": self.settings.llm_model,
                    "messages": messages,
                    "format": "json",
                    "stream": False,
                    "options": {"temperature": 0.1},
                },
                timeout=120.0,
            )
        except httpx.HTTPError as e:
            raise LLMUnavailable(
                f"Ollama not reachable at {self.settings.ollama_host}. "
                f"Start it (`ollama serve`) and pull {self.settings.llm_model}."
            ) from e
        if r.status_code == 404:
            raise LLMUnavailable(
                f"Model '{self.settings.llm_model}' not found. Run "
                f"`ollama pull {self.settings.llm_model}`."
            )
        if r.status_code >= 400:
            raise LLMUnavailable(f"Ollama error {r.status_code}: {r.text[:200]}")
        data = r.json()
        return data.get("message", {}).get("content", "")


def _validate(raw: str) -> EditPlan:
    import json

    text = (raw or "").strip()
    # tolerate accidental markdown fences
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    data = json.loads(text)
    return EditPlan.model_validate(data)
