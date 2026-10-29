/* 個人足跡的兩張圖（每年場數、演出類型）。Chart.js 只有這頁用到，所以在這裡才載入。 */
(function () {
  "use strict";
  var el = document.getElementById("fp-data");
  if (!el) return;
  var data = JSON.parse(el.textContent);
  var s = document.createElement("script");
  s.src = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/3.9.1/chart.min.js";
  s.onload = function () {
    var css = getComputedStyle(document.documentElement);
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.color = css.getPropertyValue("--muted").trim();
    Chart.defaults.borderColor = css.getPropertyValue("--border").trim();
    var legend = Chart.defaults.plugins.legend.labels;
    legend.usePointStyle = true; legend.pointStyle = "circle"; legend.boxWidth = 7; legend.boxHeight = 7;
    document.querySelectorAll("canvas[data-fp-chart]").forEach(function (c) {
      var type = c.dataset.type, d = data[c.dataset.fpChart];
      var stacked = !!c.dataset.stacked;
      var opts = { responsive: true, maintainAspectRatio: false,
                   plugins: { legend: { display: type === "doughnut" || stacked, position: "bottom" } } };
      if (type === "bar") {
        // 堆疊的色塊之間留一條白縫（跟演出統計的圖一樣）；滑鼠移上去列出那一年各類型的場數
        d.datasets.forEach(function (x) { x.borderRadius = 3; x.borderColor = "#ffffff"; x.borderWidth = 1; x.borderSkipped = false; });
        opts.interaction = { mode: "index", intersect: false };
        opts.plugins.tooltip = { filter: function (item) { return item.raw > 0; } };   // 那一年沒去的類型不列
        opts.scales = { x: { stacked: stacked, grid: { display: false } },
                        y: { stacked: stacked, beginAtZero: true, ticks: { precision: 0 } } };
      } else { opts.cutout = "58%"; opts.radius = window.DOUGHNUT_RADIUS; }
      new Chart(c, { type: type, data: d, options: opts,
                     plugins: type === "doughnut" ? [window.doughnutTopLabels] : [] });     // 前三名標名稱與數量
    });
  };
  document.head.appendChild(s);
})();
