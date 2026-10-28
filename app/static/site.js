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

  // ---- 投稿樂譜的圖檔：縮圖格預覽、拖曳或 ← → 排順序、✕ 移除；選檔按鈕一直往格子裡加。
  // 選好的圖先在瀏覽器裡縮小（最長邊 2400px、JPEG）：手機照片常常超過 5MB 的上限，
  // 伺服器收到後本來就會縮成這個大小，所以畫質不會比較差，只是上傳快很多。縮不了就照原檔上傳。
  // 送出時把新圖照格子的順序放回選檔欄位，順序寫在 order（k:舊圖 id、n:第幾張新圖）。
  var gallery = $("[data-sheet-gallery]");
  var sheetInput = $("[data-shrink]");
  if (gallery && sheetInput && window.DataTransfer) {
    var SHRINK_SIDE = 2400, SMALL_ENOUGH = 2.5 * 1024 * 1024;
    var sheetForm = sheetInput.form, glist = $(".gallery-list", gallery), gcount = $("[data-gallery-count]", gallery);
    var shrinkNote = $("[data-shrink-note]"), sheetSubmit = $("button[type=submit]", sheetForm);
    var maxImages = Number(gallery.dataset.max), gitems = [];
    var mb = function (n) { return (n / 1024 / 1024).toFixed(1) + "MB"; };
    var shrink = function (file) {
      if (!window.createImageBitmap) return Promise.resolve(file);
      return createImageBitmap(file, { imageOrientation: "from-image" }).then(function (bmp) {
        var scale = Math.min(1, SHRINK_SIDE / Math.max(bmp.width, bmp.height));
        if (scale === 1 && file.size <= SMALL_ENOUGH) return file;
        var canvas = document.createElement("canvas");
        canvas.width = Math.round(bmp.width * scale);
        canvas.height = Math.round(bmp.height * scale);
        var ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff";                       // 透明背景的 PNG 轉 JPEG 時墊白底
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
        return new Promise(function (resolve) {
          canvas.toBlob(function (blob) {
            resolve(blob && blob.size < file.size
              ? new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file);
          }, "image/jpeg", 0.88);
        });
      }).catch(function () { return file; });
    };
    var renderGallery = function () {
      var d = gallery.dataset;
      glist.innerHTML = gitems.map(function (it, i) {
        return '<li class="g-item" data-i="' + i + '"><img src="' + it.src + '" alt="' + (i + 1) + '" draggable="false">' +
          '<span class="g-num">' + (i + 1) + '</span><span class="g-tools">' +
          '<button type="button" data-g="left" aria-label="' + d.left + '"' + (i ? "" : " disabled") + '>←</button>' +
          '<button type="button" data-g="right" aria-label="' + d.right + '"' + (i < gitems.length - 1 ? "" : " disabled") + '>→</button>' +
          '<button type="button" data-g="remove" aria-label="' + d.remove + '">✕</button></span></li>';
      }).join("");
      var over = gitems.length > maxImages;
      gcount.textContent = gitems.length ? (over ? d.tooMany : d.count.replace("{n}", gitems.length)) : "";
      gcount.classList.toggle("over", over);
      sheetSubmit.disabled = over;
    };
    // 舊圖（編輯時）：從沒有 JavaScript 用的勾選框搬進格子，勾選框整塊拿掉
    $$(".keep-files label").forEach(function (label) {
      gitems.push({ kind: "k", id: $("input", label).value, src: $("img", label).src });
    });
    var keepBlock = $(".keep-files-block");
    if (keepBlock) keepBlock.remove();
    gallery.hidden = false;
    renderGallery();

    sheetInput.addEventListener("change", function () {
      var files = Array.prototype.slice.call(sheetInput.files);
      sheetInput.value = "";                          // 清掉，才能再選同一張；要上傳的檔案存在格子裡
      if (!files.length) return;
      sheetSubmit.disabled = true;
      shrinkNote.textContent = sheetInput.dataset.working;
      Promise.all(files.map(shrink)).then(function (out) {
        out.forEach(function (f) { gitems.push({ kind: "n", file: f, src: URL.createObjectURL(f) }); });
        var before = files.reduce(function (n, f) { return n + f.size; }, 0);
        var after = out.reduce(function (n, f) { return n + f.size; }, 0);
        shrinkNote.textContent = after < before ? sheetInput.dataset.done.replace("{a}", mb(before)).replace("{b}", mb(after)) : "";
        renderGallery();
      });
    });
    glist.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-g]");
      if (!btn) return;
      var i = Number(btn.closest("li").dataset.i), it = gitems[i];
      if (btn.dataset.g === "remove") {
        gitems.splice(i, 1);
        if (it.kind === "n") URL.revokeObjectURL(it.src);
      } else {
        var j = btn.dataset.g === "left" ? i - 1 : i + 1;
        gitems[i] = gitems[j]; gitems[j] = it;
      }
      renderGallery();
    });
    // 拖曳：按住縮圖移到別張的左半邊或右半邊（pointer 事件，手機也能拖）
    var gdrag = null;
    glist.addEventListener("pointerdown", function (e) {
      var li = e.target.closest(".g-item");
      if (!li || e.target.closest("button")) return;
      gdrag = li;
      li.classList.add("dragging");
      li.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    glist.addEventListener("pointermove", function (e) {
      if (!gdrag) return;
      var over = document.elementFromPoint(e.clientX, e.clientY);
      var li = over && over.closest(".g-item");
      if (!li || li === gdrag || li.parentNode !== glist) return;
      var r = li.getBoundingClientRect();
      glist.insertBefore(gdrag, e.clientX < r.left + r.width / 2 ? li : li.nextSibling);
    });
    var gdrop = function () {
      if (!gdrag) return;
      gdrag = null;
      gitems = $$(".g-item", glist).map(function (li) { return gitems[Number(li.dataset.i)]; });
      renderGallery();
    };
    glist.addEventListener("pointerup", gdrop);
    glist.addEventListener("pointercancel", gdrop);

    sheetForm.addEventListener("submit", function () {
      var dt = new DataTransfer(), order = [];
      gitems.forEach(function (it) {
        if (it.kind === "k") order.push("k:" + it.id);
        else { dt.items.add(it.file); order.push("n:" + (dt.items.length - 1)); }
      });
      sheetInput.files = dt.files;
      var field = $("input[name=order]", sheetForm) || sheetForm.appendChild(Object.assign(document.createElement("input"), { type: "hidden", name: "order" }));
      field.value = order.join(",");
    });
  }

  // 刪除之類的按鈕：先跳確認（按鈕上寫 data-confirm）
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-confirm]");
    if (btn && !window.confirm(btn.dataset.confirm)) e.preventDefault();
  });

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

  // 我去過：同一場在頁面上可能有好幾個按鈕（表格、展開的歌單、手機方塊），一起更新
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
    }).catch(function () {}).then(function () { btn.disabled = false; });
  });

  // ---- 我的 → 喜歡的歌：拖曳 ⋮⋮ 或按 ↑↓ 排順序，放開就存（手機也能拖：用 pointer 事件，不用 HTML5 拖放）
  var likeList = $("[data-like-order]");
  if (likeList) {
    var saveOrder = function () {
      var body = new FormData();
      body.append("ids", $$("li[data-song]", likeList).map(function (li) { return li.dataset.song; }).join(","));
      postJSON("/api/me/likes/order", body).catch(function () {});
    };
    var dragging = null;
    likeList.addEventListener("pointerdown", function (e) {
      var handle = e.target.closest("[data-drag]");
      if (!handle) return;
      dragging = handle.closest("li");
      dragging.classList.add("dragging");
      handle.setPointerCapture(e.pointerId);
      e.preventDefault();
    });
    likeList.addEventListener("pointermove", function (e) {
      if (!dragging) return;
      var over = document.elementFromPoint(e.clientX, e.clientY);
      var li = over && over.closest("li[data-song]");
      if (!li || li === dragging || li.parentNode !== likeList) return;
      var r = li.getBoundingClientRect();
      likeList.insertBefore(dragging, e.clientY < r.top + r.height / 2 ? li : li.nextSibling);
    });
    var drop = function () {
      if (!dragging) return;
      dragging.classList.remove("dragging");
      dragging = null;
      saveOrder();
    };
    likeList.addEventListener("pointerup", drop);
    likeList.addEventListener("pointercancel", drop);
    likeList.addEventListener("click", function (e) {
      var btn = e.target.closest("[data-move]");
      if (!btn) return;
      var li = btn.closest("li");
      if (btn.dataset.move === "up" && li.previousElementSibling) likeList.insertBefore(li, li.previousElementSibling);
      else if (btn.dataset.move === "down" && li.nextElementSibling) likeList.insertBefore(li.nextElementSibling, li);
      else return;
      btn.focus();
      saveOrder();
    });
  }

  // ♥ 喜歡
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-like]");
    if (!btn) return;
    btn.disabled = true;
    postJSON(btn.dataset.likeUrl || "/api/me/likes/" + btn.dataset.like).then(function (res) {     // 樂譜的讚有自己的網址
      btn.classList.toggle("on", res.on);
      btn.setAttribute("aria-pressed", res.on ? "true" : "false");
      var c = $("[data-like-count]", btn);
      if (c) c.textContent = res.count || ("hideZero" in c.dataset ? "" : 0);     // 歌詞索引的小愛心：0 不顯示數字
    }).catch(function () {}).then(function () { btn.disabled = false; });
  });

  // 從「我的投稿」點「去首頁留言」（網址帶 #marquee）：直接打開留言框
  var compose = document.getElementById("marquee");
  var openCompose = function () {
    if (!compose || location.hash !== "#marquee") return;
    compose.open = true;
    var field = compose.querySelector("input[name=text]");
    if (field) field.focus();
  };
  openCompose();
  window.addEventListener("hashchange", openCompose);       // 已經在首頁時只換 #，頁面不會重新載入

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
