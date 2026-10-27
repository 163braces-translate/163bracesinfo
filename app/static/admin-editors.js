/* 後台的富文字編輯器（Quill 2）與歌詞段落編輯器。需要先載入 quill.js 與 admin.js。
 *
 * 富文字：字級、顏色、對齊一律存成 inline style（不靠 Quill 的 class），前台不用載入 Quill 的 CSS 也能正確顯示。
 * 存檔時把 quill.root.innerHTML 放進同名的 hidden input。 */
(function () {
  "use strict";
  var U = window.adminUtil, $ = U.$, $$ = U.$$, el = U.el;

  var SIZES = ["12px", "14px", false, "18px", "20px", "24px", "30px", "36px"];   // false＝預設 16px
  var Size = Quill.import("attributors/style/size");
  Size.whitelist = SIZES.filter(Boolean);
  Quill.register(Size, true);
  ["attributors/style/align", "attributors/style/color", "attributors/style/background"].forEach(function (name) {
    Quill.register(Quill.import(name), true);
  });

  function makeRich(node, small) {
    var toolbar = small
      ? [["bold", "italic", "underline"], [{ color: [] }], ["link"], ["clean"]]
      : [[{ header: [1, 2, 3, false] }], [{ size: SIZES }], ["bold", "italic", "underline", "strike"],
         [{ color: [] }, { background: [] }], [{ list: "ordered" }, { list: "bullet" }], [{ align: [] }],
         ["blockquote", "link", "image", "video"], ["clean"]];
    var quill = new Quill(node, {
      theme: "snow",
      modules: { toolbar: { container: toolbar, handlers: {
        image: function () {
          var range = quill.getSelection(true);
          window.pickImage(function (img) {
            quill.insertEmbed(range.index, "image", img.url, "user");
            quill.setSelection(range.index + 1);
          });
        }
      } } }
    });
    quill.on("text-change", function (delta, old, source) {
      var form = node.closest("form");
      if (source === "user" && form && form.markDirty) form.markDirty();
    });
    return quill;
  }

  function html(quill) {
    if (quill.getLength() <= 1 && !quill.root.querySelector("img, iframe")) return "";
    // Quill 會幫每個連結加 target=_blank；站內連結不要開新分頁
    var copy = quill.root.cloneNode(true);
    $$('a[href^="/"]', copy).forEach(function (a) { a.removeAttribute("target"); a.removeAttribute("rel"); });
    return copy.innerHTML;
  }

  // ---- 一般富文字欄位：<div data-rich="欄位名"> 後面接同名 hidden input
  var editors = [];
  $$("[data-rich]").forEach(function (node) {
    var quill = makeRich(node, node.classList.contains("small"));
    editors.push({ quill: quill, input: node.closest(".form-row").querySelector('input[name="' + node.dataset.rich + '"]') });
  });
  $$("form").forEach(function (form) {
    form.addEventListener("submit", function () {
      editors.forEach(function (e) { if (form.contains(e.input)) e.input.value = html(e.quill); });
      // 告訴伺服器富文字編輯器有正常運作；沒有這個欄位時，伺服器不會覆蓋原本的內文
      if (!form.querySelector("input[name=rich_ok]")) form.appendChild(el("input", { type: "hidden", name: "rich_ok", value: "1" }));
    });
  });

  // ---- 歌詞段落編輯器
  var host = $("[data-blocks]");
  if (!host) return;
  var form = host.closest("form");
  var LINE_BREAK = "⏎";
  var modeSelect = $("[data-mode]");
  var syncMode = function () { host.classList.toggle("single-mode", modeSelect.value === "single"); };
  modeSelect.addEventListener("change", syncMode);

  function input(placeholder, value) {
    var i = el("input", { type: "text", placeholder: placeholder, "aria-label": placeholder });
    i.value = value || "";
    return i;
  }

  function tools(block) {
    var t = el("span", { class: "row-tools" }, [
      el("button", { type: "button", "aria-label": "上移", text: "↑" }),
      el("button", { type: "button", "aria-label": "下移", text: "↓" }),
      el("button", { type: "button", "aria-label": "刪除", text: "✕" })]);
    var b = t.children;
    b[0].addEventListener("click", function () { if (block.previousElementSibling) host.insertBefore(block, block.previousElementSibling); form.markDirty(); });
    b[1].addEventListener("click", function () { if (block.nextElementSibling) host.insertBefore(block.nextElementSibling, block); form.markDirty(); });
    b[2].addEventListener("click", function () { if (confirm("刪除這個區塊？")) { block.remove(); form.markDirty(); } });
    return t;
  }

  function lineCount(text) {
    var lines = text.replace(/\s+$/, "").split("\n");
    return text.trim() ? lines.length : 0;
  }

  function column(label, value) {
    var area = el("textarea", { spellcheck: "false", "aria-label": label });
    area.value = value || "";
    var count = el("span");
    var insert = el("button", { type: "button", text: "插入換行 " + LINE_BREAK });
    insert.addEventListener("click", function () {
      var pos = area.selectionStart;
      area.value = area.value.slice(0, pos) + LINE_BREAK + area.value.slice(area.selectionEnd);
      area.focus(); area.selectionStart = area.selectionEnd = pos + 1;
      area.dispatchEvent(new Event("input", { bubbles: true }));
    });
    var wrap = el("div", {}, [el("div", { class: "col-head" }, [el("span", {}, [document.createTextNode(label + "　"), count]), insert]), area]);
    wrap.area = area; wrap.count = count;
    return wrap;
  }

  function addBlock(b, before) {
    var block = el("div", { class: "block " + b.type });
    block.dataset.type = b.type;
    var head = el("div", { class: "block-head" });
    if (b.type === "section") {
      head.appendChild(el("span", { class: "kind", text: "段落" }));
      block.nameInput = input("段落名稱（選填），例：Verse 1、副歌", b.name);
      block.altInput = input("右欄的段落名稱（選填）", b.name_alt);
      head.appendChild(block.nameInput); head.appendChild(block.altInput);
      head.appendChild(tools(block));
      block.appendChild(head);
      var left = column("左欄", b.left_text), right = column("右欄", b.right_text);
      var warn = el("div", { class: "mismatch" });
      var check = function () {
        var l = lineCount(left.area.value), r = lineCount(right.area.value);
        left.count.textContent = l + " 行"; right.count.textContent = r + " 行";
        warn.textContent = r && l !== r && modeSelect.value !== "single" ? "⚠️ 左右行數不同（" + l + "／" + r + "），第幾行會對到第幾行，請確認有沒有錯位。" : "";
      };
      // 文字框長到放得下所有行，左右一樣高，才好逐行對照
      var fit = function () {
        [left.area, right.area].forEach(function (t) { t.style.height = "auto"; });
        var h = Math.max(left.area.scrollHeight, right.area.scrollHeight, 120) + 4;
        [left.area, right.area].forEach(function (t) { t.style.height = h + "px"; });
      };
      left.area.addEventListener("input", function () { check(); fit(); });
      right.area.addEventListener("input", function () { check(); fit(); });
      requestAnimationFrame(fit);
      modeSelect.addEventListener("change", check);
      block.appendChild(el("div", { class: "cols" }, [left, right]));
      block.appendChild(warn);
      block.left = left.area; block.right = right.area;
      check();
    } else if (b.type === "note") {
      head.appendChild(el("span", { class: "kind", text: "註解文字" }));
      head.appendChild(tools(block));
      block.appendChild(head);
      var node = el("div", { class: "rich small" });
      node.innerHTML = b.html || "";
      block.appendChild(node);
      block.quill = makeRich(node, true);
    } else if (b.type === "part") {
      head.appendChild(el("span", { class: "kind", text: "▼ 另一個方框" }));
      block.titleInput = input("方框標題，例：補充、發表之前的版本", b.title);
      block.titleEnInput = input("英文標題（選填）", b.title_en);
      head.appendChild(block.titleInput); head.appendChild(block.titleEnInput);
      head.appendChild(tools(block));
      block.appendChild(head);
    }
    host.insertBefore(block, before || null);
    return block;
  }

  JSON.parse($("[data-blocks-initial]").textContent).forEach(function (b) { addBlock(b); });
  $$("[data-add-block]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var type = btn.dataset.addBlock;
      var block = addBlock({ type: type, name: "", name_alt: "", left_text: "", right_text: "", html: "", title: "", title_en: "" });
      var focus = block.querySelector("textarea, input");
      if (focus) focus.focus();
      form.markDirty();
    });
  });
  syncMode();

  function serialize() {
    return $$(".block", host).map(function (block) {
      var type = block.dataset.type;
      if (type === "section") {
        var left = block.left.value.replace(/\s+$/, "").split("\n");
        var right = block.right.value.replace(/\s+$/, "").split("\n");
        var lines = [];
        for (var i = 0; i < Math.max(left.length, right.length); i++) {
          var l = (left[i] || "").trim(), r = (right[i] || "").trim();
          if (l || r) lines.push({ left: l, right: r });
        }
        return { type: "section", name: block.nameInput.value.trim(), name_alt: block.altInput.value.trim(), lines: lines };
      }
      if (type === "note") return { type: "note", html: html(block.quill) };
      return { type: "part", title: block.titleInput.value.trim(), title_en: block.titleEnInput.value.trim() };
    }).filter(function (b) { return b.type !== "section" || b.lines.length || b.name; });
  }

  // ---- 影片
  var videos = $("[data-videos]");
  function addVideo(v) {
    // 欄位存在 row.fields，不要直接掛在 row 上：row.title 是 DOM 元素本來就有的屬性
    var row = el("div", { class: "video-row" });
    row.fields = { url: input("YouTube 網址", v && v.url), title: input("標題，例：2023 浮現祭", v && v.title),
                   title_en: input("英文標題（選填）", v && v.title_en) };
    var rm = el("button", { type: "button", class: "btn small danger", text: "刪除" });
    rm.addEventListener("click", function () { row.remove(); form.markDirty(); });
    [row.fields.url, row.fields.title, row.fields.title_en, rm].forEach(function (n) { row.appendChild(n); });
    videos.appendChild(row);
    return row;
  }
  JSON.parse($("[data-videos-initial]").textContent).forEach(addVideo);
  $("[data-add-video]").addEventListener("click", function () { addVideo().fields.url.focus(); });

  form.addEventListener("submit", function () {
    form.querySelector("input[name=blocks_json]").value = JSON.stringify(serialize());
    form.querySelector("input[name=videos_json]").value = JSON.stringify($$(".video-row", videos).map(function (row) {
      return { url: row.fields.url.value.trim(), title: row.fields.title.value.trim(), title_en: row.fields.title_en.value.trim() };
    }));
  });
})();
