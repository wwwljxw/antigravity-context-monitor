import os, urllib.request, json, asyncio, websockets
from pathlib import Path

async def inject():
    try:
        port_file = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming"))) / "Antigravity" / "DevToolsActivePort"
        if not port_file.exists():
            print("DevToolsActivePort not found. Is Antigravity running?")
            return False
            
        with open(port_file, "r") as f:
            port = f.readline().strip()
            
        req = urllib.request.urlopen(f"http://127.0.0.1:{port}/json/list", timeout=3)
        targets = json.loads(req.read().decode("utf-8"))
        pages = [t for t in targets if t.get("type") == "page" and not t.get("url", "").startswith("devtools://")]
        if not pages:
            print("No page target found.")
            return False
        ws_url = pages[0]["webSocketDebuggerUrl"]
        
        async with websockets.connect(ws_url) as ws:
            injection_js = """
            (() => {
                const old = document.getElementById("antigravity-context-gauge-root");
                if (old) old.remove();

                function mountGauge() {
                    if (document.getElementById("antigravity-context-gauge-root")) return;

                    const micBtn = document.querySelector('[aria-label="Record voice memo"]');
                    if (!micBtn) return;
                    const micContainer = micBtn.closest('.flex.items-center');
                    if (!micContainer || !micContainer.parentElement) return;

                    const root = document.createElement("div");
                    root.id = "antigravity-context-gauge-root";
                    root.className = "relative flex items-center select-none mr-2";

                    const badge = document.createElement("button");
                    badge.id = "ag-ctx-badge-btn";
                    badge.type = "button";
                    badge.className = "group flex items-center gap-1.5 h-7 px-2.5 rounded-lg text-xs font-medium bg-neutral-100 hover:bg-neutral-200/80 dark:bg-neutral-800 dark:hover:bg-neutral-700 text-neutral-700 dark:text-neutral-200 transition-all duration-150 cursor-pointer outline-none border border-neutral-200 dark:border-neutral-700 shadow-sm";
                    badge.innerHTML = `
                        <span id="ag-ctx-dot" class="inline-block w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)] animate-pulse"></span>
                        <span class="font-mono text-[11px] font-bold text-neutral-800 dark:text-neutral-100" id="ag-ctx-badge-text">0.0%</span>
                        <svg class="w-3.5 h-3.5 text-neutral-400 group-hover:text-neutral-600 dark:group-hover:text-neutral-200 transition-colors" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
                            <circle cx="12" cy="12" r="10"/>
                            <path d="M12 6v6l4 2"/>
                        </svg>
                    `;

                    micContainer.parentElement.insertBefore(root, micContainer);
                }

                mountGauge();
                return true;
            })()
            """
            await ws.send(json.dumps({"id": 100, "method": "Runtime.evaluate", "params": {"expression": injection_js, "returnByValue": True}}))
            await ws.recv()
            print("Successfully injected gauge.")
            return True
    except Exception as e:
        print("Error:", e)
        return False

if __name__ == "__main__":
    asyncio.run(inject())
