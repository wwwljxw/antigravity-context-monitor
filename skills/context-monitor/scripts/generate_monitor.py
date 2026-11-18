import asyncio
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def is_chinese():
    if sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.check_output(["defaults", "read", "-g", "AppleLanguages"], text=True)
            if "zh" in out:
                return True
        except Exception:
            pass
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (lang_id & 0xFF) == 0x04:
            return True
    except Exception:
        pass
    lang = (os.environ.get("LANG") or os.environ.get("LC_ALL") or "").lower()
    return lang.startswith("zh")

def find_port_file():
    candidates = [
        Path.home() / "Library" / "Application Support" / "Antigravity" / "DevToolsActivePort",
        Path(os.environ.get("APPDATA", "")) / "Antigravity" / "DevToolsActivePort",
        Path.home() / "AppData" / "Roaming" / "Antigravity" / "DevToolsActivePort",
        Path.home() / ".config" / "Antigravity" / "DevToolsActivePort",
    ]
    for c in candidates:
        if c.exists():
            return c
    return None

def get_active_model_from_cdp():
    port_file = find_port_file()
    if not port_file or not port_file.exists():
        return None
    try:
        import websockets
        port = int(port_file.read_text(encoding="utf-8").splitlines()[0].strip())
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=1.5)
        targets = json.loads(req.read().decode("utf-8"))
        pages = [t for t in targets if t.get("type") == "page" and not t.get("url", "").startswith("devtools://")]
        if not pages:
            return None
        ws_url = pages[0]["webSocketDebuggerUrl"]

        async def _query():
            async with websockets.connect(ws_url, open_timeout=1.5, close_timeout=1) as ws:
                expr = """
                (() => {
                    let btn = document.querySelector('button[aria-label*="Select model"], button[aria-label*="选择模型"]');
                    if (btn) return btn.innerText.trim();
                    return "";
                })()
                """
                await ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate", "params": {"expression": expr, "returnByValue": True}}))
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=1.5))
                    if msg.get("id") == 1:
                        return msg.get("result", {}).get("result", {}).get("value") or None
        return asyncio.run(_query())
    except Exception:
        return None

def query_ls_model_limit(model_name):
    ls_addr = os.environ.get("ANTIGRAVITY_LS_ADDRESS")
    csrf = os.environ.get("ANTIGRAVITY_CSRF_TOKEN")
    if not ls_addr or not csrf or not model_name:
        return None
    try:
        req = urllib.request.Request(
            f"http://{ls_addr}/exa.language_server_pb.LanguageServerService/GetAvailableModels",
            data=b"{}",
            headers={"Content-Type": "application/json", "x-codeium-csrf-token": csrf},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        models = data.get("response", {}).get("models", {})
        target = re.sub(r"[\s()]+", "", model_name.lower())
        for m in models.values():
            dn = m.get("displayName", "")
            if dn and re.sub(r"[\s()]+", "", dn.lower()) == target:
                max_t = m.get("maxTokens")
                compact_t = None
                try:
                    cp_str = m.get("modelExperiments", {}).get("experiments", {}).get("CASCADE_USE_EXPERIMENT_CHECKPOINTER", {}).get("stringValue", "")
                    if cp_str:
                        cp_cfg = json.loads(cp_str)
                        if cp_cfg.get("enabled") and cp_cfg.get("max_token_limit"):
                            compact_t = int(cp_cfg["max_token_limit"])
                except Exception:
                    pass
                if max_t and int(max_t) > 0:
                    return int(max_t), dn, compact_t
    except Exception:
        pass
    return None

def get_model_limit(model_name):
    ls_hit = query_ls_model_limit(model_name)
    if ls_hit:
        max_tokens, display_name, compact_limit = ls_hit
        if max_tokens >= 2_000_000:
            label = "2M"
        elif max_tokens == 1_048_576:
            label = "1,048k"
        elif max_tokens == 1_000_000:
            label = "1M"
        else:
            label = f"{max_tokens // 1000}k"
        return max_tokens, label, display_name, compact_limit

    m = (model_name or "").lower()
    if "gpt-oss" in m or "oss-120b" in m:
        return 131_072, "128k", model_name, 80_000
    if "flash-image" in m or "flash image" in m:
        return 65_536, "64k", model_name, None
    if "claude" in m:
        if any(v in m for v in ["5.5", "5."]):
            return 1_000_000, "1M", model_name, 256_000
        return 200_000, "200k", model_name, 160_000
    if any(k in m for k in ["gpt-4", "o1", "o3", "o4"]):
        return 200_000, "200k", model_name, 160_000
    if "pro" in m and "1.5" in m:
        return 2_097_152, "2M", model_name, 512_000
    if any(k in m for k in ["gemini 4", "gemini-4", "hydrogen", "argon", "carbon"]):
        return 1_048_576, "1,048k", model_name, 512_000
    if "3.8" in m:
        return 1_048_576, "1,048k", model_name, 256_000
    if "gemini" in m:
        return 1_048_576, "1,048k", model_name, 128_000
    return 1_000_000, "1M", model_name or "Antigravity Model", 512_000

def find_active_conversation():
    brain_dir = Path.home() / ".gemini" / "antigravity" / "brain"
    if not brain_dir.exists():
        return None

    env_conv = os.environ.get("ANTIGRAVITY_CONVERSATION_ID")
    if env_conv:
        conv_dir = brain_dir / env_conv
        tp = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
        if tp.exists():
            return conv_dir, tp

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

def render_ascii_bar(percentage, compact_pct=None, width=28):
    filled = int(round((percentage / 100.0) * width))
    filled = max(1 if percentage > 0 else 0, min(width, filled))
    chars = ["█" if i < filled else "░" for i in range(width)]
    if compact_pct is not None and 0 < compact_pct < 100:
        cp_idx = max(1, min(width - 1, int(round((compact_pct / 100.0) * width))))
        chars[cp_idx] = "│"
    return "".join(chars)

def main():
    active = find_active_conversation()
    if not active:
        print(json.dumps({"error": "No active conversation found"}))
        return

    conv_dir, transcript_path = active

    steps = 0
    total_tokens = 0
    user_msgs = 0
    model_msgs = 0
    tool_calls = 0
    is_compacted = False
    active_steps = 0

    try:
        with open(transcript_path, "r", encoding="utf-8", errors="ignore") as f:
            lines = [json.loads(line) for line in f if line.strip()]

        steps = len(lines)
        for data in lines:
            msg_type = data.get("type", "")
            if msg_type == "USER_INPUT":
                user_msgs += 1
            elif msg_type == "PLANNER_RESPONSE":
                model_msgs += 1
            t_calls = str(data.get("tool_calls", ""))
            if t_calls and t_calls != "[]":
                tool_calls += 1

        latest_cp_idx = -1
        for i in range(len(lines) - 1, -1, -1):
            if lines[i].get("type") == "CHECKPOINT":
                latest_cp_idx = i
                break

        is_compacted = (latest_cp_idx != -1)
        active_start_idx = latest_cp_idx if is_compacted else 0
        active_steps = steps - active_start_idx

        last_pr_idx = -1
        for i in range(len(lines) - 1, active_start_idx - 1, -1):
            if "input_tokens" in lines[i]:
                last_pr_idx = i
                break

        BASE_SYSTEM_TOKENS = 18000

        if last_pr_idx != -1:
            pr_data = lines[last_pr_idx]
            total_tokens = pr_data.get("input_tokens", 0) + pr_data.get("cache_read_tokens", 0)
            for i in range(last_pr_idx + 1, len(lines)):
                step_data = lines[i]
                total_tokens += (estimate_tokens(str(step_data.get("content", ""))) +
                                 estimate_tokens(str(step_data.get("thinking", ""))) +
                                 estimate_tokens(str(step_data.get("tool_calls", ""))))
        else:
            total_tokens = BASE_SYSTEM_TOKENS
            for i in range(active_start_idx, len(lines)):
                step_data = lines[i]
                total_tokens += (estimate_tokens(str(step_data.get("content", ""))) +
                                 estimate_tokens(str(step_data.get("thinking", ""))) +
                                 estimate_tokens(str(step_data.get("tool_calls", ""))))
    except Exception as e:
        print(json.dumps({"error": str(e)}))
        return

    cli_model = sys.argv[1] if len(sys.argv) > 1 else None
    model_name = cli_model or get_active_model_from_cdp() or "Antigravity Model"
    max_tokens, limit_label, resolved_model, compact_limit = get_model_limit(model_name)

    percentage = min(100.0, round((total_tokens / max_tokens) * 100, 2))
    remaining_tokens = max(0, max_tokens - total_tokens)
    compact_pct = round((compact_limit / max_tokens) * 100, 2) if compact_limit else None
    compact_label = f"{compact_limit // 1000}k" if compact_limit else None
    compact_rem_k = max(0, (compact_limit - total_tokens) // 1000) if compact_limit else None
    compact_ratio = (total_tokens / compact_limit) if compact_limit else (percentage / 100.0)

    zh = is_chinese()

    if compact_ratio < 0.70:
        health_badge = "🟢 极度充沛 (健康)" if zh else "🟢 Highly Optimal (Healthy)"
        if is_compacted:
            advice = "已完成上下文压缩，当前空间充裕，可继续进行复杂任务与长代码编写。" if zh else "Context compacted. Capacity is optimal for extensive tasks."
        else:
            advice = "容量非常健康，可继续进行复杂任务与长代码编写。" if zh else "Capacity is optimal. Safe for extensive code generations and multi-step tasks."
    elif compact_ratio < 0.92:
        health_badge = "🟡 接近压缩线 (留意)" if zh else "🟡 Near Auto-Compact (Notice)"
        if compact_label:
            advice = f"距自动压缩阈值 ({compact_label}) 仅剩约 {compact_rem_k}k，当前阶段完成后可主动做总结。" if zh else f"~{compact_rem_k}k left before {compact_label} auto-compact. Consider summarizing soon."
        else:
            advice = "会话轮次较多，当前阶段完成后可考虑新开会话。" if zh else "Session turns accumulating. Consider summarizing once current goal is reached."
    else:
        health_badge = "🔴 即将触发压缩" if zh else "🔴 Auto-Compact Imminent"
        if compact_label:
            advice = f"已接近/达到自动压缩阈值 ({compact_label})，即将触发自动摘要或建议执行 /compact。" if zh else f"At/near {compact_label} auto-compact threshold. Recommended to run /compact."
        else:
            advice = "建议输入 /compact 或开启新对话，以获得最佳模型表现。" if zh else "Recommended to run /compact or start a new session for peak performance."

    progress_bar = render_ascii_bar(percentage, compact_pct=compact_pct, width=28)

    steps_display = f"{steps} 步 (压缩后活跃: {active_steps} 步)" if is_compacted else f"{steps} 步"
    steps_display_en = f"{steps} steps (Active: {active_steps})" if is_compacted else f"{steps} steps"

    compact_line_zh = f"\n> ⚡ *自动压缩线 (`│`)：`{compact_label}`（距自动压缩还剩 **`> {compact_rem_k}k`**）*" if compact_label else ""
    compact_line_en = f"\n> ⚡ *Auto-compact line (`│`): `{compact_label}` (**`> {compact_rem_k}k`** left before compact)*" if compact_label else ""

    if zh:
        markdown_card = f"""> ### 🧠 上下文监控 ({resolved_model} · {limit_label} 物理上限)
> `{progress_bar}` **`{percentage}%`** · {health_badge}{compact_line_zh}
> 
> | 📊 活跃上下文 | 🚀 物理剩余 | 🔢 交互步数 | ⚙️ 工具调用 | 💬 对话轮数 |
> | :--- | :--- | :--- | :--- | :--- |
> | **~{total_tokens:,}** | **> {int(remaining_tokens/1000)}k** | **{steps_display}** | **{tool_calls}** 次 | **{user_msgs}** 轮 |
> 
> 💡 *建议：{advice}*"""
    else:
        markdown_card = f"""> ### 🧠 Context Monitor ({resolved_model} · {limit_label} Physical Max)
> `{progress_bar}` **`{percentage}%`** · {health_badge}{compact_line_en}
> 
> | 📊 Active Context | 🚀 Physical Left | 🔢 Steps | ⚙️ Tool Calls | 💬 Turns |
> | :--- | :--- | :--- | :--- | :--- |
> | **~{total_tokens:,}** | **> {int(remaining_tokens/1000)}k** | **{steps_display_en}** | **{tool_calls}** calls | **{user_msgs}** turns |
> 
> 💡 *Advice: {advice}*"""

    result = {
        "status": "success",
        "model": resolved_model,
        "max_tokens": max_tokens,
        "compact_limit": compact_limit,
        "limit_label": limit_label,
        "steps": steps,
        "active_steps": active_steps,
        "is_compacted": is_compacted,
        "tokens": total_tokens,
        "percentage": percentage,
        "health_badge": health_badge,
        "markdown_card": markdown_card
    }
    print(json.dumps(result, ensure_ascii=False))

if __name__ == "__main__":
    main()
