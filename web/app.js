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

const REMINDER_SHOWN_DATE_KEY = "jarvis-buchhaltung-reminder-shown-date";
const REMINDER_SNOOZED_DATE_KEY = "jarvis-buchhaltung-reminder-snoozed-date";

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

function getDropdownOverlay() {
  return $("#dropdown-overlay");
}

function closeSelectMenu() {
  const overlay = getDropdownOverlay();
  if (overlay) {
    overlay.hidden = true;
    overlay.innerHTML = "";
    delete overlay._activeCombo;
  }
  $$(".select-trigger[aria-expanded='true']").forEach((trigger) => {
    trigger.setAttribute("aria-expanded", "false");
  });
}

function setSelectValue(combo, value, label) {
  if (!combo) return;
  const input = $("input[type='hidden']", combo);
  const trigger = $(".select-trigger", combo);
  const triggerLabel = $(".select-trigger span", combo);
  if (input) input.value = value ?? "";
  if (triggerLabel) triggerLabel.textContent = label ?? "";
  if (trigger) trigger.setAttribute("aria-expanded", "false");
}

function positionSelectMenu(combo, menu) {
  const trigger = $(".select-trigger", combo);
  if (!trigger) return;
  const rect = trigger.getBoundingClientRect();
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const minWidth = Math.max(220, Math.round(rect.width));
  const menuWidth = Math.min(360, Math.max(minWidth, Math.round(rect.width)));
  const maxLeft = Math.max(12, viewportWidth - menuWidth - 12);
  const left = Math.min(Math.max(12, rect.left), maxLeft);
  const availableBelow = Math.max(140, Math.floor(viewportHeight - rect.bottom - 12));
  const availableAbove = Math.max(140, Math.floor(rect.top - 12));
  const openAbove = availableBelow < 180 && availableAbove > availableBelow;

  menu.style.left = `${left}px`;
  menu.style.width = `${menuWidth}px`;
  menu.style.maxHeight = `${Math.max(140, openAbove ? availableAbove : availableBelow)}px`;
  menu.style.top = openAbove ? "auto" : `${Math.round(rect.bottom + 6)}px`;
  menu.style.bottom = openAbove ? `${Math.round(viewportHeight - rect.top + 6)}px` : "auto";
  menu.dataset.placement = openAbove ? "above" : "below";
}

function openSelectMenu(combo) {
  const overlay = getDropdownOverlay();
  if (!overlay || !combo) return;
  const trigger = $(".select-trigger", combo);
  const selectedValue = $("input[type='hidden']", combo)?.value || "";
  let options = [];
  try {
    options = JSON.parse(combo.dataset.selectOptions || "[]");
  } catch {
    options = [];
  }
  const normalized = Array.isArray(options) ? options : [];
  const menu = document.createElement("div");
  menu.className = "dropdown-menu";
  menu.setAttribute("role", "listbox");
  menu.tabIndex = -1;
  menu.innerHTML = normalized.map((option) => `
    <button type="button" role="option" data-select-option data-value="${escapeHtml(option.value)}" data-label="${escapeHtml(option.text)}" ${String(option.value) === String(selectedValue) ? "aria-selected=\"true\"" : ""}>
      ${escapeHtml(option.text)}
    </button>
  `).join("");

  overlay.innerHTML = "";
  overlay.hidden = false;
  overlay.append(menu);
  overlay._activeCombo = combo;
  positionSelectMenu(combo, menu);
  trigger?.setAttribute("aria-expanded", "true");
}

function toggleSelectMenu(combo) {
  const overlay = getDropdownOverlay();
  if (!overlay) return;
  const trigger = $(".select-trigger", combo);
  const isOpen = Boolean(trigger && trigger.getAttribute("aria-expanded") === "true");
  closeSelectMenu();
  if (!isOpen) openSelectMenu(combo);
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

function monthFromTextDate(value) {
  const parts = String(value || "").split("-");
  if (parts.length !== 3) return "";
  return `${parts[2]}-${parts[1]}`;
}

function monthLabel(month) {
  const parts = String(month || "").split("-");
  if (parts.length !== 2) return String(month || "");
  return `${parts[1]}-${parts[0]}`;
}

function collectVisibleMonths(data) {
  const months = new Set();
  if (data?.visible_month) months.add(data.visible_month);
  (data?.closed_months || []).forEach((item) => {
    if (item.month) months.add(item.month);
  });
  (data?.incomes || []).forEach((item) => {
    const month = monthFromTextDate(item.date);
    if (month) months.add(month);
  });
  (data?.expenses || []).forEach((item) => {
    const month = monthFromTextDate(item.date);
    if (month) months.add(month);
  });
  return [...months].sort().reverse();
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
  return `
    <label class="field">
      <span>${label}</span>
      <div class="custom-select" data-combo data-select-options="${escapeHtml(JSON.stringify(normalized))}">
        <input type="hidden" name="${name}" value="${escapeHtml(selectedOption.value)}">
        <button class="select-trigger" type="button" aria-haspopup="listbox" aria-expanded="false">
          <span>${escapeHtml(selectedOption.text)}</span>
          <strong>⌄</strong>
        </button>
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
  closeSelectMenu();
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === state.page);
  });
  document.querySelectorAll(".page").forEach((page) => page.classList.remove("active"));
  $(`#page-${state.page}`).classList.add("active");
  renderReminder();
  renderStart();
  renderAccounts();
  renderPayments();
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
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function setDailyReminderShown() {
  localStorage.setItem(REMINDER_SHOWN_DATE_KEY, todayIsoKey());
}

function setDailyReminderSnoozed() {
  const todayKey = todayIsoKey();
  localStorage.setItem(REMINDER_SHOWN_DATE_KEY, todayKey);
  localStorage.setItem(REMINDER_SNOOZED_DATE_KEY, todayKey);
}

function renderReminderModalList(overdue) {
  const list = $("#reminder-modal-list");
  if (!list) return;
  const maxRows = 10;
  const rows = overdue.slice(0, maxRows).map((item) => `
    <div class="reminder-row">
      <div>
        <div class="row-title">${escapeHtml(item.account)} | ${escapeHtml(item.description)}</div>
        <div class="row-sub">fällig ${escapeHtml(item.due_date)} | ${escapeHtml(item.month_label || "")}</div>
      </div>
      <strong>${escapeHtml(item.amount_label)}</strong>
      <button class="ghost" data-action="open-overdue-account" data-id="${escapeHtml(item.account_id || "")}">Konto öffnen</button>
    </div>
  `).join("");
  const extra = overdue.length > maxRows ? `<div class="empty">+ ${overdue.length - maxRows} weitere überfällige Zahlung(en)</div>` : "";
  list.innerHTML = rows + extra;
}

function showReminderModal(overdue) {
  const modal = $("#reminder-modal");
  if (!modal) return;
  renderReminderModalList(overdue);
  setDailyReminderShown();
  if (!modal.open) {
    modal.showModal();
  }
}

function maybeShowReminderPopup(force = false) {
  if (!state.data) return;
  const overdue = state.data.overdue || [];
  const todayKey = todayIsoKey();
  if (!overdue.length) {
    state.lastReminderSignature = "";
    state.lastReminderDay = todayKey;
    return;
  }

  const shownToday = localStorage.getItem(REMINDER_SHOWN_DATE_KEY) === todayKey;
  const snoozedToday = localStorage.getItem(REMINDER_SNOOZED_DATE_KEY) === todayKey;
  const dayChanged = state.lastReminderDay !== todayKey;
  const shouldShow = (force || dayChanged) && !shownToday && !snoozedToday;
  state.lastReminderDay = todayKey;
  if (!shouldShow) return;

  showReminderModal(overdue);
  state.lastReminderSignature = overdueSignature(overdue);
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
      ${card("Nächste Zahlungen je Konto", "Noch offene Zahlungen diesen Monat", `
        <div class="list">
          ${(d.next_due || []).map((item) => `
            <div class="row">
              <div>
                <div class="row-title">${escapeHtml(item.account)} | ${escapeHtml(item.description)}</div>
                <div class="row-sub">Fällig ${escapeHtml(item.due)}</div>
              </div>
              <strong>${escapeHtml(item.amount_label)}</strong>
            </div>
          `).join("") || `<p class="empty">Keine ausstehenden Zahlungen diesen Monat.</p>`}
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
  const visibleMonth = d.visible_month;
  const selectedRecurring = [...(d.selected_recurring || [])].sort((a, b) => {
    const aChecked = (a.checked_months || []).includes(visibleMonth) ? 1 : 0;
    const bChecked = (b.checked_months || []).includes(visibleMonth) ? 1 : 0;
    if (aChecked !== bChecked) return aChecked - bChecked;
    return Number(a.day || 0) - Number(b.day || 0) || String(a.description || "").localeCompare(String(b.description || ""), "de");
  });
  const openRecurring = selectedRecurring.filter((rec) => !(rec.checked_months || []).includes(visibleMonth));
  const paidRecurring = selectedRecurring.filter((rec) => (rec.checked_months || []).includes(visibleMonth));
  $("#page-accounts").innerHTML = `
    <div class="grid">
      ${card("Kontofokus", "Dauerzahlungen nach Konto", `
        <div class="chip-row">
          ${(d.accounts || []).map((account) => `
            <button class="chip ${account.id === selected ? "active" : ""}" data-action="select-account" data-id="${escapeHtml(account.id)}">${escapeHtml(account.name)}</button>
          `).join("") || `<p class="empty">Keine Konten vorhanden.</p>`}
        </div>
        <div class="actions">
          <button class="ghost" data-action="open-payments">Alle Zahlungen</button>
        </div>
      `, 12)}
      ${card("Aktive Dauerzahlungen", "Status für den Anzeigemonat", `
        ${selectedRecurring.length ? `
          <div class="payment-section">
            <div class="section-label">Offen</div>
            <div class="list">
              ${openRecurring.map((rec) => recurringRow(rec)).join("") || `<p class="empty">Keine offenen Zahlungen.</p>`}
            </div>
          </div>
          <div class="payment-section paid">
            <div class="section-label">Erledigt</div>
            <div class="list">
              ${paidRecurring.map((rec) => recurringRow(rec)).join("") || `<p class="empty">Keine erledigten Zahlungen.</p>`}
            </div>
          </div>
        ` : `<p class="empty">Keine Dauerzahlungen im ausgewählten Konto.</p>`}
      `, 12)}
    </div>
  `;
}

function recurringRow(rec) {
  const checked = (rec.checked_months || []).includes(state.data.visible_month);
  const amount = rec.current_amount_label || formatRecAmount(rec);
  const freq = rec.kind === "installment" ? "Abzahlung" : ({ monthly: "Monatlich", quarterly: "Quartal", yearly: "Jährlich" }[rec.frequency] || "Monatlich");
  const currentEditId = rec.current_expense_id || "";
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
      <button class="icon-button" title="Diesen Monat bearbeiten" data-action="edit-current-payment" data-id="${escapeHtml(currentEditId)}" ${currentEditId ? "" : "disabled"}>✎</button>
      <button class="icon-button danger-button" title="Nur diesen Monat entfernen" data-action="delete-current-payment" data-id="${escapeHtml(rec.id)}">×</button>
    </div>
  `;
}

function renderPayments() {
  const d = state.data;
  const accounts = d.accounts || [];
  const visibleMonth = d.visible_month || "";
  const recurring = [...(d.recurring || [])].sort((a, b) => (
    Number(a.day || 0) - Number(b.day || 0) || String(a.description || "").localeCompare(String(b.description || ""), "de")
  )).filter((rec) => {
    const endMonth = monthFromTextDate(rec.end_date);
    return !endMonth || endMonth >= visibleMonth;
  });
  $("#page-payments").innerHTML = `
    <div class="grid">
      ${card("Alle Zahlungen", "Globale Dauerzahlungen und Abzahlungen", `
        <div class="actions">
          <button class="solid" data-action="new-recurring">Dauerzahlung hinzufügen</button>
          <button class="ghost" data-action="new-installment">Abzahlung</button>
        </div>
      `, 12)}
      ${accounts.map((account) => {
        const rows = recurring.filter((rec) => rec.account_id === account.id);
        return card(account.name, `${rows.length} globale Zahlung(en)`, `
          <div class="list">
            ${rows.map((rec) => paymentRow(rec)).join("") || `<p class="empty">Keine Zahlungen für dieses Konto.</p>`}
          </div>
        `, 12);
      }).join("") || card("Keine Konten", "Lege zuerst ein Konto in den Einstellungen an.", `<p class="empty">Keine Zahlungen angelegt.</p>`, 12)}
    </div>
  `;
}

function paymentRow(rec) {
  const account = state.data.account_names?.[rec.account_id] || "-";
  const freq = rec.kind === "installment" ? "Abzahlung" : ({ monthly: "Monatlich", quarterly: "Quartal", yearly: "Jährlich" }[rec.frequency] || "Monatlich");
  return `
    <div class="payment-row">
      <div>
        <div class="row-title">${escapeHtml(rec.description)}</div>
        <div class="row-sub">${escapeHtml(account)} | ${freq} am ${String(rec.day).padStart(2, "0")}. | Start ${escapeHtml(rec.start_date || "-")}${rec.end_date ? ` | Ende ${escapeHtml(rec.end_date)}` : ""}</div>
      </div>
      <strong>${escapeHtml(formatRecAmount(rec))}</strong>
      <button class="icon-button" title="Global bearbeiten" data-action="edit-recurring" data-id="${escapeHtml(rec.id)}">✎</button>
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
      `, 12)}
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
  const months = collectVisibleMonths(d);
  const monthOptions = months.map((month) => {
    const closed = (d.closed_months || []).some((item) => item.month === month);
    return {
      value: month,
      label: `${monthLabel(month)}${closed ? " (geschlossen)" : ""}`,
      selected: month === d.visible_month
    };
  });
  $("#page-settings").innerHTML = `
    <div class="grid">
      ${card("Grundeinstellungen", "Währung, Autostart und Updates", `
        <form id="settings-form" class="form-grid">
          ${field("Währung", "currency", d.settings.currency || "EUR")}
          ${field("Update-Prüfung alle Stunden", "update_check_interval_hours", d.settings.update_check_interval_hours || 6, "type=\"number\" min=\"1\" max=\"168\"")}
          <label class="check-pill"><input type="checkbox" name="autostart_enabled" ${d.settings.autostart_enabled ? "checked" : ""}>Autostart aktivieren</label>
          <label class="check-pill"><input type="checkbox" name="autostart_open_window" ${d.settings.autostart_open_window ? "checked" : ""}>Beim Systemstart Fenster öffnen</label>
          <label class="check-pill"><input type="checkbox" name="auto_update_check" ${d.settings.auto_update_check ? "checked" : ""}>Periodisch auf Updates prüfen</label>
          <div class="actions">
            <button class="solid" type="submit">Einstellungen speichern</button>
            <button class="ghost" type="button" data-action="check-update">Jetzt auf Updates prüfen</button>
          </div>
        </form>
        <div class="actions">
          <button class="ghost" type="button" data-action="open-db-folder">DB-Ordner öffnen</button>
        </div>
        <p class="muted">Aktuelle Version: ${escapeHtml(d.version)}</p>
      `, 7)}
      ${card("Monatssteuerung", "Anzeigemonat und geschlossene Monate", `
        <div class="section-label">Anzeigemonat</div>
        <form id="month-form" class="form-grid single">
          ${selectField("Anzeigemonat", "month", monthOptions, d.visible_month)}
          <div class="actions">
            <button class="solid" type="submit">Anzeigemonat übernehmen</button>
            <button class="ghost" type="button" data-action="close-month">Monat schließen</button>
          </div>
        </form>
        <form id="manual-month-form" class="form-grid single" style="margin-top:12px">
          ${field("Neuen Monat beginnen", "month", "", "placeholder=\"MM-JJJJ\"")}
          <div class="actions"><button class="ghost" type="submit">Monat manuell starten</button></div>
        </form>
        <div class="section-label" style="margin-top:16px">Geschlossene Monate</div>
        <div class="list" style="margin-top:8px">
          ${(d.closed_months || []).map((item) => `
            <div class="row month-admin-row">
              <span>${escapeHtml(item.label)}</span>
              <button class="ghost" data-action="reopen-month" data-month="${escapeHtml(item.month)}">Öffnen & auswählen</button>
              <button class="danger-button" data-action="delete-closed-month" data-month="${escapeHtml(item.month)}">Löschen</button>
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
  bindForm($("#page-settings"), "#manual-month-form", async (payload) => {
    await api("/api/settings/visible-month", { method: "POST", body: postContext(payload) });
    showToast("Neuer Monat gestartet.");
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

function chooseGlobalScope(kind) {
  const action = kind === "delete" ? "gelöscht" : "geändert";
  const modal = $("#modal");
  return new Promise((resolve) => {
    modal.innerHTML = `
      <form method="dialog">
        <h2>Zeitpunkt wählen</h2>
        <div class="subtitle">Ab wann soll diese Zahlung ${action} werden?</div>
        <div class="actions">
          <button class="solid" value="current" type="submit">Ab diesem Monat</button>
          <button class="ghost" value="next" type="submit">Ab nächstem Monat</button>
          <button class="ghost" value="cancel" type="submit">Abbrechen</button>
        </div>
      </form>
    `;
    $("form", modal).addEventListener("submit", (event) => {
      event.preventDefault();
      const value = event.submitter?.value || "cancel";
      modal.close();
      resolve(value === "cancel" ? null : value);
    });
    modal.showModal();
  });
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
      payload.effective_scope = await chooseGlobalScope("edit");
      if (!payload.effective_scope) return;
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

function currentPaymentModal(item) {
  const html = `
    ${field("Betrag für diesen Monat", "amount", item.amount || "", "inputmode=\"decimal\" required")}
  `;
  openModal("Zahlung diesen Monat bearbeiten", html, async (payload) => {
    await api(`/api/expenses/${item.id}`, {
      method: "PUT",
      body: postContext({
        account_id: item.account_id,
        description: item.description,
        source: item.source,
        recurring_plan_id: item.recurring_plan_id,
        recurring_month: item.recurring_month,
        amount: payload.amount,
        date: item.date
      })
    });
    showToast("Zahlung für diesen Monat aktualisiert.");
  });
}

async function openReminderAccount(accountId) {
  if (!accountId) return;
  state.selectedAccountId = accountId;
  state.page = "accounts";
  const modal = $("#reminder-modal");
  if (modal?.open) {
    modal.close();
  }
  await loadState();
}

document.addEventListener("click", async (event) => {
  const comboOption = event.target.closest("[data-select-option]");
  if (comboOption) {
    const overlay = getDropdownOverlay();
    const combo = overlay?._activeCombo || null;
    if (combo) {
      setSelectValue(combo, comboOption.dataset.value || "", comboOption.dataset.label || "");
      closeSelectMenu();
    }
    return;
  }

  if (event.target.closest(".dropdown-overlay") && !event.target.closest(".dropdown-menu")) {
    closeSelectMenu();
    return;
  }

  const comboTrigger = event.target.closest(".select-trigger");
  if (comboTrigger) {
    const combo = comboTrigger.closest("[data-combo]");
    toggleSelectMenu(combo);
    return;
  }

  if (!event.target.closest("[data-combo]") && !event.target.closest(".dropdown-overlay")) {
    closeSelectMenu();
  }

  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  const id = target.dataset.id;
  try {
    if (action === "select-account") {
      state.selectedAccountId = id;
      await loadState();
    } else if (action === "open-payments") {
      state.page = "payments";
      render();
    } else if (action === "open-overdue-account") {
      await openReminderAccount(id);
    } else if (action === "new-recurring") {
      recurringModal(null, "standard");
    } else if (action === "new-installment") {
      recurringModal(null, "installment");
    } else if (action === "edit-recurring") {
      const rec = state.data.recurring.find((item) => item.id === id);
      if (rec) recurringModal(rec, rec.kind);
    } else if (action === "edit-current-payment") {
      const item = state.data.expenses.find((entry) => entry.id === id);
      if (item) currentPaymentModal(item);
    } else if (action === "delete-current-payment") {
      if (confirm("Diese Zahlung nur im aktuell ausgewählten Monat entfernen?")) {
        await api(`/api/recurring/${id}/skip`, {
          method: "POST",
          body: postContext({ month: state.data.visible_month })
        });
        showToast("Zahlung für diesen Monat entfernt.");
      }
    } else if (action === "delete-recurring") {
      if (confirm("Diese Zahlung global löschen? Vergangene Monate bleiben unverändert.")) {
        const effective_scope = await chooseGlobalScope("delete");
        if (!effective_scope) return;
        await api(`/api/recurring/${id}`, { method: "DELETE", body: postContext({ effective_scope }) });
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
      await api("/api/settings/visible-month", { method: "POST", body: postContext({ month: target.dataset.month }) });
      showToast("Monat geöffnet.");
    } else if (action === "delete-closed-month") {
      if (confirm("Diesen geschlossenen Monat wirklich löschen?")) {
        await api("/api/settings/delete-closed-month", { method: "POST", body: postContext({ month: target.dataset.month }) });
        showToast("Geschlossener Monat gelöscht.");
      }
    } else if (action === "select-month") {
      await api("/api/settings/visible-month", { method: "POST", body: postContext({ month: target.dataset.month }) });
      showToast("Anzeigemonat gesetzt.");
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
    } else if (action === "open-db-folder") {
      await api("/api/db/open-folder", { method: "POST", body: {} });
      showToast("DB-Ordner wurde geöffnet.");
    }
  } catch (error) {
    showToast(error.message);
  }
});

window.addEventListener("resize", closeSelectMenu);
document.addEventListener("scroll", (event) => {
  if (event.target instanceof Element && event.target.closest(".dropdown-menu")) return;
  closeSelectMenu();
}, true);

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
  reminderOpenAccountsBtn.addEventListener("click", async () => {
    const first = (state.data?.overdue || [])[0];
    await openReminderAccount(first?.account_id || state.selectedAccountId);
  });
}

const reminderSnoozeBtn = $("#reminder-snooze");
if (reminderSnoozeBtn) {
  reminderSnoozeBtn.addEventListener("click", () => {
    setDailyReminderSnoozed();
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
