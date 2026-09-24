import json
import os
import re
import sys
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def is_chinese():
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (lang_id & 0xFF) == 0x04:
            return True
    except Exception:
        pass
    lang = os.environ.get("LANG", "").lower()
    return lang.startswith("zh")

def find_active_conversation():
    brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
    if not brain_dir.exists():
        return None
    
    candidates = []
    for conv_dir in brain_dir.iterdir():
        if not conv_dir.is_dir():
            continue
        transcript_path = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
        if transcript_path.exists():
            candidates.append((transcript_path.stat().st_mtime, conv_dir, transcript_path))
            
    if not candidates:
        return None
        
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1], candidates[0][2]

def estimate_tokens(text):
    if not text:
        return 0
    chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
    other_chars = len(text) - chinese_chars
    return int(chinese_chars / 1.5 + other_chars / 3.8)

def render_ascii_bar(percentage, width=32):
    filled = int(round((percentage / 100.0) * width))
    filled = max(1 if percentage > 0 else 0, min(width, filled))
    empty = width - filled
    return "█" * filled + "░" * empty

def main():
    active = find_active_conversation()
    if not active:
        print(json.dumps({"error": "No active conversation found"}))
        return
        
    conv_dir, transcript_path = active
    
    steps = 0
    total_tokens = 5000  # Baseline system prompt + tools framing
    user_msgs = 0
    model_msgs = 0
    tool_calls = 0
    
    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                steps += 1
                try:
                    data = json.loads(line)
                    msg_type = data.get("type", "")
                    if msg_type == "USER_INPUT":
                        user_msgs += 1
                    elif msg_type == "PLANNER_RESPONSE":
                        model_msgs += 1
                    
                    content = str(data.get("content", ""))
                    thinking = str(data.get("thinking", ""))
                    t_calls = str(data.get("tool_calls", ""))
                    if t_calls and t_calls != "[]":
                        tool_calls += 1
                        
                    total_tokens += estimate_tokens(content)
                    total_tokens += estimate_tokens(thinking)
                    total_tokens += estimate_tokens(t_calls)
                except Exception:
                    pass
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return

    max_tokens = 1_000_000
    percentage = round((total_tokens / max_tokens) * 100, 2)
    remaining_tokens = max(0, max_tokens - total_tokens)
    
    zh = is_chinese()
    
    if percentage < 60:
        health_badge = "🟢 极度充沛 (健康)" if zh else "🟢 Highly Optimal (Healthy)"
        advice = "容量非常健康，可继续进行复杂任务与长代码编写。" if zh else "Capacity is optimal. Safe for extensive code generations and multi-step tasks."
    elif percentage < 85:
        health_badge = "🟡 容量适中 (留意)" if zh else "🟡 Moderate Load (Notice)"
        advice = "会话轮次较多，当前阶段完成后可考虑新开会话。" if zh else "Session turns accumulating. Consider summarizing once current goal is reached."
    else:
        health_badge = "🔴 偏高 (建议整理)" if zh else "🔴 High Load (Compact Suggested)"
        advice = "建议输入 /compact 或开启新对话，以获得最佳模型表现。" if zh else "Recommended to run /compact or start a new session for peak performance."
        
    progress_bar = render_ascii_bar(percentage, width=28)
    
    if zh:
        markdown_card = f"""> ### 🧠 上下文容量实时监控 (100万 Token 上限)
> `{progress_bar}` **`{percentage}%`** · {health_badge}
> 
> | 📊 预估消耗 | 🚀 剩余空间 | 🔢 累计步数 | ⚙️ 工具调用 | 💬 对话轮数 |
> | :--- | :--- | :--- | :--- | :--- |
> | **~{total_tokens:,}** | **> {int(remaining_tokens/1000)}k** | **{steps}** 步 | **{tool_calls}** 次 | **{user_msgs}** 轮 |
> 
> 💡 *建议：{advice}*"""
    else:
        markdown_card = f"""> ### 🧠 Context Capacity Live Monitor (1M Token Max)
> `{progress_bar}` **`{percentage}%`** · {health_badge}
> 
> | 📊 Consumed | 🚀 Remaining | 🔢 Steps | ⚙️ Tool Calls | 💬 Turns |
> | :--- | :--- | :--- | :--- | :--- |
> | **~{total_tokens:,}** | **> {int(remaining_tokens/1000)}k** | **{steps}** steps | **{tool_calls}** calls | **{user_msgs}** turns |
> 
> 💡 *Advice: {advice}*"""

    result = {
        "status": "success",
        "steps": steps,
        "tokens": total_tokens,
        "percentage": percentage,
        "health_badge": health_badge,
        "markdown_card": markdown_card
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
