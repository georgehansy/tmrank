async function loadJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: ${response.status}`);
  }
  return response.json();
}

function isCompactViewport() {
  return window.matchMedia("(max-width: 640px)").matches;
}

let activeTitleTooltipTrigger = null;
let titleTooltipGlobalListenersBound = false;
let titleTooltipCloseTimer = null;
let activeGoatPlayerTooltipTrigger = null;
let goatPlayerTooltipGlobalListenersBound = false;
let goatPlayerTooltipCloseTimer = null;

function formatNumber(value, fractionDigits = 2) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return "—";
  }

  return new Intl.NumberFormat("en", {
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(numericValue);
}

function formatInteger(value) {
  const numericValue = Number(value);
  if (!Number.isFinite(numericValue)) {
    return "—";
  }

  return new Intl.NumberFormat("en", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(numericValue);
}

function formatDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "numeric",
  }).format(date);
}

function formatMonthYear(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    timeZone: "UTC",
  }).format(date);
}

function formatMonthRange(startMonth, endMonth) {
  return `${startMonth} - ${endMonth}`;
}

function monthParts(monthKey) {
  const [year, month] = String(monthKey).split("-").map(Number);
  return { year, month };
}

function monthIndex(monthKey) {
  const { year, month } = monthParts(monthKey);
  return year * 12 + (month - 1);
}

function buildTimelineAxis(rows) {
  if (!rows.length) {
    return [];
  }

  const start = monthParts(rows[0].start_month);
  const end = monthParts(rows[rows.length - 1].end_month);
  const startIndex = monthIndex(rows[0].start_month);
  const endIndex = monthIndex(rows[rows.length - 1].end_month);
  const span = Math.max(1, endIndex - startIndex);
  const labels = [];
  const stepYears = 4;

  for (let year = start.year; year <= end.year; year += 1) {
    const shouldShow =
      year === start.year ||
      year === end.year ||
      (year - start.year) % stepYears === 0;
    if (!shouldShow) continue;
    const index = year * 12;
    const position = ((index - startIndex) / span) * 100;
    labels.push({
      year: String(year),
      position: Math.max(0, Math.min(100, position)),
    });
  }

  return labels;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function initialsForName(name) {
  const parts = String(name)
    .trim()
    .split(/[\s._-]+/)
    .filter(Boolean);

  if (!parts.length) return "TM";
  if (parts.length === 1) {
    return parts[0].slice(0, 2).toUpperCase();
  }
  return `${parts[0][0] ?? ""}${parts[1][0] ?? ""}`.toUpperCase();
}

function hueForName(name) {
  let hash = 0;
  for (const char of String(name)) {
    hash = (hash * 31 + char.charCodeAt(0)) % 360;
  }
  return (hash + 360) % 360;
}

function formatPlacement(value) {
  const placement = Number(value);
  if (!Number.isFinite(placement)) return "—";
  if (placement % 100 >= 11 && placement % 100 <= 13) return `${placement}th`;
  if (placement % 10 === 1) return `${placement}st`;
  if (placement % 10 === 2) return `${placement}nd`;
  if (placement % 10 === 3) return `${placement}rd`;
  return `${placement}th`;
}

function formatPlacementRange(placementLow, placementHigh) {
  const low = Number(placementLow);
  const high = Number(placementHigh);
  if (!Number.isFinite(low)) return "—";
  if (!Number.isFinite(high) || low === high) {
    return formatPlacement(low);
  }
  return `${formatPlacement(low)}-${formatPlacement(high)}`;
}

function formatBestWorldCupResult(result) {
  if (!result) return "—";
  const label = formatPlacementRange(result.placement_low, result.placement_high);
  const count = Number(result.count);
  if (Number.isFinite(count) && count > 1) {
    return `${label} (${count}x)`;
  }
  return label;
}

function formatCareerSpan(firstEventDate, lastEventDate) {
  if (!firstEventDate || !lastEventDate) return "—";
  const firstDate = new Date(firstEventDate);
  const lastDate = new Date(lastEventDate);
  if (Number.isNaN(firstDate.getTime()) || Number.isNaN(lastDate.getTime())) return "—";

  let months =
    (lastDate.getUTCFullYear() - firstDate.getUTCFullYear()) * 12 +
    (lastDate.getUTCMonth() - firstDate.getUTCMonth());
  months = Math.max(0, months);
  if (months === 0) return "same month";

  const years = Math.floor(months / 12);
  const remainingMonths = months % 12;
  if (years > 0 && remainingMonths > 0) {
    return `${years}y ${remainingMonths}m`;
  }
  if (years > 0) {
    return `${years}y`;
  }
  return `${remainingMonths}m`;
}

function formatMajorEventName(value) {
  return String(value)
    .replace(/^Trackmania Grand League\b/, "TMGL")
    .replace(/^Trackmania World Tour\b/, "TMWT");
}

function ensureTimelineFloatingTooltip() {
  let tooltip = document.getElementById("timeline-floating-tooltip");
  if (tooltip) return tooltip;

  tooltip = document.createElement("div");
  tooltip.id = "timeline-floating-tooltip";
  tooltip.className = "timeline-floating-tooltip";
  tooltip.style.display = "none";
  document.body.appendChild(tooltip);
  return tooltip;
}

function positionTimelineFloatingTooltip(segment, tooltip) {
  const rect = segment.getBoundingClientRect();
  const tooltipRect = tooltip.getBoundingClientRect();
  const left = Math.min(
    window.innerWidth - tooltipRect.width - 16,
    Math.max(16, rect.left + rect.width / 2 - tooltipRect.width / 2)
  );
  const top = Math.max(16, rect.top - tooltipRect.height - 14);

  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function bindTimelineTooltips(root) {
  const floatingTooltip = ensureTimelineFloatingTooltip();
  const segments = root.querySelectorAll(".timeline-segment");
  const closeTooltip = () => {
    floatingTooltip.style.display = "none";
    floatingTooltip.innerHTML = "";
  };

  for (const segment of segments) {
    const open = () => {
      segment.dataset.open = "true";
      floatingTooltip.innerHTML = `
        <div class="timeline-floating-tooltip__eyebrow">${escapeHtml(segment.dataset.range ?? "")}</div>
        <div class="timeline-floating-tooltip__player">${escapeHtml(segment.dataset.player ?? "")}</div>
        <div class="timeline-floating-tooltip__meta">
          <span>${escapeHtml(segment.dataset.months ?? "")} months</span>
          <span>peak ${escapeHtml(segment.dataset.peak ?? "")}</span>
        </div>
      `;
      floatingTooltip.style.display = "block";
      positionTimelineFloatingTooltip(segment, floatingTooltip);
    };
    const close = () => {
      segment.dataset.open = "false";
      closeTooltip();
    };

    close();
    segment.addEventListener("pointerenter", open);
    segment.addEventListener("pointerleave", close);
    segment.addEventListener("focus", open);
    segment.addEventListener("blur", close);
  }

  window.addEventListener("scroll", closeTooltip, { passive: true });
  window.addEventListener("resize", closeTooltip);
}

function ensureTitleFloatingTooltip() {
  let tooltip = document.getElementById("title-floating-tooltip");
  if (tooltip) return tooltip;

  tooltip = document.createElement("div");
  tooltip.id = "title-floating-tooltip";
  tooltip.className = "title-floating-tooltip";
  tooltip.style.display = "none";
  document.body.appendChild(tooltip);
  return tooltip;
}

function ensureGoatPlayerFloatingTooltip() {
  let tooltip = document.getElementById("goat-player-floating-tooltip");
  if (tooltip) return tooltip;

  tooltip = document.createElement("div");
  tooltip.id = "goat-player-floating-tooltip";
  tooltip.className = "title-floating-tooltip goat-player-floating-tooltip";
  tooltip.style.display = "none";
  document.body.appendChild(tooltip);
  return tooltip;
}

function positionTitleFloatingTooltip(trigger, tooltip) {
  const rect = trigger.getBoundingClientRect();
  const tooltipRect = tooltip.getBoundingClientRect();
  const offset = 8;
  const left = Math.min(
    window.innerWidth - tooltipRect.width - 16,
    Math.max(16, rect.left + rect.width / 2 - tooltipRect.width / 2)
  );
  const topAbove = rect.top - tooltipRect.height - offset;
  const canPlaceAbove = topAbove >= 16;
  const top = canPlaceAbove
    ? topAbove
    : Math.min(window.innerHeight - tooltipRect.height - 16, rect.bottom + offset);

  tooltip.dataset.position = canPlaceAbove ? "above" : "below";
  tooltip.style.left = `${left}px`;
  tooltip.style.top = `${top}px`;
}

function positionGoatPlayerFloatingTooltip(trigger, tooltip) {
  positionTitleFloatingTooltip(trigger, tooltip);
}

function bindTitleTooltips(root) {
  const tooltip = ensureTitleFloatingTooltip();
  const triggers = root.querySelectorAll("[data-major-results-trigger]");
  const isTooltipSystemTarget = (target) =>
    target instanceof Element &&
    (target.closest("[data-major-results-trigger]") || target.closest(".title-floating-tooltip"));

  const cancelScheduledClose = () => {
    if (titleTooltipCloseTimer !== null) {
      window.clearTimeout(titleTooltipCloseTimer);
      titleTooltipCloseTimer = null;
    }
  };

  const closeTooltip = () => {
    cancelScheduledClose();
    tooltip.style.display = "none";
    tooltip.innerHTML = "";
    delete tooltip.dataset.position;
    if (activeTitleTooltipTrigger) {
      activeTitleTooltipTrigger.dataset.open = "false";
    }
    activeTitleTooltipTrigger = null;
  };

  const scheduleCloseTooltip = () => {
    cancelScheduledClose();
    titleTooltipCloseTimer = window.setTimeout(() => {
      const hoveredTrigger = activeTitleTooltipTrigger?.matches(":hover") ?? false;
      const hoveredTooltip = tooltip.matches(":hover");
      if (hoveredTrigger || hoveredTooltip) {
        return;
      }
      closeTooltip();
    }, 260);
  };

  const openTooltip = (trigger) => {
    cancelScheduledClose();
    const rawResults = trigger.dataset.majorResults;
    if (!rawResults) return;
    const results = JSON.parse(decodeURIComponent(rawResults));
    if (!results.length) return;

    activeTitleTooltipTrigger = trigger;
    trigger.dataset.open = "true";
    tooltip.innerHTML = `
      <div class="title-floating-tooltip__eyebrow">Major podiums</div>
      <div class="title-floating-tooltip__header">
        <div class="title-floating-tooltip__player">${escapeHtml(trigger.dataset.playerName ?? "")}</div>
      </div>
      <div class="title-floating-tooltip__list">
        ${results
          .map((result, index) => {
            const previous = index > 0 ? results[index - 1] : null;
            const showDivider = previous && previous.is_world_cup && !result.is_world_cup;
            return `
              <div class="title-floating-tooltip__item${showDivider ? " title-floating-tooltip__item--group-start" : ""}">
                <span class="title-floating-tooltip__badge title-floating-tooltip__badge--${result.placement}">${escapeHtml(
                  formatPlacement(result.placement)
                )}</span>
                <div class="title-floating-tooltip__item-copy">
                  <div class="title-floating-tooltip__item-name">${escapeHtml(formatMajorEventName(result.event_name))}</div>
                  <div class="title-floating-tooltip__item-meta">
                    ${result.is_world_cup ? '<span class="title-floating-tooltip__tag">World Cup</span>' : ""}
                  </div>
                </div>
              </div>
            `
          })
          .join("")}
      </div>
    `;
    tooltip.style.display = "block";
    positionTitleFloatingTooltip(trigger, tooltip);
  };

  for (const trigger of triggers) {
    const toggleTooltip = (event) => {
      event.preventDefault();
      if (activeTitleTooltipTrigger === trigger) {
        closeTooltip();
        return;
      }
      openTooltip(trigger);
    };

    if (window.matchMedia("(hover: hover)").matches) {
      trigger.addEventListener("pointerenter", () => openTooltip(trigger));
      trigger.addEventListener("pointerleave", (event) => {
        if (activeTitleTooltipTrigger === trigger) {
          if (isTooltipSystemTarget(event.relatedTarget)) {
            cancelScheduledClose();
            return;
          }
          scheduleCloseTooltip();
        }
      });
    }

    trigger.addEventListener("focus", () => openTooltip(trigger));
    trigger.addEventListener("blur", (event) => {
      if (activeTitleTooltipTrigger === trigger) {
        if (isTooltipSystemTarget(event.relatedTarget)) {
          cancelScheduledClose();
          return;
        }
        scheduleCloseTooltip();
      }
    });
    trigger.addEventListener("click", toggleTooltip);
  }

  if (!titleTooltipGlobalListenersBound) {
    tooltip.addEventListener("pointerenter", cancelScheduledClose);
    tooltip.addEventListener("pointerleave", (event) => {
      if (isTooltipSystemTarget(event.relatedTarget)) {
        cancelScheduledClose();
        return;
      }
      scheduleCloseTooltip();
    });
    document.addEventListener("pointerdown", (event) => {
      if (!activeTitleTooltipTrigger) return;
      const target = event.target;
      if (target instanceof Element && target.closest("[data-major-results-trigger]")) return;
      if (target instanceof Element && target.closest(".title-floating-tooltip")) return;
      closeTooltip();
    });
    window.addEventListener("scroll", closeTooltip, { passive: true });
    window.addEventListener("resize", closeTooltip);
    titleTooltipGlobalListenersBound = true;
  }
}

function bindGoatPlayerTooltips(root) {
  const tooltip = ensureGoatPlayerFloatingTooltip();
  const triggers = root.querySelectorAll("[data-goat-player-trigger]");
  const isTooltipSystemTarget = (target) =>
    target instanceof Element &&
    (target.closest("[data-goat-player-trigger]") || target.closest(".goat-player-floating-tooltip"));

  const cancelScheduledClose = () => {
    if (goatPlayerTooltipCloseTimer !== null) {
      window.clearTimeout(goatPlayerTooltipCloseTimer);
      goatPlayerTooltipCloseTimer = null;
    }
  };

  const closeTooltip = () => {
    cancelScheduledClose();
    tooltip.style.display = "none";
    tooltip.innerHTML = "";
    delete tooltip.dataset.position;
    if (activeGoatPlayerTooltipTrigger) {
      activeGoatPlayerTooltipTrigger.dataset.open = "false";
    }
    activeGoatPlayerTooltipTrigger = null;
  };

  const scheduleCloseTooltip = () => {
    cancelScheduledClose();
    goatPlayerTooltipCloseTimer = window.setTimeout(() => {
      const hoveredTrigger = activeGoatPlayerTooltipTrigger?.matches(":hover") ?? false;
      const hoveredTooltip = tooltip.matches(":hover");
      if (hoveredTrigger || hoveredTooltip) {
        return;
      }
      closeTooltip();
    }, 180);
  };

  const openTooltip = (trigger) => {
    cancelScheduledClose();
    const rawInfo = trigger.dataset.goatPlayerInfo;
    if (!rawInfo) return;
    const info = JSON.parse(decodeURIComponent(rawInfo));

    if (activeGoatPlayerTooltipTrigger && activeGoatPlayerTooltipTrigger !== trigger) {
      activeGoatPlayerTooltipTrigger.dataset.open = "false";
    }
    activeGoatPlayerTooltipTrigger = trigger;
    trigger.dataset.open = "true";
    tooltip.innerHTML = `
      <div class="title-floating-tooltip__eyebrow">Career snapshot</div>
      <div class="title-floating-tooltip__header">
        <div class="title-floating-tooltip__player">${escapeHtml(trigger.dataset.playerName ?? "")}</div>
      </div>
      <dl class="goat-player-tooltip__stats">
        <div class="goat-player-tooltip__stat">
          <dt>Events played</dt>
          <dd>${formatInteger(info.events_played)}</dd>
        </div>
        <div class="goat-player-tooltip__stat">
          <dt>Best World Cup</dt>
          <dd>${escapeHtml(formatBestWorldCupResult(info.best_world_cup_result))}</dd>
        </div>
        <div class="goat-player-tooltip__stat">
          <dt>First event</dt>
          <dd>${escapeHtml(formatMonthYear(info.first_event_date))}</dd>
        </div>
        <div class="goat-player-tooltip__stat">
          <dt>Last event</dt>
          <dd>${escapeHtml(formatMonthYear(info.last_event_date))}</dd>
        </div>
        <div class="goat-player-tooltip__stat goat-player-tooltip__stat--wide">
          <dt>Career span</dt>
          <dd>${escapeHtml(formatCareerSpan(info.first_event_date, info.last_event_date))}</dd>
        </div>
      </dl>
    `;
    tooltip.style.display = "block";
    positionGoatPlayerFloatingTooltip(trigger, tooltip);
  };

  for (const trigger of triggers) {
    const toggleTooltip = (event) => {
      event.preventDefault();
      if (activeGoatPlayerTooltipTrigger === trigger) {
        closeTooltip();
        return;
      }
      openTooltip(trigger);
    };

    if (window.matchMedia("(hover: hover)").matches) {
      trigger.addEventListener("pointerenter", () => openTooltip(trigger));
      trigger.addEventListener("pointerleave", (event) => {
        if (activeGoatPlayerTooltipTrigger === trigger) {
          if (isTooltipSystemTarget(event.relatedTarget)) {
            cancelScheduledClose();
            return;
          }
          scheduleCloseTooltip();
        }
      });
    }

    trigger.addEventListener("focus", () => openTooltip(trigger));
    trigger.addEventListener("blur", (event) => {
      if (activeGoatPlayerTooltipTrigger === trigger) {
        if (isTooltipSystemTarget(event.relatedTarget)) {
          cancelScheduledClose();
          return;
        }
        scheduleCloseTooltip();
      }
    });
    trigger.addEventListener("click", toggleTooltip);
  }

  if (!goatPlayerTooltipGlobalListenersBound) {
    tooltip.addEventListener("pointerenter", cancelScheduledClose);
    tooltip.addEventListener("pointerleave", (event) => {
      if (isTooltipSystemTarget(event.relatedTarget)) {
        cancelScheduledClose();
        return;
      }
      scheduleCloseTooltip();
    });
    document.addEventListener("pointerdown", (event) => {
      if (!activeGoatPlayerTooltipTrigger) return;
      const target = event.target;
      if (target instanceof Element && target.closest("[data-goat-player-trigger]")) return;
      if (target instanceof Element && target.closest(".goat-player-floating-tooltip")) return;
      closeTooltip();
    });
    window.addEventListener("scroll", closeTooltip, { passive: true });
    window.addEventListener("resize", closeTooltip);
    goatPlayerTooltipGlobalListenersBound = true;
  }
}

function tableHtml(columns, rows, options = {}) {
  const header = columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns
        .map((column) => `<td>${column.render(row)}</td>`)
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  return `
    <div class="table-scroll">
      <table class="data-table${options.tableClass ? ` ${options.tableClass}` : ""}">
        <thead><tr>${header}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

function goatMobileListHtml(rows) {
  return `
    <div class="goat-mobile-list">
      ${rows
        .map(
          (row) => `
            <article class="goat-mobile-card">
              <div class="goat-mobile-card__header">
                <div class="goat-mobile-card__identity">
                  <span class="rank-pill">${row.rank}</span>
                  <div>
                    <div class="goat-mobile-card__name">${goatPlayerCell(row, { mobile: true })}</div>
                    <div class="goat-mobile-card__label">GOAT score</div>
                  </div>
                </div>
                <div class="goat-mobile-card__score">${formatNumber(row.goat_score, 3)}</div>
              </div>
              <div class="goat-mobile-card__metrics">
                <div class="goat-mobile-metric">
                  <span class="goat-mobile-metric__label">Prime</span>
                  <span class="goat-mobile-metric__value">${formatNumber(row.prime_rating)}</span>
                </div>
                <div class="goat-mobile-metric">
                  <span class="goat-mobile-metric__label">Elite Area</span>
                  <span class="goat-mobile-metric__value">${formatNumber(row.elite_area)}</span>
                </div>
                <div class="goat-mobile-metric">
                  <span class="goat-mobile-metric__label">Median</span>
                  <span class="goat-mobile-metric__value">${formatNumber(row.median_conservative)}</span>
                </div>
                <div class="goat-mobile-metric">
                  <span class="goat-mobile-metric__label">Title Points</span>
                  <span class="goat-mobile-metric__value">${formatInteger(row.title_points)}</span>
                </div>
              </div>
            </article>
          `
        )
        .join("")}
    </div>
  `;
}

function goatRows(payload) {
  return (payload.goat_top20 ?? payload.goat_top25 ?? []).slice(0, 20);
}

function goatPlayerCell(row, options = {}) {
  const hasTooltip =
    row.events_played != null &&
    (row.first_event_date || row.last_event_date || row.best_world_cup_result);
  if (!hasTooltip) {
    return escapeHtml(row.player_name);
  }

  const info = encodeURIComponent(
    JSON.stringify({
      events_played: row.events_played,
      first_event_date: row.first_event_date,
      last_event_date: row.last_event_date,
      best_world_cup_result: row.best_world_cup_result,
    })
  );
  return `
    <button
      type="button"
      class="goat-player-trigger${options.mobile ? " goat-player-trigger--mobile" : ""}"
      data-goat-player-trigger
      data-open="false"
      data-player-name="${escapeHtml(row.player_name)}"
      data-goat-player-info="${info}"
      aria-label="${escapeHtml(`${row.player_name} career snapshot`)}"
    >
      ${escapeHtml(row.player_name)}
    </button>
  `;
}

function currentListHtml(rows) {
  return `
    <div class="current-list">
      <div class="current-list__header" aria-hidden="true">
        <span>Rank</span>
        <span>Player</span>
        <span>Rating</span>
        <span class="current-list__events-heading"><span>Events</span><span>(last 24m)</span></span>
      </div>
      ${rows
        .map(
          (row) => `
            <article class="current-list__row">
              <div class="current-list__rank">
                <span class="rank-pill">${row.rank}</span>
              </div>
              <div class="current-list__player">${escapeHtml(row.player_name)}</div>
              <div class="current-list__rating">
                <span class="current-list__mobile-label">Rating</span>
                <strong>${formatNumber(row.conservative_score)}</strong>
              </div>
              <div class="current-list__events">
                <span class="current-list__mobile-label">Events (last 24m)</span>
                <strong>${row.recent_events_24_months ?? row.events_played}</strong>
              </div>
            </article>
          `
        )
        .join("")}
    </div>
  `;
}

function renderGoatTable(payload) {
  const rows = goatRows(payload);
  const root = document.getElementById("goat-table");
  if (isCompactViewport()) {
    root.innerHTML = goatMobileListHtml(rows);
    bindGoatPlayerTooltips(root);
    return;
  }

  const columns = [
    { label: "Rank", render: (row) => `<span class="rank-pill">${row.rank}</span>` },
    { label: "Player", render: (row) => goatPlayerCell(row) },
    { label: "GOAT", render: (row) => `<span class="metric-strong">${formatNumber(row.goat_score, 3)}</span>` },
    { label: "Prime", render: (row) => formatNumber(row.prime_rating) },
    { label: "Elite Area", render: (row) => formatNumber(row.elite_area) },
    { label: "Median", render: (row) => formatNumber(row.median_conservative) },
    { label: "Title Points", render: (row) => formatInteger(row.title_points) },
  ];
  root.innerHTML = tableHtml(columns, rows, { tableClass: "data-table--goat" });
  bindGoatPlayerTooltips(root);
}

function renderCurrentTable(payload) {
  document.getElementById("current-table").innerHTML = currentListHtml(payload.current_top10);
}

function titlePointsCell(row) {
  return `<strong class="metric-strong">${formatInteger(row.title_points)}</strong>`;
}

function titleLeadersListHtml(rows) {
  return `
    <div class="current-list current-list--titles">
      <div class="current-list__header" aria-hidden="true">
        <span>Rank</span>
        <span>Player</span>
        <span>Title Points</span>
        <span>Events</span>
      </div>
      ${rows
        .map((row) => {
          const hasPodiums = Boolean(row.major_podium_results?.length);
          const tooltipLabel = `${row.player_name} major podium results`;
          return `
            <article
              class="current-list__row${hasPodiums ? " current-list__row--interactive" : ""}"
              ${hasPodiums ? 'data-major-results-trigger data-open="false" tabindex="0" role="button"' : ""}
              ${hasPodiums ? `data-player-name="${escapeHtml(row.player_name)}"` : ""}
              ${hasPodiums ? `data-major-results="${encodeURIComponent(JSON.stringify(row.major_podium_results))}"` : ""}
              ${hasPodiums ? `aria-label="${escapeHtml(tooltipLabel)}"` : ""}
            >
              <div class="current-list__rank">
                <span class="rank-pill">${row.rank}</span>
              </div>
              <div class="current-list__player">${escapeHtml(row.player_name)}</div>
              <div class="current-list__rating">
                <span class="current-list__mobile-label">Title Points</span>
                ${titlePointsCell(row)}
              </div>
              <div class="current-list__events">
                <span class="current-list__mobile-label">Events</span>
                <strong>${row.events_played}</strong>
              </div>
            </article>
          `;
        })
        .join("")}
    </div>
  `;
}

function renderTitlesTable(payload) {
  const root = document.getElementById("titles-table");
  root.innerHTML = titleLeadersListHtml(payload.title_leaders_top10);
  bindTitleTooltips(root);
}

function buildTimelineSummary(rows) {
  if (!rows.length) {
    return [];
  }

  const longestReign = rows.reduce((best, row) => (row.months > best.months ? row : best), rows[0]);
  const totalReignMonths = new Map();
  for (const row of rows) {
    totalReignMonths.set(row.player_name, (totalReignMonths.get(row.player_name) || 0) + row.months);
  }

  const longestTotalReignEntry = [...totalReignMonths.entries()].reduce(
    (best, entry) => {
      if (!best) return entry;
      const [bestName, bestMonths] = best;
      const [name, months] = entry;
      if (months > bestMonths) return entry;
      if (months === bestMonths && name.localeCompare(bestName) < 0) return entry;
      return best;
    },
    null
  );

  return [
    {
      label: "Longest uninterrupted reign",
      value: `${longestReign.player_name}`,
      meta: `${longestReign.months} months`,
    },
    {
      label: "Longest total reign",
      value: longestTotalReignEntry ? longestTotalReignEntry[0] : "—",
      meta: longestTotalReignEntry ? `${longestTotalReignEntry[1]} months` : "—",
    },
  ];
}

function dominantTimelinePlayer(rows) {
  if (!rows.length) {
    return null;
  }

  const totals = new Map();
  for (const row of rows) {
    totals.set(row.player_name, (totals.get(row.player_name) || 0) + row.months);
  }

  return [...totals.entries()].reduce((best, entry) => {
    if (!best) return entry;
    const [bestName, bestMonths] = best;
    const [name, months] = entry;
    if (months > bestMonths) return entry;
    if (months === bestMonths && name.localeCompare(bestName) < 0) return entry;
    return best;
  }, null)?.[0] ?? null;
}

function renderTimeline(payload) {
  const timelineRows = payload.rating_leader_timeline ?? payload.goat_timeline ?? [];
  const summary = buildTimelineSummary(timelineRows);
  const dominantPlayer = dominantTimelinePlayer(timelineRows);
  const axisLabels = buildTimelineAxis(timelineRows);
  const summaryHtml = summary.length
    ? `
      <div class="timeline-summary">
        ${summary
          .map(
            (item) => `
              <article class="timeline-stat">
                <span class="timeline-stat__label">${escapeHtml(item.label)}</span>
                <strong class="timeline-stat__value">${escapeHtml(item.value)}</strong>
                <span class="timeline-stat__meta">${escapeHtml(item.meta)}</span>
              </article>
            `
          )
          .join("")}
      </div>
    `
    : "";
  const axisHtml = axisLabels.length
    ? `
      <div class="timeline-axis">
        ${axisLabels
          .map(
            (label) => `
              <div class="timeline-axis__tick${label.position <= 0 ? " timeline-axis__tick--start" : ""}${label.position >= 100 ? " timeline-axis__tick--end" : ""}" style="left:${label.position}%">
                <span class="timeline-axis__line"></span>
                <span class="timeline-axis__label">${escapeHtml(label.year)}</span>
              </div>
            `
          )
          .join("")}
      </div>
    `
    : "";

  const segments = timelineRows
    .map((row, index) => {
      const showInitials = row.months >= 4;
      return `
        <div
          class="timeline-segment${row.player_name === dominantPlayer ? " timeline-segment--dominant" : ""}${showInitials ? "" : " timeline-segment--compact"}"
          style="--segment-weight:${row.months}; --accent-index:${index % 4}; --player-hue:${hueForName(row.player_name)}; --player-hue-2:${(hueForName(row.player_name) + 28) % 360}"
          data-range="${escapeHtml(formatMonthRange(row.start_month, row.end_month))}"
          data-player="${escapeHtml(row.player_name)}"
          data-months="${row.months}"
          data-peak="${formatNumber(row.peak_conservative)}"
          aria-label="${escapeHtml(
            `${row.player_name}, ${formatMonthRange(row.start_month, row.end_month)}, ${row.months} months, peak ${formatNumber(row.peak_conservative)}`
          )}"
          tabindex="0"
        >
          ${showInitials ? `<span class="timeline-segment__label timeline-segment__label--initials">${escapeHtml(initialsForName(row.player_name))}</span>` : ""}
        </div>
      `;
    })
    .join("");
  document.getElementById("timeline").innerHTML = `
    ${summaryHtml}
    <div class="timeline-ribbon-wrap">
      <div class="timeline-scroll">
        <div class="timeline-ribbon-stage">
          <div class="timeline-ribbon">
            ${segments}
          </div>
          ${axisHtml}
        </div>
      </div>
      <p class="timeline-ribbon__hint">Hover a segment for player, era, reign length, and peak.</p>
    </div>
  `;
  bindTimelineTooltips(document.getElementById("timeline"));
}

function miniList(rows, valueKey, formatter, options = {}) {
  return `
    <ol class="mini-list">
      ${rows
        .map((row) => {
          const hasPodiums = Boolean(options.podiumTooltips && row.major_podium_results?.length);
          const tooltipLabel = `${row.player_name} major podium results`;
          return `
            <li
              class="mini-list__row${hasPodiums ? " mini-list__row--interactive" : ""}"
              ${hasPodiums ? 'data-major-results-trigger data-open="false" tabindex="0" role="button"' : ""}
              ${hasPodiums ? `data-player-name="${escapeHtml(row.player_name)}"` : ""}
              ${hasPodiums ? `data-major-results="${encodeURIComponent(JSON.stringify(row.major_podium_results))}"` : ""}
              ${hasPodiums ? `aria-label="${escapeHtml(tooltipLabel)}"` : ""}
            >
              <div class="mini-list__identity">
                <span class="mini-rank-pill">${row.rank}</span>
                <span class="mini-list__name">${escapeHtml(row.player_name)}</span>
              </div>
              <div class="mini-list__score">
                ${options.valueLabel ? `<span class="mini-list__value-label">${escapeHtml(options.valueLabel)}</span>` : ""}
                <strong class="mini-list__value">${formatter(row[valueKey])}</strong>
              </div>
            </li>
          `;
        })
        .join("")}
    </ol>
  `;
}

function renderProfileCards(manifest, payloadsByProfile) {
  const cards = manifest.profiles
    .filter((profile) => !profile.is_default)
    .map((profile) => {
      const payload = payloadsByProfile[profile.name];
      if (!payload) return "";
      return `
        <article class="card profile-card">
          <p class="section__eyebrow">Profile</p>
          <h3>${escapeHtml(profile.label)}</h3>
          <p class="stat__label">GOAT top 5</p>
          ${miniList(goatRows(payload).slice(0, 5), "goat_score", (value) => formatNumber(value, 3), {
            podiumTooltips: true,
            valueLabel: "GOAT",
          })}
        </article>
      `;
    })
    .join("");

  const root = document.getElementById("profile-cards");
  root.innerHTML = cards || `<div class="notice">No alternate profiles were exported yet.</div>`;
  bindTitleTooltips(root);
}

function applyManifestMeta(manifest) {
  const heroUpdated = document.getElementById("hero-updated");
  const footerUpdated = document.getElementById("footer-updated");

  if (heroUpdated) {
    heroUpdated.textContent = formatDate(manifest.generated_at);
  }
  if (footerUpdated) {
    footerUpdated.textContent = `Updated: ${formatDate(manifest.generated_at)}`;
  }

  if (manifest.repo_url) {
    for (const repoLink of document.querySelectorAll("[data-repo-link]")) {
      repoLink.href = manifest.repo_url;
      repoLink.classList.remove("is-hidden");
    }
  }
}

function renderPage(manifest, payloadsByProfile) {
  const defaultPayload = payloadsByProfile[manifest.default_profile];
  renderGoatTable(defaultPayload);
  renderCurrentTable(defaultPayload);
  renderTitlesTable(defaultPayload);
  renderTimeline(defaultPayload);
  renderProfileCards(manifest, payloadsByProfile);
}

function renderError(error) {
  const message = `<div class="notice">Failed to load site data. ${escapeHtml(error.message)}</div>`;
  document.getElementById("goat-table").innerHTML = message;
  document.getElementById("current-table").innerHTML = message;
  document.getElementById("titles-table").innerHTML = message;
  document.getElementById("timeline").innerHTML = message;
  document.getElementById("profile-cards").innerHTML = message;
}

async function main() {
  try {
    const manifest = await loadJson("./data/site-manifest.json");
    applyManifestMeta(manifest);

    const payloadEntries = await Promise.all(
      manifest.profiles.map(async (profile) => [profile.name, await loadJson(`./data/${profile.path}`)])
    );
    const payloadsByProfile = Object.fromEntries(payloadEntries);
    renderPage(manifest, payloadsByProfile);

    let compactViewport = isCompactViewport();
    window.addEventListener("resize", () => {
      const nextCompactViewport = isCompactViewport();
      if (nextCompactViewport === compactViewport) return;
      compactViewport = nextCompactViewport;
      renderPage(manifest, payloadsByProfile);
    });
  } catch (error) {
    renderError(error);
  }
}

main();
