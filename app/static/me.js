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
      var opts = { responsive: true, maintainAspectRatio: false, plugins: { legend: { display: type === "doughnut", position: "bottom" } } };
      if (type === "bar") {
        d.datasets.forEach(function (x) { x.borderRadius = 4; });
        opts.scales = { x: { grid: { display: false } }, y: { beginAtZero: true, ticks: { precision: 0 } } };
      } else { opts.cutout = "58%"; }
      new Chart(c, { type: type, data: d, options: opts });
    });
  };
  document.head.appendChild(s);
})();
