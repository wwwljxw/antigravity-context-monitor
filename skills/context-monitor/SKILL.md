---
name: context-monitor
description: Monitor conversation context window capacity, token usage, and render a real-time progress bar dashboard in Antigravity 2.0. Use this skill whenever the user asks "查看上下文", "显示容量进度条", "token使用了多少", "会话容量状态", "context status", "check context", or wants to know if the session is nearing the limit.
---

# Context Capacity Monitor for Antigravity 2.0

当用户询问当前会话的上下文容量、Token 消耗、进度条或会话状态时，执行此技能直接在对话框气泡内输出实时的可视化进度条。

## 执行步骤

1. 运行生成脚本：
   `python "%USERPROFILE%\.gemini\config\plugins\context-monitor\skills\context-monitor\scripts\generate_monitor.py"`
2. 读取脚本输出 JSON 结果中的 `markdown_card`。
3. 直接将该 Markdown 进度条卡片渲染在回复正文中，确保无需跳转、直接在当前聊天气泡内嵌入显示。
