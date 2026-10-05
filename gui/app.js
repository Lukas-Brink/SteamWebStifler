/**
 * SteamWebStifler - Modern High-Performance UI Controller
 * GPU-Accelerated WebView2 frontend connected to Python backend
 */

let state = {
  games: [],
  filteredGames: [],
  selectedGame: null,
  limiterActive: false,
  limiterBusy: false,
  logsVisible: false,
  sortMode: "Recent",
  searchQuery: "",
  settings: {
    run_at_startup: false,
    start_with_limiter: true,
    close_to_tray: true
  }
};

// DOM References
const el = {
  telemetryPill: document.getElementById("telemetryPill"),
  telemRam: document.getElementById("telemRam"),
  telemCpu: document.getElementById("telemCpu"),
  limiterToggle: document.getElementById("limiterToggle"),
  btnSettings: document.getElementById("btnSettings"),
  btnToggleLogs: document.getElementById("btnToggleLogs"),
  searchInput: document.getElementById("searchInput"),
  clearSearchBtn: document.getElementById("clearSearchBtn"),
  gamesCount: document.getElementById("gamesCount"),
  sortSelect: document.getElementById("sortSelect"),
  gamesList: document.getElementById("gamesList"),
  bannerImg: document.getElementById("bannerImg"),
  inspectTitle: document.getElementById("inspectTitle"),
  inspectMeta: document.getElementById("inspectMeta"),
  btnLaunch: document.getElementById("btnLaunch"),
  launchFeedback: document.getElementById("launchFeedback"),
  detailDir: document.getElementById("detailDir"),
  detailExe: document.getElementById("detailExe"),
  detailLib: document.getElementById("detailLib"),
  logsDrawer: document.getElementById("logsDrawer"),
  logsConsole: document.getElementById("logsConsole"),
  btnClearLogs: document.getElementById("btnClearLogs"),
  btnCopyLogs: document.getElementById("btnCopyLogs"),
  btnOpenFile: document.getElementById("btnOpenFile"),
  btnCloseLogs: document.getElementById("btnCloseLogs"),
  settingsModal: document.getElementById("settingsModal"),
  settingStartup: document.getElementById("settingStartup"),
  settingLimiter: document.getElementById("settingLimiter"),
  settingTray: document.getElementById("settingTray"),
  btnSaveSettings: document.getElementById("btnSaveSettings"),
  savedIndicator: document.getElementById("savedIndicator")
};

// ==========================================
// Initialization & PyWebView Bridge Binding
// ==========================================
window.addEventListener("pywebviewready", () => {
  initApp();
});

// Fallback for direct browser testing
if (window.pywebview) {
  initApp();
}

async function initApp() {
  bindEvents();

  // Load Settings
  try {
    const s = await window.pywebview.api.get_settings();
    if (s) {
      state.settings = s;
      el.settingStartup.checked = !!s.run_at_startup;
      el.settingLimiter.checked = s.start_with_limiter !== false;
      el.settingTray.checked = s.close_to_tray !== false;
    }
  } catch (e) {
    console.warn("Could not fetch settings:", e);
  }

  // Load Initial Games
  await refreshGames();

  // Start Background Telemetry & Log Pollers
  startTelemetryLoop();
  startLogLoop();
}

function bindEvents() {
  // Search
  el.searchInput.addEventListener("input", (e) => {
    state.searchQuery = e.target.value.trim().toLowerCase();
    el.clearSearchBtn.style.display = state.searchQuery ? "block" : "none";
    applyFilterAndSort();
  });

  el.clearSearchBtn.addEventListener("click", () => {
    el.searchInput.value = "";
    state.searchQuery = "";
    el.clearSearchBtn.style.display = "none";
    applyFilterAndSort();
    el.searchInput.focus();
  });

  // Sort
  el.sortSelect.addEventListener("change", (e) => {
    state.sortMode = e.target.value;
    applyFilterAndSort();
  });

  // Limiter Switch
  el.limiterToggle.addEventListener("change", (e) => {
    handleLimiterToggle(e.target.checked);
  });

  // Launch Button
  el.btnLaunch.addEventListener("click", () => {
    if (state.selectedGame) {
      launchGame(state.selectedGame.app_id);
    }
  });

  // Settings Modal
  el.btnSettings.addEventListener("click", openSettings);
  el.btnSaveSettings.addEventListener("click", closeSettings);
  el.settingsModal.addEventListener("click", (e) => {
    if (e.target === el.settingsModal) closeSettings();
  });

  el.settingStartup.addEventListener("change", onSettingChanged);
  el.settingLimiter.addEventListener("change", onSettingChanged);
  el.settingTray.addEventListener("change", onSettingChanged);

  // Logs Drawer
  el.btnToggleLogs.addEventListener("click", toggleLogsDrawer);
  el.btnCloseLogs.addEventListener("click", toggleLogsDrawer);
  el.btnClearLogs.addEventListener("click", clearLogs);
  el.btnCopyLogs.addEventListener("click", copyLogs);
  el.btnOpenFile.addEventListener("click", openLogFile);

  // Global Keyboard Shortcuts
  window.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.key.toLowerCase() === "f") {
      e.preventDefault();
      el.searchInput.focus();
      el.searchInput.select();
    } else if (e.key === "Escape") {
      if (el.settingsModal.style.display !== "none") {
        closeSettings();
      } else if (state.searchQuery) {
        el.clearSearchBtn.click();
      }
    } else if (e.key === "Enter" && document.activeElement !== el.searchInput) {
      if (state.selectedGame) {
        launchGame(state.selectedGame.app_id);
      }
    } else if (e.key === "ArrowDown" || e.key === "ArrowUp") {
      handleArrowNavigation(e);
    }
  });
}

// ==========================================
// Games Discovery & Rendering
// ==========================================
async function refreshGames() {
  try {
    const games = await window.pywebview.api.get_games();
    state.games = games || [];
    applyFilterAndSort();

    if (state.filteredGames.length > 0 && !state.selectedGame) {
      selectGame(state.filteredGames[0]);
    }
  } catch (err) {
    console.error("Error refreshing games:", err);
  }
}

function applyFilterAndSort() {
  let list = [...state.games];

  if (state.searchQuery) {
    list = list.filter(
      (g) =>
        g.name.toLowerCase().includes(state.searchQuery) ||
        g.app_id.includes(state.searchQuery)
    );
  }

  if (state.sortMode === "Recent") {
    list.sort((a, b) => (b.last_played || 0) - (a.last_played || 0));
  } else if (state.sortMode === "Name") {
    list.sort((a, b) => a.name.localeCompare(b.name));
  } else if (state.sortMode === "Size") {
    list.sort((a, b) => (b.raw_size || 0) - (a.raw_size || 0));
  }

  state.filteredGames = list;
  el.gamesCount.textContent = `${list.length} Games`;
  renderGamesList();
}

function renderGamesList() {
  el.gamesList.innerHTML = "";

  state.filteredGames.forEach((game) => {
    const isSelected = state.selectedGame && state.selectedGame.app_id === game.app_id;
    const row = document.createElement("div");
    row.className = `game-row ${isSelected ? "selected" : ""}`;
    row.dataset.appid = game.app_id;

    // Square Steam game icon (28x28)
    const icon = document.createElement("img");
    icon.className = "game-icon";
    icon.src = game.icon_url || `/cache/icons/${game.app_id}.png`;
    icon.onerror = () => {
      icon.onerror = () => {
        icon.style.opacity = "0.3";
        icon.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='28' height='28' fill='%239ca3af' viewBox='0 0 16 16'><path d='M8 0a8 8 0 1 0 0 16A8 8 0 0 0 8 0zm0 3a2 2 0 1 1 0 4 2 2 0 0 1 0-4zm3 8.5a.5.5 0 0 1-.5.5h-5a.5.5 0 0 1 0-1h5a.5.5 0 0 1 .5.5z'/></svg>";
      };
      icon.src = `https://shared.fastly.steamstatic.com/store_item_assets/steam/apps/${game.app_id}/logo.png`;
    };

    const title = document.createElement("span");
    title.className = "game-name";
    title.textContent = game.name;

    const size = document.createElement("span");
    size.className = "game-size";
    size.textContent = game.size_gb > 0 ? `${game.size_gb} GB` : "< 100 MB";

    row.appendChild(icon);
    row.appendChild(title);
    row.appendChild(size);

    row.addEventListener("click", () => {
      selectGame(game);
    });

    el.gamesList.appendChild(row);
  });
}

function selectGame(game) {
  state.selectedGame = game;

  // Highlight selected row in DOM
  const rows = el.gamesList.querySelectorAll(".game-row");
  rows.forEach((r) => {
    if (r.dataset.appid === game.app_id) {
      r.classList.add("selected");
      r.scrollIntoView({ block: "nearest", behavior: "smooth" });
    } else {
      r.classList.remove("selected");
    }
  });

  // High-resolution official Steam hero banner
  el.bannerImg.src = game.banner_url || `/cache/banners/${game.app_id}.jpg`;
  el.bannerImg.onerror = () => {
    el.bannerImg.onerror = () => {
      el.bannerImg.src = "data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='1600' height='220' fill='%2313151b'><rect width='100%' height='100%'/></svg>";
    };
    el.bannerImg.src = `https://cdn.akamai.steamstatic.com/steam/apps/${game.app_id}/library_hero.jpg`;
  };

  // Title & Metadata
  el.inspectTitle.textContent = game.name;

  let lastPlayedStr = "Never";
  if (game.last_played && game.last_played > 0) {
    const d = new Date(game.last_played * 1000);
    lastPlayedStr = d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" });
  }

  el.inspectMeta.textContent = `AppID: ${game.app_id}   •   Size: ${game.size_gb} GB   •   Last Played: ${lastPlayedStr}`;
  el.launchFeedback.textContent = "";

  // Installation Details
  el.detailDir.textContent = game.full_path || "--";
  el.detailExe.textContent = game.primary_exe || (game.known_exes && game.known_exes[0]) || "steam.exe";
  el.detailLib.textContent = game.library_path || "--";
}

function handleArrowNavigation(e) {
  if (state.filteredGames.length === 0) return;
  const currentIndex = state.filteredGames.findIndex(
    (g) => state.selectedGame && g.app_id === state.selectedGame.app_id
  );

  let nextIndex = currentIndex;
  if (e.key === "ArrowDown") {
    e.preventDefault();
    nextIndex = Math.min(currentIndex + 1, state.filteredGames.length - 1);
  } else if (e.key === "ArrowUp") {
    e.preventDefault();
    nextIndex = Math.max(currentIndex - 1, 0);
  }

  if (nextIndex !== currentIndex && state.filteredGames[nextIndex]) {
    selectGame(state.filteredGames[nextIndex]);
  }
}

// ==========================================
// Game Launch Pipeline
// ==========================================
async function launchGame(appId) {
  el.btnLaunch.disabled = true;
  el.btnLaunch.style.opacity = "0.6";
  el.launchFeedback.style.color = "var(--status-online)";
  el.launchFeedback.textContent = "Initiating launch pipeline...";

  try {
    const res = await window.pywebview.api.launch_game(appId);
    el.launchFeedback.textContent = res.message || "Launch signal dispatched.";
  } catch (err) {
    el.launchFeedback.style.color = "var(--status-warning)";
    el.launchFeedback.textContent = `Error: ${err}`;
  } finally {
    setTimeout(() => {
      el.btnLaunch.disabled = false;
      el.btnLaunch.style.opacity = "1";
    }, 1500);
  }
}

// ==========================================
// Telemetry & Limiter Switch
let isTelemPolling = false;
function startTelemetryLoop() {
  setInterval(async () => {
    if (isTelemPolling) return;
    isTelemPolling = true;
    try {
      const telem = await window.pywebview.api.get_telemetry();
      if (!telem) return;

      // Update RAM and CPU counters
      el.telemRam.textContent = telem.helper_ram_mb !== undefined ? telem.helper_ram_mb.toFixed(1) : "--";
      el.telemCpu.textContent = telem.helper_cpu_pct !== undefined ? telem.helper_cpu_pct.toFixed(1) : "--";

      // Keep badge in sync if not in user interaction transition
      if (!state.limiterBusy) {
        el.limiterToggle.checked = !!telem.limiter_active;
      }
    } catch (e) {
      // Background poll failure ignore
    } finally {
      isTelemPolling = false;
    }
  }, 1200);
}

async function handleLimiterToggle(targetState) {
  if (state.limiterBusy) return;
  state.limiterBusy = true;
  el.limiterToggle.disabled = true;



  try {
    const res = await window.pywebview.api.set_limiter(targetState);
    el.limiterToggle.checked = !!res.active;
  } catch (err) {
    console.error("Stifler toggle failed:", err);
  } finally {
    state.limiterBusy = false;
    el.limiterToggle.disabled = false;
  }
}

// ==========================================
// Diagnostic Logs
// ==========================================
let lastLogCount = 0;
let isLogPolling = false;

function startLogLoop() {
  setInterval(async () => {
    if (!state.logsVisible || isLogPolling) return;
    isLogPolling = true;
    try {
      const logs = await window.pywebview.api.get_logs();
      if (logs && logs.length !== lastLogCount) {
        lastLogCount = logs.length;
        renderLogs(logs);
      }
    } catch (e) {
    } finally {
      isLogPolling = false;
    }
  }, 1500);
}

function renderLogs(logs) {
  el.logsConsole.innerHTML = "";
  logs.forEach((line) => {
    const div = document.createElement("div");
    let level = "INFO";
    if (line.includes("[SUCCESS]")) level = "SUCCESS";
    else if (line.includes("[WARN]")) level = "WARN";
    else if (line.includes("[ERROR]")) level = "ERROR";

    div.className = `log-line ${level}`;
    div.textContent = line;
    el.logsConsole.appendChild(div);
  });
  el.logsConsole.scrollTop = el.logsConsole.scrollHeight;
}

function toggleLogsDrawer() {
  state.logsVisible = !state.logsVisible;
  if (state.logsVisible) {
    el.logsDrawer.classList.remove("collapsed");
    el.btnToggleLogs.classList.add("active");
    // Trigger fresh logs fetch immediately
    window.pywebview.api.get_logs().then((logs) => {
      if (logs) renderLogs(logs);
    });
  } else {
    el.logsDrawer.classList.add("collapsed");
    el.btnToggleLogs.classList.remove("active");
  }
}

async function clearLogs() {
  try {
    await window.pywebview.api.clear_logs();
    el.logsConsole.innerHTML = "";
    lastLogCount = 0;
  } catch (e) {}
}

async function copyLogs() {
  try {
    const text = el.logsConsole.textContent || "";
    await navigator.clipboard.writeText(text);
    const orig = el.btnCopyLogs.textContent;
    el.btnCopyLogs.textContent = "Copied!";
    setTimeout(() => (el.btnCopyLogs.textContent = orig), 1500);
  } catch (e) {}
}

async function openLogFile() {
  try {
    await window.pywebview.api.open_log_file();
  } catch (e) {}
}

// ==========================================
// Settings Modal
// ==========================================
function openSettings() {
  el.settingsModal.style.display = "flex";
  el.savedIndicator.textContent = "";
}

function closeSettings() {
  el.settingsModal.style.display = "none";
}

async function onSettingChanged() {
  const updated = {
    run_at_startup: el.settingStartup.checked,
    start_with_limiter: el.settingLimiter.checked,
    close_to_tray: el.settingTray.checked
  };
  state.settings = updated;

  try {
    await window.pywebview.api.save_settings(updated);
    el.savedIndicator.textContent = "✓ Saved";
    setTimeout(() => {
      el.savedIndicator.textContent = "";
    }, 1600);
  } catch (e) {
    console.error("Save settings error:", e);
  }
}
