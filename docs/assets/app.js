async function loadJson(path) {
  const response = await fetch(path, { cache: "no-store" });
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: ${response.status}`);
  }
  return response.json();
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

function tableHtml(columns, rows) {
  const header = columns.map((column) => `<th>${escapeHtml(column.label)}</th>`).join("");
  const body = rows
    .map((row) => {
      const cells = columns
        .map((column) => `<td>${column.render(row)}</td>`)
        .join("");
      return `<tr>${cells}</tr>`;
    })
    .join("");
  return `<table><thead><tr>${header}</tr></thead><tbody>${body}</tbody></table>`;
}

function renderGoatTable(payload) {
  const columns = [
    { label: "Rank", render: (row) => `<span class="rank-pill">${row.rank}</span>` },
    { label: "Player", render: (row) => escapeHtml(row.player_name) },
    { label: "GOAT", render: (row) => `<span class="metric-strong">${row.goat_score.toFixed(4)}</span>` },
    { label: "Prime", render: (row) => row.prime_rating.toFixed(4) },
    { label: "Elite Area", render: (row) => row.elite_area.toFixed(1) },
    { label: "Median", render: (row) => row.median_conservative.toFixed(4) },
    { label: "Titles", render: (row) => row.title_points.toFixed(1) },
  ];
  document.getElementById("goat-table").innerHTML = tableHtml(columns, payload.goat_top20);
}

function renderCurrentTable(payload) {
  const columns = [
    { label: "Rank", render: (row) => `<span class="rank-pill">${row.rank}</span>` },
    { label: "Player", render: (row) => escapeHtml(row.player_name) },
    { label: "Rating", render: (row) => `<span class="metric-strong">${row.conservative_score.toFixed(4)}</span>` },
    { label: "Events (24m)", render: (row) => String(row.recent_events_24_months ?? row.events_played) },
  ];
  document.getElementById("current-table").innerHTML = tableHtml(columns, payload.current_top10);
}

function renderTitlesTable(payload) {
  const columns = [
    { label: "Rank", render: (row) => `<span class="rank-pill">${row.rank}</span>` },
    { label: "Player", render: (row) => escapeHtml(row.player_name) },
    { label: "Title Points", render: (row) => `<span class="metric-strong">${row.title_points.toFixed(1)}</span>` },
    { label: "Events", render: (row) => String(row.events_played) },
  ];
  document.getElementById("titles-table").innerHTML = tableHtml(columns, payload.title_leaders_top10);
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
              <div class="timeline-axis__tick" style="left:${label.position}%">
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
    .map(
      (row, index) => `
        <div
          class="timeline-segment${row.player_name === dominantPlayer ? " timeline-segment--dominant" : ""}"
          style="--segment-weight:${row.months}; --accent-index:${index % 4}; --player-hue:${hueForName(row.player_name)}; --player-hue-2:${(hueForName(row.player_name) + 28) % 360}"
          data-range="${escapeHtml(formatMonthRange(row.start_month, row.end_month))}"
          data-player="${escapeHtml(row.player_name)}"
          data-months="${row.months}"
          data-peak="${row.peak_conservative.toFixed(4)}"
          aria-label="${escapeHtml(
            `${row.player_name}, ${formatMonthRange(row.start_month, row.end_month)}, ${row.months} months, peak ${row.peak_conservative.toFixed(4)}`
          )}"
          tabindex="0"
        >
          <span class="timeline-segment__initials">${escapeHtml(initialsForName(row.player_name))}</span>
        </div>
      `
    )
    .join("");
  document.getElementById("timeline").innerHTML = `
    ${summaryHtml}
    <div class="timeline-ribbon-wrap">
      <div class="timeline-ribbon">
        ${segments}
      </div>
      ${axisHtml}
      <p class="timeline-ribbon__hint">Hover a segment for player, era, reign length, and peak.</p>
    </div>
  `;
  bindTimelineTooltips(document.getElementById("timeline"));
}

function miniList(rows, valueKey, formatter) {
  return `
    <ol class="mini-list">
      ${rows
        .map(
          (row) => `
            <li>
              <div class="mini-list__identity">
                <span class="mini-rank-pill">${row.rank}</span>
                <span class="mini-list__name">${escapeHtml(row.player_name)}</span>
              </div>
              <strong class="mini-list__value">${formatter(row[valueKey])}</strong>
            </li>
          `
        )
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
          <div class="profile-card__split">
            <div>
              <p class="stat__label">GOAT top 5</p>
              ${miniList(payload.goat_top20.slice(0, 5), "goat_score", (value) => value.toFixed(3))}
            </div>
            <div>
              <p class="stat__label">Current top 5</p>
              ${miniList(payload.current_top10.slice(0, 5), "conservative_score", (value) => value.toFixed(3))}
            </div>
          </div>
        </article>
      `;
    })
    .join("");

  document.getElementById("profile-cards").innerHTML =
    cards || `<div class="notice">No alternate profiles were exported yet.</div>`;
}

function applyManifestMeta(manifest) {
  document.getElementById("hero-updated").textContent = formatDate(manifest.generated_at);
  document.getElementById("footer-updated").textContent = `Updated: ${formatDate(manifest.generated_at)}`;

  if (manifest.repo_url) {
    const repoLink = document.getElementById("repo-link");
    repoLink.href = manifest.repo_url;
    repoLink.classList.remove("is-hidden");
  }
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
    const defaultPayload = payloadsByProfile[manifest.default_profile];

    renderGoatTable(defaultPayload);
    renderCurrentTable(defaultPayload);
    renderTitlesTable(defaultPayload);
    renderTimeline(defaultPayload);
    renderProfileCards(manifest, payloadsByProfile);
  } catch (error) {
    renderError(error);
  }
}

main();
