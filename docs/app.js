// Vanilla JS, no build step. Fetches levels.json / metrics.json / bars/<SYMBOL>.json
// (all written by src/store.py) and renders the table + charts.

const SIGNAL_LABELS = {
  BUY_ZONE: "Buy zone",
  CALL_ZONE: "Call zone",
  NEUTRAL: "Neutral",
  BROKEN_SUPPORT: "Broken support",
};

async function fetchJson(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
  return res.json();
}

function fmtPrice(n) {
  return n == null ? "—" : `$${n.toFixed(2)}`;
}

function fmtPct(n) {
  return n == null ? "—" : `${(n * 100).toFixed(2)}%`;
}

function distanceToNearest(row) {
  const d = [row.pct_to_support, row.pct_to_resist]
    .filter((v) => v != null)
    .map(Math.abs);
  return d.length ? Math.min(...d) : Infinity;
}

// App state, populated once in init() and re-sliced on every tab switch.
const state = {
  levelsData: null,
  metrics: null,
  holdingsSet: new Set(),
  creditSpreadData: null,
  view: "holdings", // "holdings" | "watchlist" | "credit_spread"
};

function rowsForView(view) {
  const symbols = state.levelsData?.symbols ?? [];
  return view === "holdings"
    ? symbols.filter((row) => state.holdingsSet.has(row.symbol))
    : symbols.filter((row) => !state.holdingsSet.has(row.symbol));
}

function setView(view) {
  state.view = view;
  for (const btn of document.querySelectorAll("#view-tabs .tab")) {
    btn.classList.toggle("active", btn.dataset.view === view);
  }

  const isCreditSpread = view === "credit_spread";
  document.getElementById("metrics").hidden = isCreditSpread;
  document.getElementById("table-section").hidden = isCreditSpread;
  document.getElementById("credit-spread-section").hidden = !isCreditSpread;
  if (isCreditSpread) closeChart(); // per-symbol chart belongs to the other two tabs' rows

  if (isCreditSpread) {
    const data = state.creditSpreadData;
    renderTechnicals(data?.technicals ?? []);
    renderCatalysts(data?.catalysts ?? []);
    updateRunMeta(data?.technicals?.length ?? 0, data?.run_timestamp);
  } else {
    const rows = rowsForView(view);
    renderTable(rows);
    renderSignalCounts(rows);
    updateRunMeta(rows.length, state.levelsData?.run_timestamp);
  }
}

function updateRunMeta(visibleCount, timestamp) {
  const el = document.getElementById("run-meta");
  if (!timestamp) return;
  const labels = { holdings: "holdings", watchlist: "watchlist", credit_spread: "tickers" };
  el.textContent = `Last run: ${new Date(timestamp).toLocaleString()} · ${visibleCount} ${labels[state.view]}`;
}

document.getElementById("view-tabs").addEventListener("click", (e) => {
  const btn = e.target.closest(".tab");
  if (btn) setView(btn.dataset.view);
});

function renderTable(levels) {
  const tbody = document.getElementById("levels-body");
  tbody.innerHTML = "";

  const sorted = [...levels].sort((a, b) => distanceToNearest(a) - distanceToNearest(b));

  for (const row of sorted) {
    const tr = document.createElement("tr");
    tr.className = `signal-${row.signal}`;
    tr.dataset.symbol = row.symbol;
    tr.innerHTML = `
      <td>${row.symbol}</td>
      <td>${fmtPrice(row.current_price)}</td>
      <td>${fmtPrice(row.nearest_support)}</td>
      <td>${fmtPct(row.pct_to_support)}</td>
      <td>${fmtPrice(row.nearest_resist)}</td>
      <td>${fmtPct(row.pct_to_resist)}</td>
      <td>${fmtPrice(row.suggested_strike)}</td>
      <td><span class="pill ${row.signal}">${SIGNAL_LABELS[row.signal] ?? row.signal}</span></td>
    `;
    tr.addEventListener("click", () => openChart(row));
    tbody.appendChild(tr);
  }
}

function renderSignalCounts(rows) {
  // Computed from the currently visible (tab-filtered) rows, not
  // metrics.json's global counts — a "Buy zone: 33" badge that includes
  // symbols from the other tab would be misleading.
  const el = document.getElementById("signal-counts");
  el.innerHTML = "";
  const counts = {};
  for (const row of rows) counts[row.signal] = (counts[row.signal] ?? 0) + 1;
  for (const [signal, count] of Object.entries(counts)) {
    const span = document.createElement("span");
    span.className = "signal-badge";
    span.textContent = `${SIGNAL_LABELS[signal] ?? signal}: ${count}`;
    el.appendChild(span);
  }
}

function renderHoldRateChart(metrics) {
  const container = document.getElementById("hold-rate-chart");
  const emptyNote = document.getElementById("hold-rate-empty");
  const points = Object.entries(metrics.level_hold_rate_by_run ?? {})
    .filter(([, v]) => v != null)
    .map(([run, v]) => ({ time: Math.floor(new Date(run).getTime() / 1000), value: v }))
    .sort((a, b) => a.time - b.time);

  if (points.length < 1) {
    container.style.display = "none";
    emptyNote.hidden = false;
    return;
  }

  const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: "transparent" }, textColor: "#8a8f9c" },
    grid: { vertLines: { visible: false }, horzLines: { color: "#2a2e38" } },
    rightPriceScale: { visible: true, borderVisible: false },
    timeScale: { borderVisible: false },
    handleScroll: false,
    handleScale: false,
  });
  const series = chart.addLineSeries({ color: "#4a9eff", lineWidth: 2 });
  series.setData(points);
  chart.timeScale().fitContent();
}

let activeChart = null;

async function openChart(row) {
  const section = document.getElementById("chart-section");
  const title = document.getElementById("chart-symbol");
  const container = document.getElementById("candlestick-chart");

  section.hidden = false;
  title.textContent = `${row.symbol} — ${fmtPrice(row.current_price)}`;
  container.innerHTML = "";

  let bars;
  try {
    bars = await fetchJson(`bars/${row.symbol}.json`);
  } catch (e) {
    container.textContent = "No bar data available for this symbol.";
    return;
  }

  if (activeChart) {
    activeChart.remove();
    activeChart = null;
  }

  const chart = LightweightCharts.createChart(container, {
    layout: { background: { color: "transparent" }, textColor: "#8a8f9c" },
    grid: { vertLines: { color: "#2a2e38" }, horzLines: { color: "#2a2e38" } },
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: true },
  });
  activeChart = chart;

  const candleSeries = chart.addCandlestickSeries({
    upColor: "#1f6f43",
    downColor: "#7a2323",
    borderVisible: false,
    wickUpColor: "#1f6f43",
    wickDownColor: "#7a2323",
  });
  candleSeries.setData(bars.map((b) => ({ time: b.time, open: b.open, high: b.high, low: b.low, close: b.close })));

  const volumeSeries = chart.addHistogramSeries({
    color: "#4a9eff",
    priceFormat: { type: "volume" },
    priceScaleId: "",
  });
  volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
  volumeSeries.setData(bars.map((b) => ({ time: b.time, value: b.volume })));

  // Horizontal price line per level, opacity scaled by score relative to
  // this symbol's own max score so the strongest levels stand out most.
  const maxScore = Math.max(1, ...row.levels.map((l) => l.score));
  for (const level of row.levels) {
    const opacity = Math.max(0.25, level.score / maxScore);
    const color =
      level.level_type === "resistance"
        ? `rgba(122, 35, 35, ${opacity})`
        : `rgba(31, 111, 67, ${opacity})`;
    candleSeries.createPriceLine({
      price: level.price,
      color,
      lineWidth: 2,
      lineStyle: LightweightCharts.LineStyle.Dashed,
      axisLabelVisible: true,
      title: `${level.level_type} (${level.touch_count}x)`,
    });
  }

  chart.timeScale().fitContent();
}

function closeChart() {
  document.getElementById("chart-section").hidden = true;
  if (activeChart) {
    activeChart.remove();
    activeChart = null;
  }
}

document.getElementById("chart-close").addEventListener("click", closeChart);

const RSI_OVERBOUGHT = 70;
const RSI_OVERSOLD = 30;

function rsiClass(value) {
  if (value == null) return "";
  if (value >= RSI_OVERBOUGHT) return "rsi-overbought";
  if (value <= RSI_OVERSOLD) return "rsi-oversold";
  return "";
}

function srCell(level) {
  if (!level) return "—";
  return `
    <span class="sr-line support">S: ${fmtPrice(level.support)} (${fmtPct(level.pct_to_support)})</span>
    <span class="sr-line resistance">R: ${fmtPrice(level.resistance)} (${fmtPct(level.pct_to_resistance)})</span>
  `;
}

function renderTechnicals(technicals) {
  const tbody = document.getElementById("technicals-body");
  tbody.innerHTML = "";

  for (const row of technicals) {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${row.symbol}</td>
      <td>${fmtPrice(row.current_price)}</td>
      <td class="sr-cell">${srCell(row.levels?.["20"])}</td>
      <td class="sr-cell">${srCell(row.levels?.["60"])}</td>
      <td class="sr-cell">${srCell(row.levels?.["120"])}</td>
      <td>${fmtPrice(row.sma?.["50"]?.value)} <span class="muted">(${fmtPct(row.sma?.["50"]?.pct_distance)})</span></td>
      <td>${fmtPrice(row.sma?.["200"]?.value)} <span class="muted">(${fmtPct(row.sma?.["200"]?.pct_distance)})</span></td>
      <td class="rsi-value ${rsiClass(row.rsi14)}">${row.rsi14 != null ? row.rsi14.toFixed(1) : "—"}</td>
    `;
    tbody.appendChild(tr);
  }
}

const CATALYST_TYPE_LABELS = { earnings: "Earnings", macro: "Macro" };

function renderCatalysts(catalysts) {
  const tbody = document.getElementById("catalysts-body");
  const emptyNote = document.getElementById("catalysts-empty");
  tbody.innerHTML = "";

  emptyNote.hidden = catalysts.length > 0;

  for (const event of catalysts) {
    const tr = document.createElement("tr");
    if (event.is_sector_peer) tr.className = "catalyst-sector-peer";
    const pillClass = event.is_sector_peer ? "sector-peer" : event.category === "macro" ? "macro" : "";
    const pillLabel = event.is_sector_peer ? "Sector peer" : CATALYST_TYPE_LABELS[event.category] ?? event.category;
    tr.innerHTML = `
      <td>${event.date}</td>
      <td><span class="catalyst-pill ${pillClass}">${pillLabel}</span></td>
      <td>${event.title}</td>
      <td>${event.affects.join(", ")}</td>
    `;
    tbody.appendChild(tr);
  }
}

// ---- Market strip (oil + Treasury yields), refreshed from market.json ----
const MARKET_POLL_MS = 5 * 60 * 1000; // re-read the file; it's rewritten by the market workflow

function fmtAsOf(iso) {
  const d = new Date(iso);
  if (isNaN(d)) return "";
  return d.toLocaleString([], { weekday: "short", hour: "numeric", minute: "2-digit" });
}

function marketTile({ label, value, change, changeText, asOf, stale, inverted }) {
  const dir = change == null || change === 0 ? "" : change > 0 ? "up" : "down";
  const arrow = dir === "up" ? "▲ " : dir === "down" ? "▼ " : "";
  const tile = document.createElement("div");
  tile.className = `market-tile${stale ? " stale" : ""}${inverted ? " inverted" : ""}`;
  tile.title = `${label}${asOf ? " · as of " + fmtAsOf(asOf) : ""}${stale ? " · last fetch failed, showing previous value" : ""}`;
  tile.innerHTML = `
    <div class="m-label">${label}</div>
    <div class="m-value">${value}</div>
    <div class="m-change ${dir}">${changeText ? arrow + changeText : "&nbsp;"}</div>
  `;
  return tile;
}

function renderMarket(m) {
  const strip = document.getElementById("market-strip");
  const tiles = document.getElementById("market-tiles");
  tiles.innerHTML = "";
  if (!m) { strip.hidden = true; return; }

  for (const q of m.oil ?? []) {
    tiles.appendChild(marketTile({
      label: q.label,
      value: `$${q.price.toFixed(2)}`,
      change: q.change,
      changeText: q.change_pct == null ? "" : `${q.change >= 0 ? "+" : ""}${q.change.toFixed(2)} (${q.change_pct.toFixed(2)}%)`,
      asOf: q.as_of,
      stale: q.stale,
    }));
  }

  const intra = m.yield_10y_intraday;
  if (intra) {
    tiles.appendChild(marketTile({
      label: intra.label,
      value: `${intra.price.toFixed(3)}%`,
      change: intra.change,
      changeText: intra.change == null ? "" : `${intra.change >= 0 ? "+" : ""}${(intra.change * 100).toFixed(1)} bp`,
      asOf: intra.as_of,
      stale: intra.stale,
    }));
  }

  const t = m.treasury;
  if (t) {
    for (const r of t.curve) {
      if (r.rate == null) continue;
      tiles.appendChild(marketTile({
        label: `${r.maturity} Treasury`,
        value: `${r.rate.toFixed(2)}%`,
        change: r.change_bp,
        changeText: r.change_bp == null ? "" : `${r.change_bp >= 0 ? "+" : ""}${r.change_bp} bp`,
        asOf: t.as_of,
        stale: t.stale,
      }));
    }
    if (t.spread_2s10s_bp != null) {
      tiles.appendChild(marketTile({
        label: "2s10s spread",
        value: `${t.spread_2s10s_bp >= 0 ? "+" : ""}${t.spread_2s10s_bp} bp`,
        asOf: t.as_of,
        stale: t.stale,
        inverted: t.spread_2s10s_bp < 0, // inverted curve highlighted
      }));
    }
  }

  document.getElementById("market-note").textContent =
    `Oil: NYMEX futures (Yahoo Finance, ~10–15 min delayed). Treasury: official end-of-day par curve` +
    `${t ? " for " + t.as_of : ""}; 10Y intraday is the live-ish line. Fetched ${fmtAsOf(m.fetched_at)}.`;
  strip.hidden = false;
}

async function refreshMarket() {
  try {
    renderMarket(await fetchJson("market.json"));
  } catch (e) {
    renderMarket(null); // missing/unreachable file: hide the strip, don't break the page
  }
}

async function init() {
  refreshMarket();
  setInterval(refreshMarket, MARKET_POLL_MS);

  try {
    const [levelsData, metrics, holdings, creditSpreadData] = await Promise.all([
      fetchJson("levels.json"),
      fetchJson("metrics.json"),
      fetchJson("holdings.json").catch(() => []), // missing file = no holdings tagged, not fatal
      fetchJson("credit_spread.json").catch(() => null), // missing file = tab renders empty, not fatal
    ]);

    state.levelsData = levelsData;
    state.metrics = metrics;
    state.holdingsSet = new Set(holdings);
    state.creditSpreadData = creditSpreadData;

    // Level hold rate stays a global metric (it's about how well levels
    // persist across runs, not which tab you're looking at) — everything
    // else re-slices per tab.
    renderHoldRateChart(metrics);
    setView(state.view);
  } catch (e) {
    document.getElementById("run-meta").textContent = `Failed to load dashboard data: ${e.message}`;
  }
}

init();
