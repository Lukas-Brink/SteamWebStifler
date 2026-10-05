import os
import sys
import shutil

# Determine root application directory
if getattr(sys, "frozen", False):
    APP_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    APP_DIR = os.path.dirname(os.path.abspath(__file__))

# All user data, settings, caches, and webview storage live strictly in a single "data" directory
DATA_DIR = os.path.join(APP_DIR, "data")
CACHE_DIR = os.path.join(DATA_DIR, "cache")
BANNERS_DIR = os.path.join(CACHE_DIR, "banners")
ICONS_DIR = os.path.join(CACHE_DIR, "icons")
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
LOG_PATH = os.path.join(DATA_DIR, "steamwebstifler.log")
WEBVIEW_DIR = os.path.join(DATA_DIR, "webview")
PORT_FILE = os.path.join(DATA_DIR, ".port")


def init_portable_dirs():
    """Initializes all data directories and migrates any loose legacy files into data/."""
    for d in [DATA_DIR, CACHE_DIR, BANNERS_DIR, ICONS_DIR, WEBVIEW_DIR]:
        os.makedirs(d, exist_ok=True)

    # Set WebView2 User Data Folder environment variable before WebView2 runtime initializes
    os.environ["WEBVIEW2_USER_DATA_FOLDER"] = WEBVIEW_DIR

    # Migrate legacy config.json if present in APP_DIR
    legacy_config = os.path.join(APP_DIR, "config.json")
    if os.path.exists(legacy_config) and not os.path.exists(CONFIG_PATH):
        try:
            shutil.copy2(legacy_config, CONFIG_PATH)
            os.remove(legacy_config)
        except Exception:
            pass
    elif os.path.exists(legacy_config) and os.path.exists(CONFIG_PATH):
        try:
            os.remove(legacy_config)
        except Exception:
            pass

    # Migrate legacy log file if present
    for old_log in [os.path.join(APP_DIR, "steam_ghost.log"), os.path.join(DATA_DIR, "steam_ghost.log")]:
        if os.path.exists(old_log):
            if not os.path.exists(LOG_PATH):
                try:
                    shutil.copy2(old_log, LOG_PATH)
                except Exception:
                    pass
            try:
                os.remove(old_log)
            except Exception:
                pass

    # Clean up legacy cache directory in root if it exists
    legacy_cache = os.path.join(APP_DIR, "cache")
    if os.path.exists(legacy_cache) and os.path.abspath(legacy_cache) != os.path.abspath(CACHE_DIR):
        try:
            shutil.rmtree(legacy_cache, ignore_errors=True)
        except Exception:
            pass


# Ensure directories and environment variables are initialized immediately upon import
init_portable_dirs()

