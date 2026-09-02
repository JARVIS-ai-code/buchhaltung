const state = {
  data: null,
  page: "dashboard",
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
  toastTimer: null,
  activeDropdownOverlay: null,
  activeDropdownCombo: null,
  activeDateOverlay: null,
  activeDateControl: null,
  activeDateViewMonth: ""
};

const REMINDER_SHOWN_DATE_KEY = "finanz-cockpit-reminder-shown-date";
const REMINDER_SNOOZED_DATE_KEY = "finanz-cockpit-reminder-snoozed-date";
const WEEKDAY_LABELS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"];
const MONTH_LABELS = ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober", "November", "Dezember"];
const ACCOUNT_COLOR_PRESETS = ["#38a1ff", "#35d59b", "#ffc857", "#ff7ac8", "#7c5cff", "#2ee9d3", "#ff5f7a", "#a3e635"];

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

function accountColor(accountId) {
  return state.data?.account_colors?.[accountId] || "#38a1ff";
}

function accountGlowStyle(accountId) {
  return `style="--account-color: ${escapeHtml(accountColor(accountId))}"`;
}

function recurringFrequencyLabel(frequency, kind = "standard") {
  if (kind === "installment") return "Abzahlung";
  return ({
    monthly: "Monatlich",
    quarterly: "Quartal",
    semiannual: "Halbjährlich",
    yearly: "Jährlich"
  })[frequency] || "Monatlich";
}

function normalizeColor(value) {
  const color = String(value || "").trim();
  return /^#[0-9a-fA-F]{6}$/.test(color) ? color.toLowerCase() : "#38a1ff";
}

function colorControl(value, attrs = "", name = "") {
  const color = normalizeColor(value);
  const nameAttr = name ? `name="${escapeHtml(name)}"` : "";
  return `
    <span class="color-control" style="--picker-color: ${escapeHtml(color)}">
      <input type="hidden" data-color-input ${nameAttr} value="${escapeHtml(color)}" ${attrs}>
      <button class="color-control-trigger" type="button" data-action="open-color-picker" aria-label="Farbe auswählen">
        <span class="color-swatch"></span>
        <span class="color-value">${escapeHtml(color.toUpperCase())}</span>
      </button>
    </span>
  `;
}

function colorPickerField(label, name, value, attrs = "") {
  return `
    <div class="field color-picker-field">
      <span>${escapeHtml(label)}</span>
      ${colorControl(value, attrs, name)}
    </div>
  `;
}

function syncColorControl(input) {
  const color = normalizeColor(input.value);
  const control = input.closest(".color-control");
  if (control) {
    control.style.setProperty("--picker-color", color);
    const value = $(".color-value", control);
    if (value) value.textContent = color.toUpperCase();
  }
  const accountRow = input.closest(".account-row");
  if (accountRow && input.dataset.accountColor) {
    accountRow.style.setProperty("--account-color", color);
  }
}

function setColorPickerValue(modal, value) {
  if (!modal || !/^#[0-9a-fA-F]{6}$/.test(String(value || "").trim())) return;
  const color = String(value).trim().toLowerCase();
  const input = $("[data-color-picker-input]", modal);
  const preview = $("[data-color-picker-preview]", modal);
  if (input) input.value = color.toUpperCase();
  if (preview) preview.style.setProperty("--picker-color", color);
  $$('[data-color-choice]', modal).forEach((button) => {
    button.classList.toggle("active", button.dataset.colorChoice?.toLowerCase() === color);
  });
}

function openColorPicker(control) {
  const input = $("[data-color-input]", control);
  if (!input) return;
  const currentColor = normalizeColor(input.value);
  const palette = ACCOUNT_COLOR_PRESETS.map((color) => `
    <button class="color-choice ${color === currentColor ? "active" : ""}" type="button" data-color-choice="${color}" style="--picker-color: ${color}" aria-label="${color.toUpperCase()}"></button>
  `).join("");

  openModal("Kontofarbe", `
    <div class="color-picker-dialog">
      <div class="color-picker-preview" data-color-picker-preview style="--picker-color: ${currentColor}"></div>
      <div class="color-choice-grid">${palette}</div>
      ${field("Hex-Farbwert", "color", currentColor.toUpperCase(), 'data-color-picker-input autocomplete="off" spellcheck="false"')}
    </div>
  `, async (payload) => {
    const color = String(payload.color || "").trim();
    if (!/^#[0-9a-fA-F]{6}$/.test(color)) {
      throw new Error("Bitte einen gültigen Hex-Farbwert eingeben.");
    }
    input.value = color.toLowerCase();
    syncColorControl(input);
    if (input.dataset.accountColor) {
      await api(`/api/accounts/${input.dataset.accountColor}`, { method: "PUT", body: postContext({ color: input.value }) });
      showToast("Kontofarbe aktualisiert.");
    }
  });
}

function parseDateText(value) {
  const raw = String(value || "").trim();
  let match = raw.match(/^(\d{2})-(\d{2})-(\d{4})$/);
  if (match) {
    const day = Number(match[1]);
    const month = Number(match[2]);
    const year = Number(match[3]);
    const candidate = new Date(year, month - 1, day);
    if (
      candidate.getFullYear() === year
      && candidate.getMonth() === month - 1
      && candidate.getDate() === day
    ) {
      return { day, month, year };
    }
    return null;
  }
  match = raw.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!match) return null;
  const year = Number(match[1]);
  const month = Number(match[2]);
  const day = Number(match[3]);
  const candidate = new Date(year, month - 1, day);
  if (
    candidate.getFullYear() === year
    && candidate.getMonth() === month - 1
    && candidate.getDate() === day
  ) {
    return { day, month, year };
  }
  return null;
}

function formatDateParts(parts) {
  if (!parts) return "";
  return `${String(parts.day).padStart(2, "0")}-${String(parts.month).padStart(2, "0")}-${parts.year}`;
}

function normalizeDateText(value, fallback = "") {
  const parsed = parseDateText(value);
  if (parsed) return formatDateParts(parsed);
  return fallback;
}

function monthKeyFromDateParts(parts) {
  if (!parts) return "";
  return `${parts.year}-${String(parts.month).padStart(2, "0")}`;
}

function monthParts(month) {
  const [yearText, monthText] = String(month || "").split("-");
  const year = Number(yearText);
  const monthNum = Number(monthText);
  if (!Number.isInteger(year) || !Number.isInteger(monthNum) || monthNum < 1 || monthNum > 12) return null;
  return { year, month: monthNum };
}

function daysInMonth(year, month) {
  return new Date(year, month, 0).getDate();
}

function weekdayOffset(year, month) {
  return (new Date(year, month - 1, 1).getDay() + 6) % 7;
}

function datePickerField(label, name, value = "", attrs = "") {
  const normalized = normalizeDateText(value, todayText());
  return `
    <div class="field date-picker-field" data-date-picker>
      <span>${escapeHtml(label)}</span>
      <input type="hidden" name="${escapeHtml(name)}" value="${escapeHtml(normalized)}" ${attrs}>
      <button class="date-trigger" type="button" data-date-trigger aria-haspopup="dialog" aria-expanded="false">
        <span class="date-trigger-value">${escapeHtml(normalized)}</span>
        <strong>▦</strong>
      </button>
    </div>
  `;
}

function getCalendarOverlay(control = null) {
  if (control) {
    const dialog = control.closest("dialog");
    if (dialog) {
      let overlay = $(".calendar-overlay[data-calendar-overlay='dialog']", dialog);
      if (!overlay) {
        overlay = document.createElement("div");
        overlay.className = "calendar-overlay";
        overlay.dataset.calendarOverlay = "dialog";
        overlay.hidden = true;
        dialog.appendChild(overlay);
      }
      return overlay;
    }
  }
  return $("#calendar-overlay");
}

function closeDatePicker() {
  const overlay = state.activeDateOverlay || getCalendarOverlay();
  if (overlay) {
    overlay.hidden = true;
    overlay.innerHTML = "";
  }
  const trigger = state.activeDateControl ? $("[data-date-trigger]", state.activeDateControl) : null;
  if (trigger) trigger.setAttribute("aria-expanded", "false");
  state.activeDateOverlay = null;
  state.activeDateControl = null;
  state.activeDateViewMonth = "";
}

function setDatePickerValue(control, value, markDirty = true) {
  if (!control) return;
  const normalized = normalizeDateText(value, todayText());
  const input = $("input[type='hidden']", control);
  const triggerValue = $(".date-trigger-value", control);
  if (input) input.value = normalized;
  if (triggerValue) triggerValue.textContent = normalized;
  if (markDirty) markDraftState(control);
}

function markDraftState(element) {
  const form = element?.closest?.("form");
  if (form) {
    form.dataset.dirty = "true";
    return;
  }
  const editableShell = element?.closest?.(".source-row, .account-row, .date-picker-field, .custom-select");
  if (editableShell) editableShell.dataset.dirty = "true";
}

function clearDraftState(root) {
  root?.querySelectorAll?.("[data-dirty='true']").forEach((item) => {
    delete item.dataset.dirty;
  });
  if (root?.dataset?.dirty) delete root.dataset.dirty;
}

function isEditableElement(element) {
  if (!element || element === document.body) return false;
  if (element.isContentEditable) return true;
  if (!element.matches?.("input, textarea, select")) return false;
  const type = String(element.getAttribute("type") || "").toLowerCase();
  return !["hidden", "checkbox", "radio", "button", "submit"].includes(type);
}

function hasOpenDialog() {
  return $$("dialog").some((dialog) => dialog.open);
}

function hasUnsavedDraft() {
  return Boolean(
    isEditableElement(document.activeElement)
      || hasOpenDialog()
      || state.activeDateControl
      || state.activeDropdownCombo
      || $("[data-dirty='true']")
  );
}

function positionCalendarPanel(control, panel) {
  const trigger = $("[data-date-trigger]", control);
  if (!trigger) return;
  const rect = trigger.getBoundingClientRect();
  const dialog = control.closest("dialog");
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const panelWidth = Math.min(320, Math.max(280, Math.round(rect.width)));
  let left = 12;
  let availableBelow = Math.max(180, Math.floor(viewportHeight - rect.bottom - 12));
  let availableAbove = Math.max(180, Math.floor(rect.top - 12));
  let top = `${Math.round(rect.bottom + 6)}px`;
  let bottom = "auto";
  let position = "fixed";

  if (dialog) {
    const dialogRect = dialog.getBoundingClientRect();
    const maxLeft = Math.max(12, dialogRect.width - panelWidth - 12);
    left = Math.min(Math.max(12, rect.left - dialogRect.left), maxLeft);
    availableBelow = Math.max(180, Math.floor(dialogRect.bottom - rect.bottom - 12));
    availableAbove = Math.max(180, Math.floor(rect.top - dialogRect.top - 12));
    position = "absolute";
    top = `${Math.round(rect.bottom - dialogRect.top + 6)}px`;
  } else {
    const maxLeft = Math.max(12, viewportWidth - panelWidth - 12);
    left = Math.min(Math.max(12, rect.left), maxLeft);
  }

  const openAbove = availableBelow < 260 && availableAbove > availableBelow;
  if (openAbove) {
    top = "auto";
    bottom = dialog
      ? `${Math.round(dialog.getBoundingClientRect().bottom - rect.top + 6)}px`
      : `${Math.round(viewportHeight - rect.top + 6)}px`;
  }

  panel.style.position = position;
  panel.style.left = `${left}px`;
  panel.style.width = `${panelWidth}px`;
  panel.style.maxHeight = `${Math.max(220, openAbove ? availableAbove : availableBelow)}px`;
  panel.style.top = top;
  panel.style.bottom = bottom;
}

function renderDatePickerPanel() {
  const control = state.activeDateControl;
  const overlay = state.activeDateOverlay;
  if (!control || !overlay) return;
  const selectedText = $("input[type='hidden']", control)?.value || todayText();
  const selected = parseDateText(selectedText) || parseDateText(todayText());
  const viewMonth = state.activeDateViewMonth || monthKeyFromDateParts(selected);
  const current = monthParts(viewMonth);
  if (!current) return;
  state.activeDateViewMonth = viewMonth;
  const today = parseDateText(todayText());
  const totalDays = daysInMonth(current.year, current.month);
  const offset = weekdayOffset(current.year, current.month);
  const cells = [];
  for (let index = 0; index < offset; index += 1) {
    cells.push(`<span class="calendar-empty" aria-hidden="true"></span>`);
  }
  for (let day = 1; day <= totalDays; day += 1) {
    const value = formatDateParts({ day, month: current.month, year: current.year });
    const isSelected = selected && selected.day === day && selected.month === current.month && selected.year === current.year;
    const isToday = today && today.day === day && today.month === current.month && today.year === current.year;
    cells.push(`
      <button
        class="calendar-day ${isSelected ? "active" : ""} ${isToday ? "today" : ""}"
        type="button"
        data-calendar-day
        data-value="${escapeHtml(value)}"
        aria-pressed="${isSelected ? "true" : "false"}"
      >
        ${day}
      </button>
    `);
  }

  const panel = document.createElement("div");
  panel.className = "calendar-panel";
  panel.setAttribute("role", "dialog");
  panel.setAttribute("aria-label", "Datum wählen");
  panel.innerHTML = `
    <div class="calendar-header">
      <button class="calendar-nav" type="button" data-calendar-nav="-1" aria-label="Vorheriger Monat">‹</button>
      <strong class="calendar-title">${MONTH_LABELS[current.month - 1]} ${current.year}</strong>
      <button class="calendar-nav" type="button" data-calendar-nav="1" aria-label="Nächster Monat">›</button>
    </div>
    <div class="calendar-weekdays">
      ${WEEKDAY_LABELS.map((label) => `<span>${label}</span>`).join("")}
    </div>
    <div class="calendar-grid">
      ${cells.join("")}
    </div>
    <div class="calendar-footer">
      <button class="ghost" type="button" data-calendar-today>Heute</button>
      <span class="calendar-current-value">${escapeHtml(selectedText)}</span>
    </div>
  `;
  overlay.innerHTML = "";
  overlay.hidden = false;
  overlay.append(panel);
  positionCalendarPanel(control, panel);
  const trigger = $("[data-date-trigger]", control);
  if (trigger) trigger.setAttribute("aria-expanded", "true");
}

function openDatePicker(control) {
  if (!control) return;
  closeSelectMenu();
  closeDatePicker();
  const overlay = getCalendarOverlay(control);
  if (!overlay) return;
  const selectedText = $("input[type='hidden']", control)?.value || todayText();
  state.activeDateOverlay = overlay;
  state.activeDateControl = control;
  state.activeDateViewMonth = monthKeyFromDateParts(parseDateText(selectedText) || parseDateText(todayText()));
  renderDatePickerPanel();
}

function toggleDatePicker(control) {
  const isOpen = Boolean(
    state.activeDateControl === control
      && $("[data-date-trigger]", control)?.getAttribute("aria-expanded") === "true"
  );
  closeDatePicker();
  if (!isOpen) openDatePicker(control);
}

function getDropdownOverlay(combo = null) {
  if (combo) {
    const dialog = combo.closest("dialog");
    if (dialog) {
      let overlay = $(".dropdown-overlay[data-dropdown-overlay='dialog']", dialog);
      if (!overlay) {
        overlay = document.createElement("div");
        overlay.className = "dropdown-overlay";
        overlay.dataset.dropdownOverlay = "dialog";
        dialog.appendChild(overlay);
      }
      return overlay;
    }
  }
  return $("#dropdown-overlay");
}

function closeSelectMenu() {
  const overlay = state.activeDropdownOverlay || getDropdownOverlay();
  if (overlay) {
    overlay.hidden = true;
    overlay.innerHTML = "";
  }
  state.activeDropdownOverlay = null;
  state.activeDropdownCombo = null;
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
  markDraftState(combo);
}

function positionSelectMenu(combo, menu) {
  const trigger = $(".select-trigger", combo);
  if (!trigger) return;
  const rect = trigger.getBoundingClientRect();
  const dialog = combo.closest("dialog");
  const viewportWidth = window.innerWidth;
  const viewportHeight = window.innerHeight;
  const minWidth = Math.max(220, Math.round(rect.width));
  const menuWidth = Math.min(360, Math.max(minWidth, Math.round(rect.width)));
  let left = 12;
  let availableBelow = Math.max(140, Math.floor(viewportHeight - rect.bottom - 12));
  let availableAbove = Math.max(140, Math.floor(rect.top - 12));
  let top = `${Math.round(rect.bottom + 6)}px`;
  let bottom = "auto";
  let position = "fixed";

  if (dialog) {
    const dialogRect = dialog.getBoundingClientRect();
    const maxLeft = Math.max(12, dialogRect.width - menuWidth - 12);
    left = Math.min(Math.max(12, rect.left - dialogRect.left), maxLeft);
    availableBelow = Math.max(140, Math.floor(dialogRect.bottom - rect.bottom - 12));
    availableAbove = Math.max(140, Math.floor(rect.top - dialogRect.top - 12));
    position = "absolute";
    top = `${Math.round(rect.bottom - dialogRect.top + 6)}px`;
  } else {
    const maxLeft = Math.max(12, viewportWidth - menuWidth - 12);
    left = Math.min(Math.max(12, rect.left), maxLeft);
  }

  const openAbove = availableBelow < 180 && availableAbove > availableBelow;
  if (openAbove) {
    top = "auto";
    bottom = dialog
      ? `${Math.round(dialog.getBoundingClientRect().bottom - rect.top + 6)}px`
      : `${Math.round(viewportHeight - rect.top + 6)}px`;
  }

  menu.style.position = position;
  menu.style.left = `${left}px`;
  menu.style.width = `${menuWidth}px`;
  menu.style.maxHeight = `${Math.max(140, openAbove ? availableAbove : availableBelow)}px`;
  menu.style.top = top;
  menu.style.bottom = bottom;
  menu.dataset.placement = openAbove ? "above" : "below";
}

function openSelectMenu(combo) {
  const overlay = getDropdownOverlay(combo);
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
  state.activeDropdownOverlay = overlay;
  state.activeDropdownCombo = combo;
  positionSelectMenu(combo, menu);
  trigger?.setAttribute("aria-expanded", "true");
}

function toggleSelectMenu(combo) {
  const overlay = getDropdownOverlay();
  if (!overlay) return;
  const trigger = $(".select-trigger", combo);
  const isOpen = Boolean(trigger && trigger.getAttribute("aria-expanded") === "true");
  closeDatePicker();
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
  return monthKeyFromDateParts(parseDateText(value)) || "";
}

function monthLabel(month) {
  const parts = String(month || "").split("-");
  if (parts.length !== 2) return String(month || "");
  const year = Number(parts[0]);
  const monthNum = Number(parts[1]);
  if (!Number.isInteger(year) || !Number.isInteger(monthNum) || monthNum < 1 || monthNum > 12) return String(month || "");
  return `${MONTH_LABELS[monthNum - 1]} ${year} (${String(monthNum).padStart(2, "0")}-${year})`;
}

function monthIndex(month) {
  const [yearText, monthText] = String(month || "").split("-");
  const year = Number(yearText);
  const monthNum = Number(monthText);
  if (!Number.isInteger(year) || !Number.isInteger(monthNum) || monthNum < 1 || monthNum > 12) return null;
  return year * 12 + (monthNum - 1);
}

function monthFromIndex(index) {
  const year = Math.floor(index / 12);
  const monthNum = (index % 12) + 1;
  return `${year}-${String(monthNum).padStart(2, "0")}`;
}

function shiftMonth(month, delta) {
  const index = monthIndex(month);
  if (index === null) return "";
  return monthFromIndex(index + delta);
}

function currentMonthKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
}

function collectVisibleMonths(data) {
  const months = new Set();
  if (data?.visible_month) months.add(data.visible_month);
  if (data?.available_months) {
    data.available_months.forEach((item) => {
      if (item.month) months.add(item.month);
    });
  }
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
      const modal = $("#update-progress-modal");
      if (modal?.open) modal.close();
      showToast("Update abgeschlossen. Programm wird neu gestartet.");
      await api("/api/app/restart", { method: "POST", body: {} });
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

function lockedEntryContent(content, setup = null) {
  if (!setup) return content;
  return `
    <div class="entry-setup">
      <div class="entry-setup-content" inert aria-hidden="true">${content}</div>
      <div class="entry-setup-overlay">
        <button class="solid" type="button" data-action="${setup.action}">${setup.label}</button>
      </div>
    </div>
  `;
}

function render() {
  if (!state.data) return;
  closeSelectMenu();
  closeDatePicker();
  const sidebarMonth = $("#sidebar-month");
  if (sidebarMonth) sidebarMonth.textContent = state.data.visible_month_label || "-";
  document.querySelectorAll(".nav-button").forEach((button) => {
    button.classList.toggle("active", button.dataset.page === state.page);
  });
  document.querySelectorAll(".page").forEach((page) => page.classList.remove("active"));
  $(`#page-${state.page}`).classList.add("active");
  renderReminder();
  renderDashboard();
  renderPaymentPlan();
  renderExpenses();
  renderBookings();
  renderAnalysis();
  renderMonthClose();
  renderSettings();
}

function renderReminder() {
  const reminder = $("#reminder");
  const overdue = state.data.overdue || [];
  if (state.page !== "dashboard" || !overdue.length) {
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
  if (state.page !== "dashboard" || !overdue.length) {
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

function renderDashboard() {
  const d = state.data;
  $("#page-dashboard").innerHTML = `
    <div class="page-title">
      <div>
        <h1>Dashboard</h1>
        <p>${escapeHtml(d.visible_month_label)}${d.is_month_closed ? " | abgeschlossen" : ""}</p>
      </div>
      <div class="actions page-actions">
        <button class="solid" data-action="go-bookings">Buchung erfassen</button>
      </div>
    </div>
    <div class="grid">
      ${kpiCard("Einnahmen", d.summary.income_label, "positive", 3)}
      ${kpiCard("Ausgaben", d.summary.expense_label, "negative", 3)}
      ${kpiCard("Übrig", d.summary.remaining_label, moneyClass(d.summary.remaining), 3)}
      ${kpiCard("Offen", d.summary.open_total_label, "warn-text", 3)}
      ${card("Ausgewählter Monat", "Monat, für den du deine Finanzen ansiehst", monthNavigatorContent(d), 12)}
      ${card("Offene Zahlungen", "Noch nicht erledigte Dauerzahlungen", `
        <div class="list compact-list">
          ${(d.open_amounts || []).map((item) => `
            <div class="row clickable-row" role="button" tabindex="0" data-action="open-account-payments" data-id="${escapeHtml(item.account_id)}">
              <div>
                <div class="row-title">${escapeHtml(item.account)}</div>
                <div class="row-sub">Ausgewählter Monat | Konto öffnen</div>
              </div>
              <strong>${escapeHtml(item.amount_label)}</strong>
            </div>
          `).join("") || `<p class="empty">Keine Konten vorhanden.</p>`}
        </div>
      `, 6)}
      ${card("Nächste Fälligkeiten", "Die nächsten offenen Zahlungen", `
        <div class="list compact-list">
          ${(d.next_due || []).map((item) => `
            <div class="row">
              <div>
                <div class="row-title">${escapeHtml(item.account)} | ${escapeHtml(item.description)}</div>
                <div class="row-sub">Fällig ${escapeHtml(item.due)}</div>
              </div>
              <strong>${escapeHtml(item.amount_label)}</strong>
            </div>
          `).join("") || `<p class="empty">Keine offenen Zahlungen in diesem Monat.</p>`}
        </div>
      `, 6)}
      ${card("Überfällig", "Zahlungen aus vergangenen Monaten", `
        <div class="list compact-list">
          ${(d.overdue || []).slice(0, 6).map((item) => `
            <div class="overdue-dashboard-row" ${accountGlowStyle(item.account_id)}>
              <div>
                <div class="row-title">${escapeHtml(item.account)} | ${escapeHtml(item.description)}</div>
                <div class="row-sub">Fällig ${escapeHtml(item.due_date)} | ${escapeHtml(item.month_label || "")}</div>
              </div>
              <strong>${escapeHtml(item.amount_label)}</strong>
              <button class="solid" data-action="mark-overdue-done" data-id="${escapeHtml(item.recurring_id || "")}" data-month="${escapeHtml(item.month || "")}">Erledigt</button>
            </div>
          `).join("") || `<p class="empty">Keine überfälligen Zahlungen.</p>`}
        </div>
      `, 12)}
    </div>
  `;
}

function kpiCard(label, value, valueClass, span = 3) {
  return card(label, "Aktueller Monat", `
    <div class="kpi">
      <div class="value ${escapeHtml(valueClass)}">${escapeHtml(value)}</div>
    </div>
  `, span);
}

function monthNavigatorContent(d) {
  const months = collectVisibleMonths(d);
  const visibleMonth = d.visible_month;
  const previousMonth = shiftMonth(visibleMonth, -1);
  const nextMonth = shiftMonth(visibleMonth, 1);
  const todayMonth = currentMonthKey();
  const knownMonthValues = new Set(months);
  const nextExists = knownMonthValues.has(nextMonth);
  const nextIsFuture = monthIndex(nextMonth) !== null && monthIndex(nextMonth) > monthIndex(todayMonth);
  const nextButtonLabel = nextExists && !nextIsFuture ? `Weiter zu ${monthLabel(nextMonth)}` : "Nächster Monat";
  const previousMonths = months.filter((month) => {
    const monthPos = monthIndex(month);
    const visiblePos = monthIndex(visibleMonth);
    return monthPos !== null && visiblePos !== null && monthPos < visiblePos;
  });
  return `
    <div class="month-navigator">
      <button class="ghost" data-action="change-month" data-month="${escapeHtml(previousMonth)}">Zurück zu ${escapeHtml(monthLabel(previousMonth))}</button>
      <div class="month-current">
        <div>Ausgewählter Monat</div>
        <strong>${escapeHtml(d.visible_month_label)}</strong>
      </div>
      <button class="solid" data-action="change-month" data-month="${escapeHtml(nextMonth)}">${escapeHtml(nextButtonLabel)}</button>
    </div>
    <div class="month-history">
      ${previousMonths.length ? previousMonths.map((month) => `
        <button class="chip" data-action="change-month" data-month="${escapeHtml(month)}">${escapeHtml(monthLabel(month))}</button>
      `).join("") : `<p class="empty">Keine vorherigen Monate vorhanden.</p>`}
    </div>
  `;
}

function renderBookings() {
  const d = state.data;
  const recurring = recurringManagementRows();
  const incomeSources = d.income_sources || [];
  const accounts = d.accounts || [];
  const incomeForm = `
    <form id="income-form" class="form-grid">
      ${selectField("Typ", "type", incomeSources)}
      ${selectField("Konto", "account_id", accountOptions())}
      ${field("Beschreibung", "description", "", "required")}
      ${field("Betrag", "amount", "", "inputmode=\"decimal\" required")}
      ${datePickerField("Datum", "date", defaultMonthDate())}
      <div class="actions"><button class="solid" type="submit">Einnahme speichern</button></div>
    </form>
  `;
  const expenseForm = `
    <form id="expense-form" class="form-grid">
      ${selectField("Konto", "account_id", accountOptions())}
      ${field("Kategorie / Beschreibung", "description", "", "required")}
      ${field("Betrag", "amount", "", "inputmode=\"decimal\" required")}
      ${datePickerField("Datum", "date", defaultMonthDate())}
      <div class="actions"><button class="solid" type="submit">Ausgabe speichern</button></div>
    </form>
  `;
  const accountSetup = { action: "open-account-settings", label: "Jetzt Konto hinterlegen" };
  const incomeSetup = !accounts.length
    ? accountSetup
    : !incomeSources.length
      ? { action: "open-income-source-settings", label: "Jetzt Einnahmequelle hinterlegen" }
      : null;
  $("#page-bookings").innerHTML = `
    <div class="page-title">
      <div>
        <h1>Buchungen</h1>
        <p>Einnahmen, Ausgaben und wiederkehrende Zahlungen</p>
      </div>
    </div>
    <div class="grid">
      ${card("Einnahme erfassen", "Lohn, Spesen oder eigene Quelle", lockedEntryContent(incomeForm, incomeSetup), 6)}
      ${card("Ausgabe erfassen", "Kategorie oder Beschreibung", lockedEntryContent(expenseForm, accounts.length ? null : accountSetup), 6)}
      ${card("Wiederkehrende Zahlungen", `${recurring.length} aktive Zahlung(en)`, `
        <div class="actions">
          <button class="solid" data-action="new-recurring">Dauerzahlung hinzufügen</button>
          <button class="ghost" data-action="new-installment">Abzahlung</button>
        </div>
        <div class="list" style="margin-top:12px">
          ${recurring.map(recurringManagementRow).join("") || `<p class="empty">Keine wiederkehrenden Zahlungen angelegt.</p>`}
        </div>
      `, 12)}
    </div>
  `;
  bindForm($("#page-bookings"), "#income-form", async (payload, form) => {
    await api("/api/incomes", { method: "POST", body: postContext(payload) });
    form.reset();
    showToast("Einnahme gespeichert.");
  });
  bindForm($("#page-bookings"), "#expense-form", async (payload, form) => {
    await api("/api/expenses", { method: "POST", body: postContext(payload) });
    form.reset();
    showToast("Ausgabe gespeichert.");
  });
}

function renderPaymentPlan() {
  const d = state.data;
  const selected = state.selectedAccountId;
  const visibleMonth = d.visible_month;
  const selectedRecurring = [...(d.selected_recurring || [])].sort((a, b) => {
    const aStatusMonth = a.status_month || visibleMonth;
    const bStatusMonth = b.status_month || visibleMonth;
    const aChecked = (a.checked_months || []).includes(aStatusMonth) ? 1 : 0;
    const bChecked = (b.checked_months || []).includes(bStatusMonth) ? 1 : 0;
    if (aChecked !== bChecked) return aChecked - bChecked;
    const accountA = d.account_names?.[a.account_id] || "";
    const accountB = d.account_names?.[b.account_id] || "";
    return accountA.localeCompare(accountB, "de")
      || Number(a.day || 0) - Number(b.day || 0)
      || String(a.description || "").localeCompare(String(b.description || ""), "de");
  });
  const openRecurring = selectedRecurring.filter((rec) => !(rec.checked_months || []).includes(rec.status_month || visibleMonth));
  const paidRecurring = selectedRecurring.filter((rec) => (rec.checked_months || []).includes(rec.status_month || visibleMonth));
  $("#page-payment-plan").innerHTML = `
    <div class="page-title">
      <div>
        <h1>Zahlungsplan</h1>
        <p>Dauerzahlungen, Abzahlungen und monatliche Kontrolle</p>
      </div>
    </div>
    <div class="grid">
      ${card("Monatliche Kontrolle", "Offen und erledigt nach Konto", `
        <div class="chip-row">
          <button class="chip ${selected === "all" ? "active" : ""}" data-action="select-account" data-id="all">Alle Konten</button>
          ${(d.accounts || []).map((account) => `
            <button class="chip account-chip ${account.id === selected ? "active" : ""}" data-action="select-account" data-id="${escapeHtml(account.id)}" ${accountGlowStyle(account.id)}>
              <span class="color-dot"></span>${escapeHtml(account.name)}
            </button>
          `).join("") || `<p class="empty">Keine Konten vorhanden.</p>`}
        </div>
        ${selectedRecurring.length ? `
          <div class="payment-section">
            <div class="section-label">Offen</div>
            <div class="list">${openRecurring.map((rec) => recurringRow(rec)).join("") || `<p class="empty">Keine offenen Zahlungen.</p>`}</div>
          </div>
          <div class="payment-section paid">
            <div class="section-label">Erledigt</div>
            <div class="list">${paidRecurring.map((rec) => recurringRow(rec)).join("") || `<p class="empty">Keine erledigten Zahlungen.</p>`}</div>
          </div>
        ` : `<p class="empty">Keine Dauerzahlungen im ausgewählten Konto.</p>`}
      `, 12)}
    </div>
  `;
}

function isManualExpense(item) {
  return !["recurring", "installment", "deferred"].includes(String(item.source || "manual"));
}

function dateSortValue(value) {
  const parsed = parseDateText(value);
  if (!parsed) return 0;
  return parsed.year * 10000 + parsed.month * 100 + parsed.day;
}

function manualExpenseGroups() {
  const d = state.data;
  const groups = new Map();
  (d.accounts || []).forEach((account) => {
    groups.set(account.id, {
      account,
      total: 0,
      items: []
    });
  });
  (d.expenses || []).filter(isManualExpense).forEach((expense) => {
    const accountId = expense.account_id || "";
    if (!groups.has(accountId)) {
      groups.set(accountId, {
        account: { id: accountId, name: d.account_names?.[accountId] || "Ohne Konto" },
        total: 0,
        items: []
      });
    }
    const group = groups.get(accountId);
    group.total += Number(expense.amount || 0);
    group.items.push(expense);
  });
  return [...groups.values()]
    .filter((group) => group.items.length)
    .sort((a, b) => a.account.name.localeCompare(b.account.name, "de"));
}

function manualExpenseRow(item) {
  return `
    <div class="expense-row">
      <div>
        <div class="row-title">${escapeHtml(item.description)}</div>
        <div class="row-sub">${escapeHtml(item.date || "-")}</div>
      </div>
      <strong>${escapeHtml(formatAmount(item.amount))}</strong>
      <button class="icon-button" title="Bearbeiten" data-action="edit-expense" data-id="${escapeHtml(item.id)}">✎</button>
      <button class="icon-button danger-button" title="Löschen" data-action="delete-expense" data-id="${escapeHtml(item.id)}">×</button>
    </div>
  `;
}

function renderExpenses() {
  const d = state.data;
  const groups = manualExpenseGroups();
  const total = groups.reduce((sum, group) => sum + group.total, 0);
  $("#page-expenses").innerHTML = `
    <div class="page-title">
      <div>
        <h1>Ausgaben</h1>
        <p>Manuelle Ausgaben für ${escapeHtml(d.visible_month_label)} nach Konto</p>
      </div>
      <div class="actions page-actions">
        <button class="solid" data-action="go-expense-entry">Ausgabe erfassen</button>
      </div>
    </div>
    <div class="grid">
      ${kpiCard("Manuelle Ausgaben", formatAmount(total), "negative", 12)}
      ${groups.map((group) => {
        const sorted = [...group.items].sort((a, b) => dateSortValue(b.date) - dateSortValue(a.date)
          || String(a.description || "").localeCompare(String(b.description || ""), "de"));
        return card(group.account.name, `${formatAmount(group.total)} im ausgewählten Monat`, `
          <div class="list compact-list">
            ${sorted.map(manualExpenseRow).join("")}
          </div>
        `, 6);
      }).join("") || card("Keine manuellen Ausgaben", "In diesem Monat wurde noch keine manuelle Ausgabe erfasst.", `
        <div class="empty">Noch keine Einträge vorhanden.</div>
      `, 12)}
    </div>
  `;
}

function recurringManagementRows() {
  const visibleMonth = state.data.visible_month || "";
  return [...(state.data.recurring || [])].sort((a, b) => {
    const accountA = state.data.account_names?.[a.account_id] || "";
    const accountB = state.data.account_names?.[b.account_id] || "";
    return accountA.localeCompare(accountB, "de")
      || Number(a.day || 0) - Number(b.day || 0)
      || String(a.description || "").localeCompare(String(b.description || ""), "de");
  }).filter((rec) => {
    const endMonth = monthFromTextDate(rec.end_date);
    return !endMonth || endMonth >= visibleMonth;
  });
}

function recurringManagementRow(rec) {
  const account = state.data.account_names?.[rec.account_id] || "-";
  const freq = recurringFrequencyLabel(rec.frequency, rec.kind);
  return `
    <div class="recurring-management-row" ${accountGlowStyle(rec.account_id)}>
      <div>
        <div class="row-title">${escapeHtml(rec.description)}</div>
        <div class="row-sub">${escapeHtml(account)} | ${freq} am ${String(rec.day).padStart(2, "0")}. | Start ${escapeHtml(rec.start_date || "-")}${rec.end_date ? ` | Ende ${escapeHtml(rec.end_date)}` : ""}</div>
      </div>
      <strong>${escapeHtml(formatRecAmount(rec))}</strong>
      <button class="icon-button" title="Bearbeiten" data-action="edit-recurring" data-id="${escapeHtml(rec.id)}">✎</button>
      <button class="icon-button danger-button" title="Löschen" data-action="delete-recurring" data-id="${escapeHtml(rec.id)}">×</button>
    </div>
  `;
}

function recurringRow(rec) {
  const statusMonth = rec.status_month || state.data.visible_month;
  const checked = (rec.checked_months || []).includes(statusMonth);
  const amount = rec.current_amount_label || formatRecAmount(rec);
  const freq = recurringFrequencyLabel(rec.frequency, rec.kind);
  const currentEditId = rec.current_expense_id || "";
  const account = state.data.account_names?.[rec.account_id] || "-";
  const rowTitle = rec.is_deferred ? `${rec.description} (verschoben)` : rec.description;
  const dateInfo = rec.is_deferred
    ? `Verschoben aus ${monthLabel(statusMonth)} auf den 01. des aktuellen Monats`
    : `${freq} am ${String(rec.day).padStart(2, "0")}. | Start ${escapeHtml(rec.start_date || "-")}${rec.end_date ? ` | Ende ${escapeHtml(rec.end_date)}` : ""}`;
  return `
    <div class="recurring-row" ${accountGlowStyle(rec.account_id)}>
      <label class="check-pill">
        <input type="checkbox" ${checked ? "checked" : ""} data-action="toggle-recurring" data-id="${escapeHtml(rec.id)}" data-month="${escapeHtml(statusMonth)}">
        <span>${checked ? "Erledigt" : "Offen"}</span>
      </label>
      <div>
        <div class="row-title">${escapeHtml(rowTitle)}</div>
        <div class="row-sub">${escapeHtml(account)} | ${dateInfo}</div>
      </div>
      <strong>${escapeHtml(amount)}</strong>
      <button class="icon-button" title="Diesen Monat bearbeiten" data-action="edit-current-payment" data-id="${escapeHtml(currentEditId)}" ${currentEditId ? "" : "disabled"}>✎</button>
      <button class="ghost" title="Auf den 1. des nächsten Monats verschieben" data-action="postpone-current-payment" data-id="${escapeHtml(rec.id)}" data-month="${escapeHtml(statusMonth)}" ${checked || rec.is_deferred ? "disabled" : ""}>Verschieben</button>
      <button class="icon-button danger-button" title="Nur diesen Monat entfernen" data-action="delete-current-payment" data-id="${escapeHtml(rec.id)}" data-month="${escapeHtml(statusMonth)}">×</button>
    </div>
  `;
}

function renderAnalysis() {
  const d = state.data;
  $("#page-analysis").innerHTML = `
    <div class="page-title">
      <div>
        <h1>Auswertung</h1>
        <p>Kategorien und Kontofilter für ${escapeHtml(d.visible_month_label)}</p>
      </div>
    </div>
    <div class="grid">
      ${card("Monatsergebnis", d.visible_month_label, `
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
}

function renderMonthClose() {
  const d = state.data;
  $("#page-month-close").innerHTML = `
    <div class="page-title">
      <div>
        <h1>Monatsübersicht</h1>
        <p>Zwischen Monaten wechseln und neue Monate starten</p>
      </div>
    </div>
    <div class="grid">
      ${card("Ausgewählter Monat", "Monat, für den du deine Finanzen ansiehst", monthNavigatorContent(d), 12)}
    </div>
  `;
}

function formatRecAmount(rec) {
  const currency = state.data.settings.currency || "EUR";
  const amount = Number(rec.amount || 0);
  return amount.toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ` ${currency}`;
}

function formatAmount(value) {
  const currency = state.data.settings.currency || "EUR";
  return Number(value || 0).toLocaleString("de-DE", { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + ` ${currency}`;
}

function renderSettings() {
  const d = state.data;
  const autostartEnabled = Boolean(d.settings.autostart_enabled);
  const autostartStartHidden = autostartEnabled && Boolean(d.settings.autostart_start_hidden);
  $("#page-settings").innerHTML = `
    <div class="page-title">
      <div>
        <h1>Einstellungen</h1>
        <p>App-Verhalten, Updates und Stammdaten</p>
      </div>
    </div>
    <div class="grid">
      ${card("App-Einstellungen", "Währung, Autostart und Updates", `
        <form id="settings-form" class="form-grid settings-form">
          ${field("Währung", "currency", d.settings.currency || "EUR")}
          ${field("Update-Prüfung alle Stunden", "update_check_interval_hours", d.settings.update_check_interval_hours || 6, "type=\"number\" min=\"1\" max=\"168\"")}
          <label class="check-pill"><input type="checkbox" name="autostart_enabled" ${autostartEnabled ? "checked" : ""}>Autostart aktivieren</label>
          <label class="check-pill ${autostartEnabled ? "" : "is-disabled"}" data-autostart-hidden-pill><input type="checkbox" name="autostart_start_hidden" ${autostartStartHidden ? "checked" : ""} ${autostartEnabled ? "" : "disabled"}>Im Hintergrund starten</label>
          <label class="check-pill"><input type="checkbox" name="auto_update_check" ${d.settings.auto_update_check ? "checked" : ""}>Periodisch auf Updates prüfen</label>
          <div class="actions">
            <button class="solid" type="submit">Einstellungen speichern</button>
            <button class="ghost" type="button" data-action="check-update">Jetzt auf Updates prüfen</button>
            <button class="ghost" type="button" data-action="open-db-folder">DB-Ordner öffnen</button>
          </div>
        </form>
        <p class="muted">Aktuelle Version: ${escapeHtml(d.version)}</p>
      `, 12)}
      ${card("Konten", "Stammdaten für Buchungen und Zahlungsplan", `
        <form id="account-form" class="form-grid account-create-form">
          ${field("Neues Konto", "name", "", "required")}
          ${colorPickerField("Farbe", "color", "#38a1ff")}
          <div class="actions"><button class="solid" type="submit">Konto anlegen</button></div>
        </form>
        <div class="list" style="margin-top:12px">
          ${(d.accounts || []).map((account) => `
            <div class="account-row" ${accountGlowStyle(account.id)}>
              <div class="account-row-main">
                <div class="row-title">${escapeHtml(account.name)}</div>
              </div>
              <div class="account-row-controls">
                <div class="account-color-field" title="Kontofarbe">
                  ${colorControl(account.color || accountColor(account.id), `data-account-color="${escapeHtml(account.id)}" aria-label="Kontofarbe ${escapeHtml(account.name)}"`)}
                </div>
                <button class="danger-button" data-action="delete-account" data-id="${escapeHtml(account.id)}">Löschen</button>
              </div>
            </div>
          `).join("") || `<p class="empty">Keine Konten vorhanden.</p>`}
        </div>
      `, 12)}
      ${card("Einnahmequellen", "Auswahlwerte für neue Einnahmen", `
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
          `).join("") || `<p class="empty">Keine Einnahmequellen angelegt.</p>`}
        </div>
      `, 12)}
    </div>
  `;
  bindAutostartControls($("#page-settings"));
  bindForm($("#page-settings"), "#settings-form", async (payload, form) => {
    payload.autostart_enabled = Boolean(form.elements.autostart_enabled.checked);
    payload.autostart_start_hidden = payload.autostart_enabled && Boolean(form.elements.autostart_start_hidden.checked);
    payload.auto_update_check = Boolean(form.elements.auto_update_check.checked);
    await api("/api/settings", { method: "POST", body: postContext(payload) });
    showToast("Einstellungen gespeichert.");
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

function bindAutostartControls(root) {
  const form = $("#settings-form", root);
  if (!form) return;
  const autostartInput = form.elements.autostart_enabled;
  const hiddenInput = form.elements.autostart_start_hidden;
  const hiddenPill = $("[data-autostart-hidden-pill]", form);
  const sync = () => {
    const enabled = Boolean(autostartInput.checked);
    hiddenInput.disabled = !enabled;
    if (!enabled) hiddenInput.checked = false;
    hiddenPill?.classList.toggle("is-disabled", !enabled);
  };
  autostartInput.addEventListener("change", sync);
  sync();
}

function openModal(title, html, onSubmit) {
  const modal = $("#modal");
  closeSelectMenu();
  closeDatePicker();
  if (modal.open) modal.close();
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
  modal.addEventListener("close", () => {
    closeDatePicker();
    closeSelectMenu();
    clearDraftState(modal);
  }, { once: true });
  $("form", modal).addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload = Object.fromEntries(new FormData(event.currentTarget).entries());
    try {
      await onSubmit(payload);
      if (modal.open) modal.close();
    } catch (error) {
      showToast(error.message);
    }
  });
  modal.showModal();
}

function afterNextFrame() {
  return new Promise((resolve) => window.requestAnimationFrame(resolve));
}

async function chooseGlobalScope(kind) {
  const action = kind === "delete" ? "gelöscht" : "geändert";
  const modal = $("#modal");
  closeSelectMenu();
  closeDatePicker();
  if (modal.open) {
    modal.close();
    await afterNextFrame();
  }
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
    modal.addEventListener("close", () => {
      closeDatePicker();
      closeSelectMenu();
      clearDraftState(modal);
    }, { once: true });
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
      ${datePickerField("Startdatum", "start_date", rec?.start_date || defaultMonthDate())}
      ${isInstallment ? datePickerField("Enddatum", "end_date", rec?.end_date || defaultMonthDate()) : ""}
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

function openSettingsSetup(selector) {
  state.page = "settings";
  render();
  window.setTimeout(() => {
    const input = $(selector);
    input?.scrollIntoView({ behavior: "smooth", block: "center" });
    input?.focus();
  }, 0);
}

function openAccountSettings() {
  openSettingsSetup("#account-form input[name='name']");
}

function openIncomeSourceSettings() {
  openSettingsSetup("#source-form input[name='name']");
}

function transactionModal(item, kind) {
  const isIncome = kind === "income";
  if (isIncome && !(state.data.income_sources || []).length) {
    openIncomeSourceSettings();
    return;
  }
  const html = `
    ${isIncome ? selectField("Typ", "type", state.data.income_sources || [], item.type) : ""}
    ${selectField("Konto", "account_id", accountOptions(item.account_id))}
    ${field(isIncome ? "Beschreibung" : "Kategorie / Beschreibung", "description", item.description || "", "required")}
    <div class="two-col">
      ${field("Betrag", "amount", item.amount || "", "inputmode=\"decimal\" required")}
      ${datePickerField("Datum", "date", item.date || defaultMonthDate())}
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
  state.page = "payment-plan";
  const modal = $("#reminder-modal");
  if (modal?.open) {
    modal.close();
  }
  await loadState();
}

function openExpenseEntry() {
  state.page = "bookings";
  render();
  if (!(state.data.accounts || []).length) {
    return;
  }
  window.setTimeout(() => {
    const form = $("#expense-form");
    form?.scrollIntoView({ behavior: "smooth", block: "center" });
    const input = $("input[name='description']", form);
    input?.focus();
  }, 0);
}

document.addEventListener("click", async (event) => {
  const calendarNav = event.target.closest("[data-calendar-nav]");
  if (calendarNav && state.activeDateControl) {
    state.activeDateViewMonth = shiftMonth(state.activeDateViewMonth, Number(calendarNav.dataset.calendarNav || 0));
    renderDatePickerPanel();
    return;
  }

  const calendarDay = event.target.closest("[data-calendar-day]");
  if (calendarDay && state.activeDateControl) {
    setDatePickerValue(state.activeDateControl, calendarDay.dataset.value || todayText());
    closeDatePicker();
    return;
  }

  const calendarToday = event.target.closest("[data-calendar-today]");
  if (calendarToday && state.activeDateControl) {
    setDatePickerValue(state.activeDateControl, todayText());
    closeDatePicker();
    return;
  }

  const colorChoice = event.target.closest("[data-color-choice]");
  if (colorChoice) {
    setColorPickerValue(colorChoice.closest("dialog"), colorChoice.dataset.colorChoice || "");
    return;
  }

  const comboOption = event.target.closest("[data-select-option]");
  if (comboOption) {
    const combo = state.activeDropdownCombo || null;
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

  const dateTrigger = event.target.closest("[data-date-trigger]");
  if (dateTrigger) {
    const control = dateTrigger.closest("[data-date-picker]");
    toggleDatePicker(control);
    return;
  }

  if (!event.target.closest("[data-combo]") && !event.target.closest(".dropdown-overlay")) {
    closeSelectMenu();
  }
  if (!event.target.closest("[data-date-picker]") && !event.target.closest(".calendar-overlay")) {
    closeDatePicker();
  }

  const target = event.target.closest("[data-action]");
  if (!target) return;
  const action = target.dataset.action;
  const id = target.dataset.id;
  try {
    if (action === "select-account") {
      state.selectedAccountId = id;
      await loadState();
    } else if (action === "go-bookings") {
      state.page = "bookings";
      render();
    } else if (action === "go-expense-entry") {
      openExpenseEntry();
    } else if (action === "go-month-close") {
      state.page = "month-close";
      render();
    } else if (action === "open-payments") {
      state.page = "payment-plan";
      render();
    } else if (action === "open-account-payments") {
      state.selectedAccountId = id;
      state.page = "payment-plan";
      await loadState();
    } else if (action === "open-overdue-account") {
      await openReminderAccount(id);
    } else if (action === "new-recurring") {
      if ((state.data.accounts || []).length) recurringModal(null, "standard");
      else openAccountSettings();
    } else if (action === "new-installment") {
      if ((state.data.accounts || []).length) recurringModal(null, "installment");
      else openAccountSettings();
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
          body: postContext({ month: target.dataset.month || state.data.visible_month })
        });
        showToast("Zahlung für diesen Monat entfernt.");
      }
    } else if (action === "postpone-current-payment") {
      if (confirm("Diese Zahlung auf den 1. des nächsten Monats verschieben?")) {
        await api(`/api/recurring/${id}/postpone`, {
          method: "POST",
          body: postContext({ month: target.dataset.month || state.data.visible_month })
        });
        showToast("Zahlung auf nächsten Monat verschoben.");
      }
    } else if (action === "mark-overdue-done") {
      if (!id || !target.dataset.month) return;
      await api(`/api/recurring/${id}/checked`, {
        method: "POST",
        body: postContext({ month: target.dataset.month, checked: true })
      });
      showToast("Überfällige Zahlung erledigt.");
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
    } else if (action === "open-color-picker") {
      openColorPicker(target.closest(".color-control"));
    } else if (action === "change-month") {
      await api("/api/settings/visible-month", { method: "POST", body: postContext({ month: target.dataset.month }) });
      showToast(`Monat ${monthLabel(target.dataset.month)} geladen.`);
    } else if (action === "open-account-settings") {
      openAccountSettings();
    } else if (action === "open-income-source-settings") {
      openIncomeSourceSettings();
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

document.addEventListener("keydown", (event) => {
  const target = event.target.closest?.(".clickable-row[data-action]");
  if (!target || !["Enter", " "].includes(event.key)) return;
  event.preventDefault();
  target.click();
});

window.addEventListener("resize", () => {
  closeSelectMenu();
  closeDatePicker();
});
document.addEventListener("scroll", (event) => {
  if (event.target instanceof Element && event.target.closest(".dropdown-menu")) return;
  if (event.target instanceof Element && event.target.closest(".calendar-panel")) return;
  closeSelectMenu();
  closeDatePicker();
}, true);

document.addEventListener("input", (event) => {
  const target = event.target;
  if (isEditableElement(target)) {
    markDraftState(target);
  }
  if (target.matches?.("[data-color-picker-input]")) {
    setColorPickerValue(target.closest("dialog"), target.value);
  }
});

document.addEventListener("reset", (event) => {
  window.setTimeout(() => {
    clearDraftState(event.target);
    $$("[data-color-input]", event.target).forEach(syncColorControl);
    $$("[data-date-picker]", event.target).forEach((control) => {
      const input = $("input[type='hidden']", control);
      setDatePickerValue(control, input?.value || todayText(), false);
    });
  }, 0);
});

document.addEventListener("change", async (event) => {
  const target = event.target;
  if (isEditableElement(target)) {
    markDraftState(target);
  }
  if (target.dataset?.action !== "toggle-recurring") return;
  try {
    await api(`/api/recurring/${target.dataset.id}/checked`, {
      method: "POST",
      body: postContext({ month: target.dataset.month || state.data.visible_month, checked: target.checked })
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
    if (hasUnsavedDraft()) return;
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
