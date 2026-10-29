/* 後台「頁首與頁尾」的編輯器。資料格式見 app/navigation.py。
 * 送出時把畫面上的內容組回 JSON，放進 header_json、footer_json 兩個 hidden input。
 * 每個區塊的讀值函式掛在 element.read 上（不要用 title、url 這類 DOM 元素本來就有的屬性名）。 */
(function () {
  "use strict";
  var U = window.adminUtil, $ = U.$, $$ = U.$$, el = U.el;
  var form = $("[data-nav-form]");
  if (!form) return;
  var initial = JSON.parse($("[data-nav-initial]").textContent);
  var pages = initial.pages;
  var targets = initial.targets || [];     // 演出頁的分頁（不是 pages 表裡的頁面），選了就當成自訂網址存

  function input(placeholder, value, tag) {
    var i = el(tag || "input", tag ? { placeholder: placeholder, "aria-label": placeholder, rows: "2" }
                                   : { type: "text", placeholder: placeholder, "aria-label": placeholder });
    i.value = value || "";
    return i;
  }

  function tools(node, onChange) {
    var t = el("span", { class: "row-tools" }, [
      el("button", { type: "button", "aria-label": "上移", text: "↑" }),
      el("button", { type: "button", "aria-label": "下移", text: "↓" }),
      el("button", { type: "button", "aria-label": "刪除", text: "✕" })]);
    t.children[0].addEventListener("click", function () { if (node.previousElementSibling) node.parentNode.insertBefore(node, node.previousElementSibling); done(); });
    t.children[1].addEventListener("click", function () { if (node.nextElementSibling) node.parentNode.insertBefore(node.nextElementSibling, node); done(); });
    t.children[2].addEventListener("click", function () { node.remove(); done(); });
    function done() { form.markDirty(); if (onChange) onChange(); }
    return t;
  }

  // 一個連結：名稱、英文名稱、連到哪一頁（或自訂網址）
  function linkRow(link) {
    link = link || {};
    var row = el("div", { class: "link-row" });
    var label = input("名稱", link.label), labelEn = input("英文名稱（選填）", link.label_en);
    var target = el("select", { "aria-label": "連到" });
    target.appendChild(el("option", { value: "", text: "（自訂網址）" }));
    pages.forEach(function (p) {
      target.appendChild(el("option", { value: String(p.id), text: p.title + "　" + p.url + (p.published ? "" : "（未發佈）") }));
    });
    targets.forEach(function (t) {
      target.appendChild(el("option", { value: "url:" + t.url, text: t.label + "（演出頁分頁）　" + t.url }));
    });
    var preset = !link.page_id && targets.some(function (t) { return t.url === link.url; });
    target.value = link.page_id ? String(link.page_id) : (preset ? "url:" + link.url : "");
    var url = input("網址，例：/performances/stats/ 或 https://…", link.url);
    var isPage = function () { return target.value && target.value.indexOf("url:") !== 0; };
    var sync = function () {
      if (target.value.indexOf("url:") === 0) url.value = target.value.slice(4);
      url.hidden = !!target.value;
      label.placeholder = isPage() ? "名稱（留空＝頁面標題）" : "名稱";
    };
    target.addEventListener("change", sync);
    sync();
    [label, labelEn, target, url].forEach(function (n) { row.appendChild(n); });
    row.read = function () {
      return { label: label.value.trim(), label_en: labelEn.value.trim(),
               page_id: isPage() ? Number(target.value) : null, url: isPage() ? "" : url.value.trim() };
    };
    return row;
  }

  // ---- 頁首選單
  var headerHost = $("[data-header]");
  function headerItem(item, host, isChild) {
    item = item || {};
    var box = el("div", { class: isChild ? "nav-item child" : "nav-item" });
    var row = linkRow(item);
    row.appendChild(tools(box));
    box.appendChild(row);
    if (!isChild) {
      var children = el("div", { class: "nav-children" });
      (item.children || []).forEach(function (c) { headerItem(c, children, true); });
      var add = el("button", { type: "button", class: "btn small", text: "＋ 子選單項目" });
      add.addEventListener("click", function () { headerItem({}, children, true).querySelector("input").focus(); form.markDirty(); });
      box.appendChild(children);
      box.appendChild(add);
      box.read = function () {
        var data = row.read();
        data.children = $$(":scope > .nav-item", children).map(function (c) { return c.read(); });
        return data;
      };
    } else {
      box.read = row.read;
    }
    host.appendChild(box);
    return box;
  }
  initial.header.forEach(function (item) { headerItem(item, headerHost, false); });
  $("[data-add-header]").addEventListener("click", function () {
    headerItem({}, headerHost, false).querySelector("input").focus(); form.markDirty();
  });

  // ---- 頁尾
  var footerHost = $("[data-footer]"), countLabel = $("[data-col-count]");
  function renumber() {
    var cols = $$(":scope > .footer-col-edit", footerHost);
    cols.forEach(function (c, i) { $(".col-no", c).textContent = "第 " + (i + 1) + " 欄"; });
    countLabel.textContent = "共 " + cols.length + " 欄";
  }
  function footerColumn(col) {
    col = col || {};
    var box = el("div", { class: "footer-col-edit" });
    var head = el("div", { class: "block-head" }, [el("span", { class: "kind col-no" })]);
    head.appendChild(tools(box, renumber));
    var title = input("標題", col.title), titleEn = input("英文標題（選填）", col.title_en);
    var text = input("文字（選填，可以換行）", col.text, "textarea"), textEn = input("英文文字（選填）", col.text_en, "textarea");
    var links = el("div", { class: "nav-children" });
    var addLink = function (l) {
      var wrap = el("div", { class: "nav-item child" });
      var r = linkRow(l);
      r.appendChild(tools(wrap));
      wrap.appendChild(r);
      wrap.read = r.read;
      links.appendChild(wrap);
      return wrap;
    };
    (col.links || []).forEach(addLink);
    var add = el("button", { type: "button", class: "btn small", text: "＋ 連結" });
    add.addEventListener("click", function () { addLink().querySelector("input").focus(); form.markDirty(); });
    [head, el("div", { class: "grid-2" }, [title, titleEn]), el("div", { class: "grid-2" }, [text, textEn]),
     el("div", { class: "field", text: "連結" }), links, add].forEach(function (n) { box.appendChild(n); });
    box.read = function () {
      return { title: title.value.trim(), title_en: titleEn.value.trim(), text: text.value.trim(), text_en: textEn.value.trim(),
               links: $$(":scope > .nav-item", links).map(function (l) { return l.read(); }) };
    };
    footerHost.appendChild(box);
    renumber();
    return box;
  }
  (initial.footer.columns || []).forEach(footerColumn);
  $("[data-add-column]").addEventListener("click", function () { footerColumn().querySelector("input").focus(); form.markDirty(); });
  $("[data-note]").value = initial.footer.note || "";
  $("[data-note-en]").value = initial.footer.note_en || "";
  renumber();

  form.addEventListener("submit", function () {
    // 名稱、頁面、網址都空白的列不存
    var keep = function (l) { return l.label || l.page_id || l.url || (l.children && l.children.length); };
    var header = $$(":scope > .nav-item", headerHost).map(function (b) { return b.read(); }).filter(keep);
    header.forEach(function (h) { h.children = h.children.filter(keep); });
    form.querySelector("input[name=header_json]").value = JSON.stringify(header);
    form.querySelector("input[name=footer_json]").value = JSON.stringify({
      columns: $$(":scope > .footer-col-edit", footerHost).map(function (c) {
        var data = c.read();
        data.links = data.links.filter(keep);
        return data;
      }),
      note: $("[data-note]").value.trim(), note_en: $("[data-note-en]").value.trim()
    });
  });
})();
