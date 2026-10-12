(function () {
  function qs(sel, root) {
    return (root || document).querySelector(sel);
  }
  function qsa(sel, root) {
    return Array.prototype.slice.call((root || document).querySelectorAll(sel));
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
        if (key === "page") return;
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
  });
})();
