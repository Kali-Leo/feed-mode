# LLM 服务商速查

七家 OpenAI 兼容服务商的配置、实测数据与踩坑记录，供其他项目直接拷走。

```python
from call import chat
chat("dashscope", [{"role": "user", "content": "你好"}])
```

`providers.json` 是机器可读配置，`call.py` 是最小封装并把各家的坑封在里面，`keys.env` 存密钥且已被 `.gitignore` 排除。密钥读取顺序为环境变量 `BENCH_KEY_<id>` 优先，其次同目录 `keys.env`。

## 横向对比

准确率与延迟来自中文短标题四分类任务，400 条冻结评测集，方法与原始数据见 [`../research/LOG.md`](../research/LOG.md) 的 E27。价格为元/百万 token。

| id | 服务商 | 模型 | 输入 | 输出 | 准确率 | 召回 | 延迟 | 大陆直连 |
|---|---|---|---|---|---|---|---|---|
| `dashscope` | 阿里百炼 | qwen-flash | 0.15 | 1.5 | **0.898** | 0.750 | 4.4s | 通 |
| `deepseek` | DeepSeek | deepseek-v4-flash | 1.58 | 4.75 | 0.893 | 0.724 | **1.3s** | 通 |
| `gemini` | Google | gemini-3.5-flash-lite | 2.13 | 17.75 | 0.883 | **0.829** | 1.9s | **不通** |
| `siliconflow` | 硅基流动 | Qwen/Qwen3-8B | **0** | **0** | 0.858 | 0.603 | 7.6s | 通 |
| `zhipu` | 智谱 | glm-4-flash-250414 | **0** | **0** | 0.855 | 0.612 | 4.7s | 通 |
| `ark` | 火山方舟 | doubao-seed-1.6-lite | 0.3 | 0.6 | 未测 | | | 通 |
| `moonshot` | 月之暗面 | kimi-k2.6 | 6.5 | 27.0 | 未测 | | | 通 |

选型速记：要准要便宜选 `dashscope`，要快选 `deepseek`，要免费选 `zhipu`，要召回高选 `gemini`，要数据条款严选 `siliconflow`。

## 坑

这部分是本目录真正的价值，每条都是实测撞出来的。

**必须显式关思考，否则代价极大。** DeepSeek 默认开思考，reasoning token 按输出计价，成本约十倍，要传 `thinking={"type":"disabled"}`。Qwen3 系列默认开思维链，40 条一批实测 88 秒且输出撞满 `max_tokens` 导致 JSON 截断，要传 `enable_thinking=false`，关掉后降到 8 秒。`call.py` 已按模型名自动处理。

**免费不等于可用。** 智谱 `glm-4.7-flash` 官方标注完全免费，实测连打 6 次全部返回 429 错误码 1305「该模型当前访问量过大」，零成功。同为免费的 `glm-4-flash-250414` 一次就通。文档查不出这类问题。

**模型会静默退役。** `gemini-2.5-flash-lite` 已对新用户下线，调用报 404 并在报错里提示改用 `gemini-3.5-flash-lite`。智谱 `glm-4.5-flash` 于 2026-01-30 下线，请求自动路由到 4.7。

**能列出不等于能调用。** 火山方舟 `GET /api/v3/models` 返回的模型 id 照样报 404 `InvalidEndpointOrModel.NotFound`，必须先在控制台「开通管理」逐个开通。

**浏览器端要先看 CORS。** 以 `Origin` 发预检实测：七家里只有月之暗面返回 204 且不带任何 CORS 头，前端项目直接排除。其余六家均放行，`Origin: null`（`file://` 页面）也放行。

**Gemini 的鉴权分两套。** OpenAI 兼容路径 `/v1beta/openai/chat/completions` 用 `Authorization: Bearer`；原生路径才用 `?key=` 或 `x-goog-api-key`，两者混用会报 400 或 403。Key 现在是 `AQ.` 开头，不是旧的 `AIza`。首次调用可能报 403 提示项目未启用 Gemini API，稍后自动生效。

**阿里的免费额度按快照版独立发放。** `qwen-flash` 与 `qwen-flash-2025-07-28` 各算一个模型、各有 100 万 token，且仅华北2（北京）地域有。未实名账号被强制开启用完即停，耗尽返回 403 `AllocationQuota.FreeTierOnly` 且不会继续扣费。

## 训练数据条款

按「是否明文承诺不将 API 输入输出用于训练」统一衡量，取自各家官方条款页：

| 档位 | 服务商 |
|---|---|
| 明文承诺不用 | 硅基流动、火山方舟、阿里按量付费 API、Google 付费层 |
| 明文说会用 | DeepSeek、Google 免费层 |
| 沉默，未作承诺 | 智谱 |

硅基流动写得最死：不用于训练，且推理后立即销毁。DeepSeek 的关闭开关只存在于对话产品，开放平台侧没有入口。
