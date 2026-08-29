<div align="center">

# 首页信息流分类

**为 B站 / YouTube 首页推荐流提供「专业 · 精选娱乐 · 娱乐」一键切换**

[English](README.md) | 中文

[![B站版](https://img.shields.io/greasyfork/v/592929?label=B%E7%AB%99%E7%89%88&color=00aeec)](https://greasyfork.org/zh-CN/scripts/592929)
[![YouTube版](https://img.shields.io/greasyfork/v/592932?label=YouTube%E7%89%88&color=ff0000)](https://greasyfork.org/zh-CN/scripts/592932)
[![安装量](https://img.shields.io/greasyfork/dt/592929?label=%E5%AE%89%E8%A3%85%E9%87%8F)](https://greasyfork.org/zh-CN/scripts/592929)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)

<img src="docs/switchbar.png" width="620" alt="模式开关">

<img src="docs/preview.png" width="840" alt="B站首页与模式开关（未登录状态截图）">

</div>

## ✨ 功能

- **四种模式**：全部 / 娱乐 / 精选娱乐（治愈、搞笑、才艺、萌宠等正向内容，过滤引战猎奇与贩卖焦虑）/ 专业（科普、技术、财经、纪录片等，语气克制，标题党不算）
- **内置本地模型**：装上即用，离线分类，无需任何配置
- **可选云端复核**：填入 DeepSeek API Key 后精度更高；用量与金额实时显示，「容忍」滑条控制云端调用比例，拉到头即完全关闭云端、纯离线运行
- **不碰商业内容**：不屏蔽广告、不改跳转，创作者收益不受影响

## 📊 它真的让信息流更好了吗

实测，不是自称。四分类过滤器与情绪模型在不同标签上分别训练，两者一致即为独立证据。2,368 条真实视频：

| 模式 | 视频数 | 平均情绪效价 | 负面内容占比 |
|---|---|---|---|
| **精选娱乐** | 1,061 | **+1.09** | **11.9%** |
| 娱乐 | 862 | +0.70 | 24.8% |

**精选娱乐把负面内容（引战、猎奇、贩卖焦虑）的占比砍掉一半**，效应量 Cohen's d = 0.40。方法与原始数据见 [`research/LOG.md`](research/LOG.md)（E22）。

同一差距在配套的兴趣仪表盘上随时间可见——橙线是平台投喂给你的，蓝线是你实际点开的：

<img src="docs/emo_fun_zh.png" width="880" alt="娱乐模式下的情绪曲线">
<img src="docs/emo_feelgood_zh.png" width="880" alt="精选娱乐模式下的情绪曲线">

## 🧭 配套：你自己的兴趣模型

上面的曲线来自 [`interest-model/`](interest-model/README.md)——可选的本地常驻服务，把你的浏览建模给你自己看，而不是给平台看：平台投喂与你实际点开的情绪曲线、自选时间窗的词云、新出现的兴趣、看了一半没看完的专业视频。全部数据只存在你的机器上，用户脚本一键连接。运行 `interest-model/start.sh`（Windows 双击 `start.bat`）即可，仪表盘会自动在浏览器打开，细节见其 [README](interest-model/README.md)。

## 📦 安装

1. 安装 [Violentmonkey](https://violentmonkey.github.io/) 或 [Tampermonkey](https://www.tampermonkey.net/)
2. 安装脚本：[B站版](https://greasyfork.org/zh-CN/scripts/592929) · [YouTube版](https://greasyfork.org/zh-CN/scripts/592932)
3. 打开对应网站首页，左下角出现模式开关

界面语言跟随浏览器（中文或英文）。

## 🔑 API Key（可选）

不填即可正常使用。填入后分类交由云端复核，「精选娱乐」这类细分判断明显更准。

在 [platform.deepseek.com](https://platform.deepseek.com) 申请，点开关条上的 ⚙ 填入，两个站点分别设置。

> 本项目完全免费，不经手任何费用。API 费用由你与 DeepSeek 直接结算，不填 Key 则零费用。

## 🛡️ 隐私

- 仅在填入 Key 后，向 DeepSeek 发送视频标题、作者名、标签；不发送账号、Cookie、观看历史
- Key 与全部分类数据只存本地浏览器，无任何上报
- B站版调用站内推荐接口预加载内容，等同于刷新首页；YouTube 版无预加载

## 🗂️ 仓库结构

| 路径 | 内容 |
|---|---|
| `bilibili-feed-mode.user.js` | B站用户脚本，内嵌本地分类模型 |
| `youtube-feed-mode.user.js` | YouTube 用户脚本，内嵌本地分类模型 |
| `interest-model/` | 可选配套：本地优先的个人兴趣模型，见其 [README](interest-model/README.md) |
| `research/` | 实验台账、训练管线与标注数据集，见其 [README](research/README.md) |

## ⚠️ 免责

- 第三方个人工具，与哔哩哔哩、YouTube/Google 及其关联公司无关
- 修改页面显示可能不符合平台协议部分条款，风控风险请自行评估
- 分类由 AI 完成，不保证准确

## 📄 许可证

[GPL-3.0](LICENSE) — 永久免费开源，喜欢的话点个 ⭐
