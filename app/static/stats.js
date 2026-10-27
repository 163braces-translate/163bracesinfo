/* 演出頁的分頁切換與統計圖表。
 * 圖表等分頁第一次打開時才畫（藏起來的 canvas 量不到尺寸）；Chart.js 也是到那時才載入，
 * 只看演出列表的人不用下載它。 */
(function () {
  "use strict";
  var CHART_JS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js";
  var data = JSON.parse(document.getElementById("chart-data").textContent);
  var drawn = {}, loading = null;

  function loadChartJs() {
    if (window.Chart) return Promise.resolve();
    if (!loading) {
      loading = new Promise(function (resolve, reject) {
        var s = document.createElement("script");
        s.src = CHART_JS; s.onload = resolve; s.onerror = reject;
        document.head.appendChild(s);
      }).then(setDefaults);
    }
    return loading;
  }

  function setDefaults() {
    var css = getComputedStyle(document.documentElement);
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = css.getPropertyValue("--muted").trim() || "#6b7280";
    Chart.defaults.borderColor = css.getPropertyValue("--border").trim() || "#e5e7eb";
    // 圖例：小圓點，不搶資料的視線
    var legend = Chart.defaults.plugins.legend.labels;
    legend.usePointStyle = true;
    legend.pointStyle = "circle";
    legend.boxWidth = 7;
    legend.boxHeight = 7;
    legend.padding = 14;
    Chart.defaults.plugins.tooltip.usePointStyle = true;
    Chart.defaults.plugins.tooltip.boxWidth = 7;
    Chart.defaults.plugins.tooltip.boxHeight = 7;
  }

  function options(canvas) {
    var type = canvas.dataset.type, stacked = !!canvas.dataset.stacked;
    var opts = { responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
                 plugins: { legend: { position: "bottom" } } };
    if (type === "doughnut") {
      opts.interaction = { mode: "nearest", intersect: true };
      opts.cutout = "58%";
      return opts;
    }
    if (type === "line") {
      // 只有前八條線有自己的顏色，之後的是灰線：圖例只列有顏色的，灰線的曲名看滑鼠提示
      opts.plugins.legend.labels = { filter: function (item) { return item.datasetIndex < 8; } };
    }
    opts.scales = { x: { stacked: stacked, grid: { display: false } },
                    y: { stacked: stacked, beginAtZero: true, ticks: { precision: 0 } } };
    if (type === "bar") {
      // 堆疊的色塊之間留一條白縫，顏色相近時也分得出邊界
      data[canvas.dataset.chart].datasets.forEach(function (d) {
        d.borderColor = "#ffffff"; d.borderWidth = 1; d.borderRadius = 3; d.borderSkipped = false;
      });
    }
    return opts;
  }

  function drawIn(panel) {
    var canvases = panel.querySelectorAll("canvas[data-chart]");
    if (!canvases.length) return;
    loadChartJs().then(function () {
      canvases.forEach(function (canvas) {
        if (drawn[canvas.dataset.chart]) return;
        drawn[canvas.dataset.chart] = new Chart(canvas, {
          type: canvas.dataset.type, data: data[canvas.dataset.chart], options: options(canvas)
        });
      });
    });
  }

  // ---- 分頁：每個分頁有自己的網址（/performances/、/performances/stats/…）。
  // 切換時不重新載入頁面，只換網址；按上一頁會回到前一個分頁。
  var tabs = document.querySelectorAll("[role=tab]");
  function show(key, push) {
    tabs.forEach(function (tab) {
      var on = tab.dataset.tab === key;
      tab.setAttribute("aria-selected", on ? "true" : "false");
      document.getElementById("panel-" + tab.dataset.tab).hidden = !on;
    });
    drawIn(document.getElementById("panel-" + key));
    if (push) {
      var tab = document.getElementById("tab-" + key);
      history.pushState({ tab: key }, "", tab.getAttribute("href"));
      document.title = tab.dataset.title;      // 網頁標題跟著分頁換（伺服器算好放在分頁連結上）
    }
  }
  tabs.forEach(function (tab) {
    tab.addEventListener("click", function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey) return;     // 按住 Cmd／Ctrl 點：照常開新分頁
      e.preventDefault();
      if (tab.getAttribute("aria-selected") !== "true") show(tab.dataset.tab, true);
    });
  });
  window.addEventListener("popstate", function () {
    var match = Array.prototype.find.call(tabs, function (t) { return new URL(t.href).pathname === location.pathname; });
    show(match ? match.dataset.tab : "list", false);
    if (match) document.title = match.dataset.title;
  });
  var current = document.querySelector("[role=tab][aria-selected=true]");
  show(current ? current.dataset.tab : "list", false);

  // ---- 歌曲累積圖：前 N 名／全部
  var range = document.getElementById("song-range");
  if (range) {
    range.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-range]");
      if (!btn) return;
      range.querySelectorAll("button").forEach(function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); });
      var chart = drawn.song_top;
      if (!chart) return;
      chart.data = data[btn.dataset.range === "all" ? "song_all" : "song_top"];
      chart.update();
    });
  }
})();
