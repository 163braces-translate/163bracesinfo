/* 住的地方與移動路線：回顧（recap.js）和我的足跡（me.js）共用。
 * 住的地方是台灣的行政區，或「其他地點」（海外等：貼 Google 地圖連結或輸入座標，只取到小數兩位，約 1 公里）。
 * 預設只記在這台裝置（localStorage）；勾了「記在我的帳號」才送回伺服器。
 * 路線的算法：每一天一趟，從家出發，照順序到當天的每個場地，最後回家，每一段算直線距離。 */
window.HomeRoute = (function () {
  "use strict";
  var KEY = "recap-home";

  function km(a, b) {      // 兩個 [經度, 緯度] 之間的直線距離
    var rad = Math.PI / 180, dLat = (b[1] - a[1]) * rad, dLon = (b[0] - a[0]) * rad;
    var h = Math.pow(Math.sin(dLat / 2), 2) + Math.cos(a[1] * rad) * Math.cos(b[1] * rad) * Math.pow(Math.sin(dLon / 2), 2);
    return 2 * 6371 * Math.asin(Math.sqrt(h));
  }

  // shows：[{d: 日期, c: 城市 id, ll: [經度, 緯度] 或 null}, …]，照日期排好。cities：[{id, key, ll, name}, …]
  function Route(shows, cities) {
    var byId = {};
    cities.forEach(function (c) { byId[c.id] = c; });
    var trips = [], byDay = {};
    shows.forEach(function (s) {
      if (!byDay[s.d]) { byDay[s.d] = []; trips.push(byDay[s.d]); }
      byDay[s.d].push(s);
    });
    // 場地座標，還沒填的用縣市中心；海外沒填就是 null（不算距離）
    function where(s) { return s.ll || (byId[s.c] && byId[s.c].ll) || null; }
    return {
      trips: trips,
      where: where,
      distance: function (home) {      // {km: 總公里數, n: 有算進去的場次}
        var total = 0, n = 0;
        trips.forEach(function (day) {
          var stops = day.map(where).filter(Boolean);
          n += stops.length;
          stops = [home].concat(stops, [home]);
          for (var i = 1; i < stops.length; i++) total += km(stops[i - 1], stops[i]);
        });
        return { km: Math.round(total), n: n };
      }
    };
  }

  // 地圖上的位置（app/taiwan.py 的 map_data()）。nodes：城市 id → 位置；不在地圖上的（海外）在左下角各一個框，跟演出頁一樣
  function MapPlace(map, cities) {
    var nodes = {}, keyOf = {}, off = 0;
    cities.forEach(function (c) {
      keyOf[c.id] = c.key;
      var node = c.key && map.nodes[c.key];
      if (!node) {
        var y0 = map.height - 62 - off * 60;
        node = { name: c.name, x: 40, y: y0 + 28, inset: [12, y0, 56, 48] };
        off++;
      }
      nodes[c.id] = node;
    });
    function project(ll) {      // 經緯度 → 地圖座標，跟 app/taiwan.py 的 project() 一樣
      var P = map.proj;
      return { x: (ll[0] - P[0]) * P[2] * P[3], y: (P[1] - ll[1]) * P[2] };
    }
    return {
      nodes: nodes,
      // 金門、連江、海外的場地畫到各自的框（far：海外，畫虛線）；其他照場地座標，還沒填的用縣市中心
      stop: function (s, ll) {
        var node = nodes[s.c];
        if (node.inset) return { x: node.x, y: node.y, far: !keyOf[s.c] };
        return ll ? project(ll) : { x: node.x, y: node.y };
      },
      // 家：台灣本島和澎湖照座標；金門、連江在各自的框；海外在右下角自己一個框（路線畫虛線）
      home: function (ll) {
        var lon = ll[0], lat = ll[1];
        if (lon > 118 && lon < 118.7 && lat > 24.2 && lat < 24.7) return map.nodes.kinmen;
        if (lon > 119.7 && lon < 120.7 && lat > 25.8 && lat < 26.5) return map.nodes.lienchiang;
        if (lon > 119.2 && lon < 122.2 && lat > 21.7 && lat < 25.5) return project(ll);
        var box = [map.width - 62, map.height - 60, 56, 48];
        return { x: box[0] + box[2] / 2, y: box[1] + box[3] / 2 + 4, inset: box, far: true, abroad: true };
      }
    };
  }

  // 一天要畫的線：家 → 場地 → … → 家。太短的不畫；只去一個地方的那天，回程跟去程同一條，只畫一次。
  // 回傳 [{a, b, c}]，c 是二次曲線的控制點（往一側彎的弧線）
  function legs(home, stops) {
    var pts = [home].concat(stops, [home]), drawn = {}, out = [];
    for (var i = 1; i < pts.length; i++) {
      var a = pts[i - 1], b = pts[i], dx = b.x - a.x, dy = b.y - a.y;
      var key = a.x + "," + a.y + ">" + b.x + "," + b.y, back = b.x + "," + b.y + ">" + a.x + "," + a.y;
      if (Math.sqrt(dx * dx + dy * dy) < 1.5 || drawn[back]) continue;
      drawn[key] = true;
      out.push({ a: a, b: b, c: { x: (a.x + b.x) / 2 - dy * 0.22, y: (a.y + b.y) / 2 + dx * 0.22 } });
    }
    return out;
  }

  // 「其他地點」的文字 → [經度, 緯度]：座標直接讀；Google 地圖連結交給伺服器讀（短網址要跟著轉址），回傳 Promise
  var COORDS = /^\s*\(?\s*(-?\d{1,2}(?:\.\d+)?)\s*[,，\s]\s*(-?\d{1,3}(?:\.\d+)?)\s*\)?\s*$/;
  function round2(v) { return Math.round(v * 100) / 100; }
  function readPlace(text, resolveUrl) {
    var m = COORDS.exec(text || "");
    if (m) {
      var lat = +m[1], lng = +m[2];
      return Promise.resolve(Math.abs(lat) <= 90 && Math.abs(lng) <= 180 ? [round2(lng), round2(lat)] : null);
    }
    if (!/^https?:\/\//i.test((text || "").trim()) || !resolveUrl) return Promise.resolve(null);
    var body = new FormData();
    body.append("url", text.trim());
    return fetch(resolveUrl, { method: "POST", body: body, credentials: "same-origin" }).then(function (r) { return r.json(); })
      .then(function (d) { if (d.error || d.lat == null) throw new Error(d.error || ""); return [round2(d.lng), round2(d.lat)]; });
  }

  // 縣市、行政區兩個選單：載入清單、還原上次選的，選了就記下來並呼叫 o.onChange([經度, 緯度] 或 null)。
  // 縣市選單最後一項是「其他地點」：打開 o.custom（輸入框、確定按鈕、狀態文字），貼地圖連結或輸入座標。
  // o：{county, town, custom, url（行政區清單）, resolve（讀地圖連結的 API）, lang, onChange,
  //     saved（帳號裡存的「縣市|行政區」或「@緯度,經度」）, remember（「記在我的帳號」勾選框，訪客沒有）}
  // 帳號裡有存的優先；勾著「記在我的帳號」時，改了就一起存到帳號，取消勾選就從帳號刪掉
  function picker(o) {
    var list = [], county = o.county, town = o.town, custom = o.custom, other = null;
    var input = custom && custom.querySelector("input"), status = custom && custom.querySelector("[data-home-status]");
    function isOther() { return county.value === "other"; }
    function fillTowns() {
      var c = !isOther() && list[county.selectedIndex - 1];
      town.innerHTML = '<option value="">' + town.options[0].textContent + "</option>" + (c ? c[2].map(function (t, i) {
        return '<option value="' + i + '">' + (o.lang === "en" ? t[1] : t[0]) + "</option>";
      }).join("") : "");
      town.disabled = !c;
      town.hidden = isOther();
      if (custom) custom.hidden = !isOther();
    }
    function current() {
      if (isOther()) return other && { key: "@" + other[1].toFixed(2) + "," + other[0].toFixed(2), ll: other };
      var c = list[county.selectedIndex - 1], t = c && town.value !== "" && c[2][+town.value];
      return t ? { key: c[0] + "|" + t[0], ll: [t[2], t[3]] } : null;
    }
    function saveAccount(value) {
      var body = new FormData();
      body.append("home", value);
      fetch("/api/me/home", { method: "POST", body: body, credentials: "same-origin" }).catch(function () {});
    }
    function pick() {
      var cur = current();
      try {
        if (cur) localStorage.setItem(KEY, cur.key); else localStorage.removeItem(KEY);
      } catch (e) { /* 無痕模式之類存不了，就不記 */ }
      if (o.remember && o.remember.checked) saveAccount(cur ? cur.key : "");
      o.onChange(cur && cur.ll);
    }
    function applyCustom() {
      var text = input.value;
      status.textContent = status.dataset.busy;
      readPlace(text, o.resolve).then(function (ll) {
        if (!ll) { status.textContent = status.dataset.bad; return; }
        other = ll;
        input.value = ll[1].toFixed(2) + ", " + ll[0].toFixed(2);
        status.textContent = status.dataset.done;
        pick();
      }).catch(function (e) { status.textContent = e.message || status.dataset.bad; });
    }
    county.addEventListener("change", function () { fillTowns(); pick(); });
    town.addEventListener("change", pick);
    if (custom) {
      custom.querySelector("button").addEventListener("click", applyCustom);
      input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); applyCustom(); } });
    }
    if (o.remember) {
      o.remember.checked = !!o.saved;
      o.remember.addEventListener("change", function () {
        var cur = current();
        saveAccount(o.remember.checked && cur ? cur.key : "");
      });
    }
    fetch(o.url).then(function (r) { return r.json(); }).then(function (data) {
      list = data;
      county.innerHTML += list.map(function (c) { return "<option>" + (o.lang === "en" ? c[1] : c[0]) + "</option>"; }).join("") +
        (custom ? '<option value="other">' + custom.dataset.option + "</option>" : "");
      var saved = o.saved || "";
      if (!saved) {
        try { saved = localStorage.getItem(KEY) || ""; } catch (e) { saved = ""; }
      }
      var at = /^@(-?[\d.]+),(-?[\d.]+)$/.exec(saved);
      if (at && custom) {
        other = [+at[2], +at[1]];
        county.value = "other"; fillTowns();
        input.value = at[1] + ", " + at[2];
        pick();
        return;
      }
      var parts = saved.split("|");
      list.forEach(function (c, ci) {
        if (c[0] !== parts[0]) return;
        county.selectedIndex = ci + 1; fillTowns();
        c[2].forEach(function (t, ti) { if (t[0] === parts[1]) town.value = String(ti); });
      });
      if (town.value !== "") pick();
    });
  }

  return { Route: Route, MapPlace: MapPlace, legs: legs, picker: picker };
})();
