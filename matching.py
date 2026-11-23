"""Skill-exchange matching logic (pure functions, no database access).

A *profile* is {"name": str, "teach": set[str], "learn": set[str]} with lower-cased skill names.

Two-person match  : A teaches something B wants to learn AND B teaches something A wants to learn.
Three-person cycle: me -> x -> y -> me, where each arrow means "teaches a skill the next person
                    wants to learn" (e.g. A: design -> B, B: video editing -> C, C: Python -> A).
"""
from itertools import permutations


def _give(a: dict, b: dict) -> list:
    """Skills person `a` can teach that person `b` wants to learn."""
    return sorted(a["teach"] & b["learn"])


def find_pair_matches(me_id, profiles: dict) -> list:
    me = profiles[me_id]
    out = []
    for oid, other in profiles.items():
        if oid == me_id:
            continue
        i_teach, they_teach = _give(me, other), _give(other, me)
        if i_teach and they_teach:
            out.append({
                "type": "pair",
                "members": [me_id, oid],
                "edges": [
                    {"teacher": me_id, "learner": oid, "skills": i_teach},
                    {"teacher": oid, "learner": me_id, "skills": they_teach},
                ],
                "score": len(i_teach) + len(they_teach),
            })
    return sorted(out, key=lambda m: -m["score"])


def find_triangle_matches(me_id, profiles: dict) -> list:
    me = profiles[me_id]
    others = [u for u in profiles if u != me_id]
    seen, out = set(), []
    for x, y in permutations(others, 2):
        e1, e2, e3 = _give(me, profiles[x]), _give(profiles[x], profiles[y]), _give(profiles[y], me)
        if not (e1 and e2 and e3):
            continue
        key = frozenset((me_id, x, y))
        if key in seen:
            continue  # same trio, opposite direction: keep the first found
        seen.add(key)
        out.append({
            "type": "triangle",
            "members": [me_id, x, y],
            "edges": [
                {"teacher": me_id, "learner": x, "skills": e1},
                {"teacher": x, "learner": y, "skills": e2},
                {"teacher": y, "learner": me_id, "skills": e3},
            ],
            "score": len(e1) + len(e2) + len(e3),
        })
    return sorted(out, key=lambda m: -m["score"])


def find_matches(me_id, profiles: dict) -> dict:
    if me_id not in profiles or not profiles[me_id]["teach"] or not profiles[me_id]["learn"]:
        return {"pairs": [], "triangles": []}
    return {
        "pairs": find_pair_matches(me_id, profiles),
        "triangles": find_triangle_matches(me_id, profiles),
    }
