import sys
import os
import shutil
import subprocess
import winreg
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
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (lang_id & 0xFF) == 0x04:
            return True
    except Exception:
        pass
    lang = os.environ.get("LANG", "").lower()
    return lang.startswith("zh")

def main():
    zh = is_chinese()

    print("=" * 65)
    if zh:
        print("  [-] Antigravity 2.0 上下文容量监控插件 - 卸载程序")
    else:
        print("  [-] Antigravity 2.0 Context Monitor Plugin - Uninstaller")
    print("=" * 65)
    print()

    # 1. Stop daemon process
    print("[*] 正在停止后台守护进程..." if zh else "[*] Stopping background daemon process...")
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", 
             "Get-NetTCPConnection -LocalPort 38291 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
            capture_output=True
        )
        print("[+] 后台守护进程已停止。" if zh else "[+] Background daemon stopped.")
    except Exception as e:
        print(f"[-] {e}")

    # 2. Remove registry key
    print("[*] 正在移除注册表自启项..." if zh else "[*] Removing registry autostart key...")
    try:
        run_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE | winreg.KEY_ALL_ACCESS)
        try:
            winreg.DeleteValue(run_key, "AntigravityContextMonitor")
            print("[+] 注册表自启项已移除。" if zh else "[+] Registry autostart key removed.")
        except FileNotFoundError:
            pass
        winreg.CloseKey(run_key)
    except Exception as e:
        print(f"[-] {e}")

    # 3. Remove Startup VBScript
    user_home = Path.home()
    startup_dir = Path(os.environ.get("APPDATA", str(user_home / "AppData" / "Roaming"))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    vbs_path = startup_dir / "antigravity_context_monitor.vbs"
    if vbs_path.exists():
        try:
            vbs_path.unlink()
            print("[+] 启动文件夹脚本已移除。" if zh else "[+] Startup script removed.")
        except Exception as e:
            print(f"[-] {e}")

    # 4. Remove Sidecar config
    sidecar_dir = user_home / ".gemini" / "config" / "sidecars" / "context-monitor"
    if sidecar_dir.exists():
        try:
            shutil.rmtree(sidecar_dir)
            print("[+] Sidecar 配置文件已移除。" if zh else "[+] Sidecar config removed.")
        except Exception as e:
            print(f"[-] {e}")

    # 5. Remove plugin and skill files
    plugin_dir = user_home / ".gemini" / "config" / "plugins" / "context-monitor"
    skills_dir = user_home / ".agents" / "skills" / "context-monitor"
    if plugin_dir.exists():
        try:
            shutil.rmtree(plugin_dir)
            print("[+] 插件目录已删除。" if zh else "[+] Plugin directory removed.")
        except Exception as e:
            print(f"[-] {e}")
            
    if skills_dir.exists():
        try:
            shutil.rmtree(skills_dir)
            print("[+] 技能目录已删除。" if zh else "[+] Skill directory removed.")
        except Exception as e:
            print(f"[-] {e}")

    print()
    print("=" * 65)
    if zh:
        print("  [OK] 插件卸载完成！已完全清理。")
    else:
        print("  [OK] Plugin uninstalled successfully. Cleaned up completely.")
    print("=" * 65)

if __name__ == "__main__":
    main()
