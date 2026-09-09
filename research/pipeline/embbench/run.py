"""在真实浏览器里跑 e5-small 的 WASM / WebGPU 推理基准，语料取自本项目 corpus。"""
import gzip, json, os, subprocess, sys, time

S = "/tmp/claude-1000/-home-leo----bilibili/aaa57abe-fdde-4c3e-8f44-50ae9e8b3af1/scratchpad"
HERE = S + "/embbench"
REPO = "/home/leo/桌面/bilibili"

rows = []
with gzip.open(REPO + "/research/data/corpus.jsonl.gz", "rt", encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i >= 64:
            break
        d = json.loads(line)
        rows.append(f"{d.get('t','')} {d.get('u','')}")

srv = subprocess.Popen([sys.executable, "-m", "http.server", "8123", "--bind", "127.0.0.1"],
                       cwd=HERE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(1)

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service

o = Options()
o.binary_location = f"{S}/cft/chrome-linux64/chrome"
o.add_argument(f"--user-data-dir={S}/profile-emb")
o.add_argument("--no-first-run"); o.add_argument("--no-sandbox")
o.add_argument("--disable-dev-shm-usage")
o.add_argument("--proxy-server=http://127.0.0.1:10808")
o.add_argument("--enable-unsafe-webgpu")
o.add_argument("--enable-features=Vulkan")
o.set_capability("goog:loggingPrefs", {"browser": "ALL"})
d = webdriver.Chrome(service=Service(f"{S}/cft/chromedriver-linux64/chromedriver"), options=o)
d.set_page_load_timeout(120)
try:
    d.get("http://127.0.0.1:8123/bench.html")
    d.execute_script("window.__TITLES = arguments[0];", rows)
    d.execute_script("window.__HF_HOST = arguments[0];", os.environ.get("HF_HOST", "https://huggingface.co"))
    d.refresh()
    d.execute_script("window.__TITLES = arguments[0];", rows)
    d.execute_script("window.__HF_HOST = arguments[0];", os.environ.get("HF_HOST", "https://huggingface.co"))

    print("等待（首次要下模型，最多 25 分钟）…", flush=True)
    res = None
    for i in range(300):
        time.sleep(5)
        res = d.execute_script("return window.__done;")
        if res:
            break
        if i % 12 == 0:
            tail = d.execute_script("return document.getElementById('log').textContent.split('\\n').slice(-2).join(' | ');")
            print(f"  t+{(i+1)*5}s {tail[:150]}", flush=True)
    print("\n=== 结果")
    print(json.dumps(res, ensure_ascii=False, indent=1) if res else "超时未完成")
    gpu = d.execute_script("return navigator.gpu ? 'WebGPU 可用' : 'WebGPU 不可用';")
    print(gpu)
finally:
    try:
        for e in d.get_log("browser")[-6:]:
            if e["level"] in ("SEVERE", "WARNING"):
                print("console:", e["message"][:160])
    except Exception:
        pass
    d.quit(); srv.terminate()
