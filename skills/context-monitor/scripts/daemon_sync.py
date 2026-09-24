import sys, os, time, json, re, urllib.request, asyncio, socket, traceback
from pathlib import Path

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

PLUGIN_DIR = Path(__file__).resolve().parent.parent.parent
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
    _lock_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    _lock_socket.bind(('127.0.0.1', LOCK_PORT))
    _lock_socket.listen(1)
    log("Acquired single-instance lock on port 38291")
except socket.error as e:
    log(f"Another instance is running (port {LOCK_PORT} busy): {e}. Exiting.")
    sys.exit(0)

# Path-agnostic dynamic paths
BRAIN_DIR = Path.home() / ".gemini" / "antigravity" / "brain"
PORT_FILE = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Antigravity" / "DevToolsActivePort"

stats_cache = {}

def estimate_tokens(text):
    if not text:
        return 0
    cn = len(re.findall(r'[\u4e00-\u9fff]', text))
    return int(cn / 1.5 + (len(text) - cn) / 3.8)

def compute_conv_stats(conv_id):
    if not conv_id or conv_id == "new":
        pct = 0.0
        steps = 0
        tokens = 0
    else:
        p = BRAIN_DIR / conv_id / ".system_generated" / "logs" / "transcript.jsonl"
        if not p.exists():
            pct = 0.0
            steps = 0
            tokens = 0
        else:
            mtime = p.stat().st_mtime
            cached = stats_cache.get(conv_id)
            if cached and cached.get("mtime") == mtime:
                return cached["stats"]
                
            steps = 0
            tokens = 5000
            try:
                with open(p, "r", encoding="utf-8", errors="ignore") as f:
                    for line in f:
                        steps += 1
                        try:
                            data = json.loads(line)
                            tokens += estimate_tokens(str(data.get("content",""))) + estimate_tokens(str(data.get("thinking",""))) + estimate_tokens(str(data.get("tool_calls","")))
                        except:
                            pass
            except Exception:
                pass
            pct = round((tokens / 1_000_000) * 100, 2)
            
    # Calculate health levels and compact bilingual strings
    if not conv_id or conv_id == "new":
        badge_color = "emerald"
        health_zh = "🟢 全新会话"
        health_en = "🟢 New Session"
        model_health_zh = "极佳"
        model_health_en = "Optimal"
        advice_zh = "全新空白会话，上下文容量 100% 充裕。"
        advice_en = "Brand new session. 100% context capacity available."
    elif pct < 60:
        badge_color = "emerald"
        health_zh = "🟢 极度充裕"
        health_en = "🟢 Optimal"
        model_health_zh = "极佳"
        model_health_en = "Optimal"
        advice_zh = f"当前仅占用 {pct}%，余量充足，无需压缩。"
        advice_en = f"Only {pct}% used. Ample headroom, no compression needed."
    elif pct < 85:
        badge_color = "amber"
        health_zh = "🟡 容量适中"
        health_en = "🟡 Moderate"
        model_health_zh = "良好"
        model_health_en = "Normal"
        advice_zh = f"已占用 {pct}%，在完成当前任务后可做阶段性总结。"
        advice_en = f"{pct}% consumed. Consider summarizing once current task finishes."
    else:
        badge_color = "rose"
        health_zh = "🔴 容量偏高"
        health_en = "🔴 High Load"
        model_health_zh = "需关注"
        model_health_en = "High"
        advice_zh = f"已占用 {pct}%，接近上限，建议开启新会话或输入 /compact。"
        advice_en = f"{pct}% consumed (near limit). Recommended to start a new chat or run /compact."
        
    res = {
        "conv_id": conv_id,
        "steps": steps,
        "tokens": tokens,
        "percentage": pct,
        "badge_color": badge_color,
        "i18n": {
            "zh": {
                "title": "会话上下文容量",
                "consumed_label": "已消耗:",
                "remaining_label": "剩余空间",
                "steps_label": "累计交互",
                "health_label": "模型状态",
                "steps_unit": "步",
                "model_health": model_health_zh,
                "health_badge": health_zh,
                "advice": advice_zh,
                "max_suffix": "1M 上限"
            },
            "en": {
                "title": "Context Capacity",
                "consumed_label": "Used:",
                "remaining_label": "Remaining",
                "steps_label": "Steps",
                "health_label": "Status",
                "steps_unit": "",
                "model_health": model_health_en,
                "health_badge": health_en,
                "advice": advice_en,
                "max_suffix": "1M Max"
            }
        }
    }
    if conv_id and conv_id != "new":
        stats_cache[conv_id] = {"mtime": mtime, "stats": res}
    return res

SETUP_JS = """
(() => {
    window.__mountAntigravityGauge = function() {
        let micBtn = document.querySelector('[aria-label="Record voice memo"]');
        if (!micBtn) return false;
        let micContainer = micBtn.closest('.flex.items-center');
        if (!micContainer || !micContainer.parentElement) return false;

        let root = document.getElementById("antigravity-context-gauge-root");
        if (!root || !document.body.contains(root)) {
            if (root) root.remove();
            root = document.createElement("div");
            root.id = "antigravity-context-gauge-root";
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
        if (!popup || !document.body.contains(popup)) {
            if (popup) popup.remove();
            
            const isZh = (navigator.language || '').toLowerCase().startsWith('zh');
            const initTitle = isZh ? "会话上下文容量" : "Context Capacity";
            const initConsumed = isZh ? "已消耗:" : "Used:";
            const initRemaining = isZh ? "剩余空间" : "Remaining";
            const initSteps = isZh ? "累计交互" : "Steps";
            const initHealth = isZh ? "模型状态" : "Status";
            const initStatus = isZh ? "🟢 极度充裕" : "🟢 Optimal";
            const initAdvice = isZh ? "全新空白会话，上下文容量 100% 充裕。" : "Brand new session. 100% context capacity available.";

            popup = document.createElement("div");
            popup.id = "ag-ctx-popup";
            popup.style.cssText = "position: fixed !important; width: 350px !important; min-width: 350px !important; max-width: 350px !important; box-sizing: border-box !important; z-index: 999999 !important; transition: opacity 0.18s ease, transform 0.18s ease;";
            popup.className = "p-4 rounded-2xl bg-white dark:bg-neutral-900 text-neutral-900 dark:text-neutral-100 shadow-[0_16px_48px_rgba(0,0,0,0.22)] dark:shadow-[0_16px_48px_rgba(0,0,0,0.7)] border border-neutral-200 dark:border-neutral-800 opacity-0 pointer-events-none translate-y-2";
            popup.innerHTML = `
                <div style="display:flex; justify-content:space-between; align-items:center; padding-bottom:10px; border-bottom:1px solid rgba(150,150,150,0.15);">
                    <div style="display:flex; align-items:center; gap:8px; min-width:0; flex:1; margin-right:10px;">
                        <span style="font-size:18px; flex-shrink:0;">🧠</span>
                        <div style="min-width:0; flex:1;">
                            <div id="ag-pop-title" style="font-size:12px; font-weight:700; line-height:1.2; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">${initTitle}</div>
                            <div id="ag-pop-model" style="font-size:10px; color:#888; font-family:monospace; margin-top:2px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;">Antigravity Model</div>
                        </div>
                    </div>
                    <span id="ag-pop-badge" style="font-size:10px; font-weight:600; padding:2px 8px; border-radius:999px; background:rgba(16,185,129,0.12); color:#10b981; border:1px solid rgba(16,185,129,0.25); white-space:nowrap; flex-shrink:0;">
                        ${initStatus}
                    </span>
                </div>

                <div style="margin-top:12px;">
                    <div style="display:flex; justify-content:space-between; align-items:center; font-size:11px; margin-bottom:6px;">
                        <span style="color:#777;"><span id="ag-pop-consumed-label">${initConsumed}</span> <strong style="color:var(--foreground, #111); font-family:monospace;" id="ag-pop-tokens">~0 Tokens</strong></span>
                        <span style="font-family:monospace; font-weight:700; color:#10b981;" id="ag-pop-pct">0.0%</span>
                    </div>
                    <div style="width:100%; height:8px; background:rgba(150,150,150,0.15); border-radius:999px; overflow:hidden; padding:1px; border:1px solid rgba(150,150,150,0.2);">
                        <div id="ag-pop-bar" style="height:100%; width:0%; background:linear-gradient(90deg, #10b981, #14b8a6); border-radius:999px; transition:width 0.4s ease;"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:9px; color:#888; font-family:monospace; margin-top:4px;">
                        <span>0k</span>
                        <span>500k</span>
                        <span>1,000k (1M)</span>
                    </div>
                </div>

                <div style="display:grid; grid-template-columns:1fr 1fr 1fr; gap:6px; margin-top:12px; padding-top:10px; border-top:1px solid rgba(150,150,150,0.15); text-align:center;">
                    <div style="padding:6px 4px; border-radius:8px; background:rgba(150,150,150,0.06); border:1px solid rgba(150,150,150,0.12); overflow:hidden;">
                        <div id="ag-pop-rem-label" style="font-size:9px; color:#888; white-space:nowrap;">${initRemaining}</div>
                        <div id="ag-pop-rem" style="font-size:12px; font-weight:700; font-family:monospace; color:#10b981; margin-top:2px;">> 1000k</div>
                    </div>
                    <div style="padding:6px 4px; border-radius:8px; background:rgba(150,150,150,0.06); border:1px solid rgba(150,150,150,0.12); overflow:hidden;">
                        <div id="ag-pop-steps-label" style="font-size:9px; color:#888; white-space:nowrap;">${initSteps}</div>
                        <div id="ag-pop-steps" style="font-size:12px; font-weight:700; font-family:monospace; color:var(--foreground, #222); margin-top:2px;">0</div>
                    </div>
                    <div style="padding:6px 4px; border-radius:8px; background:rgba(150,150,150,0.06); border:1px solid rgba(150,150,150,0.12); overflow:hidden;">
                        <div id="ag-pop-health-label" style="font-size:9px; color:#888; white-space:nowrap;">${initHealth}</div>
                        <div id="ag-pop-health-val" style="font-size:12px; font-weight:700; font-family:monospace; color:#6366f1; margin-top:2px;">Optimal</div>
                    </div>
                </div>

                <div style="margin-top:10px; padding:8px 10px; border-radius:8px; background:rgba(16,185,129,0.08); border:1px solid rgba(16,185,129,0.2); font-size:10px; line-height:1.45; display:flex; gap:6px; align-items:flex-start;">
                    <span style="font-size:12px; flex-shrink:0;">💡</span>
                    <span id="ag-pop-advice" style="color:var(--foreground, #111);">${initAdvice}</span>
                </div>
            `;
            document.body.appendChild(popup);
        }

        let badgeBtn = document.getElementById("ag-ctx-badge-btn");
        if (badgeBtn && !badgeBtn.dataset.bound) {
            badgeBtn.dataset.bound = "true";
            let timer;
            badgeBtn.addEventListener("mouseenter", () => {
                clearTimeout(timer);
                const rect = badgeBtn.getBoundingClientRect();
                popup.style.bottom = (window.innerHeight - rect.top + 8) + "px";
                popup.style.right = (window.innerWidth - rect.right) + "px";
                popup.classList.remove("opacity-0", "pointer-events-none", "translate-y-2");
                popup.classList.add("opacity-100", "pointer-events-auto", "translate-y-0");
            });

            const hideHandler = () => {
                timer = setTimeout(() => {
                    popup.classList.add("opacity-0", "pointer-events-none", "translate-y-2");
                    popup.classList.remove("opacity-100", "pointer-events-auto", "translate-y-0");
                }, 120);
            };

            badgeBtn.addEventListener("mouseleave", hideHandler);
            popup.addEventListener("mouseenter", () => clearTimeout(timer));
            popup.addEventListener("mouseleave", hideHandler);
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
        if (popTokens) popTokens.innerText = "~" + Number(stats.tokens).toLocaleString() + " Tokens";

        let popPct = document.getElementById("ag-pop-pct");
        if (popPct) popPct.innerText = stats.percentage + "%";

        let popBar = document.getElementById("ag-pop-bar");
        if (popBar) popBar.style.width = Math.max(1.5, stats.percentage) + "%";

        let popRemLabel = document.getElementById("ag-pop-rem-label");
        if (popRemLabel && t.remaining_label) popRemLabel.innerText = t.remaining_label;

        let popRem = document.getElementById("ag-pop-rem");
        if (popRem) popRem.innerText = "> " + Math.max(0, Math.floor((1000000 - stats.tokens)/1000)) + "k";

        let popStepsLabel = document.getElementById("ag-pop-steps-label");
        if (popStepsLabel && t.steps_label) popStepsLabel.innerText = t.steps_label;

        let popSteps = document.getElementById("ag-pop-steps");
        if (popSteps) {
            let unit = t.steps_unit ? " " + t.steps_unit : "";
            popSteps.innerText = Number(stats.steps).toLocaleString() + unit;
        }

        let popHealthLabel = document.getElementById("ag-pop-health-label");
        if (popHealthLabel && t.health_label) popHealthLabel.innerText = t.health_label;

        let popHealthVal = document.getElementById("ag-pop-health-val");
        if (popHealthVal && t.model_health) popHealthVal.innerText = t.model_health;

        let popBadge = document.getElementById("ag-pop-badge");
        if (popBadge && t.health_badge) popBadge.innerText = t.health_badge;

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
            let micBtn = document.querySelector('[aria-label="Record voice memo"]');
            if (micBtn && (!root || !document.body.contains(root))) {
                window.__mountAntigravityGauge();
            }
        });
        window.__agGaugeObserver.observe(document.body, { childList: true, subtree: true });
    }

    return window.__mountAntigravityGauge();
})()
"""

def get_active_target():
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
        pages = [t for t in targets if t.get("type") == "page" and not t.get("url", "").startswith("devtools://")]
        if pages:
            return pages[0]["webSocketDebuggerUrl"]
    except Exception as e:
        log(f"get_active_target error: {e}")
    return None

async def cdp_eval(ws, expr, req_id):
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
            return data.get("result", {}).get("result", {}).get("value")
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
                    model_name = await cdp_eval(ws, "document.querySelector('[data-testid*=\"model\"]')?.innerText || document.querySelector('[aria-label*=\"model\"]')?.innerText || ''", req_counter)
                    
                    # 5. Compute and push stats
                    stats = compute_conv_stats(conv_id)
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
