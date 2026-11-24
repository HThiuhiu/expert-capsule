"""B5: lắp ráp CorrectionEvent từ nhãn cuối cùng của từng lượt, và accepted_firstshot.

Nhãn cuối của một lượt (`final`):
- đã qua verifier: high -> nhãn chung; medium -> nhãn verifier; dropped -> None (không tạo event, outcome "unknown").
- chưa qua verifier (nhãn ngoài nhóm cần kiểm, hoặc verifier chưa chạy): nhãn labeler.
"""
from __future__ import annotations

from typing import Optional

from ..schema import Session, Turn
from .common import CORRECTION, group

OUTCOME = {"accept_explicit": "accepted_explicit", "accept_build_on": "accepted_implicit", "new_topic": "accepted_implicit"}


def _outcome(label: Optional[str], exists: bool) -> str:
    if not exists:
        return "abandoned"
    if label in OUTCOME:
        return OUTCOME[label]
    if label in CORRECTION:
        return "corrected_again"
    return "unknown"


def session_events(s: Session, final: dict[str, dict], meta: dict) -> tuple[list[dict], list[dict]]:
    """final: turn_id -> {"label": {...} | None, "confidence": str}. Trả (events, accepted_firstshot)."""
    path = s.active_turns
    pos = {t.turn_id: k for k, t in enumerate(path)}

    def lab(t: Optional[Turn]) -> Optional[str]:
        if t is None or t.turn_id not in final or final[t.turn_id]["label"] is None:
            return None
        return final[t.turn_id]["label"]["primary_label"]

    def nxt(t: Turn, role: str) -> Optional[Turn]:
        for u in path[pos[t.turn_id] + 1:]:
            if u.role == role:
                return u
        return None

    def prv(t: Turn, role: str) -> Optional[Turn]:
        for u in reversed(path[: pos[t.turn_id]]):
            if u.role == role:
                return u
        return None

    def request_of(t: Turn) -> Optional[Turn]:
        """Lượt user gần nhất phía trước không thuộc nhóm Sửa sai."""
        u = prv(t, "user")
        while u is not None and group(lab(u)) == "correction":
            u = prv(u, "user")
        return u

    events: list[dict] = []
    chain_pos: dict[str, int] = {}
    for t in path:
        if t.role != "user" or pos[t.turn_id] == 0:
            continue
        f = final.get(t.turn_id)
        if not f or f["label"] is None or group(f["label"]["primary_label"]) != "correction":
            continue
        rejected = prv(t, "assistant")
        revised = nxt(t, "assistant")
        out_turn = nxt(revised, "user") if revised else None
        req = request_of(t)
        chain_id = f"{s.session_id}:{req.turn_id if req else 'start'}"
        chain_pos[chain_id] = chain_pos.get(chain_id, -1) + 1
        L = f["label"]
        events.append({
            "event_id": f"ev:{t.turn_id}", "session_id": s.session_id, "source": "chat",
            "turns": {"request": req.turn_id if req else None, "rejected": rejected.turn_id if rejected else None,
                      "feedback": t.turn_id, "revised": revised.turn_id if revised else None,
                      "outcome_turn": out_turn.turn_id if out_turn else None},
            "task": {"request_text": req.text if req else "", "task_type": meta.get("task_type"),
                     "domain": meta.get("domain")},
            "rejected_text": rejected.text if rejected else "", "feedback_text": t.text,
            "revised_text": revised.text if revised else "",
            "feedback": {k: L.get(k) for k in ("primary_label", "aspects", "generalizability", "idiosyncrasy",
                                                "evidence_span", "target_span")},
            "outcome": _outcome(lab(out_turn), out_turn is not None) if revised else "abandoned",
            "chain_id": chain_id, "chain_pos": chain_pos[chain_id],
            "confidence": f["confidence"], "created_at": t.created_at,
        })

    # Nhánh regenerate: anh em assistant ngoài tuyến chính -> event rephrase_retry, feedback rỗng
    by_id = {t.turn_id: t for t in s.turns}
    for t in s.turns:
        if t.role != "assistant" or t.on_active_path or t.sibling_count < 2:
            continue
        active_sib = next((u for u in path if u.role == "assistant" and u.parent_id == t.parent_id), None)
        if active_sib is None:
            continue
        req = by_id.get(t.parent_id)
        out_turn = nxt(active_sib, "user")
        events.append({
            "event_id": f"ev:regen:{t.turn_id}", "session_id": s.session_id, "source": "chat",
            "turns": {"request": req.turn_id if req else None, "rejected": t.turn_id, "feedback": None,
                      "revised": active_sib.turn_id, "outcome_turn": out_turn.turn_id if out_turn else None},
            "task": {"request_text": req.text if req else "", "task_type": meta.get("task_type"),
                     "domain": meta.get("domain")},
            "rejected_text": t.text, "feedback_text": "", "revised_text": active_sib.text,
            "feedback": {"primary_label": "rephrase_retry", "aspects": [], "generalizability": None,
                         "idiosyncrasy": None, "evidence_span": "", "target_span": ""},
            "outcome": _outcome(lab(out_turn), out_turn is not None),
            "chain_id": f"{s.session_id}:regen:{t.parent_id}", "chain_pos": 0,
            "confidence": "high", "created_at": t.created_at,
        })

    # accepted_firstshot: câu trả lời đầu tiên cho một yêu cầu (lượt user không phải Sửa sai) được nhận ngay
    firstshot: list[dict] = []
    for t in path:
        if t.role != "user" or group(lab(t)) == "correction" and pos[t.turn_id] > 0:
            continue
        ans = nxt(t, "assistant")
        if ans is None or pos[ans.turn_id] != pos[t.turn_id] + 1:
            continue
        follow = nxt(ans, "user")
        fl = lab(follow)
        if fl in ("accept_explicit", "accept_build_on"):
            firstshot.append({"session_id": s.session_id, "request_turn": t.turn_id, "answer_turn": ans.turn_id,
                              "response_turn": follow.turn_id, "accept_label": fl, "request_text": t.text,
                              "answer_text": ans.text, "task_type": meta.get("task_type"),
                              "confidence": final[follow.turn_id]["confidence"]})
    return events, firstshot
