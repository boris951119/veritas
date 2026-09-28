"""研判日志哈希链（榜单硬需求 + 加分项：防篡改）。

append-only 事件日志：每条记录含 payload_hash（防 payload 被改）、
prev_hash（防删条/乱序）、entry_hash（防元数据被改），SHA-256 串联。
verify_chain() 逐条重算，演示口径是「改一个字即红」。

序列化走 JSONL（一行一条记录），天然 append-only，便于展示与归档。
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

GENESIS_PREV = "0" * 64


def _canonical(obj) -> str:
    """参与哈希的规范序列化：键序、无空白、保留中文。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class ChainRecord:
    index: int
    ts: str                  # ISO8601 UTC
    actor: str               # 谁干的（智能体名 / pipeline / human）
    event: str               # 事件类型：case_loaded / evidence_rejected / ...
    payload: dict = field(default_factory=dict)
    payload_hash: str = ""
    prev_hash: str = ""
    hash: str = ""

    def to_dict(self) -> dict:
        return {
            "index": self.index, "ts": self.ts, "actor": self.actor,
            "event": self.event, "payload": self.payload,
            "payload_hash": self.payload_hash, "prev_hash": self.prev_hash,
            "hash": self.hash,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ChainRecord":
        return cls(index=int(d["index"]), ts=str(d["ts"]), actor=str(d["actor"]),
                   event=str(d["event"]), payload=dict(d.get("payload") or {}),
                   payload_hash=str(d.get("payload_hash", "")),
                   prev_hash=str(d.get("prev_hash", "")),
                   hash=str(d.get("hash", "")))


@dataclass
class VerifyResult:
    ok: bool
    bad_index: int | None = None
    reason: str = ""

    def __bool__(self) -> bool:
        return self.ok


class HashChain:
    """内存态哈希链；落盘用 to_jsonl/from_jsonl。"""

    def __init__(self, records: list[ChainRecord] | None = None):
        self.records: list[ChainRecord] = records or []

    @property
    def last_hash(self) -> str:
        return self.records[-1].hash if self.records else GENESIS_PREV

    def append(self, event: str, actor: str, payload: dict | None = None,
               ts: str | None = None) -> ChainRecord:
        """追加一条事件（ts 供测试注入确定时钟）。"""
        record = ChainRecord(
            index=len(self.records),
            ts=ts or datetime.now(timezone.utc).isoformat(),
            actor=actor, event=event, payload=dict(payload or {}),
        )
        record.payload_hash = _sha256(_canonical(record.payload))
        record.prev_hash = self.last_hash
        record.hash = _sha256(_canonical({
            "index": record.index, "ts": record.ts, "actor": record.actor,
            "event": record.event, "payload_hash": record.payload_hash,
            "prev_hash": record.prev_hash,
        }))
        self.records.append(record)
        return record

    def verify_chain(self) -> VerifyResult:
        """逐条重算全部哈希；返回首个坏点（演示「改一字即红」）。"""
        prev = GENESIS_PREV
        for rec in self.records:
            if rec.payload_hash != _sha256(_canonical(rec.payload)):
                return VerifyResult(False, rec.index, "payload 被篡改")
            expect = _sha256(_canonical({
                "index": rec.index, "ts": rec.ts, "actor": rec.actor,
                "event": rec.event, "payload_hash": rec.payload_hash,
                "prev_hash": rec.prev_hash,
            }))
            if rec.hash != expect:
                return VerifyResult(False, rec.index, "记录哈希不匹配（元数据被改）")
            if rec.prev_hash != prev:
                return VerifyResult(False, rec.index, "prev_hash 断链（删条或乱序）")
            prev = rec.hash
        return VerifyResult(True)

    # -- 序列化 --

    def to_jsonl(self, path: Path) -> Path:
        lines = [json.dumps(r.to_dict(), ensure_ascii=False) for r in self.records]
        Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path

    @classmethod
    def from_jsonl(cls, path: Path) -> "HashChain":
        records = [
            ChainRecord.from_dict(json.loads(line))
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return cls(records)
