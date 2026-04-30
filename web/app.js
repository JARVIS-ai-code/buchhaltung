const state = {
  data: null,
  page: "start",
  selectedAccountId: null,
  analysisFilterAccount: null,
  updateAsset: null,
  updateTaskId: "",
  updatePollTimer: null,
  updateLastStatus: "",
  lastUpdateCheckAt: 0,
  announcedUpdateTag: "",
  lastReminderSignature: "",
  lastReminderDay: "",
  lastReminderShownAt: 0,
  toastTimer: null
};

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function todayText() {
  const d = new Date();
  return `${String(d.getDate()).padStart(2, "0")}-${String(d.getMonth() + 1).padStart(2, "0")}-${d.getFullYear()}`;
}

function defaultMonthDate() {
  const month = state.data?.visible_month || "";
  const [year, monthNum] = month.split("-");
  if (year && monthNum) return `01-${monthNum}-${year}`;
  return todayText();
}

function showToast(message) {
  const toast = $("#toast");
  toast.textContent = message;
  toast.hidden = false;
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => {
    toast.hidden = true;
  }, 3600);
}

function formatBytes(value) {
  const bytes = Math.max(0, Number(value || 0));
  if (bytes < 1024) return `${bytes.toFixed(0)} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`;
}

function formatSpeed(value) {
  const speed = Math.max(0, Number(value || 0));
  return `${formatBytes(speed)}/s`;
}

function updatePhaseLabel(task) {
  const phase = String(task?.phase || "");
  if (phase === "queued") return "Update wird vorbereitet…";
  if (phase === "download") return "Download läuft…";
  if (phase === "install") return "Installation wird gestartet…";
  if (phase === "completed") return "Update abgeschlossen.";
  if (phase === "failed") return "Update fehlgeschlagen.";
  return "Update läuft…";
}

function setUpdateProgressModal(task) {
  const status = $("#update-progress-status");
  const progress = $("#update-progress-bar");
  const percent = $("#update-progress-percent");
  const bytes = $("#update-progress-bytes");
  const speed = $("#update-progress-speed");
  const restartButton = $("#update-restart-button");

  const downloaded = Math.max(0, Number(task?.downloaded_bytes || 0));
  const total = Math.max(0, Number(task?.total_bytes || 0));
  const computedPercent = total > 0 ? Math.min(100, (downloaded * 100) / total) : 0;

  status.textContent = task?.error || task?.message || updatePhaseLabel(task);
  if (total > 0) {
    progress.max = total;
    progress.value = downloaded;
    percent.textContent = `${computedPercent.toFixed(1)} %`;
    bytes.textContent = `${formatBytes(downloaded)} / ${formatBytes(total)}`;
  } else {
    progress.max = 1;
    progress.removeAttribute("value");
    percent.textContent = "—";
    bytes.textContent = `${formatBytes(downloaded)} / unbekannt`;
  }
  speed.textContent = formatSpeed(task?.speed_bps || 0);
  restartButton.hidden = !Boolean(task?.restart_required && task?.status === "completed");
}

function stopUpdatePolling() {
  if (state.updatePollTimer) {
    clearInterval(state.updatePollTimer);
    state.updatePollTimer = null;
  }
}

async function pollUpdateProgress() {
  if (!state.updateTaskId) return;
  const payload = await api(`/api/update/progress?task_id=${encodeURIComponent(state.updateTaskId)}`);
  const task = payload.update?.task || {};
  setUpdateProgressModal(task);

  if (task.status === "running") return;
  stopUpdatePolling();

  if (task.status === "completed") {
    if (task.restart_required) {
      showToast("Update fertig. Bitte Programm neu starten.");
    } else {
      showToast("Update gestartet.");
    }
  } else if (task.status === "failed") {
    showToast(task.error || "Update fehlgeschlagen.");
  }
}

async function startUpdateInstall(asset) {
  const payload = await api("/api/update/install", { method: "POST", body: { asset } });
  const task = payload.update?.task;
  if (!task?.id) throw new Error("Update-Task konnte nicht gestartet werden.");
  state.updateTaskId = task.id;
  state.updateLastStatus = "";
  const modal = $("#update-progress-modal");
  if (modal && !modal.open) modal.showModal();
  setUpdateProgressModal(task);
  stopUpdatePolling();
  await pollUpdateProgress();
  state.updatePollTimer = setInterval(() => {
    pollUpdateProgress().catch((error) => {
      stopUpdatePolling();
      showToast(error.message || "Update-Status konnte nicht gelesen werden.");
    });
  }, 800);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    method: options.method || "GET",
    headers: { "Content-Type": "application/json" },
    body: options.body ? JSON.stringify(options.body) : undefined
  });
  const payload = await response.json();
  if (!payload.ok) throw new Error(payload.error || "Aktion fehlgeschlagen.");
  if (payload.state) {
    state.data = payload.state;
    state.selectedAccountId = payload.state.selected_account_id;
    state.analysisFilterAccount = payload.state.analysis_filter_account;
    render();
  }
  return payload;
}

async function loadState() {
  const params = new URLSearchParams();
  if (state.selectedAccountId) params.set("selected_account_id", state.selectedAccountId);
  if (state.analysisFilterAccount) params.set("analysis_filter_account", state.analysisFilterAccount);
  const payload = await api(`/api/state?${params.toString()}`);
  state.data = payload.state;
  state.selectedAccountId = payload.state.selected_account_id;
  state.analysisFilterAccount = payload.state.analysis_filter_account;
  render();
}

function postContext(body = {}) {
  return {
    ...body,
    selected_account_id: state.selectedAccountId,
    analysis_filter_account: state.analysisFilterAccount
  };
}

function bindForm(root, selector, handler) {
  const form = $(selector, root);
  if (!form) return;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const formData = new FormData(form);
    const payload = Object.fromEntries(formData.entries());
    try {
      await handler(payload, form);
    } catch (error) {
      showToast(error.message);
    }
  });
}

function field(label, name, value = "", attrs = "") {
  return `
    <label class="field">
      <span>${label}</span>
      <input name="${name}" value="${escapeHtml(value)}" ${attrs}>
    </label>
  `;
}

function selectField(label, name, options, selected = "") {
  const normalized = options.map((option) => {
    const value = typeof option === "string" ? option : option.value;
    const text = typeof option === "string" ? option : option.label;
    const isSelected = String(value) === String(selected) || Boolean(option.selected);
    return { value, text, isSelected };
  });
  const selectedOption = normalized.find((option) => option.isSelected) || normalized[0] || { value: "", text: "" };
  const listId = `combo-${name}-${Math.random().toString(36).slice(2)}`;
  return `
    <label class="field">
      <span>${label}</span>
      <div class="custom-select" data-combo>
        <input type="hidden" name="${name}" value="${escapeHtml(selectedOption.value)}">
        <button class="select-trigger" type="button" aria-haspopup="listbox" aria-expanded="false" aria-controls="${listId}">
          <span>${escapeHtml(selectedOption.text)}</span>
          <strong>⌄</strong>
        </button>
        <div class="select-menu" id="${listId}" role="listbox" hidden>
          ${normalized.map((option) => `
            <button type="button" role="option" data-value="${escapeHtml(option.value)}" data-label="${escapeHtml(option.text)}" ${String(option.value) === String(selectedOption.value) ? "aria-selected=\"true\"" : ""}>
              ${escapeHtml(option.text)}
            </button>
          `).join("")}
        </div>
      </div>
    </label>
  `;
}

function card(title, subtitle, content, span = 6) {
  return `
    <article class="card span-${span}">
      <div class="card-head">
        <div>
          <h2>${escapeHtml(title)}</h2>
          <div class="subtitle">${escapeHtml(subtitle)}</div>
        </div>
      </div>
      ${content}
    </article>
  `;
}

function moneyClass(value) {
  return Number(value || 0) >= 0 ? "positive" : "negative";
}

function accountOptions(selected = "") {
  return (state.data.accounts || []).map((account) => ({
    value: account.id,
    label: account.name,
    selected: account.id === selected
  }));
}

function render() {
  if (!state.data) return;
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === state.page);
  });
  document.querySelectorAll(".page").forEach((page) => page.classList.remove("active"));
  $(`#page-${state.page}`).classList.add("active");
  renderReminder();
  renderStart();
  renderAccounts();
  renderAnalysis();
  renderSettings();
}

function renderReminder() {
  const reminder = $("#reminder");
  const overdue = state.data.overdue || [];
  if (!overdue.length) {
    reminder.hidden = true;
    reminder.innerHTML = "";
    return;
  }
  reminder.hidden = false;
  const preview = overdue.slice(0, 4).map((item) => (
    `<div>${escapeHtml(item.account)} | ${escapeHtml(item.description)} | ${escapeHtml(item.amount_label)} | fällig ${escapeHtml(item.due_date)}</div>`
  )).join("");
  reminder.innerHTML = `
    <strong>Offene Zahlungen sind überfällig</strong>
    ${preview}
    ${overdue.length > 4 ? `<div>+ ${overdue.length - 4} weitere überfällige Zahlung(en)</div>` : ""}
  `;
}

function overdueSignature(overdue) {
  return overdue.map((item) => String(item.key || "")).sort().join("|");
}

function todayIsoKey() {
  return new Date().toISOString().slice(0, 10);
}

function renderReminderModalList(overdue) {
  const list = $("#reminder-modal-list");
  if (!list) return;
  const maxRows = 10;
  const rows = overdue.slice(0, maxRows).map((item) => `
    <div class="row">
      <div>
        <div class="row-title">${escapeHtml(item.account)} | ${escapeHtml(item.description)}</div>
        <div class="row-sub">fällig ${escapeHtml(item.due_date)} | ${escapeHtml(item.month_label || "")}</div>
      </div>
      <strong>${escapeHtml(item.amount_label)}</strong>
    </div>
  `).join("");
  const extra = overdue.length > maxRows ? `<div class="empty">+ ${overdue.length - maxRows} weitere überfällige Zahlung(en)</div>` : "";
  list.innerHTML = rows + extra;
}

function showReminderModal(overdue) {
  const modal = $("#reminder-modal");
  if (!modal) return;
  renderReminderModalList(overdue);
  if (!modal.open) {
    modal.showModal();
  }
}

function maybeShowReminderPopup(force = false) {
  if (!state.data) return;
  const overdue = state.data.overdue || [];
  if (!overdue.length) {
    state.lastReminderSignature = "";
    return;
  }

  const signature = overdueSignature(overdue);
  const todayKey = todayIsoKey();
  const dayChanged = state.lastReminderDay !== "" && state.lastReminderDay !== todayKey;
  const isNewSignature = signature !== state.lastReminderSignature;
  const intervalMinutes = Math.max(1, Number(state.data.settings?.reminder_interval_minutes || 15));
  const cooldownMs = intervalMinutes * 60 * 1000;
  const cooldownPassed = (Date.now() - state.lastReminderShownAt) >= cooldownMs;

  const shouldShow = force || isNewSignature || dayChanged || cooldownPassed;
  if (!shouldShow) return;

  showReminderModal(overdue);
  state.lastReminderSignature = signature;
  state.lastReminderDay = todayKey;
  state.lastReminderShownAt = Date.now();
}

function renderStart() {
  const d = state.data;
  const accounts = d.accounts || [];
  const html = `
    <div class="grid">
      ${card("Einnahmen erfassen", "Lohn, Nebentätigkeit, Spesen oder eigene Quellen", `
        <form id="income-form" class="form-grid">
          ${selectField("Typ", "type", d.income_sources || [])}
          ${selectField("Konto", "account_id", accountOptions())}
          ${field("Beschreibung", "description", "", "required")}
          ${field("Betrag", "amount", "", "inputmode=\"decimal\" required")}
          ${field("Datum", "date", defaultMonthDate(), "required")}
          <div class="actions"><button class="solid" type="submit">Einnahme speichern</button></div>
        </form>
        ${accounts.length ? "" : `<p class="empty">Lege zuerst ein Konto in den Einstellungen an.</p>`}
      `, 6)}
      ${card("Cashflow", "Aktueller Monat", `
        <div class="kpi">
          <div class="label">${escapeHtml(d.visible_month_label)}</div>
          <div class="value ${moneyClass(d.summary.remaining)}">${escapeHtml(d.summary.cashflow_label)}</div>
        </div>
        <div class="list" style="margin-top:14px">
          ${(d.open_amounts || []).map((item) => `
            <div class="row">
              <div>
                <div class="row-title">${escapeHtml(item.account)}</div>
                <div class="row-sub">Offen aus Dauerzahlungen</div>
              </div>
              <strong>${escapeHtml(item.amount_label)}</strong>
            </div>
          `).join("") || `<p class="empty">Keine Konten vorhanden.</p>`}
        </div>
      `, 6)}
      ${card("Letzte Einnahmen", "Bearbeiten oder löschen", `
        <div class="list">
          ${(d.recent_incomes || []).map((item) => transactionRow(item, "income")).join("") || `<p class="empty">Keine Einnahmen im ausgewählten Monat.</p>`}
        </div>
      `, 6)}
      ${card("Nächste Zahlungen je Konto", "Fällige und kommende Dauerzahlungen", `
        <div class="list">
          ${(d.next_due || []).map((item) => `
            <div class="row">
              <div>
                <div class="row-title">${escapeHtml(item.account)} | ${escapeHtml(item.description)}</div>
                <div class="row-sub">Fällig ${escapeHtml(item.due)}</div>
              </div>
              <strong>${escapeHtml(item.amount_label)}</strong>
            </div>
          `).join("") || `<p class="empty">Keine Dauerzahlungen angelegt.</p>`}
        </div>
      `, 6)}
    </div>
  `;
  $("#page-start").innerHTML = html;
  bindForm($("#page-start"), "#income-form", async (payload, form) => {
    await api("/api/incomes", { method: "POST", body: postContext(payload) });
    form.reset();
    showToast("Einnahme gespeichert.");
  });
}

function transactionRow(item, kind) {
  const account = state.data.account_names?.[item.account_id] || item.account || "-";
  const label = kind === "income" ? item.type : item.description;
  return `
    <div class="transaction-row">
      <div>
        <div class="row-title">${escapeHtml(item.date)}</div>
        <div class="row-sub">${escapeHtml(account)}</div>
      </div>
      <div>
        <div class="row-title">${escapeHtml(label)}</div>
        <div class="row-sub">${escapeHtml(item.description || "")}</div>
      </div>
      <strong>${escapeHtml(item.amount_label || "")}</strong>
      <button class="icon-button" title="Bearbeiten" data-action="edit-${kind}" data-id="${escapeHtml(item.id)}">✎</button>
      <button class="icon-button danger-button" title="Löschen" data-action="delete-${kind}" data-id="${escapeHtml(item.id)}">×</button>
    </div>
  `;
}

function renderAccounts() {
  const d = state.data;
  const selected = state.selectedAccountId;
  $("#page-accounts").innerHTML = `
    <div class="grid">
      ${card("Kontofokus", "Dauerzahlungen nach Konto", `
        <div class="chip-row">
          ${(d.accounts || []).map((account) => `
            <button class="chip ${account.id === selected ? "active" : ""}" data-action="select-account" data-id="${escapeHtml(account.id)}">${escapeHtml(account.name)}</button>
          `).join("") || `<p class="empty">Keine Konten vorhanden.</p>`}
        </div>
        <div class="actions">
          <button class="solid" data-action="new-recurring">Dauerzahlung hinzufügen</button>
          <button class="ghost" data-action="new-installment">Abzahlung</button>
        </div>
      `, 12)}
      ${card("Aktive Dauerzahlungen", "Status für den Anzeigemonat", `
        <div class="list">
          ${(d.selected_recurring || []).map((rec) => recurringRow(rec)).join("") || `<p class="empty">Keine Dauerzahlungen im ausgewählten Konto.</p>`}
        </div>
      `, 12)}
    </div>
  `;
}

function recurringRow(rec) {
  const checked = (rec.checked_months || []).includes(state.data.visible_month);
  const amount = formatRecAmount(rec);
  const freq = rec.kind === "installment" ? "Abzahlung" : ({ monthly: "Monatlich", quarterly: "Quartal", yearly: "Jährlich" }[rec.frequency] || "Monatlich");
  return `
    <div class="recurring-row">
      <label class="check-pill">
        <input type="checkbox" ${checked ? "checked" : ""} data-action="toggle-recurring" data-id="${escapeHtml(rec.id)}">
        <span>${checked ? "Erledigt" : "Offen"}</span>
      </label>
      <div>
        <div class="row-title">${escapeHtml(rec.description)}</div>
        <div class="row-sub">${freq} am ${String(rec.day).padStart(2, "0")}. | Start ${escapeHtml(rec.start_date || "-")}${rec.end_date ? ` | Ende ${escapeHtml(rec.end_date)}` : ""}</div>
      </div>
      <strong>${escapeHtml(amount)}</strong>
      <button class="icon-button" title="Bearbeiten" data-action="edit-recurring" data-id="${escapeHtml(rec.id)}">✎</button>
      <button class="icon-button danger-button" title="Löschen" data-action="delete-recurring" data-id="${escapeHtml(rec.id)}">×</button>
    </div>
  `;
}

function formatRecAmount(rec) {
  const currency = state.data.settings.currency || "EUR";
  const amount = Number(rec.amount || 0);
  return amount.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ` ${currency}`;
}

function renderAnalysis() {
  const d = state.data;
  $("#page-analysis").innerHTML = `
    <div class="grid">
      ${card("Ausgabe erfassen", "Kategorie oder Beschreibung für den Monat", `
        <form id="expense-form" class="form-grid">
          ${selectField("Konto", "account_id", accountOptions())}
          ${field("Kategorie / Beschreibung", "description", "", "required")}
          ${field("Betrag", "amount", "", "inputmode=\"decimal\" required")}
          ${field("Datum", "date", defaultMonthDate(), "required")}
          <div class="actions"><button class="solid" type="submit">Ausgabe speichern</button></div>
        </form>
      `, 12)}
      ${card("Analyse", d.visible_month_label, `
        <div class="grid">
          <div class="kpi span-4"><div class="label">Einnahmen</div><div class="value positive">${escapeHtml(d.summary.income_label)}</div></div>
          <div class="kpi span-4"><div class="label">Ausgaben</div><div class="value negative">${escapeHtml(d.summary.expense_label)}</div></div>
          <div class="kpi span-4"><div class="label">Übrig</div><div class="value ${moneyClass(d.summary.remaining)}">${escapeHtml(d.summary.remaining_label)}</div></div>
        </div>
        <div class="actions">
          <button class="chip ${!state.analysisFilterAccount ? "active" : ""}" data-action="filter-account" data-id="">Alle</button>
          ${(d.accounts || []).map((account) => `<button class="chip ${state.analysisFilterAccount === account.id ? "active" : ""}" data-action="filter-account" data-id="${escapeHtml(account.id)}">${escapeHtml(account.name)}</button>`).join("")}
        </div>
      `, 12)}
      ${card("Kategorien", "Summen nach Ausgabe-Kategorie", `
        <div class="list">
          ${(d.categories || []).map((item) => `
            <div class="row">
              <div class="row-title">${escapeHtml(item.name)}</div>
              <strong>${escapeHtml(item.amount_label)}</strong>
            </div>
          `).join("") || `<p class="empty">Keine Ausgaben im ausgewählten Filter.</p>`}
        </div>
      `, 5)}
      ${card("Ausgaben", "Bearbeiten oder löschen", `
        <div class="list">
          ${(d.expenses || []).map((item) => transactionRow({ ...item, amount_label: formatAmount(item.amount) }, "expense")).join("") || `<p class="empty">Keine Ausgaben im ausgewählten Monat.</p>`}
        </div>
      `, 7)}
    </div>
  `;
  bindForm($("#page-analysis"), "#expense-form", async (payload, form) => {
    await api("/api/expenses", { method: "POST", body: postContext(payload) });
    form.reset();
    showToast("Ausgabe gespeichert.");
  });
}

function formatAmount(value) {
  const currency = state.data.settings.currency || "EUR";
  return Number(value || 0).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ` ${currency}`;
}

function renderSettings() {
  const d = state.data;
  $("#page-settings").innerHTML = `
    <div class="grid">
      ${card("Grundeinstellungen", "Währung, Autostart und Updates", `
        <form id="settings-form" class="form-grid">
          ${field("Währung", "currency", d.settings.currency || "EUR")}
          ${field("Erinnerung alle Minuten", "reminder_interval_minutes", d.settings.reminder_interval_minutes || 15, "type=\"number\" min=\"1\" max=\"240\"")}
          ${field("Update-Prüfung alle Stunden", "update_check_interval_hours", d.settings.update_check_interval_hours || 6, "type=\"number\" min=\"1\" max=\"168\"")}
          <label class="check-pill"><input type="checkbox" name="autostart_enabled" ${d.settings.autostart_enabled ? "checked" : ""}>Autostart aktivieren</label>
          <label class="check-pill"><input type="checkbox" name="autostart_open_window" ${d.settings.autostart_open_window ? "checked" : ""}>Beim Systemstart Fenster öffnen</label>
          <label class="check-pill"><input type="checkbox" name="auto_update_check" ${d.settings.auto_update_check ? "checked" : ""}>Periodisch auf Updates prüfen</label>
          <div class="actions">
            <button class="solid" type="submit">Einstellungen speichern</button>
            <button class="ghost" type="button" data-action="check-update">Jetzt auf Updates prüfen</button>
          </div>
        </form>
        <p class="muted">Aktuelle Version: ${escapeHtml(d.version)} | DB: ${escapeHtml(d.db_path)}</p>
      `, 7)}
      ${card("Monatssteuerung", "Anzeigemonat und geschlossene Monate", `
        <form id="month-form" class="form-grid single">
          ${field("Anzeigemonat", "month", d.visible_month_label, "placeholder=\"MM-JJJJ\"")}
          <div class="actions">
            <button class="solid" type="submit">Monat übernehmen</button>
            <button class="ghost" type="button" data-action="close-month">Monat schließen</button>
          </div>
        </form>
        <div class="list" style="margin-top:12px">
          ${(d.closed_months || []).map((item) => `
            <div class="row">
              <span>${escapeHtml(item.label)}</span>
              <button class="ghost" data-action="reopen-month" data-month="${escapeHtml(item.month)}">Öffnen</button>
            </div>
          `).join("") || `<p class="empty">Keine geschlossenen Monate.</p>`}
        </div>
      `, 5)}
      ${card("Konten verwalten", "Konten und verknüpfte Einträge", `
        <form id="account-form" class="form-grid single">
          ${field("Neues Konto", "name", "", "required")}
          <div class="actions"><button class="solid" type="submit">Anlegen</button></div>
        </form>
        <div class="list" style="margin-top:12px">
          ${(d.accounts || []).map((account) => `
            <div class="account-row">
              <strong>${escapeHtml(account.name)}</strong>
              <button class="danger-button" data-action="delete-account" data-id="${escapeHtml(account.id)}">Löschen</button>
            </div>
          `).join("") || `<p class="empty">Keine Konten vorhanden.</p>`}
        </div>
      `, 6)}
      ${card("Einnahmequellen", "Quellen hinzufügen, umbenennen oder entfernen", `
        <form id="source-form" class="form-grid single">
          ${field("Neue Einnahmequelle", "name", "", "required")}
          <div class="actions"><button class="solid" type="submit">Hinzufügen</button></div>
        </form>
        <div class="list" style="margin-top:12px">
          ${(d.income_sources || []).map((source) => `
            <div class="source-row">
              <input value="${escapeHtml(source)}" data-source="${escapeHtml(source)}">
              <button class="ghost" data-action="rename-source" data-source="${escapeHtml(source)}">Speichern</button>
              <button class="danger-button" data-action="delete-source" data-source="${escapeHtml(source)}">Löschen</button>
            </div>
          `).join("")}
        </div>
      `, 6)}
    </div>
  `;
  bindForm($("#page-settings"), "#settings-form", async (payload, form) => {
    payload.autostart_enabled = Boolean(form.elements.autostart_enabled.checked);
    payload.autostart_open_window = Boolean(form.elements.autostart_open_window.checked);
    payload.auto_update_check = Boolean(form.elements.auto_update_check.checked);
    await api("/api/settings", { method: "POST", body: postContext(payload) });
    showToast("Einstellungen gespeichert.");
  });
  bindForm($("#page-settings"), "#month-form", async (payload) => {
    await api("/api/settings/visible-month", { method: "POST", body: postContext(payload) });
    showToast("Anzeigemonat gesetzt.");
  });
  bindForm($("#page-settings"), "#account-form", async (payload, form) => {
    await api("/api/accounts", { method: "POST", body: postContext(payload) });
    form.reset();
    showToast("Konto angelegt.");
  });
  bindForm($("#page-settings"), "#source-form", async (payload, form) => {
    await api("/api/income-sources", { method: "POST", body: postContext(payload) });
    form.reset();
    showToast("Einnahmequelle hinzugefügt.");
  });
}

function openModal(title, html, onSubmit) {
  const modal = $("#modal");
  modal.innerHTML = `
    <form method="dialog">
      <h2>${escapeHtml(title)}</h2>
      ${html}
      <div class="actions">
        <button class="ghost" value="cancel" type="button" data-modal-close>Abbrechen</button>
        <button class="solid" value="default" type="submit">Speichern</button>
      </div>
    </form>
  `;
  $("[data-modal-close]", modal).addEventListener("click", () => modal.close());
  $("form", modal).addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await onSubmit(payload);
      modal.close();
    } catch (error) {
      showToast(error.message);
    }
  });
  modal.showModal();
}

function recurringModal(rec = null, kind = "standard") {
  const isInstallment = kind === "installment" || rec?.kind === "installment";
  const html = `
    ${selectField("Konto", "account_id", accountOptions(rec?.account_id || state.selectedAccountId || ""))}
    ${field("Beschreibung", "description", rec?.description || "", "required")}
    <div class="two-col">
      ${field("Betrag", "amount", rec?.amount || "", "inputmode=\"decimal\" required")}
      ${field("Tag im Monat", "day", rec?.day || "1", "type=\"number\" min=\"1\" max=\"28\" required")}
    </div>
    ${isInstallment ? "" : selectField("Intervall", "frequency", state.data.frequency_options || [], rec?.frequency || "monthly")}
    <div class="two-col">
      ${field("Startdatum", "start_date", rec?.start_date || defaultMonthDate(), "required")}
      ${isInstallment ? field("Enddatum", "end_date", rec?.end_date || defaultMonthDate(), "required") : ""}
    </div>
    ${isInstallment ? field("Abschlagssumme letzte Zahlung", "final_amount", rec?.final_amount || "", "inputmode=\"decimal\"") : ""}
  `;
  openModal(isInstallment ? "Abzahlung" : "Dauerzahlung", html, async (payload) => {
    payload.kind = isInstallment ? "installment" : "standard";
    payload.frequency = isInstallment ? "monthly" : payload.frequency;
    if (rec) {
      await api(`/api/recurring/${rec.id}`, { method: "PUT", body: postContext(payload) });
      showToast("Dauerzahlung aktualisiert.");
    } else {
      await api("/api/recurring", { method: "POST", body: postContext(payload) });
      showToast(isInstallment ? "Abzahlung gespeichert." : "Dauerzahlung gespeichert.");
    }
  });
}

function transactionModal(item, kind) {
  const isIncome = kind === "income";
  const html = `
    ${isIncome ? selectField("Typ", "type", state.data.income_sources || [], item.type) : ""}
    ${selectField("Konto", "account_id", accountOptions(item.account_id))}
    ${field(isIncome ? "Beschreibung" : "Kategorie / Beschreibung", "description", item.description || "", "required")}
    <div class="two-col">
      ${field("Betrag", "amount", item.amount || "", "inputmode=\"decimal\" required")}
      ${field("Datum", "date", item.date || defaultMonthDate(), "required")}
    </div>
  `;
  openModal(isIncome ? "Einnahme bearbeiten" : "Ausgabe bearbeiten", html, async (payload) => {
    await api(`/api/${isIncome ? "incomes" : "expenses"}/${item.id}`, { method: "PUT", body: postContext(payload) });
    showToast(isIncome ? "Einnahme aktualisiert." : "Ausgabe aktualisiert.");
  });
}

document.addEventListener("click", async (event) => {
  const comboOption = event.target.closest(".select-menu button");
  if (comboOption) {
    const combo = comboOption.closest("[data-combo]");
    const input = $("input[type='hidden']", combo);
    const trigger = $(".select-trigger", combo);
    const menu = $(".select-menu", combo);
    input.value = comboOption.dataset.value || "";
    $(".select-trigger span", combo).textContent = comboOption.dataset.label || "";
    $$(".select-menu button", combo).forEach((button) => button.removeAttribute("aria-selected"));
    comboOption.setAttribute("aria-selected", "true");
    menu.hidden = true;
    trigger.setAttribute("aria-expanded", "false");
    return;
  }

  const comboTrigger = event.target.closest(".select-trigger");
  if (comboTrigger) {
    const combo = comboTrigger.closest("[data-combo]");
    const menu = $(".select-menu", combo);
    const shouldOpen = menu.hidden;
    $$(".select-menu").forEach((item) => {
      item.hidden = true;
      const itemTrigger = item.closest("[data-combo]")?.querySelector(".select-trigger");
      itemTrigger?.setAttribute("aria-expanded", "false");
    });
    menu.hidden = !shouldOpen;
    comboTrigger.setAttribute("aria-expanded", shouldOpen ? "true" : "false");
    return;
  }

  if (!event.target.closest("[data-combo]")) {
    $$(".select-menu").forEach((item) => {
      item.hidden = true;
      const itemTrigger = item.closest("[data-combo]")?.querySelector(".select-trigger");
      itemTrigger?.setAttribute("aria-expanded", "false");
    });
  }

  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  const id = target.dataset.id;
  try {
    if (action === "select-account") {
      state.selectedAccountId = id;
      await loadState();
    } else if (action === "new-recurring") {
      recurringModal(null, "standard");
    } else if (action === "new-installment") {
      recurringModal(null, "installment");
    } else if (action === "edit-recurring") {
      const rec = state.data.recurring.find((item) => item.id === id);
      if (rec) recurringModal(rec, rec.kind);
    } else if (action === "delete-recurring") {
      if (confirm("Diesen Eintrag wirklich löschen?")) {
        await api(`/api/recurring/${id}`, { method: "DELETE", body: postContext() });
        showToast("Dauerzahlung gelöscht.");
      }
    } else if (action === "edit-income" || action === "edit-expense") {
      const isIncome = action === "edit-income";
      const item = (isIncome ? state.data.incomes : state.data.expenses).find((entry) => entry.id === id);
      if (item) transactionModal(item, isIncome ? "income" : "expense");
    } else if (action === "delete-income" || action === "delete-expense") {
      const isIncome = action === "delete-income";
      if (confirm(isIncome ? "Diese Einnahme löschen?" : "Diese Ausgabe löschen?")) {
        await api(`/api/${isIncome ? "incomes" : "expenses"}/${id}`, { method: "DELETE", body: postContext() });
        showToast(isIncome ? "Einnahme gelöscht." : "Ausgabe gelöscht.");
      }
    } else if (action === "filter-account") {
      state.analysisFilterAccount = id || null;
      await loadState();
    } else if (action === "delete-account") {
      if (confirm("Konto inklusive Einträge löschen?")) {
        await api(`/api/accounts/${id}`, { method: "DELETE", body: postContext() });
        showToast("Konto gelöscht.");
      }
    } else if (action === "close-month") {
      await api("/api/settings/close-month", { method: "POST", body: postContext() });
      showToast("Monat geschlossen.");
    } else if (action === "reopen-month") {
      await api("/api/settings/reopen-month", { method: "POST", body: postContext({ month: target.dataset.month }) });
      showToast("Monat geöffnet.");
    } else if (action === "rename-source") {
      const row = target.closest(".source-row");
      const input = $("input", row);
      await api("/api/income-sources", {
        method: "PUT",
        body: postContext({ old_name: target.dataset.source, new_name: input.value })
      });
      showToast("Einnahmequelle aktualisiert.");
    } else if (action === "delete-source") {
      await api("/api/income-sources", {
        method: "DELETE",
        body: postContext({ name: target.dataset.source })
      });
      showToast("Einnahmequelle gelöscht.");
    } else if (action === "check-update") {
      const payload = await api("/api/update/check", { method: "POST", body: {} });
      state.updateAsset = payload.update.asset;
      if (!payload.update.is_newer) {
        showToast(`Du nutzt bereits die aktuelle Version (${payload.update.current}).`);
      } else if (!payload.update.asset) {
        const names = (payload.update.assets || []).map((asset) => asset.name).filter(Boolean).slice(0, 4);
        const hint = names.length ? ` Verfügbar: ${names.join(", ")}` : "";
        showToast(`Update gefunden, aber kein passendes Paket für dieses System.${hint}`);
      } else if (confirm(`Update ${payload.update.latest} installieren?`)) {
        await startUpdateInstall(payload.update.asset);
      }
    }
  } catch (error) {
    showToast(error.message);
  }
});

document.addEventListener("change", async (event) => {
  const target = event.target;
  if (target.dataset?.action !== "toggle-recurring") return;
  try {
    await api(`/api/recurring/${target.dataset.id}/checked`, {
      method: "POST",
      body: postContext({ month: state.data.visible_month, checked: target.checked })
    });
    showToast(target.checked ? "Zahlung erledigt." : "Zahlung wieder offen.");
  } catch (error) {
    target.checked = !target.checked;
    showToast(error.message);
  }
});

document.querySelectorAll(".nav-button").forEach((button) => {
  button.addEventListener("click", () => {
    state.page = button.dataset.page;
    render();
  });
});

loadState()
  .then(() => {
    maybeShowReminderPopup(true);
  })
  .catch((error) => showToast(error.message));

async function periodicTick() {
  try {
    await loadState();
    maybeShowReminderPopup(false);
    const settings = state.data?.settings || {};
    if (!settings.auto_update_check) return;
    const intervalMs = Math.max(1, Number(settings.update_check_interval_hours || 6)) * 3600 * 1000;
    if (Date.now() - state.lastUpdateCheckAt < intervalMs) return;
    state.lastUpdateCheckAt = Date.now();
    const payload = await api("/api/update/check", { method: "POST", body: {} });
    const update = payload.update;
    if (!update?.is_newer || !update.asset || state.announcedUpdateTag === update.latest) return;
    state.announcedUpdateTag = update.latest;
    if (confirm(`Update ${update.latest} installieren?`)) {
      await startUpdateInstall(update.asset);
    }
  } catch (error) {
    console.warn(error);
  }
}

setInterval(periodicTick, 60 * 1000);
setTimeout(periodicTick, 30 * 1000);

const reminderOpenAccountsBtn = $("#reminder-open-accounts");
if (reminderOpenAccountsBtn) {
  reminderOpenAccountsBtn.addEventListener("click", () => {
    state.page = "accounts";
    render();
    const modal = $("#reminder-modal");
    if (modal?.open) {
      modal.close();
    }
  });
}

const updateProgressCloseBtn = $("#update-progress-close");
if (updateProgressCloseBtn) {
  updateProgressCloseBtn.addEventListener("click", () => {
    const modal = $("#update-progress-modal");
    if (modal?.open) modal.close();
  });
}

const updateRestartBtn = $("#update-restart-button");
if (updateRestartBtn) {
  updateRestartBtn.addEventListener("click", async () => {
    try {
      await api("/api/app/restart", { method: "POST", body: {} });
      showToast("Programm wird neu gestartet…");
    } catch (error) {
      showToast(error.message);
    }
  });
}
