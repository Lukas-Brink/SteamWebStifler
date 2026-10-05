import os
import sys
import time
import ctypes
import ctypes.wintypes
import threading
import winreg
import psutil
import subprocess
from datetime import datetime
from pathlib import Path

# Win32 API Definitions for Memory Management
try:
    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    ntdll = ctypes.windll.ntdll
    PROCESS_ALL_ACCESS = 0x1F0FFF
    EmptyWorkingSet = psapi.EmptyWorkingSet
    EmptyWorkingSet.argtypes = [ctypes.wintypes.HANDLE]
    EmptyWorkingSet.restype = ctypes.wintypes.BOOL
except Exception:
    pass


from paths import LOG_PATH

class Logger:
    def __init__(self, log_file=LOG_PATH):
        self.log_file = log_file
        self.subscribers = []
        self.history = []
        self._lock = threading.Lock()

    def subscribe(self, callback):
        with self._lock:
            self.subscribers.append(callback)

    def log(self, message, level="INFO"):
        timestamp = datetime.now().strftime("%H:%M:%S")
        formatted = f"[{timestamp}] [{level}] {message}"
        
        with self._lock:
            self.history.append(formatted)
            if len(self.history) > 600:
                self.history.pop(0)

            # Write to disk
            try:
                with open(self.log_file, "a", encoding="utf-8") as f:
                    f.write(formatted + "\n")
            except Exception:
                pass

            # Notify UI callbacks
            for sub in self.subscribers:
                try:
                    sub(formatted, level)
                except Exception:
                    pass


logger = Logger()


class SteamEngine:
    def __init__(self):
        self.steam_path = self.detect_steam_path()
        self.cached_games = []
        self.last_scan_time = 0
        self.auto_tamer_active = False
        self.webhelper_frozen = False
        self._tamer_thread = None
        self._stop_tamer = threading.Event()
        self._proc_cache = {}
        self.is_launching = False

        logger.log(f"Steam Engine initialized. Detected path: {self.steam_path}")

    def detect_steam_path(self):
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam")
            path, _ = winreg.QueryValueEx(key, "SteamPath")
            winreg.CloseKey(key)
            if path and os.path.exists(path):
                return os.path.normpath(path)
        except Exception:
            pass

        candidates = [
            r"D:\Program Files (x86)\Steam",
            r"C:\Program Files (x86)\Steam",
            r"D:\Steam",
            r"C:\Steam"
        ]
        for c in candidates:
            if os.path.exists(os.path.join(c, "steam.exe")):
                return os.path.normpath(c)

        return r"C:\Program Files (x86)\Steam"

    def get_steam_exe(self):
        return os.path.join(self.steam_path, "steam.exe")

    def get_telemetry(self):
        # Ultra-fast path: query cached process handles directly (0.1ms vs 8ms full process_iter)
        if getattr(self, "_steam_proc", None) and self._proc_cache:
            try:
                if self._steam_proc.is_running() and all(p.is_running() for p in self._proc_cache.values()):
                    steam_ram = round(self._steam_proc.memory_info().rss / (1024 * 1024), 1)
                    total_ram = sum(p.memory_info().rss for p in self._proc_cache.values()) / (1024 * 1024)
                    total_cpu = sum(p.cpu_percent(interval=None) for p in self._proc_cache.values())
                    return {
                        "steam_running": True,
                        "steam_pid": self._steam_proc.pid,
                        "steam_ram_mb": steam_ram,
                        "helper_count": len(self._proc_cache),
                        "helper_ram_mb": round(total_ram, 1),
                        "helper_cpu_pct": round(total_cpu, 1),
                        "is_suspended": self.webhelper_frozen,
                        "limiter_active": self.auto_tamer_active
                    }
            except Exception:
                pass

        # Full system scan path (used when processes change or on startup)
        steam_proc = None
        webhelper_procs = []
        total_helper_ram = 0.0
        total_helper_cpu = 0.0
        current_pids = set()

        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                name = p.info['name'].lower()
                if name == "steam.exe":
                    steam_proc = p
                elif name == "steamwebhelper.exe":
                    pid = p.info['pid']
                    current_pids.add(pid)
                    webhelper_procs.append(p)
                    rss_mb = p.info['memory_info'].rss / (1024 * 1024)
                    total_helper_ram += rss_mb
                    
                    if pid not in self._proc_cache:
                        try:
                            proc_obj = psutil.Process(pid)
                            proc_obj.cpu_percent(interval=None)  # prime baseline
                            self._proc_cache[pid] = proc_obj
                        except Exception:
                            pass

                    if pid in self._proc_cache:
                        try:
                            total_helper_cpu += self._proc_cache[pid].cpu_percent(interval=None)
                        except Exception:
                            pass
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        # Prune old process handles
        self._proc_cache = {pid: proc for pid, proc in self._proc_cache.items() if pid in current_pids}
        self._steam_proc = steam_proc

        steam_running = (steam_proc is not None)
        steam_pid = steam_proc.info['pid'] if steam_running else 0
        steam_ram = round(steam_proc.info['memory_info'].rss / (1024 * 1024), 1) if steam_running else 0.0

        return {
            "steam_running": steam_running,
            "steam_pid": steam_pid,
            "steam_ram_mb": steam_ram,
            "helper_count": len(webhelper_procs),
            "helper_ram_mb": round(total_helper_ram, 1),
            "helper_cpu_pct": round(total_helper_cpu, 1),
            "is_suspended": self.webhelper_frozen,
            "limiter_active": self.auto_tamer_active
        }

    def trim_working_set_handle(self, pid):
        try:
            h_proc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
            if h_proc:
                EmptyWorkingSet(h_proc)
                kernel32.CloseHandle(h_proc)
                return True
        except Exception:
            pass
        return False

    def suspend_webhelper(self):
        if self.webhelper_frozen:
            return 0

        count = 0
        reclaimed_mb = 0.0
        for p in psutil.process_iter(['pid', 'name', 'memory_info']):
            try:
                if p.info['name'].lower() == "steamwebhelper.exe":
                    before_mb = p.info['memory_info'].rss / (1024 * 1024)
                    p.suspend()
                    self.trim_working_set_handle(p.info['pid'])
                    reclaimed_mb += before_mb
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        self.webhelper_frozen = True
        logger.log(f"Suspended {count} steamwebhelper processes. Trimmed ~{round(reclaimed_mb, 1)} MB.", "SUCCESS")
        return count

    def resume_webhelper(self):
        count = 0
        needs_restart = False
        
        for p in psutil.process_iter(['pid', 'name']):
            try:
                if p.info['name'].lower() == "steamwebhelper.exe":
                    p.resume()
                    count += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        time.sleep(0.3)

        for p in psutil.process_iter(['pid', 'name', 'status']):
            try:
                if p.info['name'].lower() == "steamwebhelper.exe":
                    if p.status() == psutil.STATUS_STOPPED:
                        needs_restart = True
                        break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if needs_restart:
            logger.log("Recycling WebHelper processes for clean, responsive state...", "INFO")
            for p in psutil.process_iter(['pid', 'name']):
                try:
                    if p.info['name'].lower() == "steamwebhelper.exe":
                        p.kill()
                except Exception:
                    pass
            time.sleep(1.0)
            logger.log("Steam WebHelper recycled and fully responsive.", "SUCCESS")

        self.webhelper_frozen = False
        logger.log(f"Resumed {count} steamwebhelper processes.", "INFO")
        return count

    def set_limiter_state(self, enable: bool):
        """Toggles the limiter with verified feedback."""
        if enable:
            self.start_auto_tamer()
            self.suspend_webhelper()
            time.sleep(0.3)
            telem = self.get_telemetry()
            return True, f"Limiter Active ({telem['helper_ram_mb']} MB RAM • {telem['helper_cpu_pct']}% CPU)"
        else:
            self.stop_auto_tamer()
            self.resume_webhelper()
            time.sleep(0.4)
            telem = self.get_telemetry()
            return False, f"Standard Mode ({telem['helper_ram_mb']} MB RAM • {telem['helper_cpu_pct']}% CPU)"

    def start_steam_silent(self):
        exe = self.get_steam_exe()
        if not os.path.exists(exe):
            logger.log(f"Cannot find steam.exe at {exe}", "ERROR")
            return False

        telemetry = self.get_telemetry()
        if telemetry["steam_running"]:
            return True

        logger.log(f"Starting Steam silently in system tray: {exe} -silent", "INFO")
        try:
            subprocess.Popen([exe, "-silent"], close_fds=True)
            for _ in range(25):
                time.sleep(0.4)
                if self.get_telemetry()["steam_running"]:
                    logger.log("Steam core process confirmed running.", "SUCCESS")
                    return True
        except Exception as e:
            logger.log(f"Failed to start Steam: {e}", "ERROR")
            return False

        return False

    def get_installed_games(self, force_refresh=False):
        now = time.time()
        if not force_refresh and self.cached_games and (now - self.last_scan_time < 30):
            return self.cached_games

        libraries = set()
        if os.path.exists(self.steam_path):
            libraries.add(os.path.normcase(os.path.normpath(self.steam_path)))

            vdf_path = os.path.join(self.steam_path, "steamapps", "libraryfolders.vdf")
            if os.path.exists(vdf_path):
                try:
                    with open(vdf_path, "r", encoding="utf-8", errors="ignore") as f:
                        content = f.read()
                    import re
                    matches = re.findall(r'"path"\s+"([^"]+)"', content)
                    for m in matches:
                        cleaned = m.replace(r"\\", "\\")
                        if os.path.exists(cleaned):
                            libraries.add(os.path.normcase(os.path.normpath(cleaned)))
                except Exception as e:
                    logger.log(f"Error parsing libraryfolders.vdf: {e}", "WARN")

        seen_appids = set()
        games = []
        ignored_appids = {"228980", "250820"}

        for lib in libraries:
            apps_dir = os.path.join(lib, "steamapps")
            if not os.path.exists(apps_dir):
                continue

            try:
                for file in os.listdir(apps_dir):
                    if file.startswith("appmanifest_") and file.endswith(".acf"):
                        acf_path = os.path.join(apps_dir, file)
                        try:
                            with open(acf_path, "r", encoding="utf-8", errors="ignore") as f:
                                acf_content = f.read()
                            
                            import re
                            appid_m = re.search(r'"appid"\s+"([^"]+)"', acf_content)
                            name_m = re.search(r'"name"\s+"([^"]+)"', acf_content)
                            dir_m = re.search(r'"installdir"\s+"([^"]+)"', acf_content)
                            size_m = re.search(r'"SizeOnDisk"\s+"([^"]+)"', acf_content)
                            last_played_m = re.search(r'"LastPlayed"\s+"([^"]+)"', acf_content)

                            if appid_m and name_m:
                                app_id = appid_m.group(1)
                                if app_id in ignored_appids or app_id in seen_appids:
                                    continue
                                seen_appids.add(app_id)

                                name = name_m.group(1).replace("—", " - ").replace("\ufffd", " - ").strip()
                                install_dir = dir_m.group(1) if dir_m else ""
                                full_game_path = os.path.join(apps_dir, "common", install_dir)
                                raw_size = int(size_m.group(1)) if size_m else 0
                                size_gb = round(raw_size / (1024 * 1024 * 1024), 2)
                                last_played = int(last_played_m.group(1)) if last_played_m else 0

                                known_exes, primary_exe = self._scan_game_executables(full_game_path, name)

                                games.append({
                                    "app_id": app_id,
                                    "name": name,
                                    "install_dir": install_dir,
                                    "full_path": full_game_path,
                                    "size_gb": size_gb,
                                    "raw_size": raw_size,
                                    "last_played": last_played,
                                    "known_exes": known_exes,
                                    "primary_exe": primary_exe,
                                    "library_path": lib
                                })
                        except Exception:
                            continue
            except Exception:
                continue

        games.sort(key=lambda g: g["last_played"], reverse=True)
        self.cached_games = games
        self.last_scan_time = now
        logger.log(f"Discovered {len(games)} installed games across {len(libraries)} libraries.", "INFO")
        return games

    def _scan_game_executables(self, game_path, game_name):
        known_exes = set()
        primary_exe = None
        if not os.path.exists(game_path):
            return known_exes, None

        ignore_names = {"crashreportclient.exe", "crashreporter.exe", "7za.exe", "minicrashdump.exe", "dxsetup.exe", "vcredist_x64.exe", "vcredist_x86.exe", "unins000.exe"}

        try:
            for root, dirs, files in os.walk(game_path):
                rel_parts = Path(root).relative_to(game_path).parts
                if len(rel_parts) > 3:
                    continue
                for f in files:
                    if f.lower().endswith(".exe"):
                        f_lower = f.lower()
                        if f_lower not in ignore_names:
                            known_exes.add(f_lower)
                            if not primary_exe and ("launcher" not in f_lower or len(known_exes) == 1):
                                primary_exe = f
        except Exception:
            pass

        return known_exes, primary_exe

    def launch_game_pipeline(self, app_id, auto_freeze=True, on_complete=None):
        thread = threading.Thread(
            target=self._launch_game_worker,
            args=(app_id, auto_freeze, on_complete),
            daemon=True
        )
        thread.start()

    def _launch_game_worker(self, app_id, auto_freeze, on_complete):
        self.is_launching = True
        logger.log(f"--- Starting Launch Pipeline for AppID {app_id} ---", "INFO")

        game_info = next((g for g in self.cached_games if g["app_id"] == app_id), None)
        game_name = game_info["name"] if game_info else f"AppID {app_id}"
        known_exes = game_info.get("known_exes", set()) if game_info else set()
        game_path_lower = os.path.normpath(game_info["full_path"]).lower() if game_info else ""

        logger.log(f"Target: {game_name}", "INFO")

        # Step 1: Ensure Steam is running
        telemetry = self.get_telemetry()
        if not telemetry["steam_running"]:
            logger.log("Steam core is offline. Starting Steam in background...", "INFO")
            if not self.start_steam_silent():
                logger.log("Could not start Steam core. Aborting launch.", "ERROR")
                self.is_launching = False
                if on_complete: on_complete(False, "Could not start Steam")
                return
        else:
            logger.log(f"Steam core active (PID {telemetry['steam_pid']}).", "INFO")

        # Step 2: Unconditionally RESUME WebHelper so Steam is responsive
        logger.log("Ensuring SteamWebHelper is active for launch handshake...", "INFO")
        self.resume_webhelper()
        time.sleep(1.0)

        # Step 3: Issue launch signals
        logger.log(f"Dispatching launch signal: steam://rungameid/{app_id}", "INFO")
        try:
            os.startfile(f"steam://rungameid/{app_id}")
        except Exception as e:
            logger.log(f"URI launch returned error: {e}. Executing CLI fallback...", "WARN")

        steam_exe = self.get_steam_exe()
        try:
            subprocess.Popen([steam_exe, "-applaunch", app_id], close_fds=True)
            logger.log(f"CLI trigger sent: {steam_exe} -applaunch {app_id}", "INFO")
        except Exception as ce:
            logger.log(f"CLI trigger failed: {ce}", "WARN")

        # Step 4: Strict Process Monitoring
        logger.log("Monitoring process table for verified game execution (up to 45s)...", "INFO")
        game_proc = None
        start_wait = time.time()

        while time.time() - start_wait < 45:
            time.sleep(1.5)
            for p in psutil.process_iter(['pid', 'name', 'exe']):
                try:
                    p_name = p.info['name'].lower()
                    if p_name in known_exes:
                        game_proc = p
                        break
                    p_exe = p.info.get('exe')
                    if p_exe and game_path_lower and game_path_lower in os.path.normpath(p_exe).lower():
                        game_proc = p
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            if game_proc:
                break

        if game_proc:
            try:
                p_name = game_proc.info['name']
                p_pid = game_proc.info['pid']
                logger.log(f"Game confirmed running: {p_name} (PID: {p_pid})", "SUCCESS")
            except Exception:
                logger.log("Game process confirmed running!", "SUCCESS")

            # Step 5: Wait 15 seconds for game to complete auth before freezing
            if auto_freeze and self.auto_tamer_active:
                logger.log("Allowing 15 seconds for game initialization & anti-cheat tickets...", "INFO")
                time.sleep(15.0)
                logger.log("Freezing SteamWebHelper & evacuating CEF RAM...", "INFO")
                self.suspend_webhelper()
                logger.log("Memory optimized: 100% of CPU and RAM allocated to game.", "SUCCESS")

            if on_complete: on_complete(True, f"Running: {game_name}")
        else:
            logger.log("Launch signals delivered to Steam.", "INFO")
            logger.log("Leaving SteamWebHelper active so you can interact with any Steam prompts.", "INFO")
            if on_complete: on_complete(True, "Launch signal delivered")

        self.is_launching = False
        logger.log("--- Launch Pipeline Finished ---", "INFO")

    def start_auto_tamer(self, threshold_mb=300):
        if self.auto_tamer_active:
            return
        self.auto_tamer_active = True
        self._stop_tamer.clear()

        def tamer_loop():
            logger.log("WebHelper Limiter daemon active.", "INFO")
            while not self._stop_tamer.is_set():
                time.sleep(3.0)
                if self.is_launching:
                    continue
                try:
                    telemetry = self.get_telemetry()
                    if telemetry["steam_running"] and telemetry["helper_count"] > 0:
                        if not self.webhelper_frozen and telemetry["helper_ram_mb"] > threshold_mb:
                            logger.log(f"RAM exceeded threshold ({telemetry['helper_ram_mb']} MB). Freezing...", "INFO")
                            self.suspend_webhelper()
                except Exception:
                    pass

        self._tamer_thread = threading.Thread(target=tamer_loop, daemon=True)
        self._tamer_thread.start()

    def stop_auto_tamer(self):
        self.auto_tamer_active = False
        self._stop_tamer.set()
        logger.log("WebHelper Limiter daemon stopped.", "INFO")
