/* 後台「歌詞索引排序」：拖拉專輯與曲目，右邊即時預覽前台的歌詞頁。
 * 「其他歌詞」（沒對應到歌曲的歌詞）也是一個方框，可以拖到專輯之間任何位置；它裡面的歌詞只能在自己的方框裡排。
 * 拖拉在手機、平板上不一定能用，所以每一列也有 ↑ ↓ 按鈕（歌曲在專輯第一首按 ↑ 會移到上一張專輯最後面）。
 * 預覽用的是前台同一套樣式（site.css 的 .lyrics-menu／.album-menu），排成前台的寬度再整個縮小。 */
(function () {
  "use strict";
  var U = window.adminUtil, $ = U.$, $$ = U.$$, el = U.el;
  var form = $("[data-order-form]");
  if (!form) return;
  var data = JSON.parse($("[data-order-initial]").textContent);
  var albumsHost = $("[data-order-albums]");
  var PAGE_WIDTH = 852;       // 前台歌詞清單最寬 820px，加上左右留白

  function changed() { refresh(); form.markDirty(); }

  function moveButtons(onUp, onDown) {
    var up = el("button", { type: "button", "aria-label": "上移", text: "↑" });
    var down = el("button", { type: "button", "aria-label": "下移", text: "↓" });
    up.addEventListener("click", function () { onUp(); changed(); });
    down.addEventListener("click", function () { onDown(); changed(); });
    return el("span", { class: "row-tools" }, [up, down]);
  }

  // 歌曲跨專輯移動時跳過「其他歌詞」方框
  function neighbourAlbum(card, dir) {
    var next = dir < 0 ? card.previousElementSibling : card.nextElementSibling;
    while (next && next.classList.contains("order-other")) next = dir < 0 ? next.previousElementSibling : next.nextElementSibling;
    return next;
  }

  function songItem(song, kind) {
    var li = el("li", { class: "order-song" + (song.has_lyrics === false || song.published === 0 ? " muted-row" : ""), draggable: "true" });
    li.dataset.id = song.id; li.dataset.kind = kind;
    li.dataset.title = song.title; li.dataset.titleEn = song.title_en || "";
    li.dataset.hasLyrics = kind === "orphan" ? (song.published ? "1" : "") : (song.has_lyrics ? "1" : "");
    var label = el("span", { class: "order-title" }, [document.createTextNode(song.title)]);
    if (song.title_en) label.appendChild(el("span", { class: "en", text: " " + song.title_en }));
    if (kind === "orphan" && !song.published) label.appendChild(el("span", { class: "chip", text: "草稿" }));
    li.appendChild(el("span", { class: "handle", "aria-hidden": "true", text: "⋮⋮" }));
    li.appendChild(label);
    li.appendChild(moveButtons(function () {
      if (li.previousElementSibling) return li.parentNode.insertBefore(li, li.previousElementSibling);
      if (kind !== "song") return;
      var prev = neighbourAlbum(li.closest(".order-album"), -1);       // 第一首：移到上一張專輯最後面
      if (prev) $(".order-songs", prev).appendChild(li);
    }, function () {
      if (li.nextElementSibling) return li.parentNode.insertBefore(li.nextElementSibling, li);
      if (kind !== "song") return;
      var next = neighbourAlbum(li.closest(".order-album"), 1);        // 最後一首：移到下一張專輯最前面
      if (next) $(".order-songs", next).insertBefore(li, $(".order-songs", next).firstChild);
    }));
    return li;
  }

  // 一個方框：專輯，或「其他歌詞」（kind = "orphan"）
  function boxCard(opts) {
    var card = el("div", { class: "card order-album" + (opts.other ? " order-other" : ""), draggable: "true" });
    card.dataset.id = opts.id || ""; card.dataset.name = opts.name;
    card.dataset.cover = opts.cover || ""; card.dataset.year = opts.year || "";
    var handle = el("span", { class: "handle album-handle", "aria-hidden": "true", text: "⋮⋮", title: "拖這裡移動整個方框" });
    var head = el("div", { class: "order-album-head" }, [handle,
      opts.cover ? el("img", { src: opts.cover, alt: "" }) : el("span", { class: "cover-ph" }),
      el("b", { text: opts.name }), el("span", { class: "small muted count" })]);
    head.appendChild(moveButtons(function () {
      if (card.previousElementSibling) albumsHost.insertBefore(card, card.previousElementSibling);
    }, function () {
      if (card.nextElementSibling) albumsHost.insertBefore(card.nextElementSibling, card);
    }));
    var list = el("ol", { class: "order-songs" });
    opts.items.forEach(function (s) { list.appendChild(songItem(s, opts.other ? "orphan" : "song")); });
    card.appendChild(head);
    if (opts.other) card.appendChild(el("p", { class: "help", text: "沒有對應到任何歌曲的歌詞。這些歌詞只能在這個方框裡排；要放進專輯，先到「歌曲 ↔ 歌詞」對應到歌曲。" }));
    card.appendChild(list);
    return card;
  }

  data.albums.forEach(function (a) {
    albumsHost.appendChild(boxCard({ id: a.id, name: a.name, cover: a.cover, year: (a.release_date || "").slice(0, 4), items: a.songs }));
  });
  var otherCard = boxCard({ name: "其他歌詞", items: data.orphans, other: true });
  albumsHost.insertBefore(otherCard, albumsHost.children[data.other_position] || null);
  var orphansHost = $(".order-songs", otherCard);

  // ---- 拖拉
  // 方框一直都可以拖，但只有從方框的 ⋮⋮ 開始拖才算（記住按下去的位置），
  // 不然在方框的標題或空白處拖一下，整張專輯就跑掉了。拖歌曲時起點是歌曲那一列，不受影響
  var dragging = null, pressedHandle = false;
  form.addEventListener("pointerdown", function (e) { pressedHandle = !!e.target.closest(".album-handle"); });
  form.addEventListener("dragstart", function (e) {
    dragging = e.target.closest(".order-song, .order-album");
    if (!dragging) return;
    if (dragging.classList.contains("order-album") && !pressedHandle) { e.preventDefault(); dragging = null; return; }
    e.stopPropagation();
    dragging.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", dragging.dataset.id);
  });
  form.addEventListener("dragend", function () {
    if (!dragging) return;
    dragging.classList.remove("dragging");
    dragging = null;
    changed();
  });
  function after(container, selector, y) {      // 游標在哪一列的上半部，就插在那一列前面
    var rows = $$(":scope > " + selector + ":not(.dragging)", container);
    for (var i = 0; i < rows.length; i++) {
      var box = rows[i].getBoundingClientRect();
      if (y < box.top + box.height / 2) return rows[i];
    }
    return null;
  }
  form.addEventListener("dragover", function (e) {
    if (!dragging) return;
    if (dragging.classList.contains("order-album")) {
      if (!albumsHost.contains(e.target)) return;
      e.preventDefault();
      albumsHost.insertBefore(dragging, after(albumsHost, ".order-album", e.clientY));
      return;
    }
    var box = e.target.closest(".order-album");
    var list = e.target.closest(".order-songs") || (box && $(".order-songs", box));
    // 歌曲可以在專輯之間移動；「其他歌詞」只能在自己的方框裡排
    if (!list || (dragging.dataset.kind === "orphan") !== (list === orphansHost)) return;
    e.preventDefault();
    list.insertBefore(dragging, after(list, ".order-song", e.clientY));
  });
  form.addEventListener("drop", function (e) { if (dragging) e.preventDefault(); });

  // ---- 預覽（跟前台 lyrics_index.html 同樣的結構，全部展開）
  var preview = $("[data-preview]"), viewport = $("[data-preview-viewport]"), page = $("[data-preview-page]");
  function previewBox(name, sub, cover, songs) {
    var tracks = el("ol", { class: "tracks" });
    songs.forEach(function (s) {
      var label = el("span", {}, [document.createTextNode(s.dataset.title)]);
      if (s.dataset.titleEn && s.dataset.titleEn !== s.dataset.title) label.appendChild(el("span", { class: "en", text: " " + s.dataset.titleEn }));
      tracks.appendChild(el("li", {}, [s.dataset.hasLyrics ? el("a", { href: "#" }, [label]) : el("span", { class: "no-lyrics", text: s.dataset.title })]));
    });
    var box = el("details", { class: "card album-menu", open: "" }, [
      el("summary", {}, [cover ? el("img", { src: cover, alt: "" }) : el("span", { class: "cover-ph" }),
        el("span", { class: "album-menu-title" }, [el("span", { class: "name", text: name }), el("span", { class: "sub", text: sub })]),
        el("span", { class: "chevron", "aria-hidden": "true" })]),
      tracks]);
    return box;
  }
  function refresh() {
    preview.innerHTML = "";
    $$(".order-album", albumsHost).forEach(function (card) {
      var songs = $$(".order-song", card);
      $(".count", card).textContent = songs.length + " 首";
      var shown = card === otherCard ? songs.filter(function (s) { return s.dataset.hasLyrics; }) : songs;
      if (!shown.length) return;               // 前台不顯示空的方框（「其他歌詞」只算已發佈的）
      preview.appendChild(previewBox(card.dataset.name,
        (card.dataset.year ? card.dataset.year + " · " : "") + shown.length + " 首", card.dataset.cover, shown));
    });
    fit();
  }
  function fit() {
    var scale = Math.min(1, viewport.clientWidth / PAGE_WIDTH);
    page.style.width = PAGE_WIDTH + "px";
    page.style.transform = "scale(" + scale + ")";
    viewport.style.height = Math.ceil(page.scrollHeight * scale) + "px";
  }
  preview.addEventListener("click", function (e) { e.preventDefault(); });
  window.addEventListener("resize", fit);
  refresh();

  form.addEventListener("submit", function () {
    var cards = $$(".order-album", albumsHost);
    form.querySelector("input[name=order_json]").value = JSON.stringify({
      albums: cards.filter(function (c) { return c !== otherCard; }).map(function (card) {
        return { id: Number(card.dataset.id), songs: $$(".order-song", card).map(function (s) { return Number(s.dataset.id); }) };
      }),
      orphans: $$(".order-song", orphansHost).map(function (s) { return Number(s.dataset.id); }),
      other_position: cards.indexOf(otherCard)       // 前面有幾張專輯
    });
  });
})();
