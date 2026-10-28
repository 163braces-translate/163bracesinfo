/* 後台的互動：選單、刪除確認、圖片挑選、歌單編輯、數字卡片。富文字與歌詞編輯在 admin-editors.js。 */
(function () {
  "use strict";
  var $ = function (sel, root) { return (root || document).querySelector(sel); };
  var $$ = function (sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); };
  var el = function (tag, attrs, children) {
    var node = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) {
      if (k === "text") node.textContent = attrs[k]; else node.setAttribute(k, attrs[k]);
    });
    (children || []).forEach(function (c) { node.appendChild(c); });
    return node;
  };
  window.adminUtil = { $: $, $$: $$, el: el };

  // ---- 手機版選單
  var menu = $(".admin-menu");
  if (menu) menu.addEventListener("click", function () {
    var open = $(".admin-nav").classList.toggle("open");
    menu.setAttribute("aria-expanded", open ? "true" : "false");
  });

  // ---- 刪除之類的按鈕先確認
  document.addEventListener("click", function (e) {
    var btn = e.target.closest("[data-confirm]");
    if (btn && !window.confirm(btn.dataset.confirm)) e.preventDefault();
  });

  // ---- 改了沒存就離開時提醒
  $$("form.form").forEach(function (form) {
    var dirty = false;
    form.addEventListener("input", function () { dirty = true; });
    form.addEventListener("change", function () { dirty = true; });
    form.addEventListener("submit", function () { dirty = false; });
    form.markDirty = function () { dirty = true; };
    window.addEventListener("beforeunload", function (e) { if (dirty) { e.preventDefault(); e.returnValue = ""; } });
  });

  // ---- 圖片挑選視窗：pickImage(callback) → callback({id, url, thumb, title})
  var picker = $("#image-picker"), pickerCallback = null;
  function uploadFiles(files, status) {
    var data = new FormData();
    Array.prototype.forEach.call(files, function (f) { data.append("files", f); });
    status.textContent = "上傳中…";
    return fetch("/admin/api/images", { method: "POST", body: data, credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        status.textContent = res.errors && res.errors.length ? res.errors.join("；") : "已上傳 " + res.images.length + " 張";
        return res.images || [];
      })
      .catch(function () { status.textContent = "上傳失敗，請再試一次"; return []; });
  }
  function loadPicker(q) {
    var grid = $("[data-picker-grid]", picker);
    fetch("/admin/api/images?q=" + encodeURIComponent(q || ""), { credentials: "same-origin" })
      .then(function (r) { return r.json(); })
      .then(function (images) {
        grid.innerHTML = "";
        images.forEach(function (img) {
          var b = el("button", { type: "button", title: img.title }, [
            el("img", { src: img.thumb, alt: "", loading: "lazy" }), el("span", { text: img.title || "#" + img.id })]);
          b.addEventListener("click", function () { picker.close(); if (pickerCallback) pickerCallback(img); });
          grid.appendChild(b);
        });
        if (!images.length) grid.appendChild(el("p", { class: "muted", text: "沒有圖片" }));
      });
  }
  window.pickImage = function (cb) {
    pickerCallback = cb;
    $("[data-picker-status]", picker).textContent = "";
    loadPicker("");
    picker.showModal();
  };
  if (picker) {
    $("[data-picker-close]", picker).addEventListener("click", function () { picker.close(); });
    var searchTimer;
    $("[data-picker-search]", picker).addEventListener("input", function (e) {
      clearTimeout(searchTimer);
      searchTimer = setTimeout(function () { loadPicker(e.target.value); }, 250);
    });
    $("[data-picker-upload]", picker).addEventListener("change", function (e) {
      uploadFiles(e.target.files, $("[data-picker-status]", picker)).then(function (imgs) {
        e.target.value = "";
        if (imgs.length === 1) { picker.close(); if (pickerCallback) pickerCallback(imgs[0]); }
        else loadPicker("");
      });
    });
  }

  // ---- 表單上的圖片欄位
  $$("[data-image-field]").forEach(function (field) {
    var input = $("input", field), preview = $(".image-preview", field), clear = $("[data-image-clear]", field);
    $("[data-image-choose]", field).addEventListener("click", function () {
      window.pickImage(function (img) {
        input.value = img.id;
        preview.innerHTML = "";
        preview.appendChild(el("img", { src: img.thumb, alt: "" }));
        clear.hidden = false;
        var form = field.closest("form"); if (form && form.markDirty) form.markDirty();
        input.dispatchEvent(new Event("change", { bubbles: true }));     // 讓頁面上的預覽（例如首頁大標題）跟著換
      });
    });
    clear.addEventListener("click", function () {
      input.value = ""; preview.innerHTML = ""; clear.hidden = true;
      var form = field.closest("form"); if (form && form.markDirty) form.markDirty();
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
  });

  // ---- 圖片頁：直接上傳
  var pageUpload = $("[data-upload-page]");
  if (pageUpload) pageUpload.addEventListener("change", function () {
    var status = el("p", { class: "flash" });
    $(".admin-main").insertBefore(status, $(".admin-main").firstChild);
    uploadFiles(pageUpload.files, status).then(function () { location.reload(); });
  });

  // ---- 歌單編輯
  var setlist = $("[data-setlist]");
  if (setlist) {
    var template = $("[data-setlist-template]");
    var countLabel = $("[data-setlist-count]");
    var refresh = function () {
      $$(".setlist-row", setlist).forEach(function (row) {
        // 用 readOnly 不用 disabled：disabled 的欄位不會送出，三個欄位的列數就對不齊了
        var custom = $("input[name=item_custom]", row);
        custom.readOnly = !!$("select", row).value;
        if (custom.readOnly) custom.value = "";
      });
      countLabel.textContent = $$(".setlist-row", setlist).length + " 首";
    };
    var addRow = function (songId, custom, note) {
      var row = template.content.firstElementChild.cloneNode(true);
      if (songId) $("select", row).value = songId;
      if (custom) $("input[name=item_custom]", row).value = custom;
      if (note) $("input[name=item_note]", row).value = note;
      setlist.appendChild(row);
      refresh();
      return row;
    };
    $("[data-add-row]").addEventListener("click", function () { $("select", addRow()).focus(); });
    setlist.addEventListener("change", refresh);
    setlist.addEventListener("click", function (e) {
      var row = e.target.closest(".setlist-row");
      if (!row) return;
      if (e.target.closest("[data-remove]")) row.remove();
      else if (e.target.closest("[data-up]") && row.previousElementSibling) setlist.insertBefore(row, row.previousElementSibling);
      else if (e.target.closest("[data-down]") && row.nextElementSibling) setlist.insertBefore(row.nextElementSibling, row);
      else return;
      setlist.closest("form").markDirty();
      refresh();
    });
    // 拖曳排序
    var dragging = null;
    setlist.addEventListener("dragstart", function (e) {
      dragging = e.target.closest(".setlist-row");
      if (!dragging) return;
      dragging.classList.add("dragging");
      e.dataTransfer.effectAllowed = "move";
    });
    setlist.addEventListener("dragend", function () {
      if (dragging) dragging.classList.remove("dragging");
      dragging = null; refresh(); setlist.closest("form").markDirty();
    });
    setlist.addEventListener("dragover", function (e) {
      if (!dragging) return;
      e.preventDefault();
      var over = e.target.closest(".setlist-row");
      if (!over || over === dragging) return;
      var rect = over.getBoundingClientRect();
      setlist.insertBefore(dragging, e.clientY > rect.top + rect.height / 2 ? over.nextSibling : over);
    });
    // 貼上整份歌單：曲名對得上曲庫就選好，對不上當自訂曲名
    var titles = {};
    $$("option[data-titles]", template.content).forEach(function (opt) {
      opt.dataset.titles.split("|").forEach(function (t) { if (t && !titles[t]) titles[t] = opt.value; });
    });
    $("[data-paste-apply]").addEventListener("click", function () {
      var box = $("[data-paste]");
      box.value.split("\n").forEach(function (line) {
        var parts = line.split(/[｜|]/), title = parts[0].replace(/^\s*\d+[.、)\s]+/, "").trim();
        if (!title) return;
        var id = titles[title.toLowerCase()];
        addRow(id || "", id ? "" : title, (parts[1] || "").trim());
      });
      box.value = "";
      $(".paste").open = false;
      setlist.closest("form").markDirty();
    });
    refresh();
  }

  // ---- 設定頁：首頁數字卡片
  var facts = $("[data-facts]");
  if (facts) {
    var hidden = facts.parentElement.querySelector("input[type=hidden]");
    var fields = [["value", "數字"], ["value_en", "數字（英文）"], ["label", "說明"], ["label_en", "說明（英文）"]];
    var addFact = function (f) {
      var row = el("div", { class: "fact-row" });
      fields.forEach(function (pair) {
        var input = el("input", { type: "text", placeholder: pair[1], "data-k": pair[0], "aria-label": pair[1] });
        input.value = (f && f[pair[0]]) || "";
        row.appendChild(input);
      });
      var rm = el("button", { type: "button", class: "btn small danger", text: "刪除" });
      rm.addEventListener("click", function () { row.remove(); });
      row.appendChild(rm);
      facts.appendChild(row);
    };
    JSON.parse(hidden.value || "[]").forEach(addFact);
    $("[data-add-fact]").addEventListener("click", function () { addFact(); });
    facts.closest("form").addEventListener("submit", function () {
      hidden.value = JSON.stringify($$(".fact-row", facts).map(function (row) {
        var f = {};
        $$("input", row).forEach(function (i) { f[i.dataset.k] = i.value.trim(); });
        return f;
      }).filter(function (f) { return f.value || f.label; }));
    });
  }

  // ---- 頁面編輯：中文／英文內文切換
  $$("[data-lang-tabs]").forEach(function (tabs) {
    tabs.addEventListener("click", function (e) {
      var btn = e.target.closest("button[data-lang]");
      if (!btn) return;
      $$("button", tabs).forEach(function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); });
      $$("[data-lang-pane]").forEach(function (p) { p.hidden = p.dataset.langPane !== btn.dataset.lang; });
    });
  });
})();
