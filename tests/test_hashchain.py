"""哈希链：追加、校验、篡改必红、JSONL 往返、HMAC 签名。"""

from app.core.hashchain import GENESIS_PREV, HashChain


def test_append_and_verify_ok():
    chain = HashChain(key=None)
    chain.append("e1", "agentA", {"k": "v"}, ts="2026-01-01T00:00:00+00:00")
    chain.append("e2", "agentB", {"k": "v2"}, ts="2026-01-01T00:01:00+00:00")
    assert len(chain.records) == 2
    assert chain.records[0].prev_hash == GENESIS_PREV
    assert chain.records[1].prev_hash == chain.records[0].hash
    result = chain.verify_chain()
    assert result.ok and result.bad_index is None
    assert not result.signed


def test_tamper_payload_turns_red():
    chain = HashChain(key=None)
    chain.append("e1", "a", {"n": 1}, ts="t1")
    chain.append("e2", "a", {"n": 2}, ts="t2")
    chain.records[1].payload["n"] = 999  # 改一个字
    result = chain.verify_chain()
    assert not result.ok
    assert result.bad_index == 1
    assert "payload" in result.reason


def test_tamper_metadata_turns_red():
    chain = HashChain(key=None)
    chain.append("e1", "a", {"n": 1}, ts="t1")
    chain.records[0].actor = "伪造者"  # 改元数据
    result = chain.verify_chain()
    assert not result.ok and result.bad_index == 0


def test_drop_middle_record_breaks_link():
    chain = HashChain(key=None)
    chain.append("e1", "a", {"n": 1}, ts="t1")
    chain.append("e2", "a", {"n": 2}, ts="t2")
    chain.append("e3", "a", {"n": 3}, ts="t3")
    del chain.records[1]  # 删中间一条
    result = chain.verify_chain()
    assert not result.ok
    assert "断链" in result.reason or "prev_hash" in result.reason


def test_jsonl_roundtrip(tmp_path):
    chain = HashChain(key=None)
    chain.append("e1", "a", {"x": "中文"}, ts="t1")
    chain.append("e2", "b", {"y": 2}, ts="t2")
    path = chain.to_jsonl(tmp_path / "chain.jsonl")
    loaded = HashChain.from_jsonl(path, key=None)
    assert [r.to_dict() for r in loaded.records] == [r.to_dict() for r in chain.records]
    assert loaded.verify_chain().ok


def test_hmac_sign_and_verify():
    key = b"contest-demo-key"
    chain = HashChain(key=key)
    chain.append("e1", "a", {"n": 1}, ts="t1")
    chain.append("e2", "a", {"n": 2}, ts="t2")
    assert all(r.mac for r in chain.records)
    result = chain.verify_chain()
    assert result.ok and result.signed


def test_hmac_wrong_key_fails():
    chain = HashChain(key=b"right-key")
    chain.append("e1", "a", {"n": 1}, ts="t1")
    bad = HashChain(list(chain.records), key=b"wrong-key")
    result = bad.verify_chain()
    assert not result.ok
    assert "签名" in result.reason


def test_hmac_tamper_mac_fails():
    chain = HashChain(key=b"k")
    chain.append("e1", "a", {"n": 1}, ts="t1")
    chain.records[0].mac = "0" * 64
    result = chain.verify_chain()
    assert not result.ok and "签名" in result.reason


def test_hmac_missing_mac_hash_ok_but_unsigned():
    """旧链无 mac：有密钥时哈希仍可通过，但不算已签名。"""
    chain = HashChain(key=None)
    chain.append("e1", "a", {"n": 1}, ts="t1")
    signed = HashChain(list(chain.records), key=b"k")
    result = signed.verify_chain()
    assert result.ok
    assert result.signed is False
