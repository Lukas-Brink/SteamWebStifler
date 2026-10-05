import os
import sys
import time
import threading
import webview
from engine import SteamEngine, logger
from image_cache import image_cache, create_tray_icon_image
from paths import BANNERS_DIR, ICONS_DIR, CACHE_DIR, LOG_PATH, WEBVIEW_DIR, PORT_FILE, APP_DIR
import settings_manager

try:
    import pystray
except ImportError:
    pystray = None

HTTP_PORT = 29918


class StiflerBridge:
    """Two-way bridge between Python backend and GPU-accelerated WebView2 frontend."""
    def __init__(self, engine: SteamEngine, app_runner):
        self._engine = engine
        self._app = app_runner

    def get_games(self):
        try:
            games = self._engine.get_installed_games(force_refresh=True)
            result = []
            for g in games:
                aid = g["app_id"]
                known_exes = list(g.get("known_exes", [])) if g.get("known_exes") else []
                item = dict(g)
                item["known_exes"] = known_exes
                item["icon_url"] = image_cache.get_icon_url(aid, steam_path=self._engine.steam_path)
                item["banner_url"] = image_cache.get_banner_url(aid, steam_path=self._engine.steam_path)
                result.append(item)

            # Pre-cache assets in background pool
            image_cache.preload_assets(games, steam_path=self._engine.steam_path)
            return result
        except Exception as e:
            logger.log(f"Error getting games: {e}", "ERROR")
            return []

    def get_banner(self, app_id):
        return image_cache.get_banner_url(str(app_id), steam_path=self._engine.steam_path)

    def launch_game(self, app_id):
        try:
            self._engine.launch_game_pipeline(str(app_id))
            return {"success": True, "message": "Launch pipeline initiated."}
        except Exception as e:
            logger.log(f"Launch error for AppID {app_id}: {e}", "ERROR")
            return {"success": False, "message": str(e)}

    def get_telemetry(self):
        try:
            telem = self._engine.get_telemetry()
            telem["limiter_active"] = self._engine.auto_tamer_active
            return telem
        except Exception as e:
            return {
                "steam_running": False,
                "helper_count": 0,
                "helper_ram_mb": 0.0,
                "helper_cpu_pct": 0.0,
                "limiter_active": False
            }

    def set_limiter(self, active: bool):
        try:
            is_active, msg = self._engine.set_limiter_state(bool(active))
            return {"active": is_active, "message": msg}
        except Exception as e:
            logger.log(f"Set limiter error: {e}", "ERROR")
            return {"active": self._engine.auto_tamer_active, "message": str(e)}

    def get_settings(self):
        return self._app.settings

    def save_settings(self, new_settings: dict):
        try:
            self._app.settings.update(new_settings)
            settings_manager.save_settings(self._app.settings)
            logger.log("Settings saved successfully.", "INFO")
            if self._app.settings.get("close_to_tray", True) and not self._app.tray_icon:
                self._app.init_tray()
            return {"success": True}
        except Exception as e:
            logger.log(f"Error saving settings: {e}", "ERROR")
            return {"success": False, "error": str(e)}

    def get_logs(self):
        with logger._lock:
            return list(logger.history)

    def clear_logs(self):
        with logger._lock:
            logger.history.clear()
        return {"success": True}

    def open_log_file(self):
        try:
            if os.path.exists(LOG_PATH):
                os.startfile(LOG_PATH)
            return {"success": True}
        except Exception as e:
            return {"success": False, "error": str(e)}

    def quit_app(self):
        self._app.quit()


class SteamWebStiflerApp:
    def __init__(self, engine: SteamEngine):
        self.engine = engine
        self.settings = settings_manager.load_settings()
        self.window = None
        self.tray_icon = None
        self.is_quitting = False

        # Apply startup limiter preference
        if self.settings.get("start_with_limiter", True):
            self.engine.start_auto_tamer()
            self.engine.suspend_webhelper()

        # Start Tray in background if enabled
        if self.settings.get("close_to_tray", True):
            self.init_tray()

    def init_tray(self):
        if pystray is None or self.tray_icon is not None:
            return

        def setup_tray():
            try:
                tray_image = create_tray_icon_image()
                menu = pystray.Menu(
                    pystray.MenuItem("Open Steam Web Stifler", self.restore_from_tray, default=True),
                    pystray.MenuItem(
                        "WebHelper Stifler",
                        self._toggle_limiter_from_tray,
                        checked=lambda item: self.engine.auto_tamer_active
                    ),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Exit", self.quit)
                )
                self.tray_icon = pystray.Icon("SteamWebStifler", tray_image, "Steam Web Stifler", menu)
                self.tray_icon.run_detached()
            except Exception as e:
                logger.log(f"Tray note: {e}", "INFO")

        threading.Thread(target=setup_tray, daemon=True).start()

    def restore_from_tray(self, *args):
        if self.window:
            try:
                self.window.show()
                self.window.restore()
            except Exception:
                pass
        try:
            import ctypes
            hwnd = ctypes.windll.user32.FindWindowW(None, "Steam Web Stifler")
            if hwnd:
                ctypes.windll.user32.ShowWindow(hwnd, 5)  # SW_SHOW
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    def _toggle_limiter_from_tray(self, *args):
        new_val = not self.engine.auto_tamer_active
        self.engine.set_limiter_state(new_val)

    def _cleanup_before_exit(self):
        try:
            logger.log("Restoring standard SteamWebHelper operation before exit...", "INFO")
            self.engine.set_limiter_state(False)
        except Exception as e:
            logger.log(f"Cleanup note: {e}", "WARN")

        if os.path.exists(PORT_FILE):
            try:
                os.remove(PORT_FILE)
            except Exception:
                pass

    def on_window_closing(self):
        if self.is_quitting:
            return True
        if self.settings.get("close_to_tray", True):
            if self.window:
                self.window.hide()
            return False  # Cancels window close, keeps app in tray
        else:
            self.is_quitting = True
            self._cleanup_before_exit()
            if self.tray_icon:
                try:
                    self.tray_icon.stop()
                except Exception:
                    pass
            return True

    def quit(self, *args):
        if self.is_quitting:
            return
        self.is_quitting = True
        self._cleanup_before_exit()
        try:
            if self.tray_icon:
                self.tray_icon.stop()
        except Exception:
            pass
        if self.window:
            try:
                self.window.destroy()
            except Exception:
                pass
        sys.exit(0)

    def mainloop(self):
        import bottle

        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            gui_dir = os.path.join(sys._MEIPASS, "gui")
        else:
            gui_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gui")

        server = bottle.Bottle()

        @server.route('/restore')
        def restore_endpoint():
            self.restore_from_tray()
            return "OK"

        @server.route('/cache/banners/<filename:path>')
        def serve_banner(filename):
            app_id = filename.split('.')[0]
            banner_file = os.path.join(BANNERS_DIR, f"{app_id}.jpg")
            if not os.path.exists(banner_file):
                image_cache.ensure_banner(app_id, steam_path=self.engine.steam_path)
            if os.path.exists(banner_file):
                return bottle.static_file(f"{app_id}.jpg", root=BANNERS_DIR)
            return bottle.HTTPResponse(status=404)

        @server.route('/cache/icons/<filename:path>')
        def serve_icon(filename):
            app_id = filename.split('_')[0].split('.')[0]
            icon_file = os.path.join(ICONS_DIR, f"{app_id}.png")
            if not os.path.exists(icon_file):
                image_cache.ensure_icon(app_id, steam_path=self.engine.steam_path)
            if os.path.exists(icon_file):
                return bottle.static_file(f"{app_id}.png", root=ICONS_DIR)
            return bottle.HTTPResponse(status=404)

        @server.route('/')
        def serve_index():
            return bottle.static_file('index.html', root=gui_dir)

        @server.route('/<filepath:path>')
        def serve_gui(filepath):
            return bottle.static_file(filepath, root=gui_dir)

        bridge = StiflerBridge(self.engine, self)

        start_minimized = "--tray" in sys.argv or "--minimized" in sys.argv

        if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
            icon_path = os.path.join(sys._MEIPASS, "gui", "logo.png")
        else:
            icon_path = os.path.join(APP_DIR, "gui", "logo.png")

        self.window = webview.create_window(
            title="Steam Web Stifler",
            url=server,
            js_api=bridge,
            width=1120,
            height=720,
            min_size=(960, 600),
            background_color="#0c0d10",
            hidden=start_minimized
        )

        self.window.events.closing += self.on_window_closing

        def on_loaded():
            try:
                if self.window and getattr(self.window, "real_url", None):
                    import urllib.parse
                    parsed = urllib.parse.urlparse(self.window.real_url)
                    if parsed.port:
                        with open(PORT_FILE, "w", encoding="utf-8") as f:
                            f.write(str(parsed.port))
            except Exception:
                pass

        self.window.events.loaded += on_loaded

        # Start WebView2 engine with DirectComposition GPU acceleration & portable storage
        webview.start(
            gui="edgechromium",
            debug=False,
            storage_path=WEBVIEW_DIR,
            http_port=HTTP_PORT
        )
