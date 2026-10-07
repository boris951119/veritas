"""两份研判产物的结论 diff（增量新材料的及格线：重跑后能对照）。"""

from __future__ import annotations

from app.core.evidence import Dossier


def diff_conclusions(old: Dossier, new: Dossier) -> dict:
    """按结论文案（去空白）对齐：新增 / 删除 / 改写。"""
    def key(c) -> str:
        return " ".join((c.statement or "").split())

    old_map = {key(c): c for c in old.conclusions if c.status != "merged"}
    new_map = {key(c): c for c in new.conclusions if c.status != "merged"}
    added = [{"id": new_map[k].id, "statement": k, "status": new_map[k].status}
             for k in new_map if k not in old_map]
    removed = [{"id": old_map[k].id, "statement": k, "status": old_map[k].status}
               for k in old_map if k not in new_map]
    return {
        "n_added": len(added), "n_removed": len(removed),
        "added": added, "removed": removed,
        "question_changed": old.question != new.question,
    }
