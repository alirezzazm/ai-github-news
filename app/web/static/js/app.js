/* Theme toggle, bookmarks (localStorage), search shortcut, share, language dots. */
(function () {
  "use strict";
  var root = document.documentElement;
  var FA = ["۰","۱","۲","۳","۴","۵","۶","۷","۸","۹"];
  function fa(n) { return String(n).replace(/\d/g, function (d) { return FA[d]; }); }

  // ---- theme ------------------------------------------------------------
  function currentTheme() { return root.getAttribute("data-theme") || "auto"; }
  function prefersDark() { return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches; }
  document.querySelectorAll("[data-theme-toggle]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var cur = currentTheme();
      var effectiveDark = cur === "dark" || (cur === "auto" && prefersDark());
      var next = effectiveDark ? "light" : "dark";
      root.setAttribute("data-theme", next);
      try { localStorage.setItem("theme", next); } catch (e) {}
    });
  });

  // ---- language colours ---------------------------------------------------
  var LANG_COLORS = { python: "#3572A5", typescript: "#3178c6", javascript: "#f1e05a", rust: "#dea584", go: "#00ADD8",
    "c#": "#178600", "c++": "#f34b7d", c: "#555555", java: "#b07219", kotlin: "#A97BFF", swift: "#F05138", ruby: "#701516",
    php: "#4F5D95", dart: "#00B4AB", shell: "#89e051", html: "#e34c26", css: "#563d7c", "jupyter notebook": "#DA5B0B",
    lua: "#000080", zig: "#ec915c", scala: "#c22d40", elixir: "#6e4a7e", haskell: "#5e5086", vue: "#41b883", svelte: "#ff3e00", r: "#198CE7" };
  document.querySelectorAll(".dot[data-lang]").forEach(function (d) {
    var c = LANG_COLORS[d.getAttribute("data-lang")];
    if (c) d.style.background = c;
  });

  // ---- bookmarks ----------------------------------------------------------
  var KEY = "aign_bookmarks";
  function getBookmarks() { try { return JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) { return []; } }
  function setBookmarks(list) { try { localStorage.setItem(KEY, JSON.stringify(list)); } catch (e) {} updateCount(); }
  function updateCount() {
    var n = getBookmarks().length;
    document.querySelectorAll("[data-bm-count]").forEach(function (el) { el.textContent = fa(n); el.hidden = n === 0; });
  }
  function paintButtons() {
    var set = {}; getBookmarks().forEach(function (id) { set[id] = true; });
    document.querySelectorAll("[data-bookmark]").forEach(function (b) {
      var on = !!set[b.getAttribute("data-bookmark")];
      b.classList.toggle("on", on);
      b.setAttribute("aria-pressed", on ? "true" : "false");
      b.title = on ? "حذف نشان" : "نشان کردن";
    });
  }
  document.addEventListener("click", function (ev) {
    var btn = ev.target.closest("[data-bookmark]");
    if (!btn) return;
    ev.preventDefault();
    var id = parseInt(btn.getAttribute("data-bookmark"), 10);
    var list = getBookmarks();
    var idx = list.indexOf(id);
    if (idx >= 0) list.splice(idx, 1); else list.unshift(id);
    setBookmarks(list.slice(0, 300));
    paintButtons();
    if (document.querySelector("[data-bookmarks-list]") && idx >= 0) {
      var card = btn.closest("[data-item-id]");
      if (card) card.remove();
      renderEmptyIfNeeded();
    }
  });
  updateCount(); paintButtons();

  // bookmarks page
  var listEl = document.querySelector("[data-bookmarks-list]");
  function renderEmptyIfNeeded() {
    if (listEl && !listEl.querySelector("[data-item-id]")) listEl.innerHTML = '<div class="empty"><p>هنوز چیزی نشان نکرده‌اید. روی آیکن نشان در کارت‌ها بزنید.</p></div>';
  }
  if (listEl) {
    var ids = getBookmarks();
    if (!ids.length) { renderEmptyIfNeeded(); }
    else {
      fetch("/api/items?ids=" + ids.join(","))
        .then(function (r) { return r.json(); })
        .then(function (data) {
          listEl.innerHTML = "";
          var tpl = document.getElementById("bm-card");
          (data.items || []).forEach(function (it) {
            var node = tpl.content.cloneNode(true);
            var art = node.querySelector("article");
            art.setAttribute("data-item-id", it.id);
            art.classList.add("kind-" + it.kind);
            node.querySelector(".badge.kind").textContent = { github_repo: "ریپو", github_release: "ریلیز", hackernews: "Hacker News", rss: "مقاله", hf_model: "مدل HF", hf_paper: "مقالهٔ HF" }[it.kind] || it.kind;
            node.querySelector(".badge.kind").classList.add("kind-" + it.kind);
            var cat = node.querySelector(".badge.cat");
            if (it.category_fa) cat.textContent = it.category_fa; else cat.remove();
            var a = node.querySelector(".card-title a"); a.href = "/item/" + it.id; a.textContent = it.title_fa || it.title;
            node.querySelector(".card-summary").textContent = it.summary_fa || "";
            var meta = [];
            if (it.language) meta.push(it.language);
            if (it.stars) meta.push("★ " + fa(it.stars.toLocaleString("en-US")));
            if (it.points) meta.push("▲ " + fa(it.points));
            node.querySelector(".card-meta").textContent = meta.join(" · ");
            node.querySelector(".bm").setAttribute("data-bookmark", it.id);
            listEl.appendChild(node);
          });
          paintButtons();
          renderEmptyIfNeeded();
        })
        .catch(function () { listEl.innerHTML = '<div class="empty"><p>خطا در بارگذاری نشان‌ها.</p></div>'; });
    }
    var exp = document.querySelector("[data-bm-export]");
    if (exp) exp.addEventListener("click", function () {
      var blob = new Blob([JSON.stringify({ bookmarks: getBookmarks(), exported_at: new Date().toISOString() }, null, 2)], { type: "application/json" });
      var a = document.createElement("a"); a.href = URL.createObjectURL(blob); a.download = "bookmarks.json"; a.click();
    });
    var clr = document.querySelector("[data-bm-clear]");
    if (clr) clr.addEventListener("click", function () { if (confirm("همهٔ نشان‌ها پاک شود؟")) { setBookmarks([]); listEl.innerHTML = ""; renderEmptyIfNeeded(); } });
  }

  // ---- search shortcut ------------------------------------------------------
  document.addEventListener("keydown", function (ev) {
    if (ev.key === "/" && !/input|textarea|select/i.test(document.activeElement.tagName)) {
      var s = document.querySelector("[data-search]");
      if (s) { ev.preventDefault(); s.focus(); s.select(); }
    }
  });

  // ---- share -------------------------------------------------------------------
  document.querySelectorAll("[data-share]").forEach(function (btn) {
    btn.addEventListener("click", function () {
      var data = { title: btn.getAttribute("data-title") || document.title, url: location.href };
      if (navigator.share) { navigator.share(data).catch(function () {}); }
      else if (navigator.clipboard) { navigator.clipboard.writeText(location.href).then(function () { btn.title = "کپی شد"; }); }
    });
  });

  // ---- service worker (offline shell) --------------------------------------
  if ("serviceWorker" in navigator && location.protocol === "https:") {
    navigator.serviceWorker.register("/static/js/sw.js").catch(function () {});
  }
})();
