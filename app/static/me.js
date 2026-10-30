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

/* 我的足跡的移動路線：在地圖 SVG 上畫弧線（算法在 home-route.js，跟「回顧」共用）。 */
(function () {
  "use strict";
  var el = document.getElementById("fp-route-data"), svg = document.getElementById("fp-route");
  if (!el || !svg) return;
  var R = JSON.parse(el.textContent), NS = "http://www.w3.org/2000/svg";
  var route = HomeRoute.Route(R.shows, R.cities), place = HomeRoute.MapPlace(R.map, R.cities);
  var layer = svg.querySelector(".routes"), kmOut = document.getElementById("fp-km");
  function add(tag, attrs, title) {
    var n = document.createElementNS(NS, tag);
    Object.keys(attrs).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (title) { var t = document.createElementNS(NS, "title"); t.textContent = title; n.appendChild(t); }
    layer.appendChild(n);
    return n;
  }
  function draw(home) {
    layer.textContent = "";
    var at = home && place.home(home), dots = [], boxes = {};
    route.trips.forEach(function (day) {
      var stops = day.map(function (s) {
        var p = place.stop(s, route.where(s));
        if (place.nodes[s.c].inset) boxes[s.c] = place.nodes[s.c];
        dots.push([p, s.label]);
        return p;
      });
      if (!at) return;
      HomeRoute.legs(at, stops).forEach(function (l) {
        add("path", { "class": "arc" + (l.a.far || l.b.far ? " far" : ""),
                      d: "M" + l.a.x + "," + l.a.y + " Q" + l.c.x + "," + l.c.y + " " + l.b.x + "," + l.b.y });
      });
    });
    // 去過的金門、連江、海外：畫出框跟名字
    R.cities.forEach(function (c) {
      var b = boxes[c.id];
      if (!b) return;
      add("rect", { "class": "inset", x: b.inset[0], y: b.inset[1], width: b.inset[2], height: b.inset[3], rx: 8 });
      add("text", { "class": "box-label", x: b.x, y: b.inset[1] + 11, "text-anchor": "middle" }).textContent = R.lang === "en" ? c.name : b.name;
    });
    dots.forEach(function (d) { add("circle", { "class": "stop", cx: d[0].x, cy: d[0].y, r: 3 }, d[1]); });
    if (at) {
      // 住海外：右下角一個框，「家」寫在框的上緣（跟其他框一樣）
      if (at.abroad) add("rect", { "class": "inset", x: at.inset[0], y: at.inset[1], width: at.inset[2], height: at.inset[3], rx: 8 });
      add("circle", { "class": "home", cx: at.x, cy: at.y, r: 5.5 });
      add("text", at.abroad ? { "class": "home-label", x: at.x, y: at.inset[1] + 11, "text-anchor": "middle" }
                            : { "class": "home-label", x: at.x + 8, y: at.y + 4 }).textContent = R.home;
      var dist = route.distance(home);
      kmOut.textContent = R.km.replace("{km}", dist.km.toLocaleString(R.lang === "en" ? "en" : "zh-TW"));
    } else {
      kmOut.textContent = "";
    }
  }
  draw(null);
  HomeRoute.picker({
    county: document.getElementById("fp-county"), town: document.getElementById("fp-town"), custom: document.getElementById("fp-custom"), resolve: "/api/me/maplink",
    url: R.districts, lang: R.lang, saved: R.home_saved, remember: document.getElementById("fp-remember"), onChange: draw
  });
})();
