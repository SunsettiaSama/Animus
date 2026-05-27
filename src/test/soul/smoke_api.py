"""Soul HTTP API 冒烟脚本。用法（仓库根目录）:
  D:\\anaconda\\envs\\LLMs\\python.exe src/test/soul/smoke_api.py
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8300"
TIMEOUT = 30
INIT_WAIT_SEC = 120


def _req(method: str, path: str, body: dict | None = None) -> tuple[int, object]:
    url = BASE + path
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            raw = resp.read().decode("utf-8")
            try:
                return resp.status, json.loads(raw) if raw else {}
            except json.JSONDecodeError:
                return resp.status, raw
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8")
        try:
            return e.code, json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            return e.code, raw


def _wait_soul() -> dict:
    deadline = time.time() + INIT_WAIT_SEC
    last = {}
    while time.time() < deadline:
        code, data = _req("GET", "/api/soul/readiness")
        if code == 200 and isinstance(data, dict):
            last = data
            if data.get("soul_running"):
                return data
            if data.get("react_ready") and not data.get("soul_running"):
                # ReAct 已就绪但 Soul 未 start，再等一轮
                pass
        time.sleep(2)
    return last


def _case(name: str, method: str, path: str, body: dict | None = None, *, ok_codes=(200,)) -> bool:
    code, data = _req(method, path, body)
    ok = code in ok_codes
    mark = "PASS" if ok else "FAIL"
    detail = data.get("detail") if isinstance(data, dict) else data
    if isinstance(data, dict) and "error" in data:
        detail = data["error"]
    print(f"[{mark}] {method} {path} -> {code}" + (f"  ({detail})" if not ok and detail else ""))
    if ok and isinstance(data, dict):
        keys = list(data.keys())[:6]
        print(f"       keys: {keys}")
    return ok


def main() -> int:
    print(f"=== Soul API Smoke @ {BASE} ===\n")

    print("等待 Soul 初始化…")
    readiness = _wait_soul()
    if not readiness.get("soul_running"):
        print("[FAIL] Soul 未在时限内进入 running 状态")
        print(json.dumps(readiness, ensure_ascii=False, indent=2))
        return 1
    print(f"[OK] Soul running  state={readiness.get('soul_state')!r}\n")

    results: list[bool] = []

    # 无需 Soul 实例的配置类接口
    results.append(_case("soul config", "GET", "/api/soul/config"))
    results.append(_case("memory config", "GET", "/api/soul/memory/config"))
    results.append(_case("memory infra", "GET", "/api/soul/memory/infra"))
    results.append(_case("readiness", "GET", "/api/soul/readiness"))

    # 需要 Soul 实例
    results.append(_case("status", "GET", "/api/soul/status"))
    results.append(_case("persona", "GET", "/api/soul/persona"))
    results.append(_case("memory search recent", "POST", "/api/soul/memory/search", {"mode": "recent", "top_k": 3}))
    results.append(_case("life chronicle", "GET", "/api/soul/life/chronicle?days=7&tail=10"))
    results.append(_case("life hot", "GET", "/api/soul/life/hot"))
    results.append(_case("speak status", "GET", "/api/speak/status"))
    results.append(_case("speak reset", "POST", "/api/speak/reset", {}))

    passed = sum(results)
    total = len(results)
    print(f"\n=== 结果: {passed}/{total} 通过 ===")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
