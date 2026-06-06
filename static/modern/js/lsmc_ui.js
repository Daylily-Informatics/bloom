(function () {
  const themes = ["original", "lsmc", "dark", "light", "tacky"];
  const storageKey = "lsmc.ui.theme";

  function currentTheme() {
    const stored = window.localStorage.getItem(storageKey);
    return themes.includes(stored) ? stored : "original";
  }

  function applyTheme(theme) {
    const value = themes.includes(theme) ? theme : "original";
    document.documentElement.dataset.theme = value;
    window.localStorage.setItem(storageKey, value);
  }

  async function syncThemeFromBroker(select) {
    const response = await fetch("/api/v1/me/preferences", { credentials: "same-origin" });
    if (!response.ok) return;
    const payload = await response.json();
    const theme = payload && payload.preferences && payload.preferences.theme;
    if (!themes.includes(theme)) return;
    applyTheme(theme);
    if (select) select.value = theme;
  }

  async function persistThemeToBroker(theme) {
    await fetch("/api/v1/me/preferences", {
      method: "PUT",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ theme }),
    });
  }

  function commandForPage() {
    const explicit = document.body.dataset.actionHelpCommand || "";
    if (explicit) return explicit;
    if (location.pathname.startsWith("/search")) return "bloom search --help";
    if (location.pathname.startsWith("/create_object")) return "bloom object create --help";
    if (location.pathname.startsWith("/admin")) return "bloom admin --help";
    if (location.pathname.startsWith("/dag")) return "bloom dag show --help";
    return `No CLI equivalent for bloom ${location.pathname}`;
  }

  function initThemeControl() {
    const wrap = document.createElement("div");
    wrap.className = "lsmc-theme-control";
    const label = document.createElement("label");
    label.textContent = "Theme";
    const select = document.createElement("select");
    for (const theme of themes) {
      const option = document.createElement("option");
      option.value = theme;
      option.textContent = theme;
      select.appendChild(option);
    }
    select.value = currentTheme();
    select.addEventListener("change", () => {
      applyTheme(select.value);
      persistThemeToBroker(select.value).catch(() => {});
    });
    label.appendChild(select);
    wrap.appendChild(label);
    document.body.appendChild(wrap);
    syncThemeFromBroker(select).catch(() => {});
  }

  function initActionHelp() {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "lsmc-action-help-button";
    button.setAttribute("aria-expanded", "false");
    button.textContent = "?";
    const panel = document.createElement("aside");
    panel.className = "lsmc-action-help-panel";
    panel.hidden = true;
    panel.innerHTML = '<strong>Action Help</strong><pre></pre><button type="button">Copy</button>';
    const output = panel.querySelector("pre");
    const copy = panel.querySelector("button");
    function refresh() {
      output.textContent = commandForPage();
    }
    button.addEventListener("click", () => {
      panel.hidden = !panel.hidden;
      button.setAttribute("aria-expanded", String(!panel.hidden));
      refresh();
    });
    copy.addEventListener("click", () => navigator.clipboard?.writeText(output.textContent || ""));
    document.body.append(button, panel);
  }

  applyTheme(currentTheme());
  document.addEventListener("DOMContentLoaded", () => {
    initThemeControl();
    initActionHelp();
  });
})();
