/* 「我的 → 回顧」：在瀏覽器裡用 Canvas 畫回顧圖（1080×1920 限時動態或 1080×1080 正方形），
 * 圖表可以拖曳、縮放、拿掉，最後輸出 JPG。資料是頁面上的 recap-data；
 * 期間、住的行政區、版面只記在這台裝置（localStorage），不會送回伺服器。 */
(function () {
  "use strict";
  var D = JSON.parse(document.getElementById("recap-data").textContent);
  var T = D.text;
  var FONT = '"Noto Sans TC", "PingFang TC", "Microsoft JhengHei", sans-serif';
  var C = { bg1: "#e8effc", bg2: "#fafafa", card: "#ffffff", border: "#e5e7eb", text: "#1f2328", muted: "#646a73",
            primary: "#2f6fdb", home: "#eb6834", land: "#eef1f5", landLine: "#cfd5dd", dot: "rgba(47, 111, 219, .75)", zero: "#d3d7dd" };
  var W = 1080;
  // 四周不放東西的比例（上、右、下、左）：限時動態的上方、下方會被 IG 的頭像、按鈕和回覆欄蓋住
  var FORMATS = {
    story: { h: 1920, safe: [0.10, 0.06, 0.10, 0.06] },
    square: { h: 1080, safe: [0.06, 0.06, 0.06, 0.06] }
  };
  var HEADER = 136, FOOTER = 60, GAP = 20;
  var KINDS = ["years", "types", "cities", "map", "routes", "heard", "likes", "numbers"];

  var stage = document.getElementById("recap-stage");
  var canvas = document.getElementById("recap-canvas");
  var ctx = canvas.getContext("2d", { alpha: false });
  var frames = stage.querySelector(".recap-frames");
  var guides = stage.querySelector(".recap-guides");

  // ------------------------------------------------------------ 狀態（記在這台裝置）
  var STORE = "recap-v1";
  var saved = {};
  try { saved = JSON.parse(localStorage.getItem(STORE)) || {}; } catch (e) { saved = {}; }
  var state = {
    format: FORMATS[saved.format] ? saved.format : "story",
    rows: [3, 5, 8, 10].indexOf(saved.rows) >= 0 ? saved.rows : 5,
    layouts: { story: cleanLayout(saved.layouts && saved.layouts.story), square: cleanLayout(saved.layouts && saved.layouts.square) },
    home: null,
    from: "", to: ""
  };
  function cleanLayout(list) {
    if (!Array.isArray(list)) return null;
    return list.filter(function (w) {
      return w && KINDS.indexOf(w.kind) >= 0 && isFinite(w.x) && isFinite(w.y) && isFinite(w.w);
    });
  }
  function save() {
    try {
      localStorage.setItem(STORE, JSON.stringify({ format: state.format, rows: state.rows, layouts: state.layouts }));
    } catch (e) { /* 無痕模式之類存不了，就不記 */ }
  }
  function widgets() { return state.layouts[state.format]; }

  // ------------------------------------------------------------ 尺寸
  function geom() {
    var f = FORMATS[state.format], H = f.h, s = f.safe;
    var safe = { t: Math.round(H * s[0]), r: Math.round(W * (1 - s[1])), b: Math.round(H * (1 - s[2])), l: Math.round(W * s[3]) };
    return { H: H, safe: safe, area: { t: safe.t + HEADER, r: safe.r, b: safe.b - FOOTER, l: safe.l } };
  }
  // 每種圖表在「基準大小」下畫，放大縮小就是整張等比例縮放，比例不會變
  function baseSize(kind) {
    switch (kind) {
      case "numbers": return [1000, 190];
      case "years": return [640, 400];
      case "types": case "cities": return [400, 500];
      case "map": case "routes": return [380, 520];
      default: return [400, 86 + state.rows * 50 + 26];      // heard、likes：標題、每首一列、底下留白
    }
  }
  function ratio(kind) { var b = baseSize(kind); return b[0] / b[1]; }
  function minWidth(kind) { return kind === "numbers" ? 420 : 160; }

  // ------------------------------------------------------------ 期間
  var thisYear = D.today.slice(0, 4);
  var years = [];
  D.shows.forEach(function (s) { var y = s.d.slice(0, 4); if (years.indexOf(y) < 0) years.push(y); });
  if (years.indexOf(thisYear) < 0) years.push(thisYear);
  years.sort().reverse();

  function lastDay(ymd) { return new Date(+ymd.slice(0, 4), +ymd.slice(5, 7), 0).getDate(); }
  function periodLabel(a, b) {
    var ya = a.slice(0, 4), yb = b.slice(0, 4);
    if (a.slice(5) === "01-01" && b.slice(5) === "12-31") return ya === yb ? ya : ya + "~" + yb;
    if (a.slice(8) === "01" && +b.slice(8) === lastDay(b)) {
      var ma = ya + "/" + a.slice(5, 7), mb = yb + "/" + b.slice(5, 7);
      return ma === mb ? ma : ma + "~" + mb;
    }
    var da = a.replace(/-/g, "/"), db = b.replace(/-/g, "/");
    return da === db ? da : da + "~" + db;
  }
  function setYear(y) {
    if (y === "all") { state.from = years[years.length - 1] + "-01-01"; state.to = thisYear + "-12-31"; }
    else if (y !== "custom") { state.from = y + "-01-01"; state.to = y + "-12-31"; }
  }

  // ------------------------------------------------------------ 統計
  var cityById = {};
  D.cities.forEach(function (c) { cityById[c.id] = c; });

  function stats() {
    var shows = D.shows.filter(function (s) { return s.d >= state.from && s.d <= state.to; });
    var byType = {}, byCity = {}, heard = {}, plays = 0;
    shows.forEach(function (s) {
      byType[s.t] = (byType[s.t] || 0) + 1;
      byCity[s.c] = (byCity[s.c] || 0) + 1;
      s.songs.forEach(function (k) { heard[k] = (heard[k] || 0) + 1; plays++; });
    });
    var route = HomeRoute.Route(shows, D.cities), dist = state.home ? route.distance(state.home) : null;
    // 一年以內的期間按月份，跨更久按年份
    var months = (+state.to.slice(0, 4) - +state.from.slice(0, 4)) * 12 + (+state.to.slice(5, 7) - +state.from.slice(5, 7)) + 1;
    var buckets = [];
    if (months <= 12) {
      var crossYear = state.from.slice(0, 4) !== state.to.slice(0, 4);
      for (var i = 0; i < months; i++) {
        var y = +state.from.slice(0, 4), m = +state.from.slice(5, 7) + i;
        y += Math.floor((m - 1) / 12); m = (m - 1) % 12 + 1;
        var key = y + "-" + (m < 10 ? "0" : "") + m;
        buckets.push({ key: key, label: (crossYear && (i === 0 || m === 1) ? String(y).slice(2) + "/" + m : T.month.replace("{m}", m)) });
      }
    } else {
      for (var yy = +state.from.slice(0, 4); yy <= +state.to.slice(0, 4); yy++) buckets.push({ key: String(yy), label: String(yy) });
    }
    buckets.forEach(function (b) {
      b.byType = {};
      b.total = 0;
      shows.forEach(function (s) {
        if (s.d.slice(0, b.key.length) === b.key) { b.byType[s.t] = (b.byType[s.t] || 0) + 1; b.total++; }
      });
    });
    var heardRows = Object.keys(heard).map(function (k) { return { title: D.titles[k], n: heard[k] }; })
      .sort(function (a, b) { return b.n - a.n; });
    return {
      n: shows.length, byType: byType, byCity: byCity, buckets: buckets, monthly: months <= 12,
      heard: heardRows, songs: heardRows.length, plays: plays, cities: Object.keys(byCity).length,
      km: dist ? dist.km : null, kmShows: dist ? dist.n : 0, route: route
    };
  }

  // ------------------------------------------------------------ 畫圖的小工具
  function font(size, weight) { return (weight || 400) + " " + size + "px " + FONT; }
  function rr(x, y, w, h, r) {
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
    ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r);
    ctx.closePath();
  }
  function fit(text, max) {          // 太長就截掉加「…」
    text = String(text);
    if (ctx.measureText(text).width <= max) return text;
    while (text.length > 1 && ctx.measureText(text + "…").width > max) text = text.slice(0, -1);
    return text + "…";
  }
  function fitFont(text, size, weight, max, min) {    // 太長就把字縮小（最小 min）
    for (; size > min; size -= 2) { ctx.font = font(size, weight); if (ctx.measureText(text).width <= max) return size; }
    ctx.font = font(min, weight);
    return min;
  }
  function text(str, x, y, size, weight, color, align) {
    ctx.font = font(size, weight); ctx.fillStyle = color; ctx.textAlign = align || "left"; ctx.textBaseline = "alphabetic";
    ctx.fillText(str, x, y);
  }
  function fmt(n) { return Number(n).toLocaleString(D.lang === "en" ? "en" : "zh-TW"); }
  function card(bw, bh, title) {
    rr(0, 0, bw, bh, 28); ctx.fillStyle = C.card; ctx.fill();
    ctx.lineWidth = 2; ctx.strokeStyle = C.border; ctx.stroke();
    if (title) { ctx.font = font(30, 700); text(fit(title, bw - 56), 28, 54, 30, 700, C.text); }
  }

  // ------------------------------------------------------------ 地圖
  var PLACE = HomeRoute.MapPlace(D.map, D.cities), NODES = PLACE.nodes;
  // 畫卡片裡的台灣底圖，之後的座標就是地圖座標；畫完要 ctx.restore()
  function mapBase(bw, bh) {
    var M = D.map, box = [12, 72, bw - 24, bh - 84];
    var k = Math.min(box[2] / M.width, box[3] / M.height);
    ctx.save();
    ctx.translate(box[0] + (box[2] - M.width * k) / 2, box[1] + (box[3] - M.height * k) / 2);
    ctx.scale(k, k);
    ctx.fillStyle = C.land; ctx.strokeStyle = C.landLine; ctx.lineWidth = 1.2; ctx.lineJoin = "round";
    [M.mainland].concat(M.islands).forEach(function (d) { var p = new Path2D(d); ctx.fill(p); ctx.stroke(p); });
  }
  function insetBox(node) {
    ctx.setLineDash([3, 3]); ctx.strokeStyle = "#d5dae1"; ctx.lineWidth = 1;
    rr(node.inset[0], node.inset[1], node.inset[2], node.inset[3], 8); ctx.stroke(); ctx.setLineDash([]);
  }
  function mapLabel(str, x, y, align, bold, color) {      // 白邊的字，壓在線上也看得清楚
    ctx.font = font(15, bold ? 700 : 400); ctx.textAlign = align;
    ctx.lineWidth = 3; ctx.strokeStyle = "#ffffff"; ctx.lineJoin = "round"; ctx.strokeText(str, x, y);
    ctx.fillStyle = color; ctx.fillText(str, x, y);
  }
  function cityLabel(c) { return D.lang === "en" ? c.name : NODES[c.id].name; }

  // ------------------------------------------------------------ 各種圖表（在基準大小下畫）
  var DRAW = {
    numbers: function (bw, bh, S) {
      card(bw, bh);
      var tiles = [[S.n, T.n_shows], [S.songs, T.n_songs], [S.cities, T.n_cities]];
      if (S.km !== null) tiles.push([S.km, T.km]);
      var tw = bw / tiles.length;
      tiles.forEach(function (t, i) {
        var cx = tw * i + tw / 2;
        if (i) { ctx.fillStyle = C.border; ctx.fillRect(tw * i - 1, 40, 2, bh - 80); }
        var size = fitFont(fmt(t[0]), 76, 700, tw - 40, 36);
        text(fmt(t[0]), cx, 108, size, 700, C.primary, "center");
        ctx.font = font(28); text(fit(t[1], tw - 30), cx, 152, 28, 400, C.muted, "center");
      });
    },

    years: function (bw, bh, S) {
      card(bw, bh, S.monthly ? T.months : T.years);
      var B = S.buckets, x0 = 32, x1 = bw - 32, top = 104, base = 300;
      var max = Math.max.apply(null, B.map(function (b) { return b.total; }).concat([1]));
      var slot = (x1 - x0) / B.length, bar = Math.min(slot * 0.64, 70);
      var every = Math.ceil(B.length / 12);           // 年份太多就隔幾個標一次
      B.forEach(function (b, i) {
        var cx = x0 + slot * (i + 0.5), y = base;
        D.types.forEach(function (t) {
          var n = b.byType[t.id];
          if (!n) return;
          var h = (base - top) * n / max;
          ctx.fillStyle = t.color; ctx.fillRect(cx - bar / 2, y - h, bar, h);
          ctx.fillStyle = C.card; ctx.fillRect(cx - bar / 2, y - h, bar, 2);       // 色塊之間的白縫
          y -= h;
        });
        if (b.total) text(String(b.total), cx, y - 10, 24, 700, C.text, "center");
        if (i % every === 0) text(b.label, cx, base + 34, B.length > 8 ? 20 : 24, 400, C.muted, "center");
      });
      ctx.fillStyle = C.border; ctx.fillRect(x0, base, x1 - x0, 2);
      // 圖例：這段期間有去過的類型
      var used = D.types.filter(function (t) { return S.byType[t.id]; });
      var size = 22, widths;
      for (; size >= 14; size -= 2) {
        ctx.font = font(size);
        widths = used.map(function (t) { return size + 8 + ctx.measureText(t.name).width; });
        if (widths.reduce(function (a, b) { return a + b + 22; }, -22) <= bw - 48) break;
      }
      var x = (bw - widths.reduce(function (a, b) { return a + b + 22; }, -22)) / 2;
      used.forEach(function (t, i) {
        ctx.fillStyle = t.color; ctx.beginPath(); ctx.arc(x + size / 2 - 2, 372 - size / 3, size / 2 - 3, 0, Math.PI * 2); ctx.fill();
        text(t.name, x + size + 4, 372, size, 400, C.text);
        x += widths[i] + 22;
      });
    },

    types: function (bw, bh, S) {
      var rows = D.types.filter(function (t) { return S.byType[t.id]; })
        .map(function (t) { return { name: t.name, n: S.byType[t.id], color: t.color }; });
      rows.sort(function (a, b) { return b.n - a.n; });     // 多的在前；一樣多的照後台的排序（D.types 本來就照排序）
      doughnut(bw, bh, T.types, rows, S.n);
    },

    cities: function (bw, bh, S) {
      var rows = D.cities.filter(function (c) { return S.byCity[c.id]; })
        .map(function (c) { return { name: c.name, n: S.byCity[c.id] }; });
      rows.sort(function (a, b) { return b.n - a.n; });     // 多的在前；一樣多的照後台的排序（D.cities 本來就照排序）
      rows.forEach(function (r, i) { r.color = i < D.colors.length ? D.colors[i] : D.other_color; });
      doughnut(bw, bh, T.cities, rows, S.n);
    },

    map: function (bw, bh, S) {
      card(bw, bh, T.map);
      mapBase(bw, bh);
      var top = Math.max.apply(null, Object.keys(S.byCity).map(function (id) { return S.byCity[id]; }).concat([1]));
      D.cities.forEach(function (c) {
        var node = NODES[c.id], n = S.byCity[c.id] || 0, r = n ? 5 + 10 * Math.sqrt(n / top) : 3;
        if (node.inset) insetBox(node);
        ctx.beginPath(); ctx.arc(node.x, node.y, r, 0, Math.PI * 2);
        ctx.fillStyle = n ? C.dot : C.zero; ctx.fill();
        ctx.lineWidth = 1.5; ctx.strokeStyle = "#ffffff"; ctx.stroke();
        if (r >= 9) text(String(n), node.x, node.y + 4, 11, 700, "#ffffff", "center");
        if (!n && !node.inset) return;      // 沒去過的縣市只畫灰點，不寫名字
        if (node.inset) mapLabel(cityLabel(c), node.x, node.inset[1] + 12, "center", n, n ? C.text : C.muted);
        else if (node.left) mapLabel(cityLabel(c), node.x - r - 3, node.y + 4.5, "right", true, C.text);
        else mapLabel(cityLabel(c), node.x + r + 3, node.y + 4.5, "left", true, C.text);
      });
      ctx.restore();
    },

    routes: function (bw, bh, S) {
      card(bw, bh, T.routes);
      if (S.km !== null) text(T.km_short.replace("{km}", fmt(S.km)), bw - 28, 54, 26, 700, C.primary, "right");
      mapBase(bw, bh);
      var home = state.home && PLACE.home(state.home);
      var used = {};
      D.cities.forEach(function (c) {         // 有去過的框（金門、連江、海外）才畫出來
        if (NODES[c.id].inset && S.byCity[c.id]) used[c.id] = true;
      });
      Object.keys(used).forEach(function (id) {
        var node = NODES[id];
        insetBox(node);
        mapLabel(cityLabel(cityById[id]), node.x, node.inset[1] + 12, "center", false, C.muted);
      });
      var dots = [];
      S.route.trips.forEach(function (day) {
        var stops = day.map(function (s) { return PLACE.stop(s, S.route.where(s)); });
        dots = dots.concat(stops);
        if (!home) return;
        HomeRoute.legs(home, stops).forEach(function (l) {
          ctx.beginPath(); ctx.moveTo(l.a.x, l.a.y); ctx.quadraticCurveTo(l.c.x, l.c.y, l.b.x, l.b.y);
          ctx.setLineDash(l.a.far || l.b.far ? [4, 3] : []);        // 海外畫虛線
          ctx.strokeStyle = "rgba(47, 111, 219, .45)"; ctx.lineWidth = 1.6; ctx.stroke();
        });
        ctx.setLineDash([]);
      });
      dots.forEach(function (p) {
        ctx.beginPath(); ctx.arc(p.x, p.y, 3.2, 0, Math.PI * 2);
        ctx.fillStyle = C.primary; ctx.fill(); ctx.lineWidth = 1.2; ctx.strokeStyle = "#ffffff"; ctx.stroke();
      });
      if (home) {
        ctx.beginPath(); ctx.arc(home.x, home.y, 6, 0, Math.PI * 2);
        ctx.fillStyle = C.home; ctx.fill(); ctx.lineWidth = 2; ctx.strokeStyle = "#ffffff"; ctx.stroke();
        mapLabel(T.home, home.x + 9, home.y + 5, "left", true, C.home);
      }
      ctx.restore();
      if (!home) {
        ctx.font = font(20);         // 標題下面、地圖左上角是海，放提示不會壓到東西
        text(fit(T.routes_need_home, bw - 56), 28, 92, 20, 400, C.muted);
      }
    },

    heard: function (bw, bh, S) {
      songList(bw, bh, T.heard, S.heard.slice(0, state.rows), S.heard.length ? S.heard[0].n : 1);
    },

    likes: function (bw, bh) {
      songList(bw, bh, T.likes, D.likes.slice(0, state.rows).map(function (t) { return { title: t }; }));
    }
  };

  function doughnut(bw, bh, title, rows, total) {
    card(bw, bh, title);
    var cx = bw / 2, cy = 200, r = 118, a = -Math.PI / 2;
    if (!total) { ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2); ctx.fillStyle = C.zero; ctx.fill(); }
    rows.forEach(function (row) {       // 從 12 點鐘順時針，多的在前
      var b = a + Math.PI * 2 * row.n / total;
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.arc(cx, cy, r, a, b); ctx.closePath();
      ctx.fillStyle = row.color; ctx.fill();
      ctx.lineWidth = 3; ctx.strokeStyle = C.card; ctx.stroke();
      a = b;
    });
    ctx.beginPath(); ctx.arc(cx, cy, r * 0.58, 0, Math.PI * 2); ctx.fillStyle = C.card; ctx.fill();
    text(String(total), cx, cy + 12, 56, 700, C.text, "center");
    text(T.shows, cx, cy + 44, 22, 400, C.muted, "center");
    // 圖例：前三名，其餘併成「其他」
    var shown = rows.length > 4 ? rows.slice(0, 3).concat([{ name: T.other, color: D.other_color,
      n: rows.slice(3).reduce(function (s, x) { return s + x.n; }, 0) }]) : rows;
    shown.forEach(function (row, i) {
      var y = 364 + i * 34;
      ctx.fillStyle = row.color; ctx.beginPath(); ctx.arc(40, y - 8, 8, 0, Math.PI * 2); ctx.fill();
      var right = row.n + " (" + Math.round(row.n / total * 100) + "%)";
      ctx.font = font(24, 700);
      var rw = ctx.measureText(right).width;
      text(right, bw - 28, y, 24, 700, C.text, "right");
      ctx.font = font(24);
      text(fit(row.name, bw - 28 - rw - 16 - 58), 58, y, 24, 400, C.text);
    });
  }

  function songList(bw, bh, title, rows, max) {
    card(bw, bh, title);
    var pad = 36, x = pad + 30, w = bw - x - pad;          // 左右留白；曲名從編號右邊開始
    if (!rows.length) { text(T.none, pad, 120, 22, 400, C.muted); return; }
    rows.forEach(function (row, i) {
      var y = 86 + i * 50;
      text(String(i + 1), pad + 8, y + 28, 20, 700, C.muted, "center");
      var right = 0;
      if (row.n) {
        var cnt = row.n + " " + T.times;
        ctx.font = font(20, 700); right = ctx.measureText(cnt).width + 14;
        text(cnt, bw - pad, y + 28, 20, 700, C.primary, "right");
        ctx.fillStyle = C.bg1; rr(x, y + 37, w, 5, 2.5); ctx.fill();
        ctx.fillStyle = C.primary; rr(x, y + 37, Math.max(5, w * row.n / max), 5, 2.5); ctx.fill();
      }
      ctx.font = font(22);
      text(fit(row.title, w - right), x, y + 28, 22, 400, C.text);
    });
  }

  // ------------------------------------------------------------ 整張圖
  var logo = null;
  if (D.logo) {
    var img = new Image();
    img.onload = function () { logo = img; schedule(); };
    img.src = D.logo;
  }
  function chosenName() {
    var r = document.querySelector('input[name="recap-name"]:checked');
    return r ? D.names[r.value] : (D.names.nickname || D.names.google);
  }

  function render() {
    var g = geom(), H = g.H, s = g.safe, S = stats();
    if (canvas.height !== H) canvas.height = H;
    var bg = ctx.createLinearGradient(0, 0, 0, H);
    bg.addColorStop(0, C.bg1); bg.addColorStop(0.6, C.bg2); bg.addColorStop(1, C.bg2);
    ctx.fillStyle = bg; ctx.fillRect(0, 0, W, H);

    // 標題：Logo、「XXX的163braces回顧」、期間
    var x = s.l, maxW = s.r - s.l;
    if (logo) {
      var lh = 104, lw = Math.min(lh * logo.width / logo.height, 220);
      lh = lw * logo.height / logo.width;
      ctx.drawImage(logo, x, s.t + (104 - lh) / 2, lw, lh);
      x += lw + 24; maxW -= lw + 24;
    }
    var title = T.title.replace("{name}", chosenName());
    var size = fitFont(title, 60, 700, maxW, 30), mid = x + maxW / 2;        // 標題、期間都置中在 Logo 右邊的文字區
    text(title, mid, s.t + 58, size, 700, C.text, "center");
    text(periodLabel(state.from, state.to), mid, s.t + 108, 40, 700, C.primary, "center");

    widgets().forEach(function (wd) {
      var b = baseSize(wd.kind), k = wd.w / b[0];
      ctx.save(); ctx.translate(wd.x, wd.y); ctx.scale(k, k);
      DRAW[wd.kind](b[0], b[1], S);
      ctx.restore();
    });

    text(T.footer, W / 2, s.b - 16, 28, 400, C.muted, "center");
    updateInfo(S);
  }
  var pending = false;
  function schedule() {
    if (pending) return;
    pending = true;
    requestAnimationFrame(function () { pending = false; render(); });
  }

  // ------------------------------------------------------------ 自動排列
  // 照順序把圖表排成幾列，每列等高、剛好填滿寬度（放不下就整體縮小）。試過所有分列方式，
  // 挑「最小的那張圖」縮放比例最大的，也就是整張圖裡最小的字最大
  function autoLayout() {
    var g = geom(), A = g.area, AW = A.r - A.l, AH = A.b - A.t;
    var kinds = KINDS.filter(function (k) { return widgets().some(function (w) { return w.kind === k; }); });
    if (!kinds.length) return;
    var ratios = kinds.map(ratio), n = kinds.length, best = null;
    for (var mask = 0; mask < (1 << (n - 1)); mask++) {
      var rows = [[0]];
      for (var i = 1; i < n; i++) {
        if (mask & (1 << (i - 1))) rows.push([i]); else rows[rows.length - 1].push(i);
      }
      var hs = rows.map(function (r) {
        return (AW - GAP * (r.length - 1)) / r.reduce(function (sum, j) { return sum + ratios[j]; }, 0);
      });
      var total = hs.reduce(function (a, b) { return a + b; }, 0) + GAP * (rows.length - 1);
      var smallest = Math.min.apply(null, rows.map(function (r, ri) {     // 這一列裡最小的縮放比例＝列高 ÷ 基準高
        return Math.min.apply(null, r.map(function (j) { return hs[ri] / baseSize(kinds[j])[1]; }));
      }));
      var score = smallest * Math.min(1, AH / total);
      if (!best || score > best.score + 1e-6 || (Math.abs(score - best.score) <= 1e-6 && total > best.total)) {
        best = { rows: rows, hs: hs, total: total, score: score };
      }
    }
    var k = Math.min(1, AH / best.total), y = A.t + (AH - best.total * k) / 2, out = [];
    best.rows.forEach(function (r, ri) {
      var h = best.hs[ri] * k, x = A.l + (AW - AW * k) / 2;
      r.forEach(function (j) {
        var w = h * ratios[j];
        out.push({ kind: kinds[j], x: x, y: y, w: w });
        x += w + GAP * k;
      });
      y += h + GAP * k;
    });
    state.layouts[state.format] = out;
  }

  function clamp(wd) {
    var A = geom().area, r = ratio(wd.kind);
    wd.w = Math.max(Math.min(minWidth(wd.kind), A.r - A.l), Math.min(wd.w, A.r - A.l, (A.b - A.t) * r));
    wd.x = Math.min(Math.max(wd.x, A.l), A.r - wd.w);
    wd.y = Math.min(Math.max(wd.y, A.t), A.b - wd.w / r);
  }

  // ------------------------------------------------------------ 編輯：拖曳、縮放、拿掉
  function pct(v, of) { return (v / of * 100) + "%"; }
  function place(el, wd) {
    var H = geom().H;
    el.style.left = pct(wd.x, W); el.style.top = pct(wd.y, H);
    el.style.width = pct(wd.w, W); el.style.height = pct(wd.w / ratio(wd.kind), H);
  }
  function buildFrames() {
    frames.innerHTML = "";
    widgets().forEach(function (wd, i) {
      var el = document.createElement("div");
      el.className = "recap-frame";
      el.dataset.i = i;
      el.innerHTML = '<button type="button" class="recap-x" aria-label="×">×</button><span class="recap-handle"></span>';
      el.querySelector(".recap-x").setAttribute("aria-label", T[wd.kind] + " ×");
      place(el, wd);
      frames.appendChild(el);
    });
    var H = geom().H, s = geom().safe;
    guides.innerHTML = [[0, 0, W, s.t], [0, s.b, W, H - s.b], [0, s.t, s.l, s.b - s.t], [s.r, s.t, W - s.r, s.b - s.t]]
      .filter(function (b) { return b[2] > 0 && b[3] > 0; })
      .map(function (b) {
        return '<span style="left:' + pct(b[0], W) + ";top:" + pct(b[1], H) + ";width:" + pct(b[2], W) + ";height:" + pct(b[3], H) + '"></span>';
      }).join("");
    stage.classList.toggle("square", state.format === "square");
    document.querySelector(".recap-safe-hint").hidden = state.format === "square";
    document.querySelectorAll("#recap-kinds input").forEach(function (cb) {
      cb.checked = widgets().some(function (w) { return w.kind === cb.value; });
    });
  }

  frames.addEventListener("click", function (e) {
    var x = e.target.closest(".recap-x");
    if (!x) return;
    widgets().splice(+x.parentNode.dataset.i, 1);
    save(); buildFrames(); schedule();
  });
  frames.addEventListener("pointerdown", function (e) {
    var el = e.target.closest(".recap-frame");
    if (!el || e.target.closest(".recap-x")) return;
    var wd = widgets()[+el.dataset.i], A = geom().area, r = ratio(wd.kind);
    var k = W / stage.clientWidth, resize = !!e.target.closest(".recap-handle");
    var sx = e.clientX, sy = e.clientY, ox = wd.x, oy = wd.y, ow = wd.w;
    e.preventDefault();
    el.setPointerCapture(e.pointerId);
    el.classList.add("active");
    function move(ev) {
      var dx = (ev.clientX - sx) * k, dy = (ev.clientY - sy) * k;
      if (resize) {     // 往右或往下拉都可以，看哪個方向拉得多；右下角不超出可以放的範圍
        wd.w = ow + (Math.abs(dx) > Math.abs(dy * r) ? dx : dy * r);
        wd.w = Math.min(wd.w, A.r - wd.x, (A.b - wd.y) * r);
      } else { wd.x = ox + dx; wd.y = oy + dy; }
      clamp(wd); place(el, wd); schedule();
    }
    function up() {
      el.removeEventListener("pointermove", move);
      el.removeEventListener("pointerup", up);
      el.removeEventListener("pointercancel", up);
      el.classList.remove("active");
      save();
    }
    el.addEventListener("pointermove", move);
    el.addEventListener("pointerup", up);
    el.addEventListener("pointercancel", up);
  });

  // ------------------------------------------------------------ 左邊的選項
  var kindsBox = document.getElementById("recap-kinds");
  kindsBox.innerHTML = KINDS.map(function (k) {
    return '<label class="check-row"><input type="checkbox" value="' + k + '"> ' + T[k] + "</label>";
  }).join("");
  kindsBox.addEventListener("change", function (e) {
    var k = e.target.value, list = widgets();
    if (e.target.checked) {    // 新加的放在可放範圍的正中間，大小約一半寬
      var A = geom().area, wd = { kind: k, w: Math.max(minWidth(k), (A.r - A.l) * (k === "numbers" ? 1 : 0.45)) };
      wd.x = (A.l + A.r - wd.w) / 2; wd.y = (A.t + A.b - wd.w / ratio(k)) / 2;
      clamp(wd); list.push(wd);
    } else {
      state.layouts[state.format] = list.filter(function (w) { return w.kind !== k; });
    }
    save(); buildFrames(); schedule();
  });
  document.getElementById("recap-auto").addEventListener("click", function () {
    autoLayout(); save(); buildFrames(); schedule();
  });
  var rowsSel = document.getElementById("recap-rows");
  rowsSel.value = String(state.rows);
  rowsSel.addEventListener("change", function () {
    state.rows = +rowsSel.value;
    ["story", "square"].forEach(function (f) {
      var keep = state.format;
      state.format = f;
      (state.layouts[f] || []).forEach(clamp);
      state.format = keep;
    });
    save(); buildFrames(); schedule();
  });
  document.querySelectorAll('input[name="recap-format"]').forEach(function (r) {
    r.checked = r.value === state.format;
    r.addEventListener("change", function () {
      state.format = r.value;
      if (!widgets()) { state.layouts[state.format] = KINDS.map(function (k) { return { kind: k, x: 0, y: 0, w: 0 }; }); autoLayout(); }
      save(); buildFrames(); schedule();
    });
  });
  document.querySelectorAll('input[name="recap-name"]').forEach(function (r) { r.addEventListener("change", schedule); });

  // 期間
  var yearSel = document.getElementById("recap-year"), fromIn = document.getElementById("recap-from"), toIn = document.getElementById("recap-to");
  yearSel.innerHTML = ['<option value="all">' + T.all + "</option>"].concat(years.map(function (y) {
    return '<option value="' + y + '">' + y + "</option>";
  }), ['<option value="custom">' + T.custom + "</option>"]).join("");
  function syncPeriod() {
    fromIn.value = state.from; toIn.value = state.to;
    var y = state.from.slice(0, 4);
    yearSel.value = state.from === y + "-01-01" && state.to === y + "-12-31" ? y
      : state.from === years[years.length - 1] + "-01-01" && state.to === thisYear + "-12-31" ? "all" : "custom";
  }
  yearSel.addEventListener("change", function () { setYear(yearSel.value); syncPeriod(); schedule(); });
  [fromIn, toIn].forEach(function (inp) {
    inp.addEventListener("change", function () {
      if (!fromIn.value || !toIn.value) return;
      state.from = fromIn.value < toIn.value ? fromIn.value : toIn.value;
      state.to = fromIn.value < toIn.value ? toIn.value : fromIn.value;
      syncPeriod(); schedule();
    });
  });
  // 預設：今年；今年還沒去過的話用最近去過的那一年
  var lastShowYear = D.shows.length ? D.shows[D.shows.length - 1].d.slice(0, 4) : thisYear;
  setYear(D.shows.some(function (s) { return s.d.slice(0, 4) === thisYear; }) ? thisYear : lastShowYear);
  syncPeriod();

  var periodOut = document.getElementById("recap-period-label"), periodN = document.getElementById("recap-period-n");
  var kmOut = document.getElementById("recap-km");
  function updateInfo(S) {
    periodOut.textContent = periodLabel(state.from, state.to);
    periodN.textContent = T.shows_n.replace("{n}", S.n);
    kmOut.textContent = S.km === null ? "" : T.km_note.replace("{km}", fmt(S.km)).replace("{n}", S.kmShows);
  }

  // 住的行政區（清單另外載入，記在這台裝置；跟「我的足跡」共用）
  HomeRoute.picker({
    county: document.getElementById("recap-county"), town: document.getElementById("recap-town"),
    url: D.districts, lang: D.lang, saved: D.home_saved, remember: document.getElementById("recap-remember"),
    onChange: function (ll) { state.home = ll; schedule(); }
  });

  // ------------------------------------------------------------ 輸出
  var result = document.getElementById("recap-result"), resultImg = document.getElementById("recap-img");
  var blob = null;
  document.getElementById("recap-export").addEventListener("click", function () {
    render();
    canvas.toBlob(function (b) {
      blob = b;
      if (resultImg.src) URL.revokeObjectURL(resultImg.src);
      resultImg.src = URL.createObjectURL(b);
      result.hidden = false;
      result.scrollIntoView({ behavior: "smooth", block: "start" });
    }, "image/jpeg", 0.92);
  });
  document.getElementById("recap-download").addEventListener("click", function () {
    if (!blob) return;
    var name = T.file + "-" + periodLabel(state.from, state.to).replace(/[\/~]/g, "-") + ".jpg";
    function plain() {           // 不支援選資料夾的瀏覽器：照瀏覽器的下載設定存
      var a = document.createElement("a");
      a.href = resultImg.src; a.download = name;
      document.body.appendChild(a); a.click(); a.remove();
    }
    if (!window.showSaveFilePicker) return plain();
    window.showSaveFilePicker({ suggestedName: name, types: [{ description: "JPEG", accept: { "image/jpeg": [".jpg"] } }] })
      .then(function (h) { return h.createWritable().then(function (w) { return w.write(blob).then(function () { return w.close(); }); }); })
      .catch(function (e) { if (e.name !== "AbortError") plain(); });
  });

  // ------------------------------------------------------------ 開始
  if (!widgets()) { state.layouts[state.format] = KINDS.map(function (k) { return { kind: k, x: 0, y: 0, w: 0 }; }); autoLayout(); }
  widgets().forEach(clamp);
  buildFrames();
  // 字型載入後再畫一次，不然第一次可能用到備用字型
  render();
  if (document.fonts) {
    Promise.all([font(60, 700), font(28, 400)].map(function (f) { return document.fonts.load(f, "回顧163"); }))
      .then(schedule, schedule);
  }
})();
