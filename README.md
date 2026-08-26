# 首页信息流分类（B站 & YouTube）

给 B站 和 YouTube 首页加一个分类开关：专业 / 精选娱乐 / 娱乐，一键切换。内置本地模型，装上即用；填入 DeepSeek API Key 后由云端复核，更准。

- `bilibili-feed-mode.user.js` — B站
- `youtube-feed-mode.user.js` — YouTube

## 模式

- **全部**：原始首页
- **娱乐**：仅娱乐
- **精选娱乐**：仅正向情绪的娱乐，过滤引战、猎奇、贩卖焦虑
- **专业**：仅有信息量、语气克制的内容；标题党式的「专业」不算

## 安装

1. 装 [Violentmonkey](https://violentmonkey.github.io/) 或 Tampermonkey
2. 装脚本：[B站版](https://greasyfork.org/zh-CN/scripts/592929) · [YouTube版](https://greasyfork.org/zh-CN/scripts/592932)
3. 打开网站首页，左下角出现开关

## API Key（可选）

不填即可用。填入后云端复核更准：在 [platform.deepseek.com](https://platform.deepseek.com) 申请，点 ⚙ 填入，两站分别设置。「容忍」滑条调节精度与用量，用量与金额实时显示在开关条上。

## 费用与隐私

- 本项目完全免费，不经手任何费用；API 费用由你与 DeepSeek 直接结算，不填 Key 则零费用
- 仅在填 Key 后发送视频标题、作者、标签用于分类；不发送账号、Cookie、观看历史
- Key 与分类数据只存本地；B站版调用站内接口预加载内容，等同于刷新首页

## 边界

- 不屏蔽广告，不改跳转，创作者收益不受影响
- 第三方个人工具，与平台无关；修改页面显示可能不符合平台协议条款，风控风险请自行评估
- 分类由 AI 完成，不保证准确

[GPL-3.0](LICENSE) · 永久免费开源，欢迎捐赠支持
