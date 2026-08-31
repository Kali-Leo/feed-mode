"""候选 LLM 的每千条视频成本测算（E27）。

token 结构取自 E1 实测（LOG.md:13-16 行式紧凑协议）并按线上 BATCH_SIZE=40 重算：
  系统提示词 450 tok/请求（656 字符、449 汉字，约 1.7 字符/token），每请求重发一次
  每条视频载荷 23 tok（实测语料平均 33.5 字符 + 标签）
  每条视频输出 4.2 tok（"3":"p" 这种短键值）
校验：按此结构算 deepseek-v4-flash 非高峰含缓存 = ¥0.057/千条，
      E22 实测 2,368 条花 ¥0.14 = ¥0.058/千条，吻合。

用法: python3 cost_model.py
"""

SYS_TOK = 450        # 系统提示词，每请求重发
PER_VID_IN = 23      # 每条视频输入
PER_VID_OUT = 4.2    # 每条视频输出
BATCH = 40           # user.js BATCH_SIZE

def profile(n=1000):
    """返回 n 条视频的 (可缓存输入, 非缓存输入, 输出) token 数。"""
    reqs = n / BATCH
    return reqs * SYS_TOK, n * PER_VID_IN, n * PER_VID_OUT

# 元/百万 token。cache 为 None 表示不支持上下文缓存或按未命中价计。
# 价格来源见 research/LOG.md E27 与 README 的候选清单表。
MODELS = [
    # 名称,                     输入,   输出,   缓存命中输入, 备注
    ("deepseek-v4-flash 非高峰", 1.58,  4.75,  0.05,  "当前默认"),
    ("deepseek-v4-flash 高峰",   3.16,  9.50,  0.10,  "UTC 1-4/6-10 价格×2"),
    ("deepseek-v4-pro 非高峰",   4.75, 14.30,  0.16,  "打标用，非线上"),
    ("qwen-flash",              0.15,  1.50,  0.03,  "阿里百炼，隐式缓存 0.03"),
    ("doubao-seed-1.6-lite",    0.30,  0.60,  None,  "火山方舟"),
    ("doubao-seed-2.0-mini",    0.20,  2.00,  None,  "火山方舟"),
    ("GLM-4-FlashX-250414",     0.10,  0.10,  None,  "智谱，付费档最便宜"),
    ("GLM-4.7-Flash",           0.00,  0.00,  None,  "智谱免费档"),
    ("硅基流动 Qwen3-8B",        0.00,  0.00,  None,  "免费，需实名"),
]

def cost(n, pin, pout, pcache):
    cin_cacheable, cin_fresh, cout = profile(n)
    if pcache is None:
        inp = (cin_cacheable + cin_fresh) * pin
    else:
        inp = cin_cacheable * pcache + cin_fresh * pin
    return (inp + cout * pout) / 1e6

if __name__ == "__main__":
    c, f, o = profile(1000)
    print(f"每千条视频 token：可缓存输入 {c:.0f} + 非缓存输入 {f:.0f} + 输出 {o:.0f}"
          f" = 合计 {c+f+o:.0f}\n")
    base = cost(1000, 1.58, 4.75, 0.05)
    print(f"{'模型':<26}{'每千条':>10}{'相对当前':>10}   备注")
    for name, pin, pout, pc, note in MODELS:
        v = cost(1000, pin, pout, pc)
        rel = "—" if v == 0 else f"{base / v:.1f}×省" if v < base else f"{v / base:.1f}×贵"
        print(f"{name:<26}{'¥%.4f' % v:>10}{rel:>10}   {note}")

    print("\n按真实用量折算（一天刷 500 条、其中约 1/3 触发云端复核）：")
    for name, pin, pout, pc, note in MODELS[:1] + MODELS[3:]:
        m = cost(500 / 3 * 30, pin, pout, pc)
        print(f"  {name:<24} 每月 ¥{m:.3f}")
