/* Chart helpers for CloudCost AI. Colours come from CSS custom properties so
   light and dark mode each use their own validated palette. */
(function () {
  'use strict';

  var PROVIDERS = [
    { key: 'aws', label: 'AWS', color: '--series-aws' },
    { key: 'azure', label: 'Azure', color: '--series-azure' },
    { key: 'gcp', label: 'GCP', color: '--series-gcp' }
  ];
  var builders = [];
  var live = [];

  function css(name) {
    return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  }
  function money(value) {
    return '$' + Number(value || 0).toLocaleString('en-US', {
      minimumFractionDigits: 2, maximumFractionDigits: 2
    });
  }
  function compact(value) {
    var n = Number(value);
    if (Math.abs(n) >= 1e6) return '$' + (n / 1e6).toFixed(1) + 'M';
    if (Math.abs(n) >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'k';
    return '$' + n.toFixed(0);
  }
  function data(id) {
    var el = document.getElementById(id);
    return el ? JSON.parse(el.textContent) : null;
  }
  function providerLabel(key) {
    for (var i = 0; i < PROVIDERS.length; i++) if (PROVIDERS[i].key === key) return PROVIDERS[i].label;
    return key;
  }

  function baseOptions(horizontal) {
    var valueAxis = {
      beginAtZero: true,
      grid: { color: css('--grid'), drawTicks: false },
      border: { display: false },
      ticks: { color: css('--muted'), callback: compact, maxTicksLimit: 6, padding: 6 }
    };
    var categoryAxis = {
      grid: { display: false },
      border: { color: css('--border') },
      ticks: { color: css('--text-2'), maxRotation: 0, autoSkip: !horizontal, maxTicksLimit: horizontal ? undefined : 8 }
    };
    return {
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      interaction: { mode: 'index', intersect: false, axis: horizontal ? 'y' : 'x' },
      scales: horizontal ? { x: valueAxis, y: categoryAxis } : { x: categoryAxis, y: valueAxis },
      plugins: {
        legend: {
          display: false, position: 'top', align: 'start',
          labels: { color: css('--text-2'), boxWidth: 10, boxHeight: 10, usePointStyle: false, padding: 14 }
        },
        tooltip: {
          backgroundColor: css('--text'), titleColor: css('--surface'), bodyColor: css('--surface'),
          footerColor: css('--surface'), padding: 10, cornerRadius: 6, boxPadding: 4,
          callbacks: {
            label: function (ctx) {
              var v = horizontal ? ctx.parsed.x : ctx.parsed.y;
              if (v === null || v === undefined) return null;
              return ' ' + (ctx.dataset.label ? ctx.dataset.label + ': ' : '') + money(v);
            }
          }
        }
      }
    };
  }

  function make(canvasId, config) {
    var canvas = document.getElementById(canvasId);
    if (!canvas || !window.Chart) return null;
    return new Chart(canvas, config);
  }

  /* Stacked bars, one segment per provider, colour fixed per provider. */
  function stackedProviders(canvasId, payload) {
    if (!payload || !payload.labels || !payload.labels.length) return null;
    var surface = css('--surface');
    var datasets = PROVIDERS.filter(function (p) { return payload.series[p.key]; }).map(function (p) {
      return {
        label: p.label, data: payload.series[p.key], backgroundColor: css(p.color),
        borderColor: surface, borderWidth: 1, borderRadius: 3, maxBarThickness: 36
      };
    });
    var options = baseOptions(false);
    options.scales.x.stacked = true;
    options.scales.y.stacked = true;
    options.plugins.legend.display = datasets.length > 1;
    if (datasets.length > 1) {
      options.plugins.tooltip.callbacks.footer = function (items) {
        var sum = items.reduce(function (a, i) { return a + (i.parsed.y || 0); }, 0);
        return 'Total: ' + money(sum);
      };
    }
    return make(canvasId, { type: 'bar', data: { labels: payload.labels, datasets: datasets }, options: options });
  }

  /* Horizontal bars for a ranked breakdown. One hue unless bars are providers. */
  function hbar(canvasId, items, opts) {
    if (!items || !items.length) return null;
    opts = opts || {};
    var colors = items.map(function (item) {
      if (opts.providerColors) {
        for (var i = 0; i < PROVIDERS.length; i++) if (PROVIDERS[i].key === item.label) return css(PROVIDERS[i].color);
      }
      return css('--series-single');
    });
    var options = baseOptions(true);
    options.scales.y.ticks.callback = function (value) {
      var label = this.getLabelForValue(value);
      return label.length > 22 ? label.slice(0, 21) + '…' : label;
    };
    return make(canvasId, {
      type: 'bar',
      data: {
        labels: items.map(function (i) { return opts.providerColors ? providerLabel(i.label) : i.label; }),
        datasets: [{ data: items.map(function (i) { return i.cost; }), backgroundColor: colors,
                     borderRadius: 4, maxBarThickness: 22, borderSkipped: 'start' }]
      },
      options: Object.assign(options, { indexAxis: 'y' })
    });
  }

  /* History (solid) + forecast (dashed) + likely range (band). One hue. */
  function forecast(canvasId, payload) {
    if (!payload) return null;
    var hist = payload.history, fc = payload.forecast || [];
    var labels = hist.labels.concat(fc.map(function (d) { return d.date; }));
    var pad = hist.labels.map(function () { return null; });
    var blue = css('--series-single');
    var lastHist = hist.values.length ? hist.values[hist.values.length - 1] : null;
    var join = pad.slice(0, -1).concat(lastHist === null ? [] : [lastHist]);
    var options = baseOptions(false);
    options.plugins.legend.display = true;
    options.plugins.legend.labels.filter = function (item) { return item.text !== 'Range low'; };
    return make(canvasId, {
      type: 'line',
      data: {
        labels: labels,
        datasets: [
          { label: 'Actual', data: hist.values, borderColor: blue, backgroundColor: blue, borderWidth: 2,
            pointRadius: 0, pointHoverRadius: 4, tension: 0 },
          { label: 'Forecast', data: join.concat(fc.map(function (d) { return d.predicted; })),
            borderColor: blue, backgroundColor: blue, borderWidth: 2, borderDash: [6, 4],
            pointRadius: 0, pointHoverRadius: 4, tension: 0 },
          { label: 'Range low', data: pad.concat(fc.map(function (d) { return d.lower; })),
            borderColor: 'transparent', backgroundColor: 'transparent', borderWidth: 0, pointRadius: 0, pointHoverRadius: 0 },
          { label: 'Likely range', data: pad.concat(fc.map(function (d) { return d.upper; })),
            borderColor: 'transparent', backgroundColor: css('--band'), borderWidth: 0, pointRadius: 0,
            pointHoverRadius: 0, fill: '-1' }
        ]
      },
      options: options
    });
  }

  function renderAll() {
    live.forEach(function (chart) { if (chart) chart.destroy(); });
    live = [];
    if (!window.Chart) return;
    Chart.defaults.font.family = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif';
    Chart.defaults.font.size = 12;
    builders.forEach(function (build) { live = live.concat(build() || []); });
  }
  function register(builder) { builders.push(builder); }

  document.addEventListener('DOMContentLoaded', renderAll);
  if (window.matchMedia) {
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', renderAll);
  }

  window.CCCharts = {
    data: data, money: money, register: register, renderAll: renderAll,
    stackedProviders: stackedProviders, hbar: hbar, forecast: forecast
  };
})();
