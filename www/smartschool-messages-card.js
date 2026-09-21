// Smartschool messages card -- native Lovelace custom card (no Jinja / html-template-card needed).
//
// Usage in a dashboard:
//   type: custom:smartschool-messages-card
//   title: Berichten
//
// Ported from a hand-built html-template-card (same as smartschool-results-card.js).
// Key differences from that version:
// - Marks a message read via a direct hass.callService() to smartschool.mark_message_read,
//   no webhook/automation detour needed (this card has a real hass object). The
//   "Smartschool - mark message read (webhook)" automation is no longer needed once
//   this card replaces the old html-template-card.
// - No hidden-radio/CSS selection trick: message selection is tracked in a plain JS
//   field and DOM is rebuilt straightforwardly on each relevant change.
// - Scans ALL sensor.*_message_* entities regardless of child, same as the original
//   template (a combined mailbox across every configured Smartschool login).

const AVATAR_COLORS = ["#e57373", "#64b5f6", "#81c784", "#ffd54f", "#ba68c8", "#4db6ac", "#f06292", "#a1887f", "#7986cb", "#4fc3f7"];
const ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ";

const DEFAULTS = {
  language: "nl",
  children: [],
  show_avatars: true,
  show_attachment_preview: true,
  unread_color: null,
  selected_color: null,
};

const LABELS = {
  title: "Title (optional)",
  language: "Card language",
  children: "Children (empty = all children combined)",
  details: "Details",
  show_avatars: "Show avatar initials",
  show_attachment_preview: "Inline preview for PDF/docx attachments (off = always just download)",
  unread_color: "Unread indicator color (empty = theme primary color)",
  selected_color: "Selected message background color (empty = theme default)",
};

// `child` (a single string) was the field name before the multi-select existed;
// still honored so an old saved config keeps working.
function selectedChildren(config) {
  if (Array.isArray(config.children) && config.children.length) return config.children;
  if (config.child) return [config.child];
  return [];
}

// Config values from the color_rgb selector come back as [r, g, b] arrays.
function colorToCss(value, alpha) {
  if (Array.isArray(value)) {
    const [r, g, b] = value;
    return alpha != null ? `rgba(${r},${g},${b},${alpha})` : `rgb(${r},${g},${b})`;
  }
  return value;
}

function detectChildren(hass) {
  const children = new Set();
  for (const entityId of Object.keys(hass.states)) {
    const match = entityId.match(/^sensor\.(.+)_message_/);
    if (match) children.add(match[1]);
  }
  return Array.from(children).sort();
}

function titleCase(str) {
  return String(str).replace(/[_\s]+/g, " ").trim().replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1));
}

const STRINGS = {
  nl: {
    messages: "Berichten",
    totalMessages: (n) => `${n} berichten totaal`,
    from: "Van",
    to: "Aan",
    cc: "CC",
    bcc: "BCC",
    date: "Datum",
    noText: "Dit bericht bevat geen tekst.",
    attachments: (n) => `Bijlagen (${n})`,
    file: "Bestand",
    clickToOpen: "klik om te openen",
    loading: "Bezig met laden…",
    couldNotLoad: (err) => `Kon document niet laden: ${err}`,
    download: "Downloaden",
    noDownloadLink: "Geen downloadlink",
    imageNotShown: "📷 Afbeelding niet weergegeven",
    truncated: "… (bericht ingekort, was te lang om volledig te tonen)",
    unknownSender: "Onbekende afzender",
    noMessages: "Geen Smartschool-berichten gevonden",
    attachment: "Bijlage",
  },
  en: {
    messages: "Messages",
    totalMessages: (n) => `${n} messages total`,
    from: "From",
    to: "To",
    cc: "CC",
    bcc: "BCC",
    date: "Date",
    noText: "This message contains no text.",
    attachments: (n) => `Attachments (${n})`,
    file: "File",
    clickToOpen: "click to open",
    loading: "Loading…",
    couldNotLoad: (err) => `Could not load document: ${err}`,
    download: "Download",
    noDownloadLink: "No download link",
    imageNotShown: "📷 Image not shown",
    truncated: "… (message truncated, was too long to show in full)",
    unknownSender: "Unknown sender",
    noMessages: "No Smartschool messages found",
    attachment: "Attachment",
  },
};

function getStrings(language) {
  return STRINGS[language] || STRINGS.nl;
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function sensorName(entityId) {
  const afterDomain = entityId.split(".")[1] || "";
  const beforeMessage = afterDomain.split("_message_")[0] || "";
  return beforeMessage.split("_").filter(Boolean).map((w) => w[0].toUpperCase() + w.slice(1)).join(" ");
}

function avatarColor(name) {
  const letter = name ? name[0].toUpperCase() : "X";
  const idx = ALPHABET.indexOf(letter);
  return AVATAR_COLORS[(idx >= 0 ? idx : 0) % AVATAR_COLORS.length];
}

function fmtDateTime(value, locale) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleString(locale || "nl-BE", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

function fmtDateOnly(value, locale) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(locale || "nl-BE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

class SmartschoolMessagesCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  _render() {
    if (!this._hass || !this._config) return;
    if (!this._form) {
      this._form = document.createElement("ha-form");
      this._form.addEventListener("value-changed", (ev) => {
        ev.stopPropagation();
        this._config = ev.detail.value;
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._form);
    }
    const children = detectChildren(this._hass);
    this._form.hass = this._hass;
    this._form.data = { ...DEFAULTS, ...this._config, children: selectedChildren(this._config) };
    this._form.schema = [
      { name: "title", required: false, selector: { text: {} } },
      {
        name: "language",
        selector: {
          select: {
            mode: "dropdown",
            options: [
              { value: "en", label: "English" },
              { value: "nl", label: "Nederlands" },
            ],
          },
        },
      },
      {
        name: "children",
        selector: {
          select: {
            multiple: true,
            mode: "list",
            options: children.map((c) => ({ value: c, label: titleCase(c) })),
          },
        },
      },
      {
        name: "details",
        type: "expandable",
        title: "Details",
        icon: "mdi:tune",
        flatten: true,
        schema: [
          { name: "show_avatars", selector: { boolean: {} } },
          { name: "show_attachment_preview", selector: { boolean: {} } },
          { name: "unread_color", selector: { color_rgb: {} } },
          { name: "selected_color", selector: { color_rgb: {} } },
        ],
      },
    ];
    this._form.computeLabel = (schema) => LABELS[schema.name] || schema.name;

    if (!this._resetBtn) {
      this._resetBtn = document.createElement("mwc-button");
      this._resetBtn.setAttribute("outlined", "");
      this._resetBtn.style.marginTop = "12px";
      this._resetBtn.addEventListener("click", () => {
        const next = { ...this._config, unread_color: null, selected_color: null };
        this._config = next;
        this._form.data = { ...DEFAULTS, ...this._config };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._resetBtn);
    }
    this._resetBtn.textContent = this._config.language === "en" ? "Reset colors to default" : "Kleuren terugzetten naar standaard";
  }
}

if (!customElements.get("smartschool-messages-card-editor")) {
  customElements.define("smartschool-messages-card-editor", SmartschoolMessagesCardEditor);
}

class SmartschoolMessagesCard extends HTMLElement {
  setConfig(config) {
    this._config = config || {};
    this._selectedKey = null;
    this._lastSignature = null;
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this._root = document.createElement("div");
      this._card.appendChild(this._root);
      this.appendChild(this._card);
    }
    this._card.header = this._config.title || "";
  }

  set hass(hass) {
    this._hass = hass;
    const groups = this._collectGroups(hass);
    const signature = JSON.stringify(groups.map((g) => [g.key, g.primary.entityId, g.primary.state, g.isUnread, g.maxNum]));
    if (signature === this._lastSignature) return;
    this._lastSignature = signature;
    this._render(groups);
  }

  getCardSize() {
    return 10;
  }

  static getConfigElement() {
    return document.createElement("smartschool-messages-card-editor");
  }

  static getStubConfig() {
    return { title: "", language: "nl" };
  }

  _collectGroups(hass) {
    const children = selectedChildren(this._config);
    const prefixes = children.map((c) => `sensor.${c.toLowerCase()}_message_`);
    const rows = [];
    for (const entityId of Object.keys(hass.states)) {
      if (!entityId.includes("_message_")) continue;
      if (!entityId.startsWith("sensor.")) continue;
      if (prefixes.length && !prefixes.some((p) => entityId.startsWith(p))) continue;
      const st = hass.states[entityId];
      const a = st.attributes || {};
      const numMatch = entityId.split("_message_").pop();
      const num = parseInt(numMatch, 10) || 0;
      const title = st.state;
      const body = a.body || "";
      const isUnread = [true, "true", "True", "on", 1, "1"].includes(a.unread);
      rows.push({
        num,
        entityId,
        state: title,
        attributes: a,
        key: `${title}||${body}`,
        name: sensorName(entityId),
        isUnread,
        messageId: a.message_id || "",
      });
    }

    const byKey = new Map();
    for (const row of rows) {
      if (!byKey.has(row.key)) byKey.set(row.key, []);
      byKey.get(row.key).push(row);
    }

    const groups = [];
    for (const [key, entries] of byKey) {
      const newest = entries.slice().sort((a, b) => b.num - a.num)[0];
      const names = Array.from(new Set(entries.map((e) => e.name)));
      const isUnread = entries.some((e) => e.isUnread);
      const maxNum = Math.max(...entries.map((e) => e.num));
      const pairs = entries.map((e) => [e.entityId, e.messageId]);
      groups.push({ key, primary: { entityId: newest.entityId, state: newest.state, attributes: newest.attributes }, names, isUnread, maxNum, pairs });
    }
    groups.sort((a, b) => b.maxNum - a.maxNum);
    return groups;
  }

  _markRead(pairs) {
    for (const [entityId, messageId] of pairs) {
      this._hass.callService("smartschool", "mark_message_read", { entity_id: entityId, message_id: messageId }).catch((err) => {
        console.error("smartschool-messages-card: mark_message_read failed", err);
      });
    }
  }

  _attachmentIcon(filename) {
    const fl = filename.toLowerCase();
    if (fl.endsWith(".pdf")) return "mdi:file-pdf-box";
    if (fl.endsWith(".doc") || fl.endsWith(".docx")) return "mdi:file-word-box";
    if (fl.endsWith(".xls") || fl.endsWith(".xlsx")) return "mdi:file-excel-box";
    if (fl.endsWith(".ppt") || fl.endsWith(".pptx")) return "mdi:file-powerpoint-box";
    if (fl.endsWith(".zip") || fl.endsWith(".rar")) return "mdi:folder-zip-outline";
    return "mdi:file-outline";
  }

  _attachmentsHtml(attachments, t, showPreview) {
    if (!attachments || !attachments.length) return "";
    const items = attachments.map((att, idx) => {
      const filename = att.name || t.attachment;
      const url = att.download_url || "";
      const mime = String(att.mime || "");
      const size = att.size || "";
      const fl = filename.toLowerCase();
      const isImage = mime.toLowerCase().includes("image") || [".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp"].some((ext) => fl.endsWith(ext));
      const isPdf = fl.endsWith(".pdf");
      const isDocx = fl.endsWith(".docx");
      const icon = this._attachmentIcon(filename);

      if (isImage && url) {
        return `<a class="ssm-image-attachment" href="${escapeHtml(url)}" target="_blank" rel="noopener">
          <img class="ssm-image-preview" src="${escapeHtml(url)}" alt="${escapeHtml(filename)}" loading="lazy">
          <span class="ssm-image-caption">${escapeHtml(filename)}${size ? ` · ${escapeHtml(size)}` : ""}</span>
        </a>`;
      }
      if ((isPdf || isDocx) && url && showPreview) {
        return `<div class="ssm-attachment-block">
          <div class="ssm-attachment" data-preview-idx="${idx}" data-pdf="${isPdf}" data-url="${escapeHtml(url)}">
            <ha-icon icon="${icon}"></ha-icon>
            <span class="ssm-attachment-info">
              <span class="ssm-attachment-name">${escapeHtml(filename)}</span>
              <span class="ssm-attachment-meta">${mime ? escapeHtml(mime) : t.file}${size ? ` · ${escapeHtml(size)}` : ""} · ${t.clickToOpen}</span>
            </span>
            <a class="ssm-attachment-download" href="${escapeHtml(url)}" download="${escapeHtml(filename)}" title="${t.download}">
              <ha-icon icon="mdi:download"></ha-icon>
            </a>
          </div>
          <div class="ssm-attachment-preview"></div>
        </div>`;
      }
      if (url) {
        return `<a class="ssm-attachment" href="${escapeHtml(url)}" download="${escapeHtml(filename)}">
          <ha-icon icon="${icon}"></ha-icon>
          <span class="ssm-attachment-info">
            <span class="ssm-attachment-name">${escapeHtml(filename)}</span>
            <span class="ssm-attachment-meta">${mime ? escapeHtml(mime) : t.file}${size ? ` · ${escapeHtml(size)}` : ""}</span>
          </span>
        </a>`;
      }
      return `<div class="ssm-attachment">
        <ha-icon icon="mdi:file-alert-outline"></ha-icon>
        <span class="ssm-attachment-info">
          <span class="ssm-attachment-name">${escapeHtml(filename)}</span>
          <span class="ssm-attachment-meta">${t.noDownloadLink}</span>
        </span>
      </div>`;
    }).join("");

    return `<footer class="ssm-attachments">
      <div class="ssm-attachments-title"><ha-icon icon="mdi:paperclip"></ha-icon><span>${escapeHtml(t.attachments(attachments.length))}</span></div>
      <div class="ssm-attachment-list">${items}</div>
    </footer>`;
  }

  _bodyHtml(bodyRaw, budget, t) {
    let body = bodyRaw
      .replace(/<img[^>]*src="data:[^"]*"[^>]*>/g, `<div class="ssm-inline-image-removed">${t.imageNotShown}</div>`)
      .replace(/<img[^>]*src='data:[^']*'[^>]*>/g, `<div class="ssm-inline-image-removed">${t.imageNotShown}</div>`);
    if (body.length > budget) {
      body = `${body.slice(0, budget)}<p><em>${t.truncated}</em></p>`;
    }
    return body;
  }

  _render(groups) {
    const opts = { ...DEFAULTS, ...this._config };
    const t = getStrings(opts.language);

    if (!this._selectedKey || !groups.some((g) => g.key === this._selectedKey)) {
      this._selectedKey = groups[0] ? groups[0].key : null;
    }

    if (!groups.length) {
      this._root.innerHTML = `<div class="ssm-empty"><ha-icon icon="mdi:email-off-outline"></ha-icon><strong>${escapeHtml(t.noMessages)}</strong></div>${this._styles(opts)}`;
      return;
    }

    const totalGroups = groups.length;
    const perBodyBudget = Math.max(1000, Math.min(20000, Math.floor(170000 / (totalGroups || 1))));

    const rowsHtml = groups.map((grp) => {
      const mdate = grp.primary.attributes.date || "";
      const avatars = opts.show_avatars ? grp.names.map((name) => `<span class="ssm-avatar" style="background:${avatarColor(name)};" title="${escapeHtml(name)}">${name ? escapeHtml(name[0].toUpperCase()) : "?"}</span>`).join("") : "";
      const selected = grp.key === this._selectedKey;
      return `<div class="ssm-message-row${grp.isUnread ? " is-unread" : ""}${selected ? " is-selected" : ""}" data-key="${escapeHtml(grp.key)}" title="${escapeHtml(grp.primary.state)}">
        <span class="ssm-unread-dot"></span>
        ${opts.show_avatars ? `<span class="ssm-avatar-stack">${avatars}</span>` : ""}
        <span class="ssm-row-content">
          <span class="ssm-row-top"><span class="ssm-row-subject">${escapeHtml(grp.primary.state)}</span></span>
          <span class="ssm-row-sender">${escapeHtml(grp.primary.attributes.from || "")}</span>
        </span>
        <span class="ssm-row-date">${mdate ? fmtDateOnly(mdate, t === STRINGS.en ? "en-GB" : "nl-BE") : ""}</span>
      </div>`;
    }).join("");

    const selectedGroup = groups.find((g) => g.key === this._selectedKey) || groups[0];
    const message = selectedGroup.primary;
    const a = message.attributes;
    const sender = a.from || t.unknownSender;
    const receivers = a.receivers || "";
    const cc = a.cc_receivers || "";
    const bcc = a.bcc_receivers || "";
    const mdate = a.date || "";
    const attachments = a.attachments || [];
    const bodyClean = this._bodyHtml(a.body || "", perBodyBudget, t);
    const locale = opts.language === "en" ? "en-GB" : "nl-BE";

    const addrRow = (label, value) => {
      if (!value) return "";
      const text = Array.isArray(value) ? value.join(", ") : value;
      return `<div class="ssm-address-label">${escapeHtml(label)}</div><div class="ssm-address-value">${escapeHtml(text)}</div>`;
    };

    const viewHtml = `<article class="ssm-message-view">
      <header class="ssm-view-header">
        <h2 class="ssm-view-subject">${escapeHtml(message.state)}</h2>
        <div class="ssm-address-grid">
          <div class="ssm-address-label">${escapeHtml(t.from)}</div><div class="ssm-address-value ssm-from-value">${escapeHtml(sender)}</div>
          ${addrRow(t.to, receivers)}
          ${addrRow(t.cc, cc)}
          ${addrRow(t.bcc, bcc)}
          ${mdate ? `<div class="ssm-address-label">${escapeHtml(t.date)}</div><div class="ssm-address-value">${fmtDateTime(mdate, locale)}</div>` : ""}
        </div>
      </header>
      <div class="ssm-view-body">
        <div class="ssm-html-body">${bodyClean || `<p>${escapeHtml(t.noText)}</p>`}</div>
      </div>
      ${this._attachmentsHtml(attachments, t, opts.show_attachment_preview)}
    </article>`;

    this._root.innerHTML = `<div class="ssm-mail-app${opts.show_avatars ? "" : " ssm-no-avatars"}">
      <div class="ssm-mail-layout">
        <div class="ssm-message-column">
          <div class="ssm-list-header">
            <div class="ssm-list-title">
              <ha-icon icon="mdi:email-multiple-outline"></ha-icon><span>${escapeHtml(t.messages)}</span>
              <ha-icon-button class="ssm-refresh-btn" path="M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z"></ha-icon-button>
            </div>
            <div class="ssm-message-count" title="${escapeHtml(t.totalMessages(groups.length))}">${groups.length}</div>
          </div>
          <div class="ssm-message-list">${rowsHtml}</div>
        </div>
        <div class="ssm-viewer-column">${viewHtml}</div>
      </div>
    </div>${this._styles(opts)}`;

    const refreshBtn = this._root.querySelector(".ssm-refresh-btn");
    if (refreshBtn) {
      refreshBtn.addEventListener("click", (ev) => {
        ev.stopPropagation();
        if (!this._hass) return;
        const data = {};
        const children = selectedChildren(this._config);
        if (children.length && groups.length) {
          const entityIds = children
            .map((c) => groups.find((g) => g.primary.entityId.startsWith(`sensor.${c.toLowerCase()}_message_`)))
            .filter(Boolean)
            .map((g) => g.primary.entityId);
          if (entityIds.length) data.entity_id = entityIds;
        }
        refreshBtn.classList.add("ssm-spin");
        this._hass.callService("smartschool", "refresh", data)
          .catch((err) => console.error("smartschool-messages-card: refresh failed", err))
          .finally(() => setTimeout(() => refreshBtn.classList.remove("ssm-spin"), 600));
      });
    }

    this._root.querySelectorAll(".ssm-message-row").forEach((row) => {
      row.addEventListener("click", () => {
        const key = row.dataset.key;
        const grp = groups.find((g) => g.key === key);
        this._selectedKey = key;
        if (grp && grp.isUnread) {
          this._markRead(grp.pairs);
        }
        this._render(groups);
      });
    });

    this._root.querySelectorAll(".ssm-attachment[data-preview-idx]").forEach((el) => {
      el.addEventListener("click", (ev) => {
        ev.stopPropagation();
        const box = el.nextElementSibling;
        if (box.classList.contains("ssm-preview-open")) {
          box.classList.remove("ssm-preview-open");
          box.innerHTML = "";
          return;
        }
        box.classList.add("ssm-preview-open");
        const url = el.dataset.url;
        if (el.dataset.pdf === "true") {
          box.innerHTML = `<iframe class="ssm-pdf-frame" src="${escapeHtml(url)}"></iframe>`;
        } else {
          box.innerHTML = `<div class="ssm-docx-loading">${escapeHtml(t.loading)}</div>`;
          fetch(url).then((r) => r.arrayBuffer()).then((buf) => {
            if (!window.mammoth) throw new Error("mammoth.js not loaded");
            return window.mammoth.convertToHtml({ arrayBuffer: buf });
          }).then((result) => {
            box.innerHTML = `<div class="ssm-docx-preview">${result.value}</div>`;
          }).catch((err) => {
            box.innerHTML = `<div class="ssm-docx-loading">${escapeHtml(t.couldNotLoad(err))}</div>`;
          });
        }
      });
    });

    this._root.querySelectorAll(".ssm-attachment-download").forEach((el) => {
      el.addEventListener("click", (ev) => ev.stopPropagation());
    });
  }

  _styles(opts) {
    const unread = opts && opts.unread_color ? colorToCss(opts.unread_color) : "var(--primary-color)";
    const selected = opts && opts.selected_color ? colorToCss(opts.selected_color, 0.15) : "rgba(33, 150, 243, 0.15)";
    return `<style>
      .ssm-mail-app {
        --ssm-border: rgba(127, 127, 127, 0.24);
        --ssm-hover: rgba(33, 150, 243, 0.08);
        --ssm-selected: ${selected};
        --ssm-unread: ${unread};
        --ssm-muted: var(--secondary-text-color);
        --ssm-card: var(--card-background-color);
        width: 100%; min-height: 620px; background: var(--ssm-card);
        color: var(--primary-text-color); overflow: hidden; box-sizing: border-box;
      }
      .ssm-mail-app * { box-sizing: border-box; }
      .ssm-mail-layout { display: grid; grid-template-columns: minmax(260px, 34%) minmax(0, 66%); width: 100%; min-height: 620px; }
      .ssm-no-avatars .ssm-message-row { grid-template-columns: 14px minmax(0, 1fr) 70px; }
      .ssm-message-column { display: flex; flex-direction: column; min-width: 0; border-right: 1px solid var(--ssm-border); background: var(--ssm-card); }
      .ssm-list-header { position: sticky; top: 0; z-index: 2; display: flex; align-items: center; justify-content: space-between; min-height: 62px; padding: 12px 16px; border-bottom: 1px solid var(--ssm-border); background: var(--ssm-card); }
      .ssm-list-title { display: flex; align-items: center; gap: 10px; font-size: 18px; font-weight: 600; min-width: 0; }
      .ssm-list-title ha-icon { color: var(--primary-color); }
      .ssm-refresh-btn { margin-left: auto; --mdc-icon-button-size: 32px; color: var(--ssm-muted); }
      @keyframes ssm-spin { to { transform: rotate(360deg); } }
      .ssm-spin { animation: ssm-spin 0.6s linear; }
      .ssm-message-count { flex: 0 0 auto; padding: 3px 9px; border-radius: 14px; background: rgba(127,127,127,0.14); color: var(--ssm-muted); font-size: 12px; font-weight: 600; }
      .ssm-message-list { flex: 1 1 auto; max-height: 720px; overflow-x: hidden; overflow-y: auto; scrollbar-width: thin; }
      .ssm-message-row { display: grid; grid-template-columns: 14px 90px minmax(0, 1fr) 70px; align-items: center; column-gap: 9px; min-height: 70px; padding: 12px 14px 12px 12px; border-bottom: 1px solid var(--ssm-border); cursor: pointer; user-select: none; transition: background-color 120ms ease; }
      .ssm-message-row:hover { background: var(--ssm-hover); }
      .ssm-message-row.is-selected { background: var(--ssm-selected); box-shadow: inset 4px 0 0 var(--primary-color); }
      .ssm-unread-dot { align-self: start; width: 9px; height: 9px; margin-top: 6px; border: 2px solid rgba(127,127,127,0.45); border-radius: 50%; background: transparent; transition: background-color 150ms ease, border-color 150ms ease, box-shadow 150ms ease; }
      .ssm-message-row.is-unread .ssm-unread-dot { border-color: var(--ssm-unread); background: var(--ssm-unread); box-shadow: 0 0 0 3px rgba(33,150,243,0.12); }
      .ssm-row-content { min-width: 0; }
      .ssm-row-top { display: flex; align-items: baseline; justify-content: space-between; gap: 10px; min-width: 0; }
      .ssm-row-subject { min-width: 0; overflow: hidden; font-size: 14px; font-weight: 600; line-height: 1.35; text-overflow: ellipsis; white-space: nowrap; }
      .ssm-message-row.is-unread .ssm-row-subject { font-weight: 700; }
      .ssm-row-date { flex: 0 0 auto; color: var(--ssm-muted); font-size: 11px; white-space: nowrap; font-weight: 700; text-align: right; }
      .ssm-row-sender { margin-top: 3px; overflow: hidden; font-size: 12px; font-weight: 500; color: var(--ssm-muted); text-overflow: ellipsis; white-space: nowrap; }
      .ssm-message-row.is-unread .ssm-row-sender { color: var(--primary-text-color); font-weight: 600; }
      .ssm-avatar-stack { display: flex; align-items: center; flex: 0 0 auto; width: 90px; }
      .ssm-avatar { display: flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 50%; font-size: 11px; font-weight: 700; color: #fff; border: 2px solid var(--ssm-card); box-shadow: 0 0 0 1px rgba(0,0,0,0.06); }
      .ssm-avatar + .ssm-avatar { margin-left: -10px; }
      .ssm-viewer-column { position: relative; min-width: 0; min-height: 620px; background: var(--ssm-card); }
      .ssm-view-header { padding: 20px 24px 18px; border-bottom: 1px solid var(--ssm-border); background: var(--ssm-card); }
      .ssm-view-subject { margin: 0 0 18px; overflow-wrap: anywhere; font-size: clamp(20px, 2vw, 26px); font-weight: 650; line-height: 1.25; }
      .ssm-address-grid { display: grid; grid-template-columns: minmax(85px, auto) minmax(0, 1fr); gap: 7px 14px; align-items: start; font-size: 13px; line-height: 1.45; }
      .ssm-address-label { color: var(--ssm-muted); font-weight: 500; }
      .ssm-address-value { min-width: 0; overflow-wrap: anywhere; }
      .ssm-from-value { font-weight: 600; }
      .ssm-view-body { min-height: 250px; padding: 24px; overflow-wrap: anywhere; font-size: 15px; line-height: 1.6; }
      .ssm-html-body { max-width: 100%; background: #ffffff; color: #202124; padding: 16px; border-radius: 8px; user-select: text !important; -webkit-user-select: text !important; }
      .ssm-viewer-column, .ssm-view-header, .ssm-attachments { user-select: text !important; -webkit-user-select: text !important; }
      .ssm-html-body p:first-child { margin-top: 0; }
      .ssm-html-body img { display: block; max-width: 100%; height: auto; margin: 12px 0; border-radius: 8px; }
      .ssm-html-body table { display: block; max-width: 100%; overflow-x: auto; border-collapse: collapse; }
      .ssm-html-body td, .ssm-html-body th { padding: 6px 8px; border: 1px solid var(--ssm-border); }
      .ssm-html-body a { color: var(--primary-color); }
      .ssm-inline-image-removed { margin: 10px 0; padding: 10px 12px; border: 1px dashed #d0d0d0; border-radius: 8px; color: #5f6368; font-size: 13px; }
      .ssm-attachments { padding: 18px 24px 24px; border-top: 1px solid var(--ssm-border); background: rgba(127,127,127,0.035); }
      .ssm-attachments-title { display: flex; align-items: center; gap: 8px; margin-bottom: 12px; font-size: 14px; font-weight: 600; }
      .ssm-attachments-title ha-icon { color: var(--primary-color); }
      .ssm-attachment-list { display: flex; flex-wrap: wrap; gap: 10px; }
      .ssm-attachment { display: flex; align-items: center; gap: 10px; min-width: 210px; max-width: 100%; padding: 10px 12px; border: 1px solid var(--ssm-border); border-radius: 9px; background: var(--ssm-card); color: var(--primary-text-color); text-decoration: none; transition: border-color 120ms ease, background-color 120ms ease; cursor: pointer; }
      .ssm-attachment:hover { border-color: var(--primary-color); background: var(--ssm-hover); }
      .ssm-attachment ha-icon { flex: 0 0 auto; color: var(--primary-color); }
      .ssm-attachment-info { min-width: 0; }
      .ssm-attachment-name { overflow: hidden; font-size: 13px; font-weight: 600; text-overflow: ellipsis; white-space: nowrap; }
      .ssm-attachment-meta { margin-top: 2px; color: var(--ssm-muted); font-size: 11px; }
      .ssm-attachment-block { width: 100%; flex: 1 1 100%; }
      .ssm-attachment-download { margin-left: 8px; padding: 4px; border-radius: 6px; color: var(--ssm-muted); flex: 0 0 auto; display: flex; }
      .ssm-attachment-download:hover { background: var(--ssm-hover); color: var(--primary-color); }
      .ssm-attachment-preview:empty { display: none; }
      .ssm-attachment-preview.ssm-preview-open { display: block; margin-top: 10px; width: 100%; }
      .ssm-pdf-frame { width: 100%; height: 70vh; min-height: 400px; border: 1px solid var(--ssm-border); border-radius: 8px; background: #fff; }
      .ssm-docx-preview { max-width: 100%; max-height: 70vh; overflow: auto; background: #ffffff; color: #202124; padding: 16px; border: 1px solid var(--ssm-border); border-radius: 8px; }
      .ssm-docx-loading { padding: 16px; color: var(--ssm-muted); font-size: 13px; }
      .ssm-image-attachment { display: flex; flex-direction: column; width: 100%; margin: 2px 0 8px; text-decoration: none; color: var(--primary-text-color); }
      .ssm-image-preview { display: block; max-width: min(100%, 700px); max-height: 550px; object-fit: contain; border: 1px solid var(--ssm-border); border-radius: 10px; background: var(--primary-background-color); }
      .ssm-image-caption { margin-top: 6px; color: var(--ssm-muted); font-size: 12px; }
      .ssm-empty { display: flex; flex-direction: column; align-items: center; justify-content: center; min-height: 420px; padding: 30px; color: var(--ssm-muted); text-align: center; }
      .ssm-empty ha-icon { --mdc-icon-size: 52px; margin-bottom: 14px; opacity: 0.65; }
      @media (max-width: 600px) {
        .ssm-mail-app, .ssm-mail-layout { min-height: 540px; }
        .ssm-mail-layout { grid-template-columns: 42% 58%; }
        .ssm-list-title span { display: none; }
        .ssm-row-date { display: none; }
        .ssm-message-row { grid-template-columns: 14px 60px minmax(0, 1fr); }
        .ssm-avatar-stack { width: 60px; }
        .ssm-avatar { width: 20px; height: 20px; font-size: 9px; }
        .ssm-view-header, .ssm-view-body, .ssm-attachments { padding: 14px 12px; }
        .ssm-address-grid { grid-template-columns: 1fr; gap: 2px; }
        .ssm-address-label { margin-top: 6px; font-size: 11px; text-transform: uppercase; }
      }
    </style>`;
  }
}

console.info("SMARTSCHOOL-MESSAGES-CARD is loaded");

if (!customElements.get("smartschool-messages-card")) {
  customElements.define("smartschool-messages-card", SmartschoolMessagesCard);
}

// See the matching comment in smartschool-results-card.js: this makes any
// card instance already stuck on "Custom element doesn't exist" (because
// Lovelace tried to build it before this module finished loading) self-heal
// as soon as this script registers, instead of needing a manual reload.
window.dispatchEvent(new Event("ll-rebuild", { bubbles: true, composed: true }));

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "smartschool-messages-card")) {
  window.customCards.push({
    type: "smartschool-messages-card",
    name: "Smartschool Messages",
    description: "Toont Smartschool-berichten (mailbox-stijl) met bijlagen en klik-om-te-lezen.",
  });
}
