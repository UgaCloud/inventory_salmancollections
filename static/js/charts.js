/* Dashboard charts: rendered from the server-provided JSON, theme aware.
 *
 * Pages are swapped in by app.js without reloading scripts, so the chart data
 * and canvases are read fresh every time a page is loaded or the theme changes.
 * Without this a dashboard period filter left the new canvases blank.
 */
(function () {
  "use strict";

  const instances = [];

  function readCharts() {
    const source = document.getElementById("dashboard-charts");
    if (!source) return [];
    try {
      const parsed = JSON.parse(source.textContent || "[]");
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function palette(theme) {
    if (theme === "dark") {
      return {
        brand: "#818cf8",
        brandSoft: "rgba(129, 140, 248, .18)",
        second: "#38bdf8",
        third: "#f59e0b",
        text: "#94a3b8",
        grid: "rgba(148, 163, 184, .16)",
        doughnut: ["#818cf8", "#38bdf8", "#34d399", "#fbbf24", "#fb7185", "#a78bfa", "#2dd4bf", "#f472b6"],
      };
    }
    return {
      brand: "#4f46e5",
      brandSoft: "rgba(79, 70, 229, .12)",
      second: "#0ea5e9",
      third: "#f59e0b",
      text: "#64748b",
      grid: "rgba(100, 116, 139, .14)",
      doughnut: ["#4f46e5", "#0ea5e9", "#10b981", "#f59e0b", "#f43f5e", "#8b5cf6", "#14b8a6", "#ec4899"],
    };
  }

  function hasData(chart) {
    return (chart.datasets || []).some((dataset) =>
      (dataset.data || []).some((value) => Number(value) !== 0)
    );
  }

  function build(chart, canvas, theme) {
    const colors = palette(theme);
    const isDoughnut = chart.type === "doughnut";
    const isLine = chart.type === "line";
    const datasets = (chart.datasets || []).map((dataset, index) => {
      const color = index === 0 ? colors.brand : index === 1 ? colors.second : colors.third;
      if (isDoughnut) {
        return {
          label: dataset.label,
          data: dataset.data,
          backgroundColor: colors.doughnut,
          borderColor: theme === "dark" ? "#121c31" : "#ffffff",
          borderWidth: 2,
          hoverOffset: 4,
        };
      }
      if (isLine) {
        return {
          label: dataset.label,
          data: dataset.data,
          borderColor: color,
          backgroundColor: index === 0 ? colors.brandSoft : "transparent",
          fill: index === 0,
          tension: 0.32,
          borderWidth: 2.2,
          pointRadius: 2.5,
          pointHoverRadius: 4,
          pointBackgroundColor: color,
        };
      }
      return {
        label: dataset.label,
        data: dataset.data,
        backgroundColor: index === 0 ? colors.brand : index === 1 ? colors.second : colors.third,
        borderRadius: 5,
        maxBarThickness: 34,
      };
    });

    return new Chart(canvas.getContext("2d"), {
      type: chart.type,
      data: { labels: chart.labels || [], datasets },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        indexAxis: chart.horizontal ? "y" : "x",
        plugins: {
          legend: {
            display: isDoughnut || datasets.length > 1,
            position: isDoughnut ? "bottom" : "top",
            labels: { color: colors.text, boxWidth: 10, boxHeight: 10, usePointStyle: true, font: { size: 11 } },
          },
          tooltip: {
            callbacks: isDoughnut
              ? {}
              : {
                  label: (context) => {
                    const value = context.parsed[chart.horizontal ? "x" : "y"] ?? context.parsed;
                    const symbol = window.APP_CONFIG ? window.APP_CONFIG.currency : "";
                    return `${context.dataset.label}: ${symbol}${Number(value).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
                  },
                },
          },
        },
        scales: isDoughnut
          ? {}
          : {
              x: {
                ticks: { color: colors.text, font: { size: 10 }, maxRotation: 0, autoSkip: true },
                grid: { color: chart.horizontal ? colors.grid : "transparent" },
                border: { display: false },
              },
              y: {
                beginAtZero: true,
                ticks: { color: colors.text, font: { size: 10 } },
                grid: { color: colors.grid },
                border: { display: false },
              },
            },
      },
    });
  }

  function renderAll() {
    instances.splice(0).forEach((instance) => instance.destroy());
    if (typeof Chart === "undefined") return;
    const charts = readCharts();
    const theme = document.documentElement.getAttribute("data-theme") || "light";
    document.querySelectorAll("[data-chart-index]").forEach((canvas) => {
      const index = Number(canvas.dataset.chartIndex);
      const chart = charts[index];
      if (!chart) return;
      const empty = document.querySelector(`[data-chart-empty="${index}"]`);
      const visible = hasData(chart);
      canvas.parentElement.hidden = !visible;
      if (empty) empty.classList.toggle("hidden", visible);
      if (visible) instances.push(build(chart, canvas, theme));
    });
  }

  // app.js swaps #app-main in place for data-nav links (including the
  // dashboard period chips), then announces the new page.
  document.addEventListener("app:page-loaded", () => window.requestAnimationFrame(renderAll));
  document.addEventListener("app:themechanged", () => window.requestAnimationFrame(renderAll));

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", renderAll);
  } else {
    renderAll();
  }
})();
