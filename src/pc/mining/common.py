"""Nhãn (B3), nhóm nhãn, tiện ích dùng chung cho mining."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any, Optional

CORRECTION = ("correct_with_fix", "reject_no_fix", "rephrase_retry", "constraint_add", "challenge", "redirect_method")
ACCEPT = ("accept_explicit", "accept_build_on")
NEUTRAL = ("followup_info", "new_topic", "other")
PRIMARY = CORRECTION + ACCEPT + NEUTRAL

ASPECTS = ("correctness", "reasoning_method", "evidence_rigor", "assumptions", "scope_depth",
           "structure_format", "tone_style", "actionability", "domain_norm")
GENERALIZABILITY = ("one_off", "task_type", "global")
IDIOSYNCRASY = ("universal", "domain_norm", "personal")
MOVES = ("frame", "delegate", "explore", "decompose", "probe", "verify", "compare", "decide", "refine",
         "share_result", "teach_me", "consolidate", "meta", "close")

PRIMARY_DEF = {
    "correct_with_fix": "Says the answer is wrong or not good enough AND gives the correct content or direction.",
    "reject_no_fix": "Expresses that it is wrong or unsatisfying but does not say how to fix it.",
    "rephrase_retry": "Repeats the same request in other words (or edits the prompt / regenerates).",
    "constraint_add": "Adds a requirement the answer missed (format, depth, scope).",
    "challenge": "Questions correctness, asks for evidence, asks to state assumptions.",
    "redirect_method": "Imposes their own way of working: where to start, which order/method to follow.",
    "accept_explicit": "Praises or clearly confirms the answer, with specific content.",
    "accept_build_on": "Uses the result and moves to the next step (implicit acceptance, weak signal).",
    "followup_info": "Asks for more information without evaluating the answer.",
    "new_topic": "Switches to a different topic.",
    "other": "Anything else.",
}
MOVE_DEF = {
    "frame": "sets context, goal, constraints", "delegate": "asks the AI to produce an artifact",
    "explore": "open question, brainstorm", "decompose": "asks for a plan or step breakdown",
    "probe": "digs deeper into one part", "verify": "asks for evidence, re-check, or critique",
    "compare": "compares options", "decide": "the user commits to a choice",
    "refine": "edits/improves an existing artifact", "share_result": "brings an external result back to analyze",
    "teach_me": "asks for explanation, examples, comparison to learn", "consolidate": "asks for summary, spec, final version",
    "meta": "instructs the AI how to answer", "close": "ends the session",
}


def group(label: Optional[str]) -> str:
    if label in CORRECTION:
        return "correction"
    if label in ACCEPT:
        return "accept"
    return "neutral"


def needs_evidence(label: str) -> bool:
    return label in CORRECTION or label == "accept_explicit"


def clip(text: str, head: int, tail: int = 0) -> str:
    """Giữ `head` ký tự đầu và `tail` ký tự cuối (xấp xỉ 4 ký tự/token)."""
    if len(text) <= head + tail + 20:
        return text
    return text[:head] + "\n[... đã cắt ...]\n" + (text[-tail:] if tail else "")


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.M)


def parse_json(text: str) -> Optional[dict]:
    t = _FENCE.sub("", text.strip())
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except json.JSONDecodeError:
        pass
    i, j = t.find("{"), t.rfind("}")
    if i >= 0 and j > i:
        try:
            v = json.loads(t[i:j + 1])
            return v if isinstance(v, dict) else None
        except json.JSONDecodeError:
            return None
    return None


def stable_frac(*parts: Any) -> float:
    """Số trong [0,1) ổn định theo nội dung, để lấy mẫu tái lập được."""
    h = hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()
    return int(h[:8], 16) / 2 ** 32
