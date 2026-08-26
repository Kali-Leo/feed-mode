"""兴趣画像引擎（参考实现，轻量轨 JS 与完整轨 daemon 共用同一套数学）。

- 事件权重：曝光=1，点击=5，观看=5+min(时长/60s, 10)（互动重于曝光）
- 主题归属：分类器全概率向量软归属（不做硬 top-1，降低单条误分类影响）
- 双时间尺度：短期半衰期 7 天，长期 90 天（文献标准配方：长短期画像）
- 增量更新：先按距上次更新的时间衰减，再累加，O(48) 每事件
"""
import numpy as np

N_TOPICS = 48
HL_SHORT = 7 * 86400.0
HL_LONG = 90 * 86400.0


def event_weight(etype, dwell_s=0.0):
    if etype == "expose":
        return 1.0
    if etype == "click":
        return 5.0
    if etype == "watch":
        return 5.0 + min(dwell_s / 60.0, 10.0)
    return 0.0


class Profile:
    def __init__(self):
        self.short = np.zeros(N_TOPICS)
        self.long = np.zeros(N_TOPICS)
        self.expose = np.zeros(N_TOPICS)  # 曝光分布（用于"平台喂了你什么" vs "你吃了什么"的对比）
        self.ts = None

    def _decay(self, now):
        if self.ts is not None:
            dt = max(0.0, now - self.ts)
            self.short *= 0.5 ** (dt / HL_SHORT)
            self.long *= 0.5 ** (dt / HL_LONG)
            self.expose *= 0.5 ** (dt / HL_LONG)
        self.ts = now

    def update(self, topic_proba, etype, dwell_s, now):
        self._decay(now)
        w = event_weight(etype, dwell_s)
        if etype == "expose":
            self.expose += topic_proba
        else:
            self.short += w * topic_proba
            self.long += w * topic_proba

    def dist(self, which="short"):
        v = getattr(self, which)
        s = v.sum()
        return v / s if s > 0 else v
