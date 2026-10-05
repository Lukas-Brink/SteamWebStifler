import sys
import os
import ctypes
import urllib.request
import paths

# Initialize portable directories and configure WebView2 user data folder
paths.init_portable_dirs()

ERROR_ALREADY_EXISTS = 183
SW_SHOW = 5
SW_RESTORE = 9
HTTP_PORT = 29918


def ensure_single_instance():
    """Guarantees only one instance runs at a time.
    If an instance is already running (or minimized in tray), wakes it up,
    restores the window to the foreground, and exits immediately.
    """
    mutex_name = "SteamWebStifler_SingleInstance_Mutex_9918"
    mutex = ctypes.windll.kernel32.CreateMutexW(None, True, mutex_name)
    last_error = ctypes.windll.kernel32.GetLastError()

    if last_error == ERROR_ALREADY_EXISTS:
        # Signal running instance to restore via loopback IPC endpoint
        if os.path.exists(paths.PORT_FILE):
            try:
                with open(paths.PORT_FILE, "r", encoding="utf-8") as f:
                    port = int(f.read().strip())
                req = urllib.request.Request(f"http://127.0.0.1:{port}/restore")
                urllib.request.urlopen(req, timeout=1.0)
            except Exception:
                pass

        # Win32 fallback to bring existing window to front
        try:
            hwnd = ctypes.windll.user32.FindWindowW(None, "Steam Web Stifler")
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, SW_SHOW)
                ctypes.windll.user32.ShowWindow(hwnd, SW_RESTORE)
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

        sys.exit(0)

    return mutex


def main():
    _mutex = ensure_single_instance()

    from engine import SteamEngine, logger
    from ui import SteamWebStiflerApp

    logger.log("=============================================", "INFO")
    logger.log("   Steam Web Stifler & Memory Supervisor", "INFO")
    logger.log("=============================================", "INFO")

    engine = SteamEngine()
    app = SteamWebStiflerApp(engine)
    app.mainloop()


if __name__ == "__main__":
    main()
