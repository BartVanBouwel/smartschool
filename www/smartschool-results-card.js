// Smartschool results card -- native Lovelace custom card (no Jinja / html-template-card needed).
//
// Usage in a dashboard:
//   type: custom:smartschool-results-card
//   title: Alex
//   child: alex        # matches sensor.<child>_result_* entities
//
// Ported from a hand-built html-template-card. Key differences from that version:
// - Marks a result read via a direct hass.callService() to smartschool.mark_result_read,
//   no webhook/automation detour needed (this card has a real hass object).
// - Open/closed <details> state is kept in a JS Map across re-renders instead of the
//   localStorage + hidden-<img onerror> bootstrap trick the Jinja version needed (that
//   trick existed only because html-template-card replaces its whole innerHTML on every
//   entity-state change and can't run <script> tags inserted that way).

const COLOR_MAP = {
  amber: "#ffc107",
  "blue-grey": "#607d8b",
  "deep-orange": "#ff5722",
  "deep-purple": "#673ab7",
  "light-blue": "#03a9f4",
  "light-green": "#8bc34a",
};
function isTruthy(value) {
  return value === true || String(value).toLowerCase() === "true";
}

function fmtDate(value, locale) {
  if (!value) return "";
  const d = new Date(value);
  if (Number.isNaN(d.getTime())) return String(value);
  return d.toLocaleDateString(locale || "nl-BE", { day: "2-digit", month: "2-digit", year: "numeric" });
}

function escapeHtml(str) {
  return String(str).replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

function titleCase(str) {
  return String(str).replace(/[_\s]+/g, " ").trim().replace(/\w\S*/g, (w) => w[0].toUpperCase() + w.slice(1));
}

const DEFAULTS = {
  language: "nl",
  show_chart: true,
  show_average: true,
  include_non_counting: false,
  course_color: [33, 150, 243],
  period_color: [220, 230, 242],
  result_color: [23, 23, 23],
  unread_color: [255, 215, 0],
  course_icon: "mdi:book-education-outline",
  period_icon: "mdi:calendar-range",
  result_icon: "",
};

// Editor UI itself is always in English; STRINGS below controls the language
// the rendered card's own text is shown in (independent setting).
const LABELS = {
  child: "Child",
  title: "Title (optional)",
  language: "Card language",
  details: "Details",
  show_chart: "Show chart",
  show_average: "Show average",
  include_non_counting: 'Include non-counting results ("does_count: false") in average/chart',
  course_color: "Course background color (applied semi-transparent)",
  period_color: "Period background color",
  result_color: "Result background color",
  unread_color: "Color of the new/unread result dot",
  course_icon: "Course icon",
  period_icon: "Period icon",
  result_icon: "Result icon (empty = icon from Smartschool itself)",
};

const STRINGS = {
  nl: {
    schoolYearAvg: "schooljaar gem.",
    avg: "gem.",
    achieved: "Behaald",
    resultDate: "Resultaatdatum",
    availableSince: "Beschikbaar sinds",
    component: "Onderdeel",
    teacher: "Leerkracht",
    feedback: "Feedback:",
    notApplicable: "n.v.t.",
    unknown: "Onbekend",
    doesCount: "Telt mee voor gemiddelde",
    yes: "Ja",
    no: "Nee",
    noResults: (child) => `Geen resultaten gevonden voor "${child}".`,
    chooseChild: 'Kies een kind in de kaartinstellingen (veld "child").',
    dateLocale: "nl-BE",
  },
  en: {
    schoolYearAvg: "school year avg.",
    avg: "avg.",
    achieved: "Achieved",
    resultDate: "Result date",
    availableSince: "Available since",
    component: "Component",
    teacher: "Teacher",
    feedback: "Feedback:",
    notApplicable: "n/a",
    unknown: "Unknown",
    doesCount: "Counts towards average",
    yes: "Yes",
    no: "No",
    noResults: (child) => `No results found for "${child}".`,
    chooseChild: 'Choose a child in the card settings ("child" field).',
    dateLocale: "en-GB",
  },
};

function getStrings(language) {
  return STRINGS[language] || STRINGS.nl;
}

// Config values from the color_rgb selector come back as [r, g, b] arrays; older
// configs (saved before this became a color picker) may still have a plain CSS
// string, so both are accepted here.
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
    const match = entityId.match(/^sensor\.(.+)_result_/);
    if (match) children.add(match[1]);
  }
  return Array.from(children).sort();
}

class SmartschoolResultsCardEditor extends HTMLElement {
  setConfig(config) {
    this._config = config;
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
    this._form.data = { ...DEFAULTS, ...this._config };
    this._form.schema = [
      {
        name: "child",
        required: true,
        selector: { select: { mode: "dropdown", options: children.map((c) => ({ value: c, label: titleCase(c) })) } },
      },
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
        name: "details",
        type: "expandable",
        title: "Details",
        icon: "mdi:tune",
        flatten: true,
        schema: [
          { name: "show_chart", selector: { boolean: {} } },
          { name: "show_average", selector: { boolean: {} } },
          { name: "include_non_counting", selector: { boolean: {} } },
          { name: "course_icon", selector: { icon: {} } },
          { name: "period_icon", selector: { icon: {} } },
          { name: "result_icon", selector: { icon: {} } },
          { name: "course_color", selector: { color_rgb: {} } },
          { name: "period_color", selector: { color_rgb: {} } },
          { name: "result_color", selector: { color_rgb: {} } },
          { name: "unread_color", selector: { color_rgb: {} } },
        ],
      },
    ];
    this._form.computeLabel = (schema) => LABELS[schema.name] || schema.name;

    if (!this._resetBtn) {
      this._resetBtn = document.createElement("mwc-button");
      this._resetBtn.setAttribute("outlined", "");
      this._resetBtn.style.marginTop = "12px";
      this._resetBtn.addEventListener("click", () => {
        const resetFields = [
          "course_color", "period_color", "result_color", "unread_color",
          "course_icon", "period_icon", "result_icon",
        ];
        const next = { ...this._config };
        for (const field of resetFields) next[field] = DEFAULTS[field];
        this._config = next;
        this._form.data = { ...DEFAULTS, ...this._config };
        this.dispatchEvent(new CustomEvent("config-changed", { detail: { config: this._config }, bubbles: true, composed: true }));
      });
      this.appendChild(this._resetBtn);
    }
    this._resetBtn.textContent = this._config.language === "en" ? "Reset colors & icons to default" : "Kleuren & iconen terugzetten naar standaard";
  }
}

if (!customElements.get("smartschool-results-card-editor")) {
  customElements.define("smartschool-results-card-editor", SmartschoolResultsCardEditor);
}

class SmartschoolResultsCard extends HTMLElement {
  setConfig(config) {
    // Never throw here: the card picker/preview dialog can call this with an
    // empty/stub config (e.g. no result sensors loaded yet) and doesn't catch
    // exceptions from it, which left the preview stuck on a spinner forever
    // instead of showing a normal card-level error. Missing config is instead
    // handled as a render-time state, same as any other custom card.
    this._config = config || {};
    this._entityPrefix = this._config.child ? `sensor.${this._config.child.toLowerCase()}_result` : null;
    this._openState = new Map();
    this._lastSignature = null;
    if (!this._card) {
      this._card = document.createElement("ha-card");
      this._root = document.createElement("div");
      this._root.style.padding = "8px 12px 12px";
      this._card.appendChild(this._root);
      this.appendChild(this._card);
      this._refreshBtn = document.createElement("ha-icon-button");
      this._refreshBtn.style.position = "absolute";
      this._refreshBtn.style.top = "4px";
      this._refreshBtn.style.right = "4px";
      this._refreshBtn.style.zIndex = "2";
      this._refreshBtn.setAttribute("path", "M17.65,6.35C16.2,4.9 14.21,4 12,4A8,8 0 0,0 4,12A8,8 0 0,0 12,20C15.73,20 18.84,17.45 19.73,14H17.65C16.83,16.33 14.61,18 12,18A6,6 0 0,1 6,12A6,6 0 0,1 12,6C13.66,6 15.14,6.69 16.22,7.78L13,11H20V4L17.65,6.35Z");
      this._refreshBtn.addEventListener("click", () => {
        if (!this._hass) return;
        const data = {};
        if (this._lastEntityId) data.entity_id = this._lastEntityId;
        this._refreshBtn.classList.add("ssrc-spin");
        this._hass.callService("smartschool", "refresh", data)
          .catch((err) => console.error("smartschool-results-card: refresh failed", err))
          .finally(() => setTimeout(() => this._refreshBtn.classList.remove("ssrc-spin"), 600));
      });
      this._card.appendChild(this._refreshBtn);
      const style = document.createElement("style");
      style.textContent = "@keyframes ssrc-spin{to{transform:rotate(360deg);}} .ssrc-spin{animation:ssrc-spin 0.6s linear;}";
      this._card.appendChild(style);
    }
    this._card.header = this._config.title || (this._config.child ? titleCase(this._config.child) : "Smartschool Results");
    if (!this._config.child) {
      const t = getStrings(this._config.language);
      this._root.innerHTML = `<div style="padding:16px;opacity:0.7;">${escapeHtml(t.chooseChild)}</div>`;
    }
  }

  set hass(hass) {
    this._hass = hass;
    if (!this._entityPrefix) return;
    const items = this._collectItems(hass);
    const signature = JSON.stringify(items.map((it) => [it.entityId, it.state, it.unread]));
    if (signature === this._lastSignature) return;
    this._lastSignature = signature;
    this._render(items);
  }

  getCardSize() {
    return 6;
  }

  static getConfigElement() {
    return document.createElement("smartschool-results-card-editor");
  }

  static getStubConfig(hass) {
    const children = detectChildren(hass);
    return { child: children[0] || "", title: "" };
  }

  _collectItems(hass) {
    const items = [];
    for (const entityId of Object.keys(hass.states)) {
      if (!entityId.startsWith(this._entityPrefix)) continue;
      const st = hass.states[entityId];
      const a = st.attributes || {};
      const period = a.period || null;
      const component = a.component || null;
      items.push({
        entityId,
        course: a.course_name || "",
        trimester: (period && period.name) || "",
        date: a.result_date,
        availabilityDate: a.availability_date,
        name: a.result_name,
        component: component && component.name,
        state: st.state,
        color: a.graphic_color || "grey",
        icon: a.icon || "mdi:school-outline",
        achieved: parseFloat(a.achieved_points) || 0,
        total: parseFloat(a.total_points) || 0,
        pct: parseFloat(a.graphic_value) || 0,
        doesCount: isTruthy(a.does_count),
        feedback: a.feedback,
        teacher: a.Teacher || "",
        unread: isTruthy(a.unread),
      });
    }
    return items;
  }

  _captureOpenState() {
    this._root.querySelectorAll("details[data-key]").forEach((d) => {
      this._openState.set(d.getAttribute("data-key"), d.open);
    });
  }

  _restoreOpenState() {
    this._root.querySelectorAll("details[data-key]").forEach((d) => {
      const key = d.getAttribute("data-key");
      if (this._openState.has(key)) d.open = this._openState.get(key);
    });
  }

  _markRead(item, dotEl) {
    if (dotEl) dotEl.style.display = "none";
    this._openState.set(`item:${item.entityId}`, true);
    this._hass.callService("smartschool", "mark_result_read", { entity_id: item.entityId }).catch((err) => {
      console.error("smartschool-results-card: mark_result_read failed", err);
    });
  }

  _buildChartSvg(counted, avg) {
    const n = counted.length;
    if (n === 0) return "";
    const denom = n > 1 ? n - 1 : 1;
    const x0 = 26, w = 274, top = 9, bottom = 62, h = bottom - top;
    const pctToY = (pct) => (top + (100 - Math.max(0, Math.min(100, pct))) / 100 * h).toFixed(1);

    let grid = "";
    for (let step = 0; step <= 100; step += 10) {
      const gy = pctToY(step);
      const major = step === 0 || step === 50 || step === 100;
      grid += `<line x1="${x0}" y1="${gy}" x2="300" y2="${gy}" stroke="rgba(58,58,58,${major ? 0.4 : 0.18})" stroke-width="${major ? 1.5 : 1}"></line>`;
      if (major) {
        grid += `<text x="${x0 - 4}" y="${Number(gy) + 3}" text-anchor="end" font-size="9" fill="rgba(58,58,58,0.75)">${step}%</text>`;
      }
    }

    const sorted = counted.slice().sort((a, b) => new Date(a.date) - new Date(b.date));
    const points = sorted.map((it, i) => `${(x0 + (i / denom) * w).toFixed(1)},${pctToY(it.pct)}`).join(" ");
    const circles = sorted.map((it, i) => {
      const cx = (x0 + (i / denom) * w).toFixed(1);
      const cy = pctToY(it.pct);
      const color = COLOR_MAP[it.color] || it.color;
      return `<circle cx="${cx}" cy="${cy}" r="3.5" fill="${color}"><title>${escapeHtml(it.name)}: ${it.pct}%</title></circle>`;
    }).join("");

    return `<svg viewBox="0 0 300 70" preserveAspectRatio="none" style="width:100%;height:70px;display:block;margin:2px 0 6px;">
      ${grid}
      <polyline fill="none" stroke="#64b5f6" stroke-width="2" points="${points}"></polyline>
      ${circles}
    </svg>`;
  }

  _feedbackHtml(feedback, strings) {
    let entries = [];
    if (typeof feedback === "string") {
      const trimmed = feedback.trim();
      if (trimmed) entries.push({ name: "", text: trimmed });
    } else if (Array.isArray(feedback)) {
      for (const fb of feedback) {
        const text = (fb && typeof fb === "object" ? fb.text : typeof fb === "string" ? fb : "") || "";
        const trimmed = text.trim();
        if (!trimmed) continue;
        const name = (fb && fb.user && fb.user.name && fb.user.name.startingWithFirstName) || "";
        entries.push({ name, text: trimmed });
      }
    }
    if (!entries.length) return "";
    return `<div style="margin-top:6px;font-weight:600;">${escapeHtml(strings.feedback)}</div>` + entries.map((fb) => `
      <div style="margin-top:2px;padding:6px 8px;background:rgba(255,255,255,0.05);border-radius:4px;">
        ${fb.name ? `<div style="font-weight:600;opacity:0.85;">${escapeHtml(fb.name)}</div>` : ""}
        <div style="white-space:pre-wrap;">${escapeHtml(fb.text)}</div>
      </div>`).join("");
  }

  _render(items) {
    this._captureOpenState();
    this._lastEntityId = items[0] ? items[0].entityId : null;

    const opts = { ...DEFAULTS, ...this._config };
    const t = getStrings(opts.language);
    const courseColor = colorToCss(opts.course_color, 0.12);
    const periodColor = colorToCss(opts.period_color);
    const resultColor = colorToCss(opts.result_color);
    const unreadColor = colorToCss(opts.unread_color);

    const byCourse = new Map();
    for (const it of items) {
      if (!byCourse.has(it.course)) byCourse.set(it.course, []);
      byCourse.get(it.course).push(it);
    }

    const countsForAvg = (it) => opts.include_non_counting || it.doesCount;

    let html = "";
    for (const [course, courseItems] of byCourse) {
      const counted = courseItems.filter(countsForAvg);
      const avg = counted.length ? `${(counted.reduce((s, it) => s + it.pct, 0) / counted.length).toFixed(1)}%` : t.notApplicable;
      const unread = courseItems.some((it) => it.unread);
      const icon = unread ? "mdi:circle" : opts.course_icon;
      const iconColor = unread ? unreadColor : "inherit";
      const iconSize = unread ? "12px" : "18px";
      const avgHtml = opts.show_average ? `<span style="font-weight:normal;opacity:0.75;"> — ${escapeHtml(t.schoolYearAvg)}: ${avg}</span>` : "";
      const courseLabel = course || t.unknown;

      html += `<details data-key="course:${escapeHtml(course)}" style="margin-bottom:10px;background:${courseColor};border-radius:8px;overflow:hidden;">
        <summary style="display:flex;align-items:center;font-weight:bold;padding:8px 10px;cursor:pointer;">
          <ha-icon icon="${icon}" style="margin-right:8px;--mdc-icon-size:${iconSize};color:${iconColor};opacity:0.9;"></ha-icon>
          <span>${escapeHtml(courseLabel)}${avgHtml}</span>
        </summary>
        <div style="padding:4px 10px 8px 10px;">`;

      const byTri = new Map();
      for (const it of courseItems) {
        if (!byTri.has(it.trimester)) byTri.set(it.trimester, []);
        byTri.get(it.trimester).push(it);
      }

      for (const [trimester, triItems] of byTri) {
        const triCounted = triItems.filter(countsForAvg);
        const triAvg = triCounted.length ? `${(triCounted.reduce((s, it) => s + it.pct, 0) / triCounted.length).toFixed(1)}%` : t.notApplicable;
        const triUnread = triItems.some((it) => it.unread);
        const triIcon = triUnread ? "mdi:circle" : opts.period_icon;
        const triIconColor = triUnread ? unreadColor : "#000000";
        const triIconSize = triUnread ? "12px" : "16px";
        const triAvgHtml = opts.show_average ? ` — ${escapeHtml(t.avg)}: ${triAvg}` : "";
        const trimesterLabel = trimester || t.unknown;

        html += `<details open data-key="tri:${escapeHtml(course)}:${escapeHtml(trimester)}" style="margin:6px 0;background:${periodColor};border-radius:6px;overflow:hidden;color:#ffffff;">
          <summary style="display:flex;align-items:center;font-weight:600;padding:5px 8px;cursor:pointer;opacity:0.95;color:#000000;">
            <ha-icon icon="${triIcon}" style="margin-right:8px;--mdc-icon-size:${triIconSize};color:${triIconColor};opacity:0.9;"></ha-icon>
            <span>${escapeHtml(trimesterLabel)}${triAvgHtml}</span>
          </summary>
          ${opts.show_chart ? this._buildChartSvg(triCounted, triAvg) : ""}
          <div style="padding:2px 8px 6px 8px;">`;

        const sortedItems = triItems.slice().sort((a, b) => new Date(a.date) - new Date(b.date));
        for (const item of sortedItems) {
          const color = COLOR_MAP[item.color] || item.color;
          const itemIcon = opts.result_icon || item.icon;
          html += `<details data-key="item:${item.entityId}" style="background:${resultColor};border-radius:10px;margin:3px 0;overflow:hidden;">
            <summary data-entity="${item.entityId}" data-unread="${item.unread}" style="display:flex;align-items:center;padding:5px 8px;cursor:pointer;list-style:revert;">
              ${item.unread ? `<span class="ssrc-dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${unreadColor};box-shadow:0 0 0 3px ${colorToCss(opts.unread_color, 0.2)};margin-right:8px;flex:0 0 auto;"></span>` : ""}
              <ha-icon icon="${itemIcon}" style="margin-right:8px;--mdc-icon-size:18px;opacity:0.9;"></ha-icon>
              <span style="flex:1;">${fmtDate(item.date, t.dateLocale)}: ${escapeHtml(item.name)}</span>
              <span style="text-align:right;min-width:48px;color:${color};font-weight:bold;margin-left:8px;">${escapeHtml(item.state)}</span>
            </summary>
            <div style="padding:6px 10px 10px 34px;font-size:0.9em;opacity:0.9;">
              ${item.component ? `<div>${escapeHtml(t.component)}: ${escapeHtml(item.component)}</div>` : ""}
              ${item.teacher ? `<div>${escapeHtml(t.teacher)}: ${escapeHtml(item.teacher)}</div>` : ""}
              <div>${escapeHtml(t.achieved)}: ${item.achieved} / ${item.total} (${item.pct}%)</div>
              <div>${escapeHtml(t.doesCount)}: ${item.doesCount ? escapeHtml(t.yes) : escapeHtml(t.no)}</div>
              <div>${escapeHtml(t.resultDate)}: ${fmtDate(item.date, t.dateLocale)}</div>
              ${item.availabilityDate ? `<div>${escapeHtml(t.availableSince)}: ${fmtDate(item.availabilityDate, t.dateLocale)}</div>` : ""}
              ${this._feedbackHtml(item.feedback, t)}
            </div>
          </details>`;
        }

        html += `</div></details>`;
      }

      html += `</div></details>`;
    }

    this._root.innerHTML = html || `<div style="padding:16px;opacity:0.7;">${escapeHtml(t.noResults(this._config.child))}</div>`;

    this._root.querySelectorAll("summary[data-entity]").forEach((summary) => {
      if (summary.dataset.unread !== "true") return;
      summary.addEventListener("click", () => {
        const entityId = summary.dataset.entity;
        const item = { entityId };
        const dot = summary.querySelector(".ssrc-dot");
        summary.dataset.unread = "false";
        this._markRead(item, dot);
      }, { once: true });
    });

    this._restoreOpenState();
  }
}

console.info("SMARTSCHOOL-RESULTS-CARD is loaded");

if (!customElements.get("smartschool-results-card")) {
  customElements.define("smartschool-results-card", SmartschoolResultsCard);
}

// On a page with many competing resources, this module can finish loading
// after Lovelace already tried (and failed) to build any "custom:smartschool-results-card"
// cards, leaving them stuck on "Custom element doesn't exist" until a manual
// reload. "ll-rebuild" is the event Home Assistant's own dashboard listens for
// to rebuild the current view's cards; firing it here makes already-broken
// instances self-heal within a moment of this script finishing, instead of
// requiring the user to notice and refresh.
window.dispatchEvent(new Event("ll-rebuild", { bubbles: true, composed: true }));

window.customCards = window.customCards || [];
if (!window.customCards.some((c) => c.type === "smartschool-results-card")) {
  window.customCards.push({
    type: "smartschool-results-card",
    name: "Smartschool Results",
    description: "Toont Smartschool-resultaten per cursus en periode, met unread-status en grafiek per periode.",
  });
}
