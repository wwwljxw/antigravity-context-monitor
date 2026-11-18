"""Shared Antigravity transcript parser and 5-category context breakdown."""

import json
import re
import time
from pathlib import Path

BRAIN_DIR = Path.home() / ".gemini" / "antigravity" / "brain"

CATEGORIES = [
    ("system", "#6366f1", "系统提示词", "System Prompt"),
    ("tools", "#10b981", "工具及子智能体", "Tools & Subagents"),
    ("messages", "#f59e0b", "对话消息", "Messages"),
    ("mcp", "#8b5cf6", "连接器及MCP", "Connectors & MCP"),
    ("skills", "#ec4899", "技能", "Skills"),
]

_BASELINE_CACHE = {"ts": 0.0, "data": None}
_TRANSCRIPT_CACHE = {}


def estimate_tokens(text):
    """Estimate token count for mixed CJK/English text."""
    if not text:
        return 0
    cn = len(re.findall(r"[\u4e00-\u9fff]", text))
    return int(cn / 1.5 + (len(text) - cn) / 3.8)


def measure_disk_baseline():
    """Measure fixed prompt overhead from installed rules, skills, and MCP dirs (cached 30s)."""
    now = time.time()
    if _BASELINE_CACHE["data"] is not None and (now - _BASELINE_CACHE["ts"]) < 30.0:
        return dict(_BASELINE_CACHE["data"])

    agy_dir = Path.home() / ".gemini" / "antigravity"
    cfg_dir = Path.home() / ".gemini" / "config"

    # 1. User rules (~/.gemini/config/rules/*.md)
    rules_tok = 0
    rules_dir = cfg_dir / "rules"
    if rules_dir.exists():
        for rf in rules_dir.glob("*.md"):
            try:
                rules_tok += estimate_tokens(rf.read_text(encoding="utf-8", errors="ignore"))
            except Exception:
                pass

    # 2. Installed SKILL.md frontmatter metadata injected into <skills>
    skills_chars = 0
    seen_skills = set()
    for root in (agy_dir / "builtin" / "skills", cfg_dir / "plugins", Path.home() / ".agents" / "skills"):
        if not root.exists():
            continue
        for sm in root.rglob("SKILL.md"):
            try:
                txt = sm.read_text(encoding="utf-8", errors="ignore")
                m = re.match(r"^---\s*\n(.*?)\n---", txt, re.S)
                if not m:
                    continue
                hdr = m.group(1)
                nm = re.search(r"^name:\s*(.+)$", hdr, re.M)
                name = nm.group(1).strip() if nm else sm.parent.name
                if name in seen_skills:
                    continue
                seen_skills.add(name)
                skills_chars += len(hdr) + len(str(sm)) + 24
            except Exception:
                pass
    skills_base_tok = max(400, int(skills_chars / 3.5)) if seen_skills else 400

    # 3. MCP tool index injected into <mcp_servers>
    mcp_chars = 0
    mcp_dir = agy_dir / "mcp"
    if mcp_dir.exists():
        for srv in mcp_dir.iterdir():
            if srv.is_dir():
                mcp_chars += len(srv.name) + 24 + sum(len(f.stem) + 2 for f in srv.glob("*.json"))
    mcp_base_tok = max(150, int(mcp_chars / 3.5) + 120) if mcp_chars else 120

    baseline = {
        "system": 6500 + rules_tok,
        "tools": 3500,
        "mcp": mcp_base_tok,
        "skills": skills_base_tok,
    }
    _BASELINE_CACHE["ts"] = now
    _BASELINE_CACHE["data"] = baseline
    return dict(baseline)


def _classify_tool_calls(tool_calls):
    """Classify a step's tool_calls list into ('mcp' | 'skills' | 'tools') per call."""
    kinds = []
    for tc in tool_calls:
        if not isinstance(tc, dict):
            kinds.append("tools")
            continue
        name = str(tc.get("name") or tc.get("function", {}).get("name") or "").lower()
        args_str = json.dumps(tc.get("arguments") or tc.get("args") or tc, ensure_ascii=False).lower()
        if name in ("call_mcp_tool", "list_resources", "read_resource"):
            kinds.append("mcp")
        elif name == "read_file" and ("\\antigravity\\mcp\\" in args_str or "/antigravity/mcp/" in args_str):
            kinds.append("mcp")
        elif name == "read_file" and "skill.md" in args_str:
            kinds.append("skills")
        else:
            kinds.append("tools")
    return kinds


def _load_active_steps(log_dir):
    """Parse transcript.jsonl and hydrate truncated active steps from transcript_full.jsonl."""
    tp = log_dir / "transcript.jsonl"
    if not tp.exists():
        return None

    fp = log_dir / "transcript_full.jsonl"
    tp_mtime = tp.stat().st_mtime
    fp_mtime = fp.stat().st_mtime if fp.exists() else 0.0
    cache_key = str(tp)
    cached = _TRANSCRIPT_CACHE.get(cache_key)
    if cached and cached["tp_mtime"] == tp_mtime and cached["fp_mtime"] == fp_mtime:
        return cached["data"]

    with open(tp, "r", encoding="utf-8", errors="ignore") as f:
        lines = [json.loads(line) for line in f if line.strip()]

    total_steps = len(lines)
    user_msgs = 0
    model_msgs = 0
    tool_calls_count = 0
    latest_cp_idx = -1

    for idx, data in enumerate(lines):
        msg_type = data.get("type", "")
        if msg_type == "USER_INPUT":
            user_msgs += 1
        elif msg_type == "PLANNER_RESPONSE":
            model_msgs += 1
        elif msg_type == "CHECKPOINT":
            latest_cp_idx = idx
        t_calls = data.get("tool_calls")
        if t_calls:
            tool_calls_count += 1

    is_compacted = latest_cp_idx != -1
    active_start_idx = latest_cp_idx if is_compacted else 0
    active = lines[active_start_idx:]

    if fp.exists() and any(step.get("truncated_fields") for step in active):
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as ff:
                full_raw = ff.read().splitlines()
            for rel_idx, step in enumerate(active):
                global_idx = active_start_idx + rel_idx
                if step.get("truncated_fields") and global_idx < len(full_raw) and full_raw[global_idx].strip():
                    active[rel_idx] = json.loads(full_raw[global_idx])
        except Exception:
            pass

    parsed = {
        "steps": total_steps,
        "active_steps": total_steps - active_start_idx,
        "is_compacted": is_compacted,
        "user_msgs": user_msgs,
        "model_msgs": model_msgs,
        "tool_calls_count": tool_calls_count,
        "active": active,
    }
    _TRANSCRIPT_CACHE[cache_key] = {"tp_mtime": tp_mtime, "fp_mtime": fp_mtime, "data": parsed}
    return parsed


def _reconcile_totals(cats, total_tokens, dyn_msg, dyn_tools):
    """Align the 5 category estimates so their sum matches total_tokens."""
    if total_tokens <= 0:
        return {k: 0 for k in cats}

    raw_sum = sum(cats.values())
    diff = total_tokens - raw_sum
    if diff > 0:
        if (dyn_msg + dyn_tools) > 2000:
            pool = cats["messages"] + cats["tools"]
            add_msg = int(diff * (cats["messages"] / pool)) if pool > 0 else diff
            cats["messages"] += add_msg
            cats["tools"] += diff - add_msg
        else:
            cats["system"] += diff
    elif diff < 0 and raw_sum > 0:
        scale = total_tokens / raw_sum
        for k in cats:
            cats[k] = int(cats[k] * scale)
        cats["messages"] = max(0, cats["messages"] + (total_tokens - sum(cats.values())))
    return cats


def analyze_conversation(conv_id, max_tokens):
    """Compute total tokens and 5-category breakdown for an Antigravity conversation."""
    empty_cats = {key: 0 for key, _, _, _ in CATEGORIES}
    if not conv_id or conv_id == "new":
        return _format_result(0, max_tokens, 0, 0, False, 0, 0, 0, empty_cats)

    log_dir = BRAIN_DIR / conv_id / ".system_generated" / "logs"
    parsed = _load_active_steps(log_dir)
    if not parsed:
        return _format_result(0, max_tokens, 0, 0, False, 0, 0, 0, empty_cats)

    active = parsed["active"]
    base = measure_disk_baseline()

    last_pr_idx = -1
    for i in range(len(active) - 1, -1, -1):
        if "input_tokens" in active[i]:
            last_pr_idx = i
            break

    if last_pr_idx != -1:
        pr = active[last_pr_idx]
        total_tokens = pr.get("input_tokens", 0) + pr.get("cache_read_tokens", 0)
        for step in active[last_pr_idx + 1:]:
            total_tokens += (
                estimate_tokens(str(step.get("content", "")))
                + estimate_tokens(str(step.get("thinking", "")))
                + estimate_tokens(str(step.get("tool_calls", "")))
            )
    else:
        total_tokens = sum(base.values())
        for step in active:
            total_tokens += (
                estimate_tokens(str(step.get("content", "")))
                + estimate_tokens(str(step.get("thinking", "")))
                + estimate_tokens(str(step.get("tool_calls", "")))
            )

    dyn_tools = 0
    dyn_msg = 0
    dyn_mcp = 0
    dyn_skills = 0
    pending_kinds = []

    for step in active:
        st = step.get("type", "")
        tcalls = step.get("tool_calls") or []
        tc_tok = estimate_tokens(str(tcalls)) if tcalls else 0
        content_tok = estimate_tokens(str(step.get("content", "")))
        thinking_tok = estimate_tokens(str(step.get("thinking", "")))

        if st == "USER_INPUT":
            pending_kinds.clear()
            dyn_msg += content_tok + thinking_tok + tc_tok
            continue

        if st == "CHECKPOINT":
            pending_kinds.clear()
            dyn_msg += content_tok + thinking_tok
            continue

        call_kinds = _classify_tool_calls(tcalls) if tcalls else []
        if call_kinds:
            pending_kinds.extend(call_kinds)

        if st == "GENERIC":
            kind = pending_kinds.pop(0) if pending_kinds else "tools"
            if kind == "mcp":
                dyn_mcp += content_tok
            elif kind == "skills":
                dyn_skills += content_tok
            else:
                dyn_tools += content_tok
        elif st == "PLANNER_RESPONSE":
            dyn_msg += content_tok + thinking_tok
            if tc_tok:
                dominant = "mcp" if "mcp" in call_kinds else ("skills" if "skills" in call_kinds else "tools")
                if dominant == "mcp":
                    dyn_mcp += tc_tok
                elif dominant == "skills":
                    dyn_skills += tc_tok
                else:
                    dyn_tools += tc_tok
        else:
            dyn_msg += content_tok + thinking_tok + tc_tok

    raw_cats = {
        "system": base["system"],
        "tools": base["tools"] + dyn_tools,
        "messages": dyn_msg,
        "mcp": base["mcp"] + dyn_mcp,
        "skills": base["skills"] + dyn_skills,
    }
    cats = _reconcile_totals(raw_cats, total_tokens, dyn_msg, dyn_tools)

    return _format_result(
        total_tokens,
        max_tokens,
        parsed["steps"],
        parsed["active_steps"],
        parsed["is_compacted"],
        parsed["user_msgs"],
        parsed["model_msgs"],
        parsed["tool_calls_count"],
        cats,
    )


def _format_k(tokens):
    if tokens >= 1000:
        return f"{tokens / 1000:.1f}k"
    return f"{tokens}"


def _format_result(total_tokens, max_tokens, steps, active_steps, is_compacted, user_msgs, model_msgs, tool_calls_count, cats):
    denom = max_tokens if max_tokens > 0 else 1_000_000
    breakdown = []
    for key, color, label_zh, label_en in CATEGORIES:
        tok = max(0, int(cats.get(key, 0)))
        pct = round((tok / denom) * 100, 1)
        exact_pct = round((tok / denom) * 100, 3)
        breakdown.append({
            "key": key,
            "color": color,
            "label_zh": label_zh,
            "label_en": label_en,
            "tokens": tok,
            "tokens_k": _format_k(tok),
            "pct": pct,
            "bar_pct": exact_pct,
        })

    return {
        "tokens": total_tokens,
        "steps": steps,
        "active_steps": active_steps,
        "is_compacted": is_compacted,
        "user_msgs": user_msgs,
        "model_msgs": model_msgs,
        "tool_calls": tool_calls_count,
        "breakdown": breakdown,
    }
