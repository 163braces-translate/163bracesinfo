/* 後台「首頁大標題方框」：在跟前台同一套樣式的預覽裡拖動背景圖。
 *
 * 位置用的是 background-position 的百分比（--hero-x／--hero-y）：0% 是圖的左（上）邊貼齊方框，
 * 100% 是右（下）邊貼齊。圖放大後實際寬度是 Wr，方框寬 aw，圖的左緣在 x × (aw − Wr)；
 * 所以滑鼠拖 dx 像素，x 要減掉 dx ÷ (Wr − aw)。圖剛好塞滿那個方向時（Wr = aw）就拖不動，要先放大。 */
(function () {
  "use strict";
  var U = window.adminUtil, $ = U.$, $$ = U.$$;
  var form = $("[data-hero-form]");
  if (!form) return;
  var preview = $("[data-hero-preview]"), stage = $("[data-hero-stage]"), art = $("[data-hero-art]"), hint = $("[data-hero-hint]");
  var imageInput = form.querySelector("input[name=home_hero_image_id]");
  var zoom = $("#hero-zoom"), overlay = $("#hero-overlay");
  var posX = form.querySelector("input[name=home_hero_pos_x]"), posY = form.querySelector("input[name=home_hero_pos_y]");
  var natural = null;          // 原圖尺寸 {w, h}
  var frame = $(".hero-frame", stage), scale = 1;
  var WIDTH = { desktop: 1148, mobile: 358 };      // 前台方框的實際寬度

  // 用前台的實際寬度排版，再縮小到放得下；拖曳的距離要除以這個縮放比例
  function fit() {
    var w = WIDTH[stage.classList.contains("mobile") ? "mobile" : "desktop"];
    var room = stage.clientWidth - 36;           // 扣掉 .hero-stage 左右 padding
    scale = Math.min(1, room / w);
    frame.style.width = w + "px";
    frame.style.transform = "scale(" + scale + ")";
    frame.style.marginLeft = Math.max(0, (room - w * scale) / 2) + "px";
    frame.style.marginBottom = -(frame.offsetHeight * (1 - scale)) + "px";   // transform 不影響排版高度，手動收掉多的空白
  }

  function mode() { return form.querySelector("input[name=home_hero_mode]:checked").value; }

  function loadImage() {
    natural = null;
    if (!imageInput.value) return apply();
    var img = new Image();
    img.onload = function () { natural = { w: img.naturalWidth, h: img.naturalHeight }; apply(); };
    img.src = "/images/" + imageInput.value + "/w1600/";
    apply();
  }

  function apply() {
    var has = !!imageInput.value;
    preview.className = "hero" + (has ? " hero-" + mode() : "");
    art.hidden = has;
    var st = preview.style;
    if (has) {
      st.setProperty("--hero-image", "url('/images/" + imageInput.value + "/w1600/')");
      st.setProperty("--hero-overlay", overlay.value / 100);
      st.setProperty("--hero-x", posX.value + "%");
      st.setProperty("--hero-y", posY.value + "%");
      st.setProperty("--hero-zoom", zoom.value / 100);
    } else {
      ["--hero-image", "--hero-overlay", "--hero-x", "--hero-y", "--hero-zoom"].forEach(function (k) { st.removeProperty(k); });
    }
    $$("output[data-for]").forEach(function (o) { o.textContent = $("#" + o.dataset.for).value + "%"; });
    fit();
    stage.classList.toggle("draggable", has);
    var r = ranges();
    hint.textContent = !has ? "還沒選背景圖" : !r ? "" : (r.x < 1 && r.y < 1) ? "圖剛好塞滿方框，放大後才能拖動"
      : "↔ 拖動圖片調整位置" + (r.x < 1 ? "（目前只能上下移動，放大後可以左右移動）" : r.y < 1 ? "（目前只能左右移動，放大後可以上下移動）" : "");
  }

  // 圖比方框多出來、可以拖的距離（像素）。背景圖畫在 ::before，它的大小直接讀算好的樣式
  function ranges() {
    if (!natural) return null;
    var cs = getComputedStyle(preview, "::before");
    var aw = parseFloat(cs.width), ah = parseFloat(cs.height);
    if (!aw || !ah) return null;
    var s = Math.max(aw / natural.w, ah / natural.h) * zoom.value / 100;
    return { x: natural.w * s - aw, y: natural.h * s - ah };
  }

  // ---- 拖曳
  var drag = null;
  preview.addEventListener("pointerdown", function (e) {
    if (!imageInput.value || !natural) return;
    drag = { x: e.clientX, y: e.clientY, px: parseFloat(posX.value), py: parseFloat(posY.value), r: ranges() };
    preview.setPointerCapture(e.pointerId);
    stage.classList.add("dragging");
    e.preventDefault();
  });
  preview.addEventListener("pointermove", function (e) {
    if (!drag || !drag.r) return;
    var clamp = function (v) { return Math.round(Math.min(100, Math.max(0, v)) * 10) / 10; };
    if (drag.r.x >= 1) posX.value = clamp(drag.px - (e.clientX - drag.x) / scale / drag.r.x * 100);
    if (drag.r.y >= 1) posY.value = clamp(drag.py - (e.clientY - drag.y) / scale / drag.r.y * 100);
    apply();
  });
  function endDrag() {
    if (!drag) return;
    drag = null;
    stage.classList.remove("dragging");
    form.markDirty();
  }
  preview.addEventListener("pointerup", endDrag);
  preview.addEventListener("pointercancel", endDrag);

  // ---- 其他控制項
  [zoom, overlay].forEach(function (r) { r.addEventListener("input", apply); });
  $$("input[name=home_hero_mode]").forEach(function (r) { r.addEventListener("change", apply); });
  imageInput.addEventListener("change", loadImage);       // admin.js 的圖片欄位換圖時會發 change
  $("[data-hero-reset]").addEventListener("click", function () {
    posX.value = 50; posY.value = 50; zoom.value = 100; apply(); form.markDirty();
  });
  $("[data-hero-device]").addEventListener("click", function (e) {
    var btn = e.target.closest("button[data-device]");
    if (!btn) return;
    $$("button", e.currentTarget).forEach(function (b) { b.setAttribute("aria-pressed", b === btn ? "true" : "false"); });
    stage.classList.toggle("mobile", btn.dataset.device === "mobile");
    apply();
  });
  window.addEventListener("resize", apply);
  loadImage();
})();
