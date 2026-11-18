import sys, os, time, json, re, urllib.request, asyncio, socket, traceback
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
from context_breakdown import analyze_conversation, estimate_tokens

# Auto-install websockets if missing on a new machine
try:
    import websockets
except ImportError:
    try:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "websockets", "-q"])
        import websockets
    except Exception as e:
        sys.exit(1)

PLUGIN_DIR = Path(__file__).resolve().parents[3]
LOG_FILE = PLUGIN_DIR / "daemon.log"

def log(msg):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}\n")
    except Exception:
        pass

if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Single-instance mutex lock
LOCK_PORT = 38291
try:
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        _lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    else:
        _lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _lock_socket.bind(('127.0.0.1', LOCK_PORT))
    _lock_socket.listen(1)
    log("Acquired single-instance lock on port 38291")
except socket.error as e:
    log(f"Another instance is running (port {LOCK_PORT} busy): {e}. Exiting.")
    sys.exit(0)

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
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Antigravity" / "DevToolsActivePort"
    elif sys.platform == "win32":
        return Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Antigravity" / "DevToolsActivePort"
    return Path.home() / ".config" / "Antigravity" / "DevToolsActivePort"

# Path-agnostic dynamic paths
BRAIN_DIR = Path.home() / ".gemini" / "antigravity" / "brain"
PORT_FILE = find_port_file()

stats_cache = {}

def get_model_limit(model_name):
    m = (model_name or "").lower()
    if "gpt-oss" in m or "oss-120b" in m:
        return 131_072, "128k", "64k", "128k", 80_000
    if "flash-image" in m or "flash image" in m:
        return 65_536, "64k", "32k", "64k", None
    if "claude" in m:
        if any(v in m for v in ["5.5", "5."]):
            return 1_000_000, "1M", "500k", "1,000k (1M)", 256_000
        return 200_000, "200k", "100k", "200k", 160_000
    if any(k in m for k in ["gpt-4", "o1", "o3", "o4"]):
        return 200_000, "200k", "100k", "200k", 160_000
    if "pro" in m and "1.5" in m:
        return 2_097_152, "2M", "1M", "2M", 512_000
    if any(k in m for k in ["gemini 4", "gemini-4", "hydrogen", "argon", "carbon"]):
        return 1_048_576, "1M", "524k", "1,048k", 512_000
    if "3.8" in m:
        return 1_048_576, "1M", "524k", "1,048k", 256_000
    if "gemini" in m:
        return 1_048_576, "1M", "524k", "1,048k", 128_000
    return 1_000_000, "1M", "500k", "1,000k (1M)", 512_000

def compute_conv_stats(conv_id, model_name=None):
    max_tokens, limit_label, tick_mid, tick_max, compact_limit = get_model_limit(model_name)
    analysis = analyze_conversation(conv_id, max_tokens)
    tokens = analysis["tokens"]
    steps = analysis["steps"]
    active_steps = analysis["active_steps"]
    is_compacted = analysis["is_compacted"]
    breakdown = analysis["breakdown"]
    pct = min(100.0, round((tokens / max_tokens) * 100, 2)) if tokens > 0 else 0.0
            
    compact_pct = round((compact_limit / max_tokens) * 100, 2) if compact_limit else None
    compact_label = f"{compact_limit // 1000}k" if compact_limit else None
    compact_rem_k = max(0, (compact_limit - tokens) // 1000) if compact_limit else None
    compact_ratio = (tokens / compact_limit) if compact_limit else (pct / 100.0)

    # Calculate health levels and compact bilingual strings
    if not conv_id or conv_id == "new":
        badge_color = "emerald"
        health_zh = "🟢 新会话"
        health_en = "🟢 New"
        advice_zh = "空白会话，容量 100% 充裕"
        advice_en = "Blank session, 100% free"
    elif compact_ratio < 0.70:
        badge_color = "emerald"
        health_zh = "🟢 充裕"
        health_en = "🟢 Optimal"
        if is_compacted:
            advice_zh = f"已压缩（占用 {pct}%），余量充足"
            advice_en = f"Compacted ({pct}% used), ample room"
        else:
            advice_zh = f"余量充足（占用 {pct}%），无需压缩"
            advice_en = f"Ample room ({pct}% used)"
    elif compact_ratio < 0.92:
        badge_color = "amber"
        health_zh = "🟡 接近压缩"
        health_en = "🟡 Near Limit"
        if compact_label:
            advice_zh = f"距 {compact_label} 压缩线约剩 {compact_rem_k}k，建议总结"
            advice_en = f"~{compact_rem_k}k to {compact_label} compact, summarize soon"
        else:
            advice_zh = f"已用 {pct}%，任务收尾可做总结"
            advice_en = f"{pct}% used, wrap up soon"
    else:
        badge_color = "rose"
        health_zh = "🔴 即将压缩"
        health_en = "🔴 Compact Soon"
        if compact_label:
            advice_zh = f"即将触及 {compact_label} 压缩线，建议 /compact"
            advice_en = f"Near {compact_label} compact, run /compact"
        else:
            advice_zh = f"接近上限（{pct}%），建议 /compact"
            advice_en = f"Near limit ({pct}%), run /compact"
        
    res = {
        "conv_id": conv_id,
        "steps": steps,
        "active_steps": active_steps,
        "is_compacted": is_compacted,
        "tokens": tokens,
        "percentage": pct,
        "max_tokens": max_tokens,
        "compact_limit": compact_limit,
        "compact_pct": compact_pct,
        "compact_label": compact_label,
        "compact_rem_k": compact_rem_k,
        "tick_mid": tick_mid,
        "tick_max": tick_max,
        "badge_color": badge_color,
        "breakdown": breakdown,
        "i18n": {
            "zh": {
                "title": "上下文监控",
                "consumed_label": "已用",
                "steps_label": "交互",
                "footer_title": "💡 建议",
                "steps_unit": "步",
                "health_badge": health_zh,
                "advice": advice_zh,
                "max_suffix": f"{limit_label}",
                "compact_prefix": f"压缩线 {compact_label}" if compact_label else "",
                "compact_rem_text": f"剩 {compact_rem_k}k" if compact_rem_k is not None else "",
                "compact_tooltip": f"自动压缩阈值: {compact_label}" if compact_label else ""
            },
            "en": {
                "title": "Context Monitor",
                "consumed_label": "Used",
                "steps_label": "Steps",
                "footer_title": "💡 Advice",
                "steps_unit": "",
                "health_badge": health_en,
                "advice": advice_en,
                "max_suffix": f"{limit_label}",
                "compact_prefix": f"Compact {compact_label}" if compact_label else "",
                "compact_rem_text": f"{compact_rem_k}k left" if compact_rem_k is not None else "",
                "compact_tooltip": f"Auto-compact limit: {compact_label}" if compact_label else ""
            }
        }
    }
    return res

SETUP_JS = """
(() => {
    window.__mountAntigravityGauge = function() {
        // 1. Strictly purge any root that was erroneously mounted in sidebar
        document.querySelectorAll('#antigravity-context-gauge-root').forEach(el => {
            if (el.closest('nav, aside, [class*="sidebar"]')) el.remove();
        });

        // 2. Locate mic/action button STRICTLY inside the main chat input bar (never in sidebar)
        let micBtn = document.querySelector('button[data-tooltip-id="input-send-button-record-tooltip"]') ||
                     document.querySelector('button[data-tooltip-id="input-send-button-cancel-tooltip"]');
        
        if (!micBtn) {
            let candidates = [...document.querySelectorAll('button')].filter(b => {
                if (b.closest('nav, aside, [class*="sidebar"]')) return false;
                let tip = b.getAttribute('data-tooltip-id') || '';
                let aria = b.getAttribute('aria-label') || '';
                return tip.includes('record') || aria.includes('录音') || aria.includes('Record');
            });
            if (candidates.length > 0) micBtn = candidates[candidates.length - 1];
        }

        if (!micBtn || micBtn.closest('nav, aside, [class*="sidebar"]')) return false;

        let micContainer = micBtn.closest('.flex.items-center');
        if (!micContainer || !micContainer.parentElement || micContainer.closest('nav, aside, [class*="sidebar"]')) return false;

        let root = document.getElementById("antigravity-context-gauge-root");
        if (!root || !document.body.contains(root) || root.parentElement !== micContainer.parentElement || root.dataset.version !== "1.5.2") {
            if (root) root.remove();
            root = document.createElement("div");
            root.id = "antigravity-context-gauge-root";
            root.dataset.version = "1.5.2";
            root.className = "relative flex items-center select-none mr-2";
            root.innerHTML = `
                <button id="ag-ctx-badge-btn" type="button" class="group flex items-center gap-1.5 h-7 px-2.5 rounded-lg text-xs font-medium bg-neutral-100 hover:bg-neutral-200/80 dark:bg-neutral-800 dark:hover:bg-neutral-700 text-neutral-700 dark:text-neutral-200 transition-all duration-150 cursor-pointer outline-none border border-neutral-200 dark:border-neutral-700 shadow-sm">
                    <span id="ag-ctx-dot" class="inline-block w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse"></span>
                    <span class="font-mono text-[11px] font-bold text-neutral-800 dark:text-neutral-100" id="ag-ctx-badge-text">0.0%</span>
                    <svg class="w-3.5 h-3.5 text-neutral-400 group-hover:text-neutral-600 dark:group-hover:text-neutral-200 transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                        <circle cx="12" cy="12" r="10"/>
                        <path d="M12 6v6l4 2"/>
                    </svg>
                </button>
            `;
            micContainer.parentElement.insertBefore(root, micContainer);
        }

        let popup = document.getElementById("ag-ctx-popup");
        if (!popup || !document.body.contains(popup) || popup.dataset.version !== "1.5.2") {
            if (popup) popup.remove();
            
            const isZh = (navigator.language || '').toLowerCase().startsWith('zh');
            const initTitle = isZh ? "上下文监控" : "Context Monitor";
            const initConsumed = isZh ? "已用" : "Used";
            const initSteps = isZh ? "交互" : "Steps";
            const initFooterTitle = isZh ? "💡 建议" : "💡 Advice";
            const initStatus = isZh ? "🟢 充裕" : "🟢 Optimal";
            const initAdvice = isZh ? "空白会话，容量 100% 充裕" : "Blank session, 100% free";
            const initCats = [
                { key: "system", color: "#6366f1", label: isZh ? "系统提示词" : "System Prompt" },
                { key: "tools", color: "#10b981", label: isZh ? "工具及子智能体" : "Tools & Subagents" },
                { key: "messages", color: "#f59e0b", label: isZh ? "对话消息" : "Messages" },
                { key: "mcp", color: "#8b5cf6", label: isZh ? "连接器及MCP" : "Connectors & MCP" },
                { key: "skills", color: "#ec4899", label: isZh ? "技能" : "Skills" }
            ];
            const segsHtml = initCats.map(c => `<div id="ag-seg-${c.key}" style="display:none; height:100%; width:0%; min-width:3px; background:${c.color}; border-radius:2px; transition:width 0.35s ease;"></div>`).join("");
            const rowsHtml = initCats.map(c => `
                <div style="display:flex; justify-content:space-between; align-items:center; font-size:12.5px; line-height:1.4;">
                    <span style="display:flex; align-items:center; gap:8px; min-width:0;">
                        <span style="display:inline-block; width:8px; height:8px; border-radius:999px; background:${c.color}; flex-shrink:0;"></span>
                        <span id="ag-cat-label-${c.key}" style="color:var(--foreground, #222); white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${c.label}</span>
                    </span>
                    <span style="display:flex; align-items:center; gap:10px; font-family:monospace; flex-shrink:0;">
                        <span id="ag-cat-tok-${c.key}" style="font-size:11.5px; color:#888;">0</span>
                        <span id="ag-cat-pct-${c.key}" style="font-size:12.5px; font-weight:700; min-width:42px; text-align:right; color:var(--foreground, #222);">0.0%</span>
                    </span>
                </div>
            `).join("");

            popup = document.createElement("div");
            popup.id = "ag-ctx-popup";
            popup.dataset.version = "1.5.2";
            popup.style.cssText = "position: fixed !important; width: 360px !important; min-width: 360px !important; max-width: 360px !important; box-sizing: border-box !important; z-index: 999999 !important; opacity: 0; pointer-events: none; transform: translateY(8px); transition: opacity 0.18s ease, transform 0.18s ease;";
            popup.className = "p-4 rounded-2xl bg-white dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 shadow-[0_16px_48px_rgba(0,0,0,0.22)] dark:shadow-[0_16px_48px_rgba(0,0,0,0.7)] border border-neutral-200 dark:border-neutral-800 opacity-0 pointer-events-none translate-y-2";
            popup.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; padding-bottom:10px; border-bottom:1px solid rgba(150,150,150,0.15);">
                    <div style="display:flex; align-items:center; gap:9px; min-width:0; flex:1; margin-right:10px;">
                        <span style="font-size:20px; flex-shrink:0;">🧠</span>
                        <div style="min-width:0; flex:1;">
                            <div id="ag-pop-title" style="font-size:14px; font-weight:700; line-height:1.25; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${initTitle}</div>
                            <div id="ag-pop-model" style="font-size:11.5px; color:#888; font-family:monospace; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">Antigravity Model</div>
                        </div>
                    </div>
                    <span id="ag-pop-badge" style="font-size:11.5px; font-weight:600; padding:3px 9px; border-radius:999px; background:rgba(16,185,129,0.12); color:#10b981; border:1px solid rgba(16,185,129,0.25); white-space:nowrap; flex-shrink:0;">
                        ${initStatus}
                    </span>
                </div>

                <div style="margin-top:11px;">
                    <div style="display:flex; justify-content:space-between; align-items:baseline; margin-bottom:7px;">
                        <span style="font-size:13px; color:#777;"><span id="ag-pop-consumed-label">${initConsumed}</span> <strong style="color:var(--foreground, #111); font-family:monospace;" id="ag-pop-tokens">0 / 1M</strong></span>
                        <span style="font-family:monospace; font-size:16px; font-weight:700; color:#10b981;" id="ag-pop-pct">0.0%</span>
                    </div>
                    <div style="position:relative; width:100%;">
                        <div style="display:flex; align-items:center; gap:1.5px; width:100%; height:9px; background:rgba(150,150,150,0.15); border-radius:999px; overflow:hidden; padding:1px; border:1px solid rgba(150,150,150,0.2);">
                            ${segsHtml}
                        </div>
                        <div id="ag-pop-compact-marker" style="display:none; position:absolute; top:-2px; bottom:-2px; left:48.8%; width:2px; background:#f59e0b; border-radius:2px; box-shadow:0 0 6px rgba(245,158,11,0.85); cursor:help; transform:translateX(-50%); z-index:2;" title="">
                            <div style="position:absolute; top:-4px; left:50%; transform:translateX(-50%); width:0; height:0; border-left:3.5px solid transparent; border-right:3.5px solid transparent; border-top:4px solid #f59e0b;"></div>
                        </div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:10.5px; color:#888; font-family:monospace; margin-top:4px;">
                        <span>0k</span>
                        <span id="ag-pop-tick-mid">524k</span>
                        <span id="ag-pop-tick-max">1,048k</span>
                    </div>
                    <div id="ag-pop-compact-row" style="display:none; align-items:center; justify-content:space-between; font-size:11.5px; color:#d97706; margin-top:6px; padding:4px 8px; border-radius:7px; background:rgba(245,158,11,0.1); border:1px solid rgba(245,158,11,0.22);">
                        <span style="display:flex; align-items:center; gap:6px;">
                            <span style="display:inline-block; width:2.5px; height:11px; background:#f59e0b; border-radius:1px;"></span>
                            <span id="ag-pop-compact-label">压缩线 512k</span>
                        </span>
                        <span id="ag-pop-compact-rem" style="font-family:monospace; font-weight:600;"></span>
                    </div>
                </div>

                <div id="ag-pop-breakdown" style="display:flex; flex-direction:column; gap:6px; margin-top:10px; padding-top:9px; border-top:1px solid rgba(150,150,150,0.15);">
                    ${rowsHtml}
                </div>

                <div id="ag-pop-footer" style="margin-top:10px; padding:9px 11px; border-radius:10px; background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.2);">
                    <div style="display:flex; justify-content:space-between; align-items:center; font-size:12px; margin-bottom:5px; padding-bottom:5px; border-bottom:1px solid rgba(150,150,150,0.12);">
                        <span id="ag-pop-footer-title" style="font-weight:700; color:#10b981;">${initFooterTitle}</span>
                        <span style="font-family:monospace; font-size:11.5px; color:#777; white-space:nowrap;">
                            <span id="ag-pop-steps-label">${initSteps}</span> <strong id="ag-pop-steps" style="color:var(--foreground, #111);">0</strong>
                        </span>
                    </div>
                    <div id="ag-pop-advice" style="font-size:12px; line-height:1.45; color:var(--foreground, #111);">${initAdvice}</div>
                </div>
            `;
            document.body.appendChild(popup);
        }

        let badgeBtn = document.getElementById("ag-ctx-badge-btn");
        if (badgeBtn && !badgeBtn.dataset.bound) {
            badgeBtn.dataset.bound = "true";
            let timer;
            const getPop = () => document.getElementById("ag-ctx-popup");
            const hideHandler = () => {
                timer = setTimeout(() => {
                    const p = getPop();
                    if (!p) return;
                    p.classList.add("opacity-0", "pointer-events-none", "translate-y-2");
                    p.classList.remove("opacity-100", "pointer-events-auto", "translate-y-0");
                    p.style.opacity = "0";
                    p.style.pointerEvents = "none";
                    p.style.transform = "translateY(8px)";
                }, 120);
            };
            badgeBtn.addEventListener("mouseenter", () => {
                clearTimeout(timer);
                const p = getPop();
                if (!p) return;
                const rect = badgeBtn.getBoundingClientRect();
                p.style.bottom = (window.innerHeight - rect.top + 8) + "px";
                p.style.right = (window.innerWidth - rect.right) + "px";
                p.classList.remove("opacity-0", "pointer-events-none", "translate-y-2");
                p.classList.add("opacity-100", "pointer-events-auto", "translate-y-0");
                p.style.opacity = "1";
                p.style.pointerEvents = "auto";
                p.style.transform = "translateY(0px)";
                if (!p.dataset.bound) {
                    p.dataset.bound = "true";
                    p.addEventListener("mouseenter", () => clearTimeout(timer));
                    p.addEventListener("mouseleave", hideHandler);
                }
            });
            badgeBtn.addEventListener("mouseleave", hideHandler);
        }
        return true;
    };

    window.__updateAntigravityGauge = function(stats) {
        window.__mountAntigravityGauge();
        
        // Auto-detect language: non-Chinese -> English
        const isZh = (navigator.language || '').toLowerCase().startsWith('zh');
        const t = (stats.i18n && (isZh ? stats.i18n.zh : stats.i18n.en)) || {};
        
        let badgeText = document.getElementById("ag-ctx-badge-text");
        if (badgeText) badgeText.innerText = stats.percentage + "%";
        
        let dot = document.getElementById("ag-ctx-dot");
        if (dot) {
            dot.className = "inline-block w-2 h-2 rounded-full animate-pulse " + 
                (stats.badge_color === "rose" ? "bg-rose-500 shadow-[0_0_8px_rgba(244,63,94,0.6)]" :
                 stats.badge_color === "amber" ? "bg-amber-500 shadow-[0_0_8px_rgba(245,158,11,0.6)]" :
                 "bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]");
        }

        let popTitle = document.getElementById("ag-pop-title");
        if (popTitle && t.title) popTitle.innerText = t.title;

        let popConsumed = document.getElementById("ag-pop-consumed-label");
        if (popConsumed && t.consumed_label) popConsumed.innerText = t.consumed_label;

        let popTokens = document.getElementById("ag-pop-tokens");
        if (popTokens) {
            const usedStr = stats.tokens >= 1000 ? (stats.tokens / 1000).toFixed(1) + "k" : String(stats.tokens);
            const maxStr = stats.tick_max || "1M";
            popTokens.innerText = `${usedStr} / ${maxStr}`;
        }

        let popPct = document.getElementById("ag-pop-pct");
        if (popPct) {
            popPct.innerText = stats.percentage + "%";
            popPct.style.color = stats.badge_color === "rose" ? "#f43f5e" :
                                 stats.badge_color === "amber" ? "#f59e0b" : "#10b981";
        }

        if (Array.isArray(stats.breakdown)) {
            for (const b of stats.breakdown) {
                const seg = document.getElementById("ag-seg-" + b.key);
                if (seg) {
                    if (b.tokens > 0) {
                        seg.style.display = "block";
                        seg.style.width = b.bar_pct + "%";
                        seg.title = (isZh ? b.label_zh : b.label_en) + ": ~" + b.tokens_k + " (" + b.pct.toFixed(1) + "%)";
                    } else {
                        seg.style.display = "none";
                        seg.style.width = "0%";
                    }
                }
                const lbl = document.getElementById("ag-cat-label-" + b.key);
                if (lbl) lbl.innerText = isZh ? b.label_zh : b.label_en;
                const tok = document.getElementById("ag-cat-tok-" + b.key);
                if (tok) tok.innerText = b.tokens_k;
                const pctEl = document.getElementById("ag-cat-pct-" + b.key);
                if (pctEl) pctEl.innerText = Number(b.pct).toFixed(1) + "%";
            }
        }

        let marker = document.getElementById("ag-pop-compact-marker");
        let compactRow = document.getElementById("ag-pop-compact-row");
        let compactLabel = document.getElementById("ag-pop-compact-label");
        let compactRem = document.getElementById("ag-pop-compact-rem");
        if (stats.compact_pct && stats.compact_pct > 0 && stats.compact_pct < 100) {
            if (marker) {
                marker.style.display = "block";
                marker.style.left = stats.compact_pct + "%";
                if (t.compact_tooltip) marker.title = t.compact_tooltip;
            }
            if (compactRow) compactRow.style.display = "flex";
            if (compactLabel && t.compact_prefix) compactLabel.innerText = t.compact_prefix;
            if (compactRem && t.compact_rem_text) compactRem.innerText = t.compact_rem_text;
        } else {
            if (marker) marker.style.display = "none";
            if (compactRow) compactRow.style.display = "none";
        }

        let tickMid = document.getElementById("ag-pop-tick-mid");
        let tickMax = document.getElementById("ag-pop-tick-max");
        if (tickMid && stats.tick_mid) tickMid.innerText = stats.tick_mid;
        if (tickMax && stats.tick_max) tickMax.innerText = stats.tick_max;

        let popStepsLabel = document.getElementById("ag-pop-steps-label");
        if (popStepsLabel && t.steps_label) popStepsLabel.innerText = t.steps_label;

        let popSteps = document.getElementById("ag-pop-steps");
        if (popSteps) {
            let unit = t.steps_unit ? " " + t.steps_unit : "";
            popSteps.innerText = Number(stats.steps).toLocaleString() + unit;
            if (stats.is_compacted) {
                popSteps.title = isZh ? 
                    `累计 ${stats.steps} 步（压缩后活跃: ${stats.active_steps} 步）` : 
                    `Total ${stats.steps} steps (Active: ${stats.active_steps})`;
            } else {
                popSteps.title = "";
            }
        }

        const toneMap = {
            rose: { color: "#f43f5e", bg: "rgba(244,63,94,0.10)", border: "rgba(244,63,94,0.26)" },
            amber: { color: "#f59e0b", bg: "rgba(245,158,11,0.10)", border: "rgba(245,158,11,0.26)" },
            emerald: { color: "#10b981", bg: "rgba(16,185,129,0.08)", border: "rgba(16,185,129,0.22)" }
        };
        const tone = toneMap[stats.badge_color] || toneMap.emerald;

        let popBadge = document.getElementById("ag-pop-badge");
        if (popBadge && t.health_badge) {
            popBadge.innerText = t.health_badge;
            popBadge.style.color = tone.color;
            popBadge.style.background = tone.bg;
            popBadge.style.borderColor = tone.border;
        }

        let popFooter = document.getElementById("ag-pop-footer");
        if (popFooter) {
            popFooter.style.background = tone.bg;
            popFooter.style.borderColor = tone.border;
        }

        let popFooterTitle = document.getElementById("ag-pop-footer-title");
        if (popFooterTitle) {
            if (t.footer_title) popFooterTitle.innerText = t.footer_title;
            popFooterTitle.style.color = tone.color;
        }

        let popAdvice = document.getElementById("ag-pop-advice");
        if (popAdvice && t.advice) popAdvice.innerText = t.advice;

        let popModel = document.getElementById("ag-pop-model");
        if (popModel) {
            let mName = stats.model_name || "Antigravity Model";
            let suffix = t.max_suffix || "1M Max";
            popModel.innerText = `${mName} · ${suffix}`;
            popModel.title = `${mName} · ${suffix}`;
        }
    };

    if (!window.__agGaugeObserver) {
        window.__agGaugeObserver = new MutationObserver(() => {
            let root = document.getElementById("antigravity-context-gauge-root");
            if (root && root.closest('nav, aside, [class*="sidebar"]')) {
                root.remove();
                root = null;
            }
            let micBtn = document.querySelector('button[data-tooltip-id="input-send-button-record-tooltip"]') ||
                         document.querySelector('button[data-tooltip-id="input-send-button-cancel-tooltip"]');
            if (micBtn && !micBtn.closest('nav, aside, [class*="sidebar"]') && (!root || !document.body.contains(root))) {
                window.__mountAntigravityGauge();
            }
        });
        window.__agGaugeObserver.observe(document.body, { childList: true, subtree: true });
    }

    return window.__mountAntigravityGauge();
})()
"""

def get_active_target():
    global PORT_FILE
    if not PORT_FILE or not PORT_FILE.exists():
        PORT_FILE = find_port_file()
    if not PORT_FILE.exists():
        return None
    try:
        with open(PORT_FILE, "r", encoding="utf-8") as f:
            lines = [l.strip() for l in f.readlines() if l.strip()]
        if not lines or not lines[0].isdigit():
            return None
        port = int(lines[0])
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=2)
        targets = json.loads(req.read().decode("utf-8"))
        valid_pages = []
        for t in targets:
            if t.get("type") != "page":
                continue
            url = t.get("url", "")
            if not url or url.startswith("devtools://") or url.startswith("data:") or url.startswith("chrome-extension://"):
                continue
            valid_pages.append(t)
        
        if not valid_pages:
            return None

        # Prioritize true Antigravity chat window
        for p in valid_pages:
            url = p.get("url", "")
            title = p.get("title", "")
            if "/c/" in url or "project=" in url or "Antigravity" in title:
                return p["webSocketDebuggerUrl"]

        return valid_pages[0]["webSocketDebuggerUrl"]
    except Exception as e:
        log(f"get_active_target error: {e}")
    return None

async def cdp_eval(ws, expr, req_id):
    try:
        await ws.send(json.dumps({
            "id": req_id,
            "method": "Runtime.evaluate",
            "params": {"expression": expr, "returnByValue": True}
        }))
        start_t = time.time()
        while time.time() - start_t < 4.0:
            msg = await asyncio.wait_for(ws.recv(), timeout=4.0)
            data = json.loads(msg)
            if data.get("id") == req_id:
                res = data.get("result", {})
                if "exceptionDetails" in res:
                    log(f"CDP JS Exception: {res['exceptionDetails']}")
                return res.get("result", {}).get("value")
    except Exception:
        pass
    return None

async def run_sync_loop(iterations=None):
    log("Antigravity Context Daemon sync loop started.")
    req_counter = 100
    iter_count = 0
    
    while True:
        try:
            ws_url = get_active_target()
            if not ws_url:
                await asyncio.sleep(2)
                continue
                
            log(f"Connecting to CDP target: {ws_url}")
            async with websockets.connect(ws_url, ping_interval=5, ping_timeout=5) as ws:
                log("CDP WebSocket connection established.")
                # 1. Initialize gauge DOM and scripts
                req_counter += 1
                await cdp_eval(ws, SETUP_JS, req_counter)
                
                while True:
                    # Periodically check if target has shifted to a better window
                    if iter_count % 3 == 0:
                        current_best = get_active_target()
                        if current_best and current_best != ws_url:
                            log(f"Active target shifted to {current_best}. Reconnecting...")
                            break

                    # 2. Check if setup function still exists (detects full page navigation/refresh)
                    req_counter += 1
                    fn_exists = await cdp_eval(ws, "typeof window.__updateAntigravityGauge === 'function'", req_counter)
                    if not fn_exists:
                        req_counter += 1
                        await cdp_eval(ws, SETUP_JS, req_counter)
                    
                    # 3. Get current conversation path
                    req_counter += 1
                    pathname = await cdp_eval(ws, "window.location.pathname", req_counter)
                    if pathname is None:
                        pathname = ""
                        
                    m = re.search(r'/c/([^/?]+)', pathname)
                    conv_id = m.group(1) if m else "new"
                    
                    # 4. Read current model name from DOM
                    req_counter += 1
                    model_js = """
                    (() => {
                        let btn = document.querySelector('button[aria-label*="Select model"], button[aria-label*="选择模型"]');
                        if (btn) return btn.innerText.trim();
                        let candidates = Array.from(document.querySelectorAll('button[aria-label*="model" i], button[data-testid*="model" i]'));
                        for (let c of candidates) {
                            let aria = (c.getAttribute("aria-label") || "").toLowerCase();
                            if (aria.includes("select") || aria.includes("current")) return c.innerText.trim();
                        }
                        return "";
                    })()
                    """
                    model_name = await cdp_eval(ws, model_js, req_counter)
                    
                    # 5. Compute and push stats
                    stats = compute_conv_stats(conv_id, model_name)
                    if model_name and str(model_name).strip():
                        stats["model_name"] = str(model_name).strip()
                    update_expr = f"window.__updateAntigravityGauge({json.dumps(stats, ensure_ascii=False)});"
                    req_counter += 1
                    await cdp_eval(ws, update_expr, req_counter)
                    
                    iter_count += 1
                    if iterations and iter_count >= iterations:
                        log("Reached iteration limit, exiting.")
                        return
                    await asyncio.sleep(1.2)
        except Exception as e:
            log(f"CDP loop exception: {e}. Retrying in 2s...")
            await asyncio.sleep(2)

if __name__ == "__main__":
    try:
        max_iter = int(sys.argv[1]) if len(sys.argv) > 1 else None
        asyncio.run(run_sync_loop(max_iter))
    except BaseException as e:
        log(f"Fatal exception: {e}\n{traceback.format_exc()}")
