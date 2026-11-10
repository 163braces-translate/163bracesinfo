/* 相簿（app/photos.py 的頁面）：
 *   1. 挑場次：下拉選單換成跟演出列表一樣的篩選（關鍵字、類型、城市、日期）＋結果清單
 *   2. 上傳：依「放到哪裡」顯示用得到的欄位；照片先在瀏覽器縮小再傳，顯示上傳進度
 *   3. 燈箱：點格子裡的照片放大看，← → 換張、Esc 關閉、手機左右滑；網址帶 #p<id> 可以直接打開那一張
 */
(function () {
  var $ = function (sel, el) { return (el || document).querySelector(sel); };
  var $$ = function (sel, el) { return Array.prototype.slice.call((el || document).querySelectorAll(sel)); };
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  };
  var readJSON = function (id) {
    var el = document.getElementById(id);
    try { return el ? JSON.parse(el.textContent) : null; } catch (e) { return null; }
  };

  // ==================================================================== 1. 挑場次
  var pdata = readJSON("picker-data");
  var WD = { zh: ["日", "一", "二", "三", "四", "五", "六"], en: ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"] };
  var LIMIT = 60;                                   // 清單一次最多列幾場，其他的請用篩選縮小

  var setupPicker = function (root) {
    var d = root.dataset, select = $("select", root), shows = pdata.shows, byId = {};
    shows.forEach(function (s) { byId[s.id] = s; });
    var wd = WD[d.lang] || WD.zh;
    var dateLabel = function (s) {
      var t = new Date(s.d + "T00:00:00");
      return s.d.replace(/-/g, "/") + " (" + wd[t.getDay()] + ")";
    };
    var pills = function (list, name) {
      return list.map(function (x) {
        return '<label class="pill"><input type="checkbox" data-f="' + name + '" value="' + x.id + '"><span>' + esc(x.name) + "</span></label>";
      }).join("");
    };
    var ui = document.createElement("div");
    ui.className = "picker";
    ui.innerHTML =
      '<div class="picker-chosen"><span class="picker-label"></span>' +
      '<button type="button" class="btn small" data-p="open">' + esc(d.change) + "</button>" +
      (d.required ? "" : '<button type="button" class="btn small" data-p="clear">' + esc(d.clear) + "</button>") + "</div>" +
      '<div class="picker-panel" hidden>' +
      '<input type="search" data-f="q" placeholder="' + esc(d.search) + '" aria-label="' + esc(d.search) + '">' +
      (pdata.types.length > 1 ? '<div class="pills" role="group" aria-label="' + esc(d.type) + '">' + pills(pdata.types, "type") + "</div>" : "") +
      (pdata.cities.length > 1 ? '<details class="city-list"><summary>' + esc(d.city) + '</summary><div class="pills">' + pills(pdata.cities, "city") + "</div></details>" : "") +
      '<div class="date-row"><input type="date" data-f="from" aria-label="' + esc(d.from) + '"><input type="date" data-f="to" aria-label="' + esc(d.to) + '"></div>' +
      '<p class="small muted picker-count" aria-live="polite"></p><ul class="picker-list"></ul></div>';
    select.hidden = true;
    select.parentNode.insertBefore(ui, select.nextSibling);
    var panel = $(".picker-panel", ui), list = $(".picker-list", ui), label = $(".picker-label", ui);
    var openBtn = $('[data-p="open"]', ui), clearBtn = $('[data-p="clear"]', ui);

    var showChosen = function () {
      var s = byId[select.value];
      label.innerHTML = s ? "<b>" + esc(s.n) + '</b> <span class="muted">' + esc(dateLabel(s)) + " · " + esc(s.cn) + "</span>"
                          : '<span class="muted">' + esc(d.none) + "</span>";
      openBtn.hidden = !s;
      if (clearBtn) clearBtn.hidden = !s;
      panel.hidden = !!s;
    };
    var filter = function () {
      var q = $('[data-f="q"]', ui).value.trim().toLowerCase();
      var types = $$('[data-f="type"]:checked', ui).map(function (i) { return +i.value; });
      var cities = $$('[data-f="city"]:checked', ui).map(function (i) { return +i.value; });
      var from = $('[data-f="from"]', ui).value, to = $('[data-f="to"]', ui).value;
      var hits = shows.filter(function (s) {
        if (q && [s.n, s.n2, s.v, s.v2].join(" ").toLowerCase().indexOf(q) < 0) return false;
        if (types.length && types.indexOf(s.t) < 0) return false;
        if (cities.length && cities.indexOf(s.c) < 0) return false;
        if (from && s.d < from) return false;
        if (to && s.d > to) return false;
        return true;
      });
      $(".picker-count", ui).textContent = d.count.replace("{n}", hits.length);
      list.innerHTML = hits.length ? hits.slice(0, LIMIT).map(function (s) {
        return '<li><button type="button" data-id="' + s.id + '"' + (String(s.id) === select.value ? ' aria-pressed="true"' : "") + ">" +
          '<span class="d">' + esc(dateLabel(s)) + '</span><span class="n">' + esc(s.n) + "</span>" +
          '<span class="m">' + esc(s.cn) + (s.v ? " · " + esc(s.v) : "") + "</span></button></li>";
      }).join("") + (hits.length > LIMIT ? '<li class="small muted picker-more">' + esc(d.more.replace("{n}", hits.length - LIMIT)) + "</li>" : "")
        : '<li class="small muted picker-more">' + esc(d.empty) + "</li>";
    };
    ui.addEventListener("input", function (e) { if (e.target.dataset.f) filter(); });
    // 勾選框只有 change；搜尋框離開時也會觸發 change，那時重畫清單會把正要點的那一場換掉，所以只聽勾選框
    ui.addEventListener("change", function (e) { if (e.target.dataset.f && e.target.type === "checkbox") filter(); });
    ui.addEventListener("click", function (e) {
      var pick = e.target.closest("[data-id]");
      if (pick) {
        select.value = pick.dataset.id;
        select.dispatchEvent(new Event("change", { bubbles: true }));
        showChosen();
        return;
      }
      var btn = e.target.closest("[data-p]");
      if (!btn) return;
      if (btn.dataset.p === "open") {
        panel.hidden = false;
        openBtn.hidden = true;
        $('[data-f="q"]', ui).focus();
      } else {
        select.value = "";
        select.dispatchEvent(new Event("change", { bubbles: true }));
        showChosen();
      }
    });
    filter();
    showChosen();
  };
  if (pdata) $$("[data-show-picker]").forEach(setupPicker);

  // ==================================================================== 2. 上傳
  var form = $("[data-upload]");
  if (form) {
    var fd = form.dataset, input = $("[data-files]", form), previews = $("[data-previews]", form);
    var note = $("[data-upload-note]", form), submit = $("[data-submit]", form), albumSel = $("[data-album-select]", form);
    var showSelect = $("[data-picker-select]", form);
    var items = [];                                 // {file, src, video}
    var target = function () { var r = $("input[name=target]:checked", form); return r ? r.value : "show"; };

    var applyTarget = function () {
      var t = target();
      $$("[data-for]", form).forEach(function (el) {
        var on = el.dataset.for.split(" ").indexOf(t) >= 0;
        if (on && el.hasAttribute("data-new-album")) on = albumSel.value === "new";
        el.hidden = !on;
      });
      $$("[data-new-album]", form).forEach(function (el) {
        if (!el.dataset.for) el.hidden = albumSel.value !== "new";
      });
      $("#u-title").required = t === "custom" && albumSel.value === "new";
      input.accept = t === "group" ? input.dataset.acceptGroup : input.dataset.acceptPhoto;
      // 不是合照就不能傳影片：已經選了的影片拿掉
      if (t !== "group") items = items.filter(function (it) { return !it.video; });
      renderItems();
    };

    var SHRINK_SIDE = 2400, SMALL_ENOUGH = 2.5 * 1024 * 1024;
    var shrink = function (file) {
      if (!window.createImageBitmap || !/^image\/(jpeg|png|webp)$/.test(file.type)) return Promise.resolve(file);
      return createImageBitmap(file, { imageOrientation: "from-image" }).then(function (bmp) {
        var scale = Math.min(1, SHRINK_SIDE / Math.max(bmp.width, bmp.height));
        if (scale === 1 && file.size <= SMALL_ENOUGH) return file;
        var canvas = document.createElement("canvas");
        canvas.width = Math.round(bmp.width * scale);
        canvas.height = Math.round(bmp.height * scale);
        var ctx = canvas.getContext("2d");
        ctx.fillStyle = "#fff";
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(bmp, 0, 0, canvas.width, canvas.height);
        return new Promise(function (resolve) {
          canvas.toBlob(function (blob) {
            resolve(blob && blob.size < file.size
              ? new File([blob], file.name.replace(/\.\w+$/, "") + ".jpg", { type: "image/jpeg" }) : file);
          }, "image/jpeg", 0.86);
        });
      }).catch(function () { return file; });
    };
    var isVideo = function (f) { return /^video\//.test(f.type) || /\.(mp4|mov|webm)$/i.test(f.name); };
    var max = Number(fd.max), videoMax = Number(fd.videoMb) * 1024 * 1024;

    var renderItems = function () {
      previews.hidden = !items.length;
      previews.innerHTML = items.map(function (it, i) {
        return '<li><' + (it.video ? 'video muted preload="metadata"' : 'img alt=""') + ' src="' + it.src + '">' + (it.video ? "</video>" : "") +
          (it.video ? '<span class="ph-play" aria-hidden="true"></span>' : "") +
          '<button type="button" data-rm="' + i + '" aria-label="' + esc(fd.remove) + '">✕</button>' +
          (it.big ? '<span class="ph-flag">' + esc(fd.videoBig) + "</span>" : "") + "</li>";
      }).join("");
      var over = items.length > max, big = items.some(function (it) { return it.big; });
      note.textContent = over ? fd.tooMany : big ? fd.videoBig : items.length ? fd.count.replace("{n}", items.length) : "";
      note.classList.toggle("over", over || big);
      submit.disabled = over || big;
    };

    input.addEventListener("change", function () {
      var files = Array.prototype.slice.call(input.files);
      input.value = "";                             // 清掉才能再選同一張；要上傳的檔案存在 items
      if (!files.length) return;
      submit.disabled = true;
      note.textContent = fd.shrinking;
      Promise.all(files.map(function (f) {
        if (isVideo(f)) return Promise.resolve(target() === "group" ? { file: f, video: true, big: f.size > videoMax } : null);
        return shrink(f).then(function (out) { return { file: out }; });
      })).then(function (out) {
        out.forEach(function (it) {
          if (!it) return;
          it.src = URL.createObjectURL(it.file);
          items.push(it);
        });
        renderItems();
      });
    });
    previews.addEventListener("click", function (e) {
      var b = e.target.closest("[data-rm]");
      if (!b) return;
      var it = items.splice(Number(b.dataset.rm), 1)[0];
      URL.revokeObjectURL(it.src);
      renderItems();
    });
    $$("input[name=target]", form).forEach(function (r) { r.addEventListener("change", applyTarget); });
    albumSel.addEventListener("change", applyTarget);

    // 送出：自己組表單（換成縮好的檔案），用 XMLHttpRequest 才看得到上傳進度；完成後跳到伺服器轉址的那一頁
    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var t = target();
      if ((t === "show" || t === "group") && !showSelect.value) { note.textContent = fd.needShow; note.classList.add("over"); return; }
      var yt = $("#u-yt");
      if (!items.length && !(t === "group" && yt.value.trim())) { note.textContent = fd.needFiles; note.classList.add("over"); return; }
      var body = new FormData(form);
      body.delete("files");
      items.forEach(function (it) { body.append("files", it.file, it.file.name); });
      submit.disabled = true;
      note.classList.remove("over");
      var xhr = new XMLHttpRequest();
      xhr.open("POST", form.action);
      xhr.upload.addEventListener("progress", function (ev) {
        if (!ev.lengthComputable) return;
        var p = Math.round(ev.loaded / ev.total * 100);
        note.textContent = p < 100 ? fd.sending.replace("{p}", p) : fd.processing;
      });
      xhr.addEventListener("load", function () {
        if (xhr.status < 400 && xhr.responseURL) location.href = xhr.responseURL;
        else { note.textContent = fd.failed; submit.disabled = false; }
      });
      xhr.addEventListener("error", function () { note.textContent = fd.failed; submit.disabled = false; });
      xhr.send(body);
    });
    applyTarget();
  }

  // ==================================================================== 3. 燈箱
  var photos = readJSON("photo-data"), box = $("[data-lightbox]");
  if (photos && photos.length && box) {
    var ld = box.dataset, idx = -1, lastFocus = null;
    var byPhoto = {};
    photos.forEach(function (p, i) { byPhoto[p.id] = i; });
    box.innerHTML =
      '<button type="button" class="lb-close" data-lb="close" aria-label="' + esc(ld.close) + '">✕</button>' +
      '<button type="button" class="lb-nav lb-prev" data-lb="prev" aria-label="' + esc(ld.prev) + '">‹</button>' +
      '<figure class="lb-figure"><div class="lb-media"></div><figcaption class="lb-cap"></figcaption></figure>' +
      '<button type="button" class="lb-nav lb-next" data-lb="next" aria-label="' + esc(ld.next) + '">›</button>';
    var media = $(".lb-media", box), cap = $(".lb-cap", box);

    var draw = function () {
      var p = photos[idx];
      if (p.media === "image") media.innerHTML = '<img src="' + esc(p.full) + '" alt="' + esc(p.caption) + '">';
      else if (p.media === "video") media.innerHTML = '<video src="' + esc(p.video) + '" controls autoplay playsinline></video>';
      else media.innerHTML = '<iframe src="https://www.youtube-nocookie.com/embed/' + esc(p.yt) + '?autoplay=1" title="YouTube" ' +
        'allow="autoplay; encrypted-media; picture-in-picture; fullscreen" allowfullscreen></iframe>';
      var bits = [];
      if (p.show) bits.push('🎤 <a href="' + esc(p.show.url) + '">' + esc(p.show.label) + "</a>");
      bits.push(esc(ld.by.replace("{name}", p.by)) + " · " + esc(p.date));
      if (p.orig) bits.push('<a href="' + esc(p.orig) + '" target="_blank" rel="noopener">' + esc(ld.original) + "</a>");
      cap.innerHTML = (p.caption ? '<p class="lb-text">' + esc(p.caption) + "</p>" : "") +
        (p.removed ? '<p class="lb-removed">' + esc(p.note ? ld.removed.replace("{note}", p.note) : ld.removedPlain) + "</p>" : "") +
        (p.pending ? '<p class="lb-removed">' + esc(ld.pending) + "</p>" : "") +
        '<p class="lb-meta">' + bits.join(" · ") +
        (p.mine ? ' · <a href="' + esc(p.edit) + '">' + esc(ld.edit) + "</a>" +
          ' · <form method="post" action="' + esc(p.delete) + '" class="lb-del"><button type="submit" class="linklike" data-confirm="' +
          esc(ld.confirm) + '">' + esc(ld["delete"]) + "</button></form>" : "") + "</p>" +
        '<p class="lb-pos small">' + (idx + 1) + " / " + photos.length + "</p>";
      $(".lb-prev", box).disabled = idx === 0;
      $(".lb-next", box).disabled = idx === photos.length - 1;
      history.replaceState(null, "", "#p" + p.id);
      // 先載入下一張大圖，按 → 時比較快
      var nxt = photos[idx + 1];
      if (nxt && nxt.full) new Image().src = nxt.full;
    };
    var open = function (i) {
      if (idx < 0) lastFocus = document.activeElement;
      idx = i;
      box.hidden = false;
      document.body.classList.add("lb-open");
      draw();
      $(".lb-close", box).focus();
    };
    var close = function () {
      media.innerHTML = "";                         // 停掉影片
      box.hidden = true;
      idx = -1;
      document.body.classList.remove("lb-open");
      history.replaceState(null, "", location.pathname + location.search);
      if (lastFocus) lastFocus.focus();
    };
    var step = function (n) {
      var j = idx + n;
      if (j >= 0 && j < photos.length) { idx = j; draw(); }
    };
    document.addEventListener("click", function (e) {
      var a = e.target.closest("[data-photo]");
      if (a && byPhoto[a.dataset.photo] !== undefined && !e.metaKey && !e.ctrlKey) {
        e.preventDefault();
        open(byPhoto[a.dataset.photo]);
      }
    });
    box.addEventListener("click", function (e) {
      var b = e.target.closest("[data-lb]");
      if (b) { b.dataset.lb === "close" ? close() : step(b.dataset.lb === "prev" ? -1 : 1); return; }
      if (e.target === box || e.target.classList.contains("lb-media")) close();   // 點黑色背景關閉
    });
    document.addEventListener("keydown", function (e) {
      if (box.hidden) return;
      if (e.key === "Escape") close();
      else if (e.key === "ArrowLeft") step(-1);
      else if (e.key === "ArrowRight") step(1);
    });
    var x0 = null;
    box.addEventListener("touchstart", function (e) { x0 = e.touches.length === 1 ? e.touches[0].clientX : null; }, { passive: true });
    box.addEventListener("touchend", function (e) {
      if (x0 === null) return;
      var dx = e.changedTouches[0].clientX - x0;
      if (Math.abs(dx) > 50) step(dx < 0 ? 1 : -1);
      x0 = null;
    });
    var m = /^#p(\d+)$/.exec(location.hash);
    if (m && byPhoto[m[1]] !== undefined) open(byPhoto[m[1]]);
  }
})();
