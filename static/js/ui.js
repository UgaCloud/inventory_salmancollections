/* Interface system: theme, loader, cancel, uploads, PWA and connection state. */
(function () {
  "use strict";

  const html = document.documentElement;

  /* ---------------- Theme ---------------- */
  const THEME_KEY = "app-theme";

  function currentTheme() {
    return html.getAttribute("data-theme") === "dark" ? "dark" : "light";
  }

  function applyTheme(theme, persist) {
    html.setAttribute("data-theme", theme);
    if (persist) {
      try { localStorage.setItem(THEME_KEY, theme); } catch (error) { /* ignore */ }
    }
    document.querySelectorAll("[data-theme-icon]").forEach((icon) => {
      icon.textContent = theme === "dark" ? "☀" : "☾";
    });
    document.querySelectorAll("[data-theme-label]").forEach((label) => {
      if (label.classList.contains("sr-only") || label.tagName === "SPAN") {
        label.textContent = theme === "dark" ? "Light mode" : "Dark mode";
      }
    });
    const meta = document.querySelector('meta[name="theme-color"]');
    if (meta) meta.setAttribute("content", theme === "dark" ? "#0b1220" : "#4f46e5");
    document.dispatchEvent(new CustomEvent("app:themechanged", { detail: { theme } }));
  }

  applyTheme(currentTheme(), false);

  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-theme-toggle]");
    if (!toggle) return;
    event.preventDefault();
    applyTheme(currentTheme() === "dark" ? "light" : "dark", true);
  });

  // Keep two open tabs in sync.
  window.addEventListener("storage", (event) => {
    if (event.key === THEME_KEY && event.newValue) applyTheme(event.newValue, false);
  });

  /* ---------------- Application loader ---------------- */
  const loader = document.getElementById("app-loader");
  let loaderShownAt = 0;

  function showLoader() {
    if (!loader) return;
    loaderShownAt = Date.now();
    loader.classList.remove("is-hidden");
  }

  function hideLoader() {
    if (!loader) return;
    const elapsed = Date.now() - loaderShownAt;
    const wait = Math.max(0, 550 - elapsed);
    window.setTimeout(() => loader.classList.add("is-hidden"), wait);
  }

  window.AppLoader = { show: showLoader, hide: hideLoader };

  if (loader) {
    if (document.readyState === "complete") {
      hideLoader();
    } else {
      window.addEventListener("load", hideLoader);
      // Never trap the interface behind the loader if a resource hangs.
      window.setTimeout(() => loader.classList.add("is-hidden"), 4500);
    }
  }

  /* ---------------- Cancel buttons ---------------- */
  function formIsDirty(form) {
    if (!form || form.dataset.initialState === undefined) return false;
    return form.dataset.initialState !== serializeForm(form);
  }

  function serializeForm(form) {
    const parts = [];
    new FormData(form).forEach((value, key) => {
      if (value instanceof File) {
        parts.push(`${key}:${value.name}:${value.size}`);
      } else {
        parts.push(`${key}:${value}`);
      }
    });
    return parts.join("|");
  }

  function primeFormState(root) {
    const scope = root || document;
    scope.querySelectorAll("form").forEach((form) => {
      if (form.dataset.initialState === undefined && !form.hasAttribute("data-filter-form")) {
        form.dataset.initialState = serializeForm(form);
      }
    });
  }

  document.addEventListener("click", (event) => {
    const cancel = event.target.closest("[data-form-cancel]");
    if (!cancel) return;
    event.preventDefault();
    const form = cancel.closest("form");
    const label = cancel.dataset.cancelLabel || "this form";
    if (form && formIsDirty(form)) {
      if (!window.confirm(`Discard the unsaved changes in ${label}?`)) return;
    }
    const panel = cancel.closest("[data-form-panel]");
    if (panel && window.AppUI && window.AppUI.closeFormPanel) {
      window.AppUI.closeFormPanel();
      return;
    }
    const target = cancel.dataset.cancelUrl;
    if (target) {
      if (target === window.location.pathname + window.location.search) {
        window.history.back();
      } else {
        window.location.href = target;
      }
    } else if (window.history.length > 1) {
      window.history.back();
    } else {
      window.location.href = "/";
    }
  });

  document.addEventListener("app:page-loaded", () => primeFormState());
  document.addEventListener("DOMContentLoaded", () => {
    primeFormState();
    // The shared inline form panel is replaced by AJAX, so prepare whatever
    // lands in it (cancel baseline, upload widgets).
    const panel = document.querySelector("[data-form-panel]");
    if (panel && window.MutationObserver) {
      new MutationObserver(() => {
        primeFormState(panel);
        enhanceUploads(panel);
      }).observe(panel, { childList: true, subtree: true });
    }
  });
  document.addEventListener("reset", (event) => {
    const form = event.target.closest("form");
    if (!form) return;
    window.setTimeout(() => {
      form.dataset.initialState = serializeForm(form);
      enhanceUploads(form);
    }, 0);
  }, true);

  // Uploads are a major operation: show the loader while the file posts.
  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form");
    if (!form) return;
    if (form.getAttribute("enctype") === "multipart/form-data" || form.querySelector('input[type="file"]')) {
      const fileInput = form.querySelector('input[type="file"]');
      if (fileInput && fileInput.files && fileInput.files.length) showLoader();
    }
  }, true);

  /* ---------------- Optional field groups ---------------- */
  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-form-more]");
    if (!toggle) return;
    event.preventDefault();
    const scope = toggle.closest("form") || document;
    const body = scope.querySelector("[data-form-more-body]");
    if (!body) return;
    const opening = body.hidden;
    body.hidden = !opening;
    toggle.setAttribute("aria-expanded", opening ? "true" : "false");
    const label = toggle.querySelector("[data-form-more-label]");
    if (label) label.textContent = opening ? "Show less" : "Add more info";
    if (opening) {
      const first = body.querySelector("input, select, textarea");
      if (first) first.focus({ preventScroll: true });
    }
  });

  /* ---------------- Custom file uploads ---------------- */
  const ICON_UPLOAD =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" aria-hidden="true"><path d="M12 16V4m0 0 4 4m-4-4-4 4"/><path d="M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15"/></svg>';

  function humanSize(bytes) {
    if (bytes < 1024) return `${bytes} B`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
    return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
  }

  function fileMatchesAccept(file, accept) {
    if (!accept) return true;
    const rules = accept.split(",").map((rule) => rule.trim().toLowerCase()).filter(Boolean);
    if (!rules.length) return true;
    const name = file.name.toLowerCase();
    const type = (file.type || "").toLowerCase();
    return rules.some((rule) => {
      if (rule.startsWith(".")) return name.endsWith(rule);
      if (rule.endsWith("/*")) return type.startsWith(rule.slice(0, -1));
      return type === rule;
    });
  }

  function enhanceUpload(input) {
    if (!input || input.dataset.uploadReady === "true") return;
    input.dataset.uploadReady = "true";

    const maxBytes = Number(input.dataset.maxSize || 5 * 1024 * 1024);
    const accepted = input.getAttribute("accept") || "";
    const field = document.createElement("div");
    field.className = "upload-field";
    field.tabIndex = 0;
    input.parentNode.insertBefore(field, input);
    field.appendChild(input);

    field.innerHTML += `
      <div class="upload-body">
        <span class="upload-icon">${ICON_UPLOAD}</span>
        <div class="upload-copy">
          <p class="upload-title" data-upload-title>Choose a file or drag it here</p>
          <p class="upload-hint" data-upload-hint>${accepted ? accepted.replace(/,/g, ", ") : "Any supported file"} · up to ${humanSize(maxBytes)}</p>
        </div>
        <span class="btn btn-secondary btn-sm" data-upload-browse>Browse</span>
      </div>
      <div class="upload-preview" data-upload-preview hidden>
        <img data-upload-thumb alt="" hidden>
        <div class="upload-filename">
          <p data-upload-name></p>
          <p class="upload-size" data-upload-size></p>
        </div>
        <button type="button" class="btn btn-ghost btn-sm" data-upload-remove>Remove</button>
      </div>
      <div class="upload-progress" data-upload-progress hidden><span></span></div>
      <p class="upload-error" data-upload-error hidden></p>
    `;

    const title = field.querySelector("[data-upload-title]");
    const hint = field.querySelector("[data-upload-hint]");
    const preview = field.querySelector("[data-upload-preview]");
    const thumb = field.querySelector("[data-upload-thumb]");
    const nameNode = field.querySelector("[data-upload-name]");
    const sizeNode = field.querySelector("[data-upload-size]");
    const errorNode = field.querySelector("[data-upload-error]");

    function clearError() {
      errorNode.hidden = true;
      errorNode.textContent = "";
    }

    function showError(message) {
      errorNode.textContent = message;
      errorNode.hidden = false;
      input.value = "";
      render();
    }

    function render() {
      const file = input.files && input.files[0];
      if (!file) {
        preview.hidden = true;
        thumb.hidden = true;
        title.textContent = "Choose a file or drag it here";
        hint.hidden = false;
        return;
      }
      preview.hidden = false;
      title.textContent = "File selected";
      hint.hidden = true;
      nameNode.textContent = file.name;
      sizeNode.textContent = humanSize(file.size);
      if (file.type.startsWith("image/")) {
        const url = URL.createObjectURL(file);
        thumb.src = url;
        thumb.hidden = false;
        thumb.onload = () => URL.revokeObjectURL(url);
      } else {
        thumb.hidden = true;
        thumb.removeAttribute("src");
      }
    }

    function validate() {
      clearError();
      const file = input.files && input.files[0];
      if (!file) return true;
      if (!fileMatchesAccept(file, accepted)) {
        showError("That file type is not supported here.");
        return false;
      }
      if (file.size > maxBytes) {
        showError(`That file is too large. The limit is ${humanSize(maxBytes)}.`);
        return false;
      }
      return true;
    }

    function openPicker() {
      input.click();
    }

    field.querySelector("[data-upload-browse]").addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      openPicker();
    });
    field.addEventListener("click", (event) => {
      if (event.target.closest("[data-upload-remove]")) return;
      if (event.target.closest("[data-upload-preview]")) return;
      openPicker();
    });
    field.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openPicker();
      }
    });
    field.querySelector("[data-upload-remove]").addEventListener("click", (event) => {
      event.preventDefault();
      event.stopPropagation();
      input.value = "";
      clearError();
      render();
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });
    input.addEventListener("change", () => {
      validate();
      render();
    });
    ["dragenter", "dragover"].forEach((name) => {
      field.addEventListener(name, (event) => {
        event.preventDefault();
        field.classList.add("is-dragover");
      });
    });
    ["dragleave", "drop"].forEach((name) => {
      field.addEventListener(name, (event) => {
        event.preventDefault();
        field.classList.remove("is-dragover");
      });
    });
    field.addEventListener("drop", (event) => {
      const files = event.dataTransfer && event.dataTransfer.files;
      if (!files || !files.length) return;
      const transfer = new DataTransfer();
      transfer.items.add(files[0]);
      input.files = transfer.files;
      input.dispatchEvent(new Event("change", { bubbles: true }));
    });

    render();
  }

  function enhanceUploads(root) {
    if (!root) return;
    const inputs = root.matches && root.matches('input[type="file"]')
      ? [root]
      : Array.from(root.querySelectorAll('input[type="file"]'));
    inputs.forEach(enhanceUpload);
  }

  window.AppUploads = { enhance: enhanceUploads };
  document.addEventListener("DOMContentLoaded", () => enhanceUploads(document));
  document.addEventListener("app:page-loaded", () => enhanceUploads(document));

  /* ---------------- Connection state ---------------- */
  const netStatus = document.getElementById("net-status");
  const netLabel = netStatus ? netStatus.querySelector("[data-net-label]") : null;

  function updateConnection() {
    const online = navigator.onLine;
    if (netStatus) {
      netStatus.dataset.state = online ? "online" : "offline";
      if (netLabel) netLabel.textContent = online ? "Online" : "Offline · changes will not be saved";
    }
    document.documentElement.dataset.connection = online ? "online" : "offline";
    if (!online && window.AppUI) {
      window.AppUI.toast("You are offline. Pages already visited stay available, but nothing is saved to the server.", "error");
    }
  }

  window.addEventListener("online", updateConnection);
  window.addEventListener("offline", updateConnection);
  document.addEventListener("DOMContentLoaded", updateConnection);

  /* ---------------- PWA ---------------- */
  let installPrompt = null;
  const installButton = document.getElementById("pwa-install");

  window.addEventListener("beforeinstallprompt", (event) => {
    event.preventDefault();
    installPrompt = event;
    if (installButton) installButton.hidden = false;
  });

  if (installButton) {
    installButton.addEventListener("click", async () => {
      if (!installPrompt) return;
      installPrompt.prompt();
      try {
        await installPrompt.userChoice;
      } finally {
        installPrompt = null;
        installButton.hidden = true;
      }
    });
  }
  window.addEventListener("appinstalled", () => {
    installPrompt = null;
    if (installButton) installButton.hidden = true;
    if (window.AppUI) window.AppUI.toast("The app has been installed on this device.", "success");
  });

  if ("serviceWorker" in navigator && window.isSecureContext) {
    window.addEventListener("load", () => {
      navigator.serviceWorker.register("/service-worker.js", { scope: "/" }).catch(() => {
        /* The app still works online without the service worker. */
      });
    });
  }
})();
