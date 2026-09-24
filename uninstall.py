import sys
import os
import shutil
import subprocess
import winreg
from pathlib import Path

# Ensure UTF-8 output
if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

def main():
    print("=" * 60)
    print("  🗑️ Antigravity 2.0 上下文容量监控插件 - 卸载程序")
    print("=" * 60)
    print()

    # 1. Stop daemon process
    print("[*] 正在停止后台守护进程...")
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", 
             "Get-NetTCPConnection -LocalPort 38291 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
            capture_output=True
        )
        print("[+] 后台守护进程已停止。")
    except Exception as e:
        print(f"[-] 停止进程提示: {e}")

    # 2. Remove registry key
    print("[*] 正在移除注册表自启项...")
    try:
        run_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE | winreg.KEY_ALL_ACCESS)
        try:
            winreg.DeleteValue(run_key, "AntigravityContextMonitor")
            print("[+] 注册表自启项已移除。")
        except FileNotFoundError:
            pass
        winreg.CloseKey(run_key)
    except Exception as e:
        print(f"[-] 移除注册表项提示: {e}")

    # 3. Remove Startup VBScript
    user_home = Path.home()
    startup_dir = Path(os.environ.get("APPDATA", str(user_home / "AppData" / "Roaming"))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    vbs_path = startup_dir / "antigravity_context_monitor.vbs"
    if vbs_path.exists():
        try:
            vbs_path.unlink()
            print("[+] 启动文件夹脚本已移除。")
        except Exception as e:
            print(f"[-] 移除启动脚本失败: {e}")

    # 4. Remove Sidecar config
    sidecar_dir = user_home / ".gemini" / "config" / "sidecars" / "context-monitor"
    if sidecar_dir.exists():
        try:
            shutil.rmtree(sidecar_dir)
            print("[+] Sidecar 配置文件已移除。")
        except Exception as e:
            print(f"[-] 移除 Sidecar 目录失败: {e}")

    # 5. Remove plugin and skill files
    plugin_dir = user_home / ".gemini" / "config" / "plugins" / "context-monitor"
    skills_dir = user_home / ".agents" / "skills" / "context-monitor"
    if plugin_dir.exists():
        try:
            shutil.rmtree(plugin_dir)
            print("[+] 插件目录已删除。")
        except Exception as e:
            print(f"[-] 删除插件目录失败: {e}")
            
    if skills_dir.exists():
        try:
            shutil.rmtree(skills_dir)
            print("[+] 技能目录已删除。")
        except Exception as e:
            print(f"[-] 删除技能目录失败: {e}")

    print()
    print("=" * 60)
    print("  ✅ 插件卸载完成！已完全清理。")
    print("=" * 60)

if __name__ == "__main__":
    main()
