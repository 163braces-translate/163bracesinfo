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
    // YouTube 要看得到是哪個網站在嵌入（Referer），看不到就顯示「錯誤 153：影片播放器設定錯誤」。
    // 明確指定，免得網站或主機哪天加了 Referrer-Policy: same-origin（舊站就是這樣）把它擋掉
    iframe.referrerPolicy = "strict-origin-when-cross-origin";
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
    $$(".tw-map [data-city]").forEach(function (el) {
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
      var extra = $('[data-f="extra"]', drawer), tpl = document.getElementById("extra" + d.id);
      extra.innerHTML = "";
      if (tpl) extra.appendChild(tpl.content.cloneNode(true));
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

  // ---- 粉絲功能的按鈕：沒登入時伺服器回 401，帶著現在的網址去登入頁
  function postJSON(url, body) {
    return fetch(url, { method: "POST", body: body || null, credentials: "same-origin",
                        headers: { "X-Return-To": location.pathname + location.search } })
      .then(function (r) {
        return r.json().then(function (data) {
          if (r.status === 401 && data.login_url) { location.href = data.login_url; throw new Error("login"); }
          if (!r.ok) throw new Error(data.error || "error");
          return data;
        });
      });
  }

  // 我去過：同一場在頁面上可能有好幾個按鈕（表格、展開的歌單、手機抽屜），一起更新
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-attend]");
    if (!btn) return;
    var id = btn.dataset.attend;
    btn.disabled = true;
    postJSON("/api/me/attendance/" + id).then(function (res) {
      $$('[data-attend="' + id + '"]').forEach(function (b) {
        b.classList.toggle("on", res.on);
        b.setAttribute("aria-pressed", res.on ? "true" : "false");
        b.textContent = res.on ? b.dataset.on : b.dataset.off;
      });
      $$('[data-attend-count="' + id + '"]').forEach(function (c) {
        c.textContent = res.count ? c.dataset.label.replace("{n}", res.count) : "";
      });
      // 手機方塊上的 ✓
      var card = document.querySelector('.perf-card[data-id="' + id + '"] .m'), badge = document.querySelector('[data-attend-badge="' + id + '"]');
      if (res.on && card && !badge) card.appendChild(Object.assign(document.createElement("span"), { className: "chip blue", textContent: "✓" })).dataset.attendBadge = id;
      if (!res.on && badge) badge.remove();
      // 抽屜裡的是複製出來的，原本 <template> 裡的也要改，下次打開才會對
      var tpl = document.getElementById("extra" + id);
      if (tpl) $$('[data-attend="' + id + '"]', tpl.content).forEach(function (b) {
        b.classList.toggle("on", res.on); b.textContent = res.on ? b.dataset.on : b.dataset.off;
      });
    }).catch(function () {}).then(function () { btn.disabled = false; });
  });

  // ♥ 喜歡
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-like]");
    if (!btn) return;
    btn.disabled = true;
    postJSON("/api/me/likes/" + btn.dataset.like).then(function (res) {
      btn.classList.toggle("on", res.on);
      btn.setAttribute("aria-pressed", res.on ? "true" : "false");
      var c = $("[data-like-count]", btn);
      if (c) c.textContent = res.count;
    }).catch(function () {}).then(function () { btn.disabled = false; });
  });

  // ---- 首頁跑馬燈
  // 字數：一個中文字算 1、一個英文單字算 1（跟伺服器 visitors.text_units 一樣的規則）
  function textUnits(text) {
    var cjk = (text.match(/[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff\uac00-\ud7af]/g) || []).length;
    var words = (text.match(/[A-Za-z0-9]+(?:['’\-][A-Za-z0-9]+)*/g) || []).length;
    return cjk + words;
  }
  var mform = $("[data-marquee-form]");
  if (mform) {
    var input = $("input[name=text]", mform), counter = $("[data-units]", mform), status = $("[data-marquee-status]", mform);
    var max = Number(mform.dataset.max);
    var update = function () {
      var left = max - textUnits(input.value);
      counter.textContent = (left < 0 ? counter.dataset.over : counter.dataset.label).replace("{n}", Math.abs(left));
      counter.classList.toggle("over", left < 0);
    };
    input.addEventListener("input", update);
    update();
    mform.addEventListener("submit", function (e) {
      e.preventDefault();
      status.textContent = "";
      postJSON("/api/marquee", new FormData(mform)).then(function () {
        status.textContent = mform.dataset.sent;
        setTimeout(function () { location.reload(); }, 700);
      }).catch(function (err) { if (err.message !== "login") status.textContent = err.message; });
    });
  }
  // 捲動速度固定（每秒約 70px），內容多就跑久一點
  $$(".marquee-track").forEach(function (track) {
    track.style.animationDuration = Math.max(20, track.scrollWidth / 2 / 70) + "s";
  });

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
      try { localStorage.setItem("lyricsViewMode", btn.dataset.view); } catch (err) {}
    });
    try {
      // 換過 key：舊版預設是雙語，存過的舊值不能蓋掉新的預設（只看主要語言）
      var saved = localStorage.getItem("lyricsViewMode");
      var btn = saved && $('button[data-view="' + saved + '"]', group);
      if (btn) btn.click();
    } catch (err) {}
  });
})();
