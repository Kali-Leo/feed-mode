"""六家 OpenAI 兼容 LLM 的最小调用封装，供其他项目直接拷走。

把各家的坑封在 build_body 里：DeepSeek 不关思考会贵十倍，Qwen3 不关思考会慢十倍
并撞满 max_tokens 导致 JSON 截断。配置与实测数据见同目录 providers.json。

用法：
    from call import chat, PROVIDERS
    print(chat("dashscope", [{"role": "user", "content": "你好"}]))

密钥读取顺序：环境变量 BENCH_KEY_<id> → 同目录 keys.env。
keys.env 已被 .gitignore 排除，不会进仓库。
"""
import json, os, urllib.request, urllib.error

HERE = os.path.dirname(os.path.abspath(__file__))
PROVIDERS = json.load(open(os.path.join(HERE, "providers.json"), encoding="utf-8"))["providers"]


def load_key(pid):
    v = os.environ.get("BENCH_KEY_" + pid)
    if v:
        return v.strip()
    path = os.path.join(HERE, "keys.env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            line = line.strip()
            if line.startswith("BENCH_KEY_" + pid + "="):
                return line.split("=", 1)[1].strip()
    raise RuntimeError(f"没有 {pid} 的密钥：设环境变量 BENCH_KEY_{pid} 或写进 {path}")


def build_body(pid, messages, model=None, max_tokens=1024, json_mode=False):
    p = PROVIDERS[pid]
    model = model or p["model"]
    body = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if model.startswith("deepseek"):
        # 不关思考：reasoning token 按输出计价，实测成本约十倍
        body["thinking"] = {"type": "disabled"}
    if "qwen3" in model.lower():
        # 不关思考：40 条一批实测 88 秒，且输出撞满 max_tokens 使 JSON 截断
        body["enable_thinking"] = False
    return body


def chat(pid, messages, model=None, max_tokens=1024, json_mode=False, timeout=120, key=None):
    """返回助手回复的纯文本。抛 RuntimeError 时带上服务商的原始报错。"""
    p = PROVIDERS[pid]
    req = urllib.request.Request(
        p["url"],
        data=json.dumps(build_body(pid, messages, model, max_tokens, json_mode)).encode(),
        headers={"content-type": "application/json",
                 "authorization": "Bearer " + (key or load_key(pid))})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"{pid} HTTP {e.code}: {e.read().decode('utf-8', 'replace')[:300]}") from None


def reachable(pid, timeout=8):
    """无效 Key 发一次最小请求：收到任何 HTTP 响应即可达，抛异常即不可达。"""
    try:
        chat(pid, [{"role": "user", "content": "hi"}], max_tokens=1, timeout=timeout, key="probe")
        return True
    except RuntimeError:
        return True          # 服务端应答了，只是鉴权失败
    except Exception:
        return False


if __name__ == "__main__":
    import sys
    ids = sys.argv[1:] or [k for k, v in PROVIDERS.items() if v.get("cors")]
    for pid in ids:
        try:
            print(f"{pid:12} {chat(pid, [{'role': 'user', 'content': '回复OK两个字'}], max_tokens=10)!r}")
        except Exception as e:
            print(f"{pid:12} {str(e)[:120]}")
