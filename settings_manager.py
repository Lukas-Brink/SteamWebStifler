import os
import sys
import json
import winreg
from paths import CONFIG_PATH

REG_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "SteamWebStifler"

DEFAULT_SETTINGS = {
    "run_at_startup": False,
    "start_with_limiter": True,
    "close_to_tray": True
}


def get_executable_command():
    """Returns the command line string to launch SteamWebStifler at startup."""
    if getattr(sys, "frozen", False):
        exe_path = os.path.abspath(sys.executable)
        return f'"{exe_path}" --tray'
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        exe_path = os.path.join(base_dir, "SteamWebStifler.exe")
        if os.path.exists(exe_path):
            return f'"{exe_path}" --tray'
        python_exe = sys.executable
        main_py = os.path.join(base_dir, "main.py")
        return f'"{python_exe}" "{main_py}" --tray'


def is_run_at_startup_enabled():
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_READ)
        val, _ = winreg.QueryValueEx(key, APP_NAME)
        winreg.CloseKey(key)
        return bool(val)
    except Exception:
        return False


def set_run_at_startup(enable: bool):
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_RUN_KEY, 0, winreg.KEY_SET_VALUE)
        if enable:
            cmd = get_executable_command()
            winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, APP_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        return True
    except Exception as e:
        return False


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    settings.update(data)
        except Exception:
            pass

    # Verify actual registry state
    settings["run_at_startup"] = is_run_at_startup_enabled()
    return settings


def save_settings(settings):
    try:
        # Update registry if run_at_startup is specified
        if "run_at_startup" in settings:
            set_run_at_startup(bool(settings["run_at_startup"]))

        # Read existing file to preserve any other keys if needed
        existing = {}
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                    existing = json.load(f)
            except Exception:
                existing = {}

        existing.update(settings)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(existing, f, indent=2)
        return True
    except Exception:
        return False
