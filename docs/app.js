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

function renderSignalCounts(metrics) {
  const el = document.getElementById("signal-counts");
  el.innerHTML = "";
  const runs = metrics.runs ?? [];
  if (!runs.length) return;
  const latest = runs[runs.length - 1];
  const counts = metrics.signal_counts_by_run?.[latest] ?? {};
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

document.getElementById("chart-close").addEventListener("click", () => {
  document.getElementById("chart-section").hidden = true;
  if (activeChart) {
    activeChart.remove();
    activeChart = null;
  }
});

async function init() {
  try {
    const [levelsData, metrics] = await Promise.all([
      fetchJson("levels.json"),
      fetchJson("metrics.json"),
    ]);

    document.getElementById("run-meta").textContent =
      `Last run: ${new Date(levelsData.run_timestamp).toLocaleString()} · ${levelsData.symbols.length} symbols`;

    renderTable(levelsData.symbols);
    renderSignalCounts(metrics);
    renderHoldRateChart(metrics);
  } catch (e) {
    document.getElementById("run-meta").textContent = `Failed to load dashboard data: ${e.message}`;
  }
}

init();
