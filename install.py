import sys
import os
import shutil
import subprocess
import json
from pathlib import Path

# Safe console reconfigure - never crash on encoding
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(errors='replace')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(errors='replace')
    except Exception:
        pass

def is_chinese():
    if sys.platform == "darwin":
        try:
            out = subprocess.check_output(["defaults", "read", "-g", "AppleLanguages"], text=True)
            if "zh" in out:
                return True
        except Exception:
            pass
    elif sys.platform == "win32":
        try:
            import ctypes
            lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            if (lang_id & 0xFF) == 0x04:
                return True
        except Exception:
            pass
    lang = (os.environ.get("LANG") or os.environ.get("LC_ALL") or "").lower()
    return lang.startswith("zh")

def kill_existing_daemon():
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-NetTCPConnection -LocalPort 38291 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                capture_output=True
            )
        else:
            subprocess.run("lsof -ti :38291 | xargs kill -9 2>/dev/null || true", shell=True, capture_output=True)
    except Exception:
        pass

def main():
    zh = is_chinese()

    print("=" * 65)
    if zh:
        print("  [+] Antigravity 上下文监控插件 (Context Monitor) - 一键安装程序")
    else:
        print("  [+] Antigravity Context Monitor - One-Click Installer")
    print("=" * 65)
    print()

    # 1. Check Python
    python_exe = sys.executable
    if sys.platform == "win32":
        python_dir = Path(python_exe).parent
        python_runner = python_dir / "pythonw.exe"
        if not python_runner.exists():
            python_runner = Path(shutil.which("pythonw") or python_exe)
    else:
        python_runner = Path(python_exe)

    if zh:
        print(f"[*] 检测到系统: {sys.platform}")
        print(f"[*] 检测到 Python 环境: {python_exe}")
        print(f"[*] 后台执行器: {python_runner}")
        print("[*] 正在检查依赖库 websockets...")
    else:
        print(f"[*] Detected OS: {sys.platform}")
        print(f"[*] Python environment: {python_exe}")
        print(f"[*] Background runner: {python_runner}")
        print("[*] Checking dependency: websockets...")

    # 2. Check websockets
    try:
        import websockets
        print("[+] websockets is already installed." if not zh else "[+] websockets 已安装。")
    except ImportError:
        print("[*] Installing websockets via pip..." if not zh else "[*] 正在自动安装 websockets...")
        try:
            subprocess.check_call([python_exe, "-m", "pip", "install", "websockets", "-q"])
            print("[+] websockets installed successfully!" if not zh else "[+] websockets 安装成功！")
        except Exception as e:
            if zh:
                print(f"[-] 安装 websockets 失败: {e}，请手动执行 pip install websockets")
            else:
                print(f"[-] Failed to install websockets: {e}. Please run: pip install websockets")

    # 3. Directories
    src_dir = Path(__file__).resolve().parent
    user_home = Path.home()
    plugin_target = user_home / ".gemini" / "config" / "plugins" / "context-monitor"
    skills_plugin_target = plugin_target / "skills" / "context-monitor"
    skills_global_target = user_home / ".gemini" / "config" / "skills" / "context-monitor"
    skills_agents_target = user_home / ".agents" / "skills" / "context-monitor"
    sidecar_target = user_home / ".gemini" / "config" / "sidecars" / "context-monitor"

    if zh:
        print(f"[*] 目标安装路径: {plugin_target}")
        print("[*] 正在复制插件核心文件...")
    else:
        print(f"[*] Installation directory: {plugin_target}")
        print("[*] Copying core plugin files...")

    # 4. Copy files
    os.makedirs(skills_plugin_target / "scripts", exist_ok=True)
    os.makedirs(skills_global_target / "scripts", exist_ok=True)
    os.makedirs(skills_agents_target / "scripts", exist_ok=True)
    os.makedirs(sidecar_target, exist_ok=True)

    shutil.copy2(src_dir / "plugin.json", plugin_target / "plugin.json")

    src_skills = src_dir / "skills" / "context-monitor"
    shutil.copy2(src_skills / "SKILL.md", skills_plugin_target / "SKILL.md")
    shutil.copy2(src_skills / "SKILL.md", skills_global_target / "SKILL.md")
    shutil.copy2(src_skills / "SKILL.md", skills_agents_target / "SKILL.md")

    for script_name in ["daemon_sync.py", "generate_monitor.py", "inject_gauge.py", "context_breakdown.py"]:
        src_script = src_skills / "scripts" / script_name
        if src_script.exists():
            shutil.copy2(src_script, skills_plugin_target / "scripts" / script_name)
            shutil.copy2(src_script, skills_global_target / "scripts" / script_name)
            shutil.copy2(src_script, skills_agents_target / "scripts" / script_name)

    print("[+] Core files copied successfully." if not zh else "[+] 插件核心文件复制完毕！")

    # 5. Configure Antigravity Sidecar
    print("[*] Configuring Antigravity Sidecar..." if not zh else "[*] 正在配置 Antigravity Sidecar 服务...")
    daemon_script_path = skills_plugin_target / "scripts" / "daemon_sync.py"
    sidecar_config = {
        "name": "context-monitor",
        "description": "Antigravity Context Gauge & Token Live Monitor",
        "command": str(python_runner),
        "args": [str(daemon_script_path)],
        "restart_policy": "always"
    }
    with open(sidecar_target / "sidecar.json", "w", encoding="utf-8") as f:
        json.dump(sidecar_config, f, indent=2, ensure_ascii=False)
    print(f"[+] Sidecar ready: {sidecar_target / 'sidecar.json'}" if not zh else f"[+] Sidecar 配置文件已就绪: {sidecar_target / 'sidecar.json'}")

    # 6. Configure Autostart (OS Specific)
    kill_existing_daemon()

    if sys.platform == "darwin":
        print("[*] Configuring macOS LaunchAgent..." if not zh else "[*] 正在配置 macOS LaunchAgent 开机常驻服务...")
        launch_agents_dir = user_home / "Library" / "LaunchAgents"
        launch_agents_dir.mkdir(parents=True, exist_ok=True)
        plist_path = launch_agents_dir / "com.antigravity.context-monitor.plist"
        log_file = plugin_target / "daemon.log"
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.antigravity.context-monitor</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_runner}</string>
        <string>{daemon_script_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_file}</string>
    <key>StandardErrorPath</key>
    <string>{log_file}</string>
</dict>
</plist>
"""
        try:
            if plist_path.exists():
                subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
            with open(plist_path, "w", encoding="utf-8") as f:
                f.write(plist_content)
            subprocess.run(["launchctl", "load", str(plist_path)], capture_output=True)
            print(f"[+] LaunchAgent registered: {plist_path}" if not zh else f"[+] LaunchAgent 服务已加载: {plist_path}")
        except Exception as e:
            print(f"[-] LaunchAgent setup error: {e}" if not zh else f"[-] 配置 LaunchAgent 失败: {e}")

    elif sys.platform == "win32":
        import winreg
        print("[*] Configuring Windows background autostart..." if not zh else "[*] 正在配置 Windows 开机静默自启...")
        startup_dir = Path(os.environ.get("APPDATA", str(user_home / "AppData" / "Roaming"))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        vbs_content = f'Set WshShell = CreateObject("WScript.Shell")\nWshShell.Run """{python_runner}"" ""{daemon_script_path}""", 0, False\n'
        vbs_path = startup_dir / "antigravity_context_monitor.vbs"
        try:
            with open(vbs_path, "w", encoding="utf-8") as f:
                f.write(vbs_content)
            print(f"[+] Startup script ready: {vbs_path}" if not zh else f"[+] 开机启动脚本已就绪: {vbs_path}")
        except Exception as e:
            print(f"[-] Startup folder error: {e}" if not zh else f"[-] 写入启动文件夹失败: {e}")

        try:
            run_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            winreg.SetValueEx(run_key, "AntigravityContextMonitor", 0, winreg.REG_SZ, f'"{python_runner}" "{daemon_script_path}"')
            winreg.CloseKey(run_key)
            print("[+] Registry startup key configured!" if not zh else "[+] 注册表开机自启项已成功写入！")
        except Exception as e:
            print(f"[-] Registry error: {e}" if not zh else f"[-] 写入注册表失败: {e}")

        try:
            cmd = f'Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{CommandLine = \'"{python_runner}" "{daemon_script_path}"\'}}'
            subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True)
            print("[+] Daemon process started in background!" if not zh else "[+] 后台守护进程已成功启动！")
        except Exception as e:
            print(f"[-] Launch error: {e}" if not zh else f"[-] 启动进程失败: {e}")

    # 7. Ensure daemon is running on Unix/macOS
    if sys.platform != "win32":
        try:
            check = subprocess.run(["lsof", "-ti", ":38291"], capture_output=True, text=True)
            if not check.stdout.strip():
                with open(plugin_target / "daemon.log", "a") as logf:
                    subprocess.Popen(
                        [str(python_runner), str(daemon_script_path)],
                        stdout=logf,
                        stderr=logf,
                        start_new_session=True
                    )
            print("[+] Background daemon process started!" if not zh else "[+] 后台守护进程已成功启动！")
        except Exception as e:
            print(f"[-] Launch error: {e}" if not zh else f"[-] 启动进程失败: {e}")

    print()
    print("=" * 65)
    if zh:
        print("  [OK] 安装完成！")
        print("  打开或重启 Antigravity 2.0，输入框右侧即可看到上下文监控胶囊。")
        print("  鼠标悬停在百分比上方即可弹出详细仪表盘卡片。")
    else:
        print("  [OK] Installation Complete!")
        print("  Open or restart Antigravity 2.0 to see the context monitor gauge in")
        print("  the bottom right of the input box. Hover over the badge to expand!")
    print("=" * 65)

if __name__ == "__main__":
    main()
