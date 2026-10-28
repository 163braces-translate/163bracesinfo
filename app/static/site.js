/* 前台共用的小互動。每段都先檢查頁面上有沒有對應的元素，沒有就略過。 */
(function () {
  "use strict";
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };

  // ---- 手機版選單
  var toggle = $(".nav-toggle"), nav = $("#site-nav");
  if (toggle && nav) {
    toggle.addEventListener("click", function () {
      var open = nav.classList.toggle("open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
    });
  }

  // ---- 頁首下拉選單：觸控螢幕沒有 hover，點 ▾ 展開／收合
  document.addEventListener("click", function (e) {
    var caret = e.target.closest(".nav-caret");
    $$(".nav-group.open").forEach(function (g) {
      if (!caret || g !== caret.parentElement) { g.classList.remove("open"); $(".nav-caret", g).setAttribute("aria-expanded", "false"); }
    });
    if (caret) {
      var open = caret.parentElement.classList.toggle("open");
      caret.setAttribute("aria-expanded", open ? "true" : "false");
    }
  });

  // ---- YouTube：點縮圖才換成播放器
  document.addEventListener("click", function (e) {
    var yt = e.target.closest(".yt[data-yt]");
    if (!yt || yt.classList.contains("playing")) return;
    var iframe = document.createElement("iframe");
    iframe.src = "https://www.youtube-nocookie.com/embed/" + yt.dataset.yt + "?autoplay=1&rel=0";
    iframe.allow = "autoplay; encrypted-media; picture-in-picture";
    iframe.allowFullscreen = true;
    iframe.title = yt.getAttribute("aria-label") || "YouTube";
    yt.appendChild(iframe);
    yt.classList.add("playing");
  });

  // ---- 首頁：換一首
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-another]");
    if (!btn) return;
    var slot = $("#listen-slot");
    btn.disabled = true;
    var prefix = document.documentElement.lang === "en" ? "/en" : "";
    fetch(prefix + "/api/random-song?exclude=" + encodeURIComponent(btn.dataset.another))
      .then(function (r) { return r.text(); })
      .then(function (html) { slot.innerHTML = html; })
      .catch(function () { btn.disabled = false; });
  });

  // ---- 演出頁：篩選
  var form = $("#filters");
  if (form) {
    var ftoggle = $(".filters-toggle", form);
    ftoggle.addEventListener("click", function () {
      var open = form.classList.toggle("open");
      ftoggle.setAttribute("aria-expanded", open ? "true" : "false");
    });

    // 日期模式：之後只要起日、之前只要迄日、期間兩個都要；迄日不能早於起日
    var mode = $("#date-mode"), dFrom = $("#date-from"), dTo = $("#date-to");
    var syncDates = function () {
      dFrom.hidden = mode.value === "before";
      dTo.hidden = mode.value === "after";
      dTo.min = mode.value === "range" ? dFrom.value : "";
    };
    mode.addEventListener("change", syncDates);
    dFrom.addEventListener("change", syncDates);
    syncDates();

    // 送出前把被隱藏的日期欄清掉，網址才乾淨
    form.addEventListener("submit", function () {
      if (dFrom.hidden) dFrom.value = "";
      if (dTo.hidden) dTo.value = "";
      $$("input, select", form).forEach(function (el) {
        if (!el.value || (el.name === "sort" && el.value === "event_date_desc") ||
            (el.name === "date_filter_type" && !dFrom.value && !dTo.value)) el.disabled = true;
      });
    });

    // 上一頁回來時（瀏覽器快取了頁面）把送出時停用的欄位恢復
    window.addEventListener("pageshow", function () {
      $$("input, select", form).forEach(function (el) { el.disabled = false; });
    });

    // 地圖、海外按鈕：切換對應城市的勾選後直接送出
    var toggleCity = function (id) {
      var box = $('input[name=city][value="' + id + '"]', form);
      if (!box) {
        box = document.createElement("input");
        box.type = "checkbox"; box.name = "city"; box.value = id; box.hidden = true;
        form.appendChild(box);
      }
      box.checked = !box.checked;
      if (form.requestSubmit) form.requestSubmit(); else form.submit();
    };
    $$(".tw-map [data-city], .map-other [data-city]").forEach(function (el) {
      el.addEventListener("click", function () { toggleCity(el.dataset.city); });
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggleCity(el.dataset.city); }
      });
    });
  }

  // ---- 演出頁（電腦版）：點活動名稱展開歌單
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".perf-name");
    if (!btn) return;
    var row = document.getElementById(btn.getAttribute("aria-controls"));
    var open = btn.getAttribute("aria-expanded") !== "true";
    btn.setAttribute("aria-expanded", open ? "true" : "false");
    row.hidden = !open;
  });

  // ---- 演出頁（手機版）：點方塊開抽屜
  var drawer = $(".drawer"), backdrop = $(".drawer-backdrop"), lastCard = null;
  if (drawer) {
    var close = function () {
      drawer.classList.remove("open");
      backdrop.classList.remove("open");
      document.body.style.overflow = "";
      setTimeout(function () { drawer.hidden = true; backdrop.hidden = true; }, 250);
      if (lastCard) lastCard.focus();
    };
    document.addEventListener("click", function (e) {
      var card = e.target.closest(".perf-card");
      if (!card) return;
      lastCard = card;
      var d = card.dataset;
      $("#drawer-title").textContent = d.name;
      var fields = {date: d.date, type: d.type, venue: d.venue, city: d.cityname};
      Object.keys(fields).forEach(function (k) { $('[data-f="' + k + '"]', drawer).textContent = fields[k] || "—"; });
      var slot = $('[data-f="setlist"]', drawer), src = document.querySelector("#sl" + d.id + " .setlist-content");
      slot.innerHTML = "";
      slot.appendChild(src ? src.cloneNode(true) : $("#no-setlist").content.cloneNode(true));
      drawer.hidden = false; backdrop.hidden = false;
      document.body.style.overflow = "hidden";
      requestAnimationFrame(function () { drawer.classList.add("open"); backdrop.classList.add("open"); });
      $("[data-close]", drawer).focus();
    });
    backdrop.addEventListener("click", close);
    $("[data-close]", drawer).addEventListener("click", close);
    document.addEventListener("keydown", function (e) { if (e.key === "Escape" && !drawer.hidden) close(); });
  }

  // ---- 歌詞索引：全部展開／全部收起（按鈕文字跟著目前狀態）
  var menu = $("[data-lyrics-menu]");
  if (menu) {
    var toggleAll = $("[data-toggle-all]", menu);
    var items = $$("details", menu);
    var sync = function () {
      var allOpen = items.every(function (d) { return d.open; });
      toggleAll.textContent = allOpen ? toggleAll.dataset.collapse : toggleAll.dataset.expand;
    };
    toggleAll.addEventListener("click", function () {
      var open = !items.every(function (d) { return d.open; });
      items.forEach(function (d) { d.open = open; });
      sync();
    });
    items.forEach(function (d) { d.addEventListener("toggle", sync); });
    sync();
  }

  // ---- 歌詞頁：中英對照／只看中文／只看英文
  $$("[data-lyrics-view]").forEach(function (group) {
    var bodies = $$(".lyrics-body.bilingual");
    group.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-view]");
      if (!btn) return;
      $$("button", group).forEach(function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); });
      bodies.forEach(function (b) {
        b.classList.remove("only-left", "only-right");
        if (btn.dataset.view !== "both") b.classList.add("only-" + btn.dataset.view);
      });
      try { localStorage.setItem("lyricsView", btn.dataset.view); } catch (err) {}
    });
    try {
      var saved = localStorage.getItem("lyricsView");
      var btn = saved && $('button[data-view="' + saved + '"]', group);
      if (btn) btn.click();
    } catch (err) {}
  });
})();
