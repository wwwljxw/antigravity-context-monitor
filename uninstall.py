import sys
import os
import shutil
import subprocess
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

def main():
    zh = is_chinese()

    print("=" * 65)
    if zh:
        print("  [-] Antigravity 上下文监控插件 (Context Monitor) - 卸载程序")
    else:
        print("  [-] Antigravity Context Monitor - Uninstaller")
    print("=" * 65)
    print()

    # 1. Stop background daemon
    print("[*] Terminating background daemon process..." if not zh else "[*] 正在终止后台监控守护进程...")
    try:
        if sys.platform == "win32":
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "Get-NetTCPConnection -LocalPort 38291 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
                capture_output=True
            )
        else:
            subprocess.run("lsof -ti :38291 | xargs kill -9 2>/dev/null || true", shell=True, capture_output=True)
        print("[+] Daemon process terminated." if not zh else "[+] 守护进程已停止。")
    except Exception as e:
        print(f"[-] Kill process error: {e}")

    user_home = Path.home()
    plugin_target = user_home / ".gemini" / "config" / "plugins" / "context-monitor"
    skills_global_target = user_home / ".gemini" / "config" / "skills" / "context-monitor"
    skills_agents_target = user_home / ".agents" / "skills" / "context-monitor"
    sidecar_target = user_home / ".gemini" / "config" / "sidecars" / "context-monitor"

    # 2. Clean autostart
    if sys.platform == "darwin":
        plist_path = user_home / "Library" / "LaunchAgents" / "com.antigravity.context-monitor.plist"
        if plist_path.exists():
            try:
                subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
                plist_path.unlink(missing_ok=True)
                print("[+] Removed macOS LaunchAgent." if not zh else "[+] 已清理 macOS LaunchAgent 服务。")
            except Exception as e:
                print(f"[-] Remove LaunchAgent error: {e}")
    elif sys.platform == "win32":
        try:
            import winreg
            run_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE | winreg.KEY_ALL_ACCESS)
            try:
                winreg.DeleteValue(run_key, "AntigravityContextMonitor")
            except FileNotFoundError:
                pass
            winreg.CloseKey(run_key)
            print("[+] Removed Registry startup key." if not zh else "[+] 已清理 Windows 注册表自启项。")
        except Exception as e:
            print(f"[-] Registry cleanup error: {e}")

        startup_dir = Path(os.environ.get("APPDATA", str(user_home / "AppData" / "Roaming"))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
        vbs_path = startup_dir / "antigravity_context_monitor.vbs"
        if vbs_path.exists():
            try:
                vbs_path.unlink()
                print("[+] Removed Startup VBS file." if not zh else "[+] 已清理启动文件夹 VBS 脚本。")
            except Exception as e:
                print(f"[-] VBS cleanup error: {e}")

    # 3. Clean directories
    print("[*] Removing plugin and skill directories..." if not zh else "[*] 正在清理插件与技能安装目录...")
    for target in [plugin_target, skills_global_target, skills_agents_target, sidecar_target]:
        if target.exists():
            try:
                shutil.rmtree(target)
                print(f"[+] Removed: {target}")
            except Exception as e:
                print(f"[-] Remove {target} error: {e}")

    print()
    print("=" * 65)
    if zh:
        print("  [OK] 卸载完成！所有关联文件、守护进程与自启动项已彻底清理。")
    else:
        print("  [OK] Uninstallation Complete! All files, daemons, and startup entries removed.")
    print("=" * 65)

if __name__ == "__main__":
    main()
