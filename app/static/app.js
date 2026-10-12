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

  document.addEventListener("DOMContentLoaded", function () {
    setupMenu();
    setupDropdown();
    setupAutoSubmit();
  });
})();
