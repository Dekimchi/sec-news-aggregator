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

  function setupDrawer() {
    var panel = qs("[data-drawer]");
    var backdrop = qs("[data-drawer-backdrop]");
    if (!panel) return;

    function open() {
      panel.classList.add("is-open");
      if (backdrop) {
        backdrop.hidden = false;
        requestAnimationFrame(function () {
          backdrop.classList.add("is-visible");
        });
      }
      document.body.classList.add("drawer-open");
    }

    function close() {
      panel.classList.remove("is-open");
      if (backdrop) {
        backdrop.classList.remove("is-visible");
        setTimeout(function () {
          backdrop.hidden = true;
        }, 200);
      }
      document.body.classList.remove("drawer-open");
    }

    qsa("[data-drawer-open]").forEach(function (btn) {
      btn.addEventListener("click", open);
    });
    qsa("[data-drawer-close]").forEach(function (btn) {
      btn.addEventListener("click", close);
    });
    if (backdrop) {
      backdrop.addEventListener("click", close);
    }
    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape") close();
    });
  }

  function setupAutoSubmit() {
    qsa("[data-auto-submit]").forEach(function (el) {
      el.addEventListener("change", function () {
        var form = el.form || qs("#filter-form");
        if (!form) return;
        // Keep hidden sort in sync when using external select
        var hidden = form.querySelector('input[name="sort"]');
        if (hidden && el.name === "sort") {
          hidden.value = el.value;
        }
        form.requestSubmit ? form.requestSubmit() : form.submit();
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    setupMenu();
    setupDrawer();
    setupAutoSubmit();
  });
})();
