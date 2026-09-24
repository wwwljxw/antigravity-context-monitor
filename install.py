import sys
import os
import shutil
import subprocess
import json
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
    print("  🚀 Antigravity 2.0 上下文容量监控插件 - 一键安装程序")
    print("=" * 60)
    print()

    # 1. Check Python and pythonw
    python_exe = sys.executable
    python_dir = Path(python_exe).parent
    pythonw_exe = python_dir / "pythonw.exe"
    if not pythonw_exe.exists():
        pythonw_exe = Path(shutil.which("pythonw") or python_exe)
    
    print(f"[*] 检测到 Python 环境: {python_exe}")
    print(f"[*] 后台静默执行器: {pythonw_exe}")

    # 2. Check & install websockets
    print("[*] 正在检查依赖库 websockets...")
    try:
        import websockets
        print("[+] websockets 已安装。")
    except ImportError:
        print("[*] 正在自动安装 websockets...")
        try:
            subprocess.check_call([python_exe, "-m", "pip", "install", "websockets", "-q"])
            print("[+] websockets 安装成功！")
        except Exception as e:
            print(f"[-] 安装 websockets 失败: {e}，请手动执行 pip install websockets")

    # 3. Directories
    src_dir = Path(__file__).resolve().parent
    user_home = Path.home()
    plugin_target = user_home / ".gemini" / "config" / "plugins" / "context-monitor"
    skills_target = user_home / ".agents" / "skills" / "context-monitor"
    sidecar_target = user_home / ".gemini" / "config" / "sidecars" / "context-monitor"
    startup_dir = Path(os.environ.get("APPDATA", str(user_home / "AppData" / "Roaming"))) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"

    print(f"[*] 目标安装路径: {plugin_target}")

    # 4. Copy files
    print("[*] 正在复制插件核心文件...")
    os.makedirs(plugin_target / "skills" / "context-monitor" / "scripts", exist_ok=True)
    os.makedirs(skills_target / "scripts", exist_ok=True)
    os.makedirs(sidecar_target, exist_ok=True)

    # Copy plugin.json
    shutil.copy2(src_dir / "plugin.json", plugin_target / "plugin.json")
    
    # Copy skills
    src_skills = src_dir / "skills" / "context-monitor"
    shutil.copy2(src_skills / "SKILL.md", plugin_target / "skills" / "context-monitor" / "SKILL.md")
    shutil.copy2(src_skills / "SKILL.md", skills_target / "SKILL.md")
    
    for script_name in ["daemon_sync.py", "generate_monitor.py", "inject_gauge.py"]:
        src_script = src_skills / "scripts" / script_name
        if src_script.exists():
            shutil.copy2(src_script, plugin_target / "skills" / "context-monitor" / "scripts" / script_name)
            shutil.copy2(src_script, skills_target / "scripts" / script_name)

    print("[+] 插件核心文件复制完毕！")

    # 5. Configure Sidecar
    print("[*] 正在配置 Antigravity Sidecar 服务...")
    daemon_script_path = plugin_target / "skills" / "context-monitor" / "scripts" / "daemon_sync.py"
    sidecar_config = {
        "name": "context-monitor",
        "description": "Antigravity Context Gauge & Token Live Monitor",
        "command": str(pythonw_exe),
        "args": [str(daemon_script_path)],
        "restart_policy": "always"
    }
    with open(sidecar_target / "sidecar.json", "w", encoding="utf-8") as f:
        json.dump(sidecar_config, f, indent=2, ensure_ascii=False)
    print(f"[+] Sidecar 配置文件已就绪: {sidecar_target / 'sidecar.json'}")

    # 6. Configure Windows Startup (VBS)
    print("[*] 正在配置 Windows 开机静默自启...")
    vbs_content = f'Set WshShell = CreateObject("WScript.Shell")\nWshShell.Run """{pythonw_exe}"" ""{daemon_script_path}""", 0, False\n'
    vbs_path = startup_dir / "antigravity_context_monitor.vbs"
    try:
        with open(vbs_path, "w", encoding="utf-8") as f:
            f.write(vbs_content)
        print(f"[+] 开机启动脚本已就绪: {vbs_path}")
    except Exception as e:
        print(f"[-] 写入启动文件夹失败: {e}")

    # 7. Configure HKCU Run Registry Key
    print("[*] 正在写入 Windows 注册表自启项...")
    try:
        run_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(run_key, "AntigravityContextMonitor", 0, winreg.REG_SZ, f'"{pythonw_exe}" "{daemon_script_path}"')
        winreg.CloseKey(run_key)
        print("[+] 注册表开机自启项已成功写入！")
    except Exception as e:
        print(f"[-] 写入注册表失败: {e}")

    # 8. Start the daemon immediately via WMI or pythonw
    print("[*] 正在立即启动后台守护进程...")
    try:
        # Stop existing process on 38291 if any
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", 
             "Get-NetTCPConnection -LocalPort 38291 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"],
            capture_output=True
        )
        # Launch detached via WMI
        cmd = f'Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{{CommandLine = \'"{pythonw_exe}" "{daemon_script_path}"\'}}'
        subprocess.run(["powershell", "-NoProfile", "-Command", cmd], capture_output=True)
        print("[+] 后台守护进程已成功启动！")
    except Exception as e:
        print(f"[-] 启动进程失败: {e}")

    print()
    print("=" * 60)
    print("  🎉 安装完成！")
    print("  打开或重启 Antigravity 2.0，输入框右侧即可看到上下文容量监控胶囊。")
    print("  鼠标悬停在百分比上方即可弹出详细卡片。")
    print("=" * 60)

if __name__ == "__main__":
    main()
