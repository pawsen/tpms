(() => {
  "use strict";

  // Prometheus query_range endpoint (relative to this site)
  const PROM_RANGE = "/lfhs/prom/api/v1/query_range";

  // Single place to tweak chart tick density + font sizes
  const CHART_STYLE = {
    tickFontPx: 22,        // tick label font size (x/y tick labels)
    axisLabelFontPx: 18,   // axis label font size (x/y axis titles)
    yTicks: 7,             // number of y tick intervals (labels = yTicks + 1)
    xTargetTicks: 7,       // approx number of x ticks (converted to a “nice” time step)
  };

  const canvas = document.getElementById("graph");
  const sensorSel = document.getElementById("sensor");
  const scaleEl = document.getElementById("scaletext");
  const statusEl = document.getElementById("statustext");
  const rangeEl = document.getElementById("rangetext");
  const lastEl = document.getElementById("lastblip");
  const fixBox = document.getElementById("fixbox");

  // default range 20 * 60 -> 20min
  let rangeSec = 24 * 60 * 60; // default 24h
  let fixVertical = false;

  // Cache last fetch so resize redraw doesn't re-query Prometheus
  let lastData = null; // {points: Array<[ms, y]>, startSec, endSec, stepSec, maxY, minY, seriesInfo}

  function nowSec() { return Math.floor(Date.now() / 1000); }

  function fmtLocal(sec) {
    return new Date(sec * 1000).toLocaleString();
  }

  function setStatus(txt) { statusEl.textContent = txt; }

  function chooseStepSec(spanSec) {
    // Target <= ~900 points to keep payload + render fast.
    const targetPoints = 900;
    const raw = Math.ceil(spanSec / targetPoints);

    // "Nice" step ladder (seconds)
    const ladder = [
      1,2,5,10,15,30,
      60,120,300,600,900,1800,
      3600,7200,14400,21600,43200,86400
    ];
    for (const s of ladder) if (s >= raw) return s;
    return 86400;
  }

  function scaleLabel(stepSec) {
    if (stepSec >= 86400) return "day";
    if (stepSec >= 3600) return "hour";
    if (stepSec >= 60) return "minute";
    return "none";
  }

  async function fetchRange(query, startSec, endSec, stepSec) {
    const url = new URL(PROM_RANGE, window.location.origin);
    url.searchParams.set("query", query);
    url.searchParams.set("start", String(startSec));
    url.searchParams.set("end", String(endSec));
    url.searchParams.set("step", String(stepSec));

    const r = await fetch(url.toString(), { cache: "no-store" });
    if (!r.ok) throw new Error(`HTTP ${r.status}`);
    const j = await r.json();
    if (j.status !== "success") throw new Error("Prometheus query failed");
    return j;
  }

  function mergeMatrixToPoints(prom) {
    const res = prom?.data?.result ?? [];
    const seriesCount = res.length;

    // pointsPerSeries: number of samples per series (after numeric filtering)
    const pointsPerSeries = [];
    const labelsPerSeries = [];

    // Merge strategy:
    // - Build a map t(ms)-> {sum, n} across all series.
    // - For timestamps present in multiple series, value becomes average.
    const map = new Map(); // ms -> {sum, n}

    for (const s of res) {
      const values = s?.values ?? [];
      let kept = 0;

      labelsPerSeries.push(s?.metric ?? {});
      for (const pair of values) {
        const t = Number(pair[0]);
        const v = Number(pair[1]);
        if (!Number.isFinite(t) || !Number.isFinite(v)) continue;
        const ms = t * 1000;

        const cur = map.get(ms);
        if (cur) {
          cur.sum += v;
          cur.n += 1;
        } else {
          map.set(ms, { sum: v, n: 1 });
        }
        kept += 1;
      }
      pointsPerSeries.push(kept);
    }

    // Convert merged map -> sorted point array
    const points = Array.from(map.entries())
      .sort((a, b) => a[0] - b[0])
      .map(([ms, agg]) => [ms, agg.sum / agg.n]);

    let maxY = null, minY = null;
    for (const [, v] of points) {
      maxY = (maxY === null) ? v : Math.max(maxY, v);
      minY = (minY === null) ? v : Math.min(minY, v);
    }

    return {
      points,
      maxY,
      minY,
      seriesInfo: {
        seriesCount,
        pointsPerSeries,
        mergedPoints: points.length,
        // Keep a tiny hint about why multiple series happened (helpful when debugging label drift)
        labelKeys: labelsPerSeries.map(m => Object.keys(m || {}).length),
      }
    };
  }

  function cssVar(name, fallback) {
    const v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }

  function resizeCanvasToCSS() {
    const dpr = window.devicePixelRatio || 1;
    const rect = canvas.getBoundingClientRect();
    const w = Math.max(1, Math.floor(rect.width * dpr));
    const h = Math.max(1, Math.floor(rect.height * dpr));

    if (canvas.width !== w || canvas.height !== h) {
      canvas.width = w;
      canvas.height = h;
      return true;
    }
    return false;
  }

  // Use CHART_STYLE.xTargetTicks to control tick density.
  function niceTimeTickSec(spanSec, targetTicks) {
    targetTicks = Math.max(2, Math.floor(Number(targetTicks) || 7));
    const target = spanSec / targetTicks;

    // seconds ladder for ticks (not step)
    const ladder = [
      60, 2*60, 5*60, 10*60, 15*60, 30*60,
      60*60, 2*60*60, 3*60*60, 6*60*60, 12*60*60,
      24*60*60, 2*24*60*60, 7*24*60*60,
      30*24*60*60, 90*24*60*60, 180*24*60*60
    ];
    for (const s of ladder) if (s >= target) return s;
    return 180*24*60*60;
  }

  function fmtTimeLabel(ms, spanSec) {
    const d = new Date(ms);
    if (spanSec <= 6 * 3600) { // <= 6h
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    }
    if (spanSec <= 3 * 24 * 3600) { // <= 3d
      return d.toLocaleString([], { weekday: "short", hour: "2-digit", minute: "2-digit" });
    }
    if (spanSec <= 60 * 24 * 3600) { // <= ~2mo
      return d.toLocaleDateString([], { month: "short", day: "2-digit" });
    }
    return d.toLocaleDateString([], { year: "numeric", month: "short" });
  }

  function draw(data) {
    if (!data) return;

    resizeCanvasToCSS();
    const ctx = canvas.getContext("2d", { alpha: false });

    // Hard reset (fixes any state leakage and guarantees clear)
    ctx.setTransform(1, 0, 0, 1, 0, 0);

    const W = canvas.width, H = canvas.height;

    const bg = cssVar("--bg", "#fff");
    const fg = cssVar("--fg", "#111");
    const grid = cssVar("--grid", "#e6e6e6");
    const border = cssVar("--border", "#c9c9c9");
    const accent = cssVar("--accent", "#b00020");

    // Clear
    ctx.clearRect(0, 0, W, H);
    ctx.fillStyle = bg;
    ctx.fillRect(0, 0, W, H);

    const padL = 72;
    const padR = 16;
    const padT = 14;
    const padB = 54;

    const plotX0 = padL, plotY0 = padT;
    const plotW = W - padL - padR;
    const plotH = H - padT - padB;

    // Border
    ctx.strokeStyle = border;
    ctx.lineWidth = 1;
    ctx.strokeRect(0.5, 0.5, W - 1, H - 1);

    const { points, startSec, endSec, maxY, minY } = data;
    const spanSec = Math.max(1, endSec - startSec);

    // X scale
    const xMin = startSec * 1000;
    const xMax = endSec * 1000;
    const xToPx = (ms) => plotX0 + ((ms - xMin) / (xMax - xMin)) * plotW;

    // Y scale
    let yMin = (minY ?? 0);
    let yMax = (maxY ?? 1);

    if (fixVertical && maxY !== null) {
      yMin = 0;
      yMax = maxY * 1.10;
    } else if (maxY !== null && minY !== null) {
      const pad = (maxY - minY) * 0.10 || 1;
      yMin = minY - pad;
      yMax = maxY + pad;
    } else {
      yMin = 0; yMax = 1;
    }

    const yToPx = (y) => plotY0 + (1 - (y - yMin) / (yMax - yMin)) * plotH;

    // --- Grid + ticks (configurable) ---
    const tickFontPx = Number.isFinite(Number(CHART_STYLE.tickFontPx))
      ? Number(CHART_STYLE.tickFontPx)
      : Math.max(11, Math.floor(W / 90));

    ctx.font = `${tickFontPx}px ui-sans-serif, system-ui`;
    ctx.fillStyle = fg;
    ctx.strokeStyle = grid;
    ctx.lineWidth = 1;

    // Y ticks (configurable)
    const yTicks = Math.max(1, Math.floor(Number(CHART_STYLE.yTicks) || 5));
    for (let i = 0; i <= yTicks; i++) {
      const y = yMin + (i / yTicks) * (yMax - yMin);
      const py = yToPx(y);

      // horizontal grid line
      ctx.beginPath();
      ctx.moveTo(plotX0, py);
      ctx.lineTo(plotX0 + plotW, py);
      ctx.stroke();

      // label
      ctx.fillStyle = fg;
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(y.toFixed(1), plotX0 - 8, py);
    }

    // X ticks (range-aware + configurable density)
    const tickSec = niceTimeTickSec(spanSec, CHART_STYLE.xTargetTicks);
    const firstTickSec = Math.ceil(startSec / tickSec) * tickSec;

    for (let t = firstTickSec; t <= endSec; t += tickSec) {
      const ms = t * 1000;
      const px = xToPx(ms);

      // vertical grid line
      ctx.strokeStyle = grid;
      ctx.beginPath();
      ctx.moveTo(px, plotY0);
      ctx.lineTo(px, plotY0 + plotH);
      ctx.stroke();

      // label
      ctx.fillStyle = fg;
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(fmtTimeLabel(ms, spanSec), px, plotY0 + plotH + 6);
    }

    // Axis lines
    ctx.strokeStyle = fg;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(plotX0, plotY0);
    ctx.lineTo(plotX0, plotY0 + plotH);
    ctx.lineTo(plotX0 + plotW, plotY0 + plotH);
    ctx.stroke();

    // --- Axis labels (configurable) ---
    const axisFontPx = Number.isFinite(Number(CHART_STYLE.axisLabelFontPx))
      ? Number(CHART_STYLE.axisLabelFontPx)
      : Math.max(12, Math.floor(W / 80));

    ctx.fillStyle = fg;
    ctx.font = `${axisFontPx}px ui-sans-serif, system-ui`;

    // X label
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText(
      "Time",
      plotX0 + plotW / 2,
      plotY0 + plotH + 28
    );

    // Y label (rotated)
    ctx.save();
    ctx.translate(18, plotY0 + plotH / 2);
    ctx.rotate(-Math.PI / 2);
    ctx.textAlign = "center";
    ctx.textBaseline = "top";
    ctx.fillText("Temperature (°C)", 0, 0);
    ctx.restore();

    // Data line
    if (points.length >= 2) {
      ctx.strokeStyle = accent;
      ctx.lineWidth = 2;
      ctx.beginPath();

      let started = false;
      for (const [ms, y] of points) {
        const px = xToPx(ms);
        const py = yToPx(y);
        if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
        if (!started) {
          ctx.moveTo(px, py);
          started = true;
        } else {
          ctx.lineTo(px, py);
        }
      }
      ctx.stroke();
    } else {
      ctx.fillStyle = fg;
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("no data", plotX0 + plotW / 2, plotY0 + plotH / 2);
    }
  }

  function formatSeriesStatus(seriesInfo) {
    const n = seriesInfo?.seriesCount ?? 0;
    const arr = seriesInfo?.pointsPerSeries ?? [];
    const merged = seriesInfo?.mergedPoints ?? 0;

    if (!n) return "ready (0 series)";
    // Example: "ready (2 series; points: 110, 609; merged: 609)"
    return `ready (${n} series; points: ${arr.join(", ")}; merged: ${merged})`;
  }

  async function refresh() {
    try {
      setStatus("loading…");

      const endSec = nowSec();
      const startSec = endSec - rangeSec;
      const stepSec = chooseStepSec(rangeSec);
      const query = sensorSel.value;

      const prom = await fetchRange(query, startSec, endSec, stepSec);
      const { points, maxY, minY, seriesInfo } = mergeMatrixToPoints(prom);

      lastData = { points, startSec, endSec, stepSec, maxY, minY, seriesInfo };

      scaleEl.textContent = scaleLabel(stepSec);
      rangeEl.textContent = `${fmtLocal(startSec)} to ${fmtLocal(endSec)}`;

      if (points.length) {
        const [ms, v] = points[points.length - 1];
        lastEl.textContent = `${new Date(ms).toString()}  ->  ${v.toFixed(2)}°C`;
      } else {
        lastEl.textContent = "no data";
      }

      draw(lastData);
      setStatus(formatSeriesStatus(seriesInfo));
    } catch (e) {
      setStatus("error");
      lastEl.textContent = `error: ${e?.message ?? String(e)}`;
      // Still clear and show empty plot area
      draw({ points: [], startSec: nowSec() - rangeSec, endSec: nowSec(), stepSec: 1, maxY: null, minY: null });
    }
  }

  function wireUI() {
    // Range links
    document.querySelectorAll("[data-range]").forEach(a => {
      a.addEventListener("click", () => {
        const sec = Number(a.getAttribute("data-range"));
        if (Number.isFinite(sec) && sec > 0) {
          rangeSec = sec;
          refresh();
        }
      });
    });

    sensorSel.addEventListener("change", refresh);

    fixBox.addEventListener("change", () => {
      fixVertical = !!fixBox.checked;
      // redraw only (no need to re-fetch)
      if (lastData) draw(lastData);
      else refresh();
    });

    window.addEventListener("resize", () => {
      if (lastData) draw(lastData);
    });
  }

  // init
  wireUI();
  refresh();
  setInterval(refresh, 15000);
})();
