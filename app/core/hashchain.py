"""研判日志哈希链（榜单硬需求 + 加分项：防篡改）。

append-only 事件日志：每条记录含 payload_hash（防 payload 被改）、
prev_hash（防删条/乱序）、entry_hash（防元数据被改），SHA-256 串联。
可选 HMAC-SHA256 签名（VERITAS_CHAIN_KEY）：有密钥时每条附 mac，
外人可用同一密钥独立核验——「信任可移交」，不只本机自洽。

verify_chain() 逐条重算，演示口径是「改一个字即红」。
序列化走 JSONL（一行一条记录），天然 append-only，便于展示与归档。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

GENESIS_PREV = "0" * 64

# 比赛演示默认 HMAC 密钥（可独立核验；非生产秘密）。未设置环境变量时
# demo_offline / 启动器会 setdefault；生产请改 VERITAS_CHAIN_KEY。
DEMO_CHAIN_KEY = "veritas-contest-demo-hmac"


def ensure_demo_chain_key() -> None:
    """现场演示：未配置时写入默认演示密钥，链带 mac、审计包可验签。"""
    if not (os.environ.get("VERITAS_CHAIN_KEY") or "").strip():
        os.environ["VERITAS_CHAIN_KEY"] = DEMO_CHAIN_KEY


def _canonical(obj) -> str:
    """参与哈希的规范序列化：键序、无空白、保留中文。"""
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def chain_key_from_env() -> bytes | None:
    """从环境变量读链签名密钥；空则返回 None（仅哈希、不签名）。"""
    raw = (os.environ.get("VERITAS_CHAIN_KEY") or "").strip()
    return raw.encode("utf-8") if raw else None


def _mac(key: bytes, entry_hash: str) -> str:
    return hmac.new(key, entry_hash.encode("utf-8"), hashlib.sha256).hexdigest()


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
    mac: str = ""            # HMAC-SHA256(key, hash)；无密钥时为空

    def to_dict(self) -> dict:
        d = {
            "index": self.index, "ts": self.ts, "actor": self.actor,
            "event": self.event, "payload": self.payload,
            "payload_hash": self.payload_hash, "prev_hash": self.prev_hash,
            "hash": self.hash,
        }
        if self.mac:
            d["mac"] = self.mac
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "ChainRecord":
        return cls(index=int(d["index"]), ts=str(d["ts"]), actor=str(d["actor"]),
                   event=str(d["event"]), payload=dict(d.get("payload") or {}),
                   payload_hash=str(d.get("payload_hash", "")),
                   prev_hash=str(d.get("prev_hash", "")),
                   hash=str(d.get("hash", "")),
                   mac=str(d.get("mac", "") or ""))


@dataclass
class VerifyResult:
    ok: bool
    bad_index: int | None = None
    reason: str = ""
    signed: bool = False

    def __bool__(self) -> bool:
        return self.ok


class HashChain:
    """内存态哈希链；落盘用 to_jsonl/from_jsonl。

    key：HMAC 密钥。None 时读环境变量；仍为空则只做哈希自洽。
    """

    def __init__(self, records: list[ChainRecord] | None = None,
                 key: bytes | None | object = ...):
        self.records: list[ChainRecord] = records or []
        if key is ...:
            self.key = chain_key_from_env()
        else:
            self.key = key  # type: ignore[assignment]

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
        if self.key:
            record.mac = _mac(self.key, record.hash)
        self.records.append(record)
        return record

    def verify_chain(self, key: bytes | None | object = ...) -> VerifyResult:
        """逐条重算全部哈希；有密钥时再验 HMAC（演示「改一字即红」）。

        key 缺省用实例 key；显式传入可覆盖（审计包导出时复用）。
        """
        use_key = self.key if key is ... else key
        prev = GENESIS_PREV
        any_mac = False
        for rec in self.records:
            if rec.payload_hash != _sha256(_canonical(rec.payload)):
                return VerifyResult(False, rec.index, "payload 被篡改",
                                    signed=bool(use_key))
            expect = _sha256(_canonical({
                "index": rec.index, "ts": rec.ts, "actor": rec.actor,
                "event": rec.event, "payload_hash": rec.payload_hash,
                "prev_hash": rec.prev_hash,
            }))
            if rec.hash != expect:
                return VerifyResult(False, rec.index,
                                    "记录哈希不匹配（元数据被改）",
                                    signed=bool(use_key))
            if rec.prev_hash != prev:
                return VerifyResult(False, rec.index,
                                    "prev_hash 断链（删条或乱序）",
                                    signed=bool(use_key))
            if use_key:
                if rec.mac:
                    if not hmac.compare_digest(rec.mac, _mac(use_key, rec.hash)):
                        return VerifyResult(False, rec.index,
                                            "HMAC 签名不匹配", signed=True)
                    any_mac = True
                # 无 mac：旧链兼容——哈希仍可过，signed 保持 False
            prev = rec.hash
        fully_signed = bool(use_key) and bool(self.records) and all(
            r.mac for r in self.records)
        # 演示钥公开（veritas-contest-demo-hmac），signed 只表示「每条都有
        # mac 且与当前密钥一致」，不表示生产级抗伪造。缺 mac 的旧链哈希
        # 仍可过，但 signed=False——审计移交必须看 signed，不能只看 ok。
        return VerifyResult(True, signed=fully_signed)

    # -- 序列化 --

    def to_jsonl(self, path: Path) -> Path:
        lines = [json.dumps(r.to_dict(), ensure_ascii=False) for r in self.records]
        Path(path).write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return path

    @classmethod
    def from_jsonl(cls, path: Path, key: bytes | None | object = ...) -> "HashChain":
        records = [
            ChainRecord.from_dict(json.loads(line))
            for line in Path(path).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        return cls(records, key=key)
