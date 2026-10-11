(function () {
  function showToast(message, level) {
    var host = document.getElementById("toast-host");
    if (!host) {
      host = document.createElement("div");
      host.id = "toast-host";
      host.className = "toast-host";
      document.body.appendChild(host);
    }
    var el = document.createElement("div");
    el.className = "toast toast-" + (level || "info");
    el.setAttribute("role", "status");
    el.textContent = message;
    host.appendChild(el);
    requestAnimationFrame(function () {
      el.classList.add("toast-show");
    });
    setTimeout(function () {
      el.classList.remove("toast-show");
      setTimeout(function () {
        el.remove();
      }, 250);
    }, 4200);
  }

  window.secNewsToast = showToast;

  document.addEventListener("DOMContentLoaded", function () {
    var boot = document.getElementById("toast-boot");
    if (boot && boot.textContent) {
      try {
        var data = JSON.parse(boot.textContent);
        if (data && data.message) {
          showToast(data.message, data.level || "info");
        }
      } catch (err) {
        // ignore malformed boot payload
      }
    }

    document.querySelectorAll("form.js-action").forEach(function (form) {
      form.addEventListener("submit", function () {
        var btn = form.querySelector('button[type="submit"], button:not([type])');
        if (btn) {
          btn.disabled = true;
          if (!btn.dataset.originalText) {
            btn.dataset.originalText = btn.textContent;
          }
          btn.textContent = form.dataset.loadingText || "Выполняется…";
        }
        var pending = form.dataset.pendingToast;
        if (pending) {
          showToast(pending, "info");
        }
      });
    });
  });
})();
