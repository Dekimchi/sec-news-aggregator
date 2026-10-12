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

  function hoursWord(n) {
    var value = Math.abs(parseInt(n, 10) || 0);
    var n10 = value % 10;
    var n100 = value % 100;
    if (n10 === 1 && n100 !== 11) return "час";
    if (n10 >= 2 && n10 <= 4 && !(n100 >= 12 && n100 <= 14)) return "часа";
    return "часов";
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
      /* ignore */
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

  function setupDropdowns() {
    var roots = qsa("[data-dropdown]");
    if (!roots.length) return;

    function isOpen(root) {
      return root.classList.contains("is-open");
    }

    function closeOne(root) {
      var toggle = qs("[data-dropdown-toggle]", root);
      var panel = qs("[data-dropdown-panel]", root);
      if (!toggle || !panel) return;
      panel.hidden = true;
      root.classList.remove("is-open");
      toggle.setAttribute("aria-expanded", "false");
    }

    function openOne(root) {
      var toggle = qs("[data-dropdown-toggle]", root);
      var panel = qs("[data-dropdown-panel]", root);
      if (!toggle || !panel) return;
      panel.hidden = false;
      root.classList.add("is-open");
      toggle.setAttribute("aria-expanded", "true");
    }

    function closeAll(except) {
      roots.forEach(function (root) {
        if (except && root === except) return;
        closeOne(root);
      });
    }

    roots.forEach(function (root) {
      var toggle = qs("[data-dropdown-toggle]", root);
      var panel = qs("[data-dropdown-panel]", root);
      if (!toggle || !panel) return;

      // Ensure closed initial state even if CSS previously forced display.
      closeOne(root);

      toggle.addEventListener("click", function (e) {
        e.preventDefault();
        e.stopPropagation();
        var wasOpen = isOpen(root);
        closeAll();
        if (!wasOpen) openOne(root);
      });
      panel.addEventListener("click", function (e) {
        // Keep open while interacting inside; links still navigate.
        e.stopPropagation();
      });
    });

    document.addEventListener("click", function () {
      closeAll();
    });
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") closeAll();
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

  function setupHoursPlural() {
    qsa("[data-hours-suffix]").forEach(function (input) {
      var target = qs(input.getAttribute("data-hours-suffix"));
      if (!target) return;
      function sync() {
        target.textContent = hoursWord(input.value);
      }
      input.addEventListener("input", sync);
      input.addEventListener("change", sync);
      sync();
    });
  }

  function setupRefreshProgress() {
    var form = qs("form[data-refresh-progress]");
    var bar = qs("#refresh-progress");
    if (!form || !bar) return;

    form.addEventListener("submit", function (e) {
      e.preventDefault();
      var btn = qs(".refresh-btn", form);
      if (btn) {
        btn.disabled = true;
        btn.classList.add("is-busy");
      }
      bar.hidden = false;
      bar.setAttribute("aria-hidden", "false");
      if (window.secNewsToast && form.dataset.pendingToast) {
        window.secNewsToast(form.dataset.pendingToast, "info");
      }

      var data = new FormData(form);
      fetch(form.action, {
        method: "POST",
        body: data,
        credentials: "same-origin",
        redirect: "follow",
      })
        .then(function (resp) {
          window.location.href = resp.url || form.querySelector('[name="next"]').value || "/";
        })
        .catch(function () {
          bar.hidden = true;
          if (btn) {
            btn.disabled = false;
            btn.classList.remove("is-busy");
          }
          if (window.secNewsToast) {
            window.secNewsToast("Не удалось обновить ленту", "error");
          }
        });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    setupDropdowns();
    setupAutoSubmit();
    setupPresetSave();
    setupFilterScopes();
    setupHoursPlural();
    setupRefreshProgress();
  });
})();
