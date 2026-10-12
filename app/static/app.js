(function () {
  var FILTER_KEYS = {
    feed: "sec-news.filters.feed",
    bookmarks: "sec-news.filters.bookmarks",
  };

  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }
  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
  }

  function currentScope() {
    var body = document.body;
    var scope = body && body.getAttribute("data-filter-scope");
    return scope === "bookmarks" ? "bookmarks" : scope === "feed" ? "feed" : null;
  }

  function normalizeQs(search, scope) {
    var raw = typeof search === "string" ? search : "";
    if (raw.charAt(0) === "?") raw = raw.slice(1);
    var params = new URLSearchParams(raw);
    params.delete("page");
    if (scope === "bookmarks") {
      params.set("bookmarks", "1");
    } else if (scope === "feed") {
      params.delete("bookmarks");
    }
    return params.toString();
  }

  function urlForScope(scope) {
    var stored = "";
    try {
      stored = sessionStorage.getItem(FILTER_KEYS[scope]) || "";
    } catch (e) {
      stored = "";
    }
    var qsValue = normalizeQs(stored, scope);
    if (!qsValue) {
      return scope === "bookmarks" ? "/?bookmarks=1" : "/";
    }
    return "/?" + qsValue;
  }

  function saveScopeQs(scope, search) {
    if (!scope || !FILTER_KEYS[scope]) return;
    var qsValue = normalizeQs(search, scope);
    try {
      sessionStorage.setItem(FILTER_KEYS[scope], qsValue);
    } catch (e) {
      /* ignore quota / private mode */
    }
  }

  function clearScope(scope) {
    if (!scope || !FILTER_KEYS[scope]) return;
    try {
      sessionStorage.removeItem(FILTER_KEYS[scope]);
    } catch (e) {
      /* ignore */
    }
  }

  function refreshNavLinks() {
    qsa("[data-nav]").forEach(function (el) {
      var nav = el.getAttribute("data-nav");
      if (nav === "feed" || nav === "bookmarks") {
        el.setAttribute("href", urlForScope(nav));
      }
    });
  }

  function setupFilterScopes() {
    var scope = currentScope();
    if (scope) {
      saveScopeQs(scope, window.location.search);
    }
    refreshNavLinks();

    var reset = qs("[data-filter-reset]");
    if (reset && scope) {
      reset.addEventListener("click", function (e) {
        e.preventDefault();
        clearScope(scope);
        refreshNavLinks();
        window.location.href = scope === "bookmarks" ? "/?bookmarks=1" : "/";
      });
    }

    var filterForm = qs("[data-filter-form]");
    if (filterForm && scope) {
      filterForm.addEventListener("submit", function () {
        var data = new FormData(filterForm);
        var params = new URLSearchParams();
        data.forEach(function (value, key) {
          if (key === "page") return;
          params.append(key, value);
        });
        var sort = qs("#sort-select");
        if (sort && !params.has("sort")) {
          params.set("sort", sort.value);
        }
        saveScopeQs(scope, params.toString());
        refreshNavLinks();
      });
    }
  }

  function setupMenu() {
    var toggle = qs("#menu-toggle");
    var actions = qs("#top-actions");
    if (!toggle || !actions) return;
    toggle.addEventListener("click", function () {
      var open = actions.classList.toggle("is-open");
      toggle.setAttribute("aria-expanded", open ? "true" : "false");
      toggle.classList.toggle("is-open", open);
    });
  }

  function setupDropdown() {
    var root = qs("[data-dropdown]");
    if (!root) return;
    var toggle = qs("[data-dropdown-toggle]", root);
    var panel = qs("[data-dropdown-panel]", root);
    if (!toggle || !panel) return;

    function open() {
      panel.hidden = false;
      root.classList.add("is-open");
      toggle.setAttribute("aria-expanded", "true");
    }

    function close() {
      panel.hidden = true;
      root.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
    }

    function toggleOpen() {
      if (panel.hidden) open();
      else close();
    }

    toggle.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleOpen();
    });
    panel.addEventListener("click", function (e) {
      e.stopPropagation();
    });
    document.addEventListener("click", close);
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }

  function setupAutoSubmit() {
    qsa("[data-auto-submit]").forEach(function (el) {
      el.addEventListener("change", function () {
        var form = el.form || qs("#filter-form");
        if (!form) return;
        form.requestSubmit ? form.requestSubmit() : form.submit();
      });
    });
  }

  function setupPresetSave() {
    var form = qs("#preset-save-form");
    var out = qs("#preset-params-json");
    var filterForm = qs("#filter-form");
    if (!form || !out || !filterForm) return;
    form.addEventListener("submit", function () {
      var data = new FormData(filterForm);
      var params = {};
      data.forEach(function (value, key) {
        if (key === "page" || key === "bookmarks") return;
        if (["direction", "content_type", "technology", "source"].indexOf(key) >= 0) {
          params[key] = params[key] || [];
          params[key].push(value);
        } else {
          params[key] = value;
        }
      });
      var sort = qs("#sort-select");
      if (sort) params.sort = sort.value;
      out.value = JSON.stringify(params);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    setupMenu();
    setupDropdown();
    setupAutoSubmit();
    setupPresetSave();
    setupFilterScopes();
  });
})();
