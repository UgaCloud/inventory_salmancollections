/* Shared interface behaviour: SPA-style navigation, workspace forms, filters. */
(function () {
  "use strict";

  const csrfToken = () => {
    const meta = document.querySelector('meta[name="csrf-token"]');
    return meta ? meta.getAttribute("content") : "";
  };

  const escapeHtml = (value) =>
    String(value ?? "").replace(/[&<>"']/g, (char) => ({
      "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
    }[char]));

  /* ---------------- Toasts ---------------- */
  function toast(message, type = "success") {
    const root = document.getElementById("toast-root");
    if (!root || !message) return;
    const node = document.createElement("div");
    node.className = `toast toast-${type === "error" ? "error" : type === "info" ? "info" : "success"}`;
    node.setAttribute("role", type === "error" ? "alert" : "status");
    node.innerHTML = `<span>${escapeHtml(message)}</span><button type="button" aria-label="Dismiss" class="text-white/80 hover:text-white">&times;</button>`;
    node.querySelector("button").addEventListener("click", () => node.remove());
    root.appendChild(node);
    setTimeout(() => node.remove(), 6000);
  }

  function setLoading(on) {
    const bar = document.getElementById("loading-bar");
    if (bar) bar.style.opacity = on ? "1" : "0";
  }

  /* ---------------- Searchable dropdowns ---------------- */
  function closeSelects(except) {
    document.querySelectorAll(".select-wrap.is-open").forEach((wrap) => {
      if (wrap === except) return;
      wrap.classList.remove("is-open");
      const panel = wrap.querySelector(".select-panel");
      const trigger = wrap.querySelector(".select-trigger");
      if (panel) panel.hidden = true;
      if (trigger) trigger.setAttribute("aria-expanded", "false");
    });
  }

  function syncSelect(select) {
    const wrap = select.closest(".select-wrap");
    if (!wrap) return;
    const valueNode = wrap.querySelector(".select-value");
    const trigger = wrap.querySelector(".select-trigger");
    const option = select.options[select.selectedIndex];
    const label = option ? option.textContent.trim() : "";
    if (valueNode) {
      valueNode.textContent = label || "—";
      valueNode.classList.toggle("is-placeholder", !select.value);
    }
    if (trigger) {
      trigger.disabled = select.disabled;
      trigger.title = label;
    }
  }

  function syncSelects(root) {
    if (!root) return;
    const selects = root.matches && root.matches("select") ? [root] : Array.from(root.querySelectorAll("select"));
    selects.forEach(syncSelect);
  }

  function renderSelectOptions(select, wrap, filterText) {
    const list = wrap.querySelector(".select-options");
    const empty = wrap.querySelector(".select-empty");
    if (!list) return;
    const query = (filterText || "").trim().toLowerCase();
    list.innerHTML = "";
    let visible = 0;
    Array.from(select.options).forEach((option) => {
      if (option.hidden) return;
      const text = option.textContent.trim();
      if (query && !text.toLowerCase().includes(query)) return;
      const item = document.createElement("button");
      item.type = "button";
      item.className = "select-option";
      item.dataset.value = option.value;
      item.setAttribute("role", "option");
      item.setAttribute("aria-selected", option.selected ? "true" : "false");
      if (option.selected) item.classList.add("is-selected");
      item.textContent = text || "—";
      list.appendChild(item);
      visible += 1;
    });
    if (empty) empty.hidden = visible > 0;
  }

  function positionSelectPanel(wrap) {
    const trigger = wrap.querySelector(".select-trigger");
    const panel = wrap.querySelector(".select-panel");
    if (!trigger || !panel) return;
    const rect = trigger.getBoundingClientRect();
    const width = Math.max(rect.width, 220);
    const left = Math.max(8, Math.min(rect.left, window.innerWidth - width - 12));
    const spaceBelow = window.innerHeight - rect.bottom - 16;
    const spaceAbove = rect.top - 16;
    const openUp = spaceBelow < 220 && spaceAbove > spaceBelow;
    panel.style.width = `${width}px`;
    panel.style.left = `${left}px`;
    panel.style.top = openUp ? "" : `${rect.bottom + 6}px`;
    panel.style.bottom = openUp ? `${window.innerHeight - rect.top + 6}px` : "";
    panel.style.maxHeight = `${Math.max(160, Math.min(320, openUp ? spaceAbove : spaceBelow))}px`;
    panel.style.overflow = "hidden";
  }

  function openSelect(wrap) {
    const select = wrap.querySelector("select");
    const panel = wrap.querySelector(".select-panel");
    const search = wrap.querySelector(".select-search");
    if (!select || !panel) return;
    closeSelects(wrap);
    renderSelectOptions(select, wrap, "");
    if (search) search.value = "";
    panel.hidden = false;
    wrap.classList.add("is-open");
    const trigger = wrap.querySelector(".select-trigger");
    if (trigger) trigger.setAttribute("aria-expanded", "true");
    positionSelectPanel(wrap);
    if (search) window.setTimeout(() => search.focus(), 0);
  }

  function enhanceSelect(select) {
    if (!select || select.dataset.enhanced === "true") return;
    if (select.multiple || select.size > 1) return;
    const wrap = document.createElement("div");
    wrap.className = "select-wrap";
    select.parentNode.insertBefore(wrap, select);
    wrap.appendChild(select);
    select.dataset.enhanced = "true";
    select.classList.add("select-native");

    const trigger = document.createElement("button");
    trigger.type = "button";
    trigger.className = "select-trigger field-control";
    trigger.setAttribute("aria-haspopup", "listbox");
    trigger.setAttribute("aria-expanded", "false");
    trigger.innerHTML = '<span class="select-value"></span><svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path fill-rule="evenodd" d="M5.23 7.21a.75.75 0 011.06.02L10 11.17l3.71-3.94a.75.75 0 111.08 1.04l-4.25 4.5a.75.75 0 01-1.08 0l-4.25-4.5a.75.75 0 01.02-1.06z" clip-rule="evenodd"/></svg>';

    const panel = document.createElement("div");
    panel.className = "select-panel";
    panel.hidden = true;
    panel.innerHTML = '<div class="select-search-wrap"><input type="search" class="select-search" placeholder="Search…" autocomplete="off" aria-label="Search options"></div><div class="select-options" role="listbox"></div><p class="select-empty" hidden>No matches</p>';

    wrap.appendChild(trigger);
    wrap.appendChild(panel);

    trigger.addEventListener("click", () => {
      if (wrap.classList.contains("is-open")) closeSelects();
      else openSelect(wrap);
    });
    trigger.addEventListener("keydown", (event) => {
      if (event.key === "ArrowDown" || event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        openSelect(wrap);
      }
    });

    panel.addEventListener("click", (event) => {
      const option = event.target.closest(".select-option");
      if (!option) return;
      select.value = option.dataset.value;
      syncSelect(select);
      select.dispatchEvent(new Event("change", { bubbles: true }));
      closeSelects();
      trigger.focus();
    });

    const search = panel.querySelector(".select-search");
    search.addEventListener("input", () => renderSelectOptions(select, wrap, search.value));
    search.addEventListener("keydown", (event) => {
      const items = Array.from(panel.querySelectorAll(".select-option"));
      const current = panel.querySelector(".select-option.is-active");
      if (event.key === "ArrowDown" || event.key === "ArrowUp") {
        event.preventDefault();
        if (!items.length) return;
        let index = current ? items.indexOf(current) : -1;
        index = event.key === "ArrowDown"
          ? Math.min(index + 1, items.length - 1)
          : Math.max(index - 1, 0);
        items.forEach((item) => item.classList.remove("is-active"));
        items[index].classList.add("is-active");
        items[index].scrollIntoView({ block: "nearest" });
      } else if (event.key === "Enter") {
        event.preventDefault();
        const choice = current || items[0];
        if (choice) choice.click();
      } else if (event.key === "Escape") {
        event.preventDefault();
        closeSelects();
        trigger.focus();
      }
    });

    select.addEventListener("change", () => syncSelect(select));
    if (window.MutationObserver) {
      new MutationObserver(() => {
        syncSelect(select);
        if (wrap.classList.contains("is-open")) renderSelectOptions(select, wrap, search.value);
      }).observe(select, { childList: true, subtree: true });
    }
    syncSelect(select);
  }

  function enhanceSelects(root) {
    if (!root) return;
    if (root.matches && root.matches("select")) {
      enhanceSelect(root);
      return;
    }
    root.querySelectorAll("select").forEach(enhanceSelect);
  }

  /* ---------------- Workspace form panel ---------------- */
  function formPanel() {
    return document.querySelector("[data-form-panel]");
  }

  function setPanelVisible(panel, visible) {
    const grid = document.querySelector("[data-workspace-grid]");
    if (grid) grid.classList.toggle("is-panel-hidden", !visible);
    if (visible) {
      panel.classList.remove("hidden");
      panel.classList.remove("is-open");
      void panel.offsetWidth;
      panel.classList.add("is-open");
    } else {
      panel.classList.add("hidden");
      panel.classList.remove("is-open");
    }
  }

  async function openFormPanel(url) {
    const panel = formPanel();
    if (!panel) return;
    if (url) {
      const target = new URL(url, window.location.origin);
      const fragmentUrl = new URL(target.href);
      fragmentUrl.searchParams.set("fragment", "form");
      setLoading(true);
      try {
        const response = await fetch(fragmentUrl.pathname + fragmentUrl.search, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
          credentials: "same-origin",
        });
        if (!response.ok) {
          window.location.href = target.href;
          return;
        }
        panel.innerHTML = await response.text();
        history.pushState({}, "", target.pathname + target.search);
      } catch (error) {
        window.location.href = target.href;
        return;
      } finally {
        setLoading(false);
      }
    }
    setPanelVisible(panel, true);
    enhanceSelects(panel);
    syncSelects(panel);
    const rect = panel.getBoundingClientRect();
    if (rect.top < 0 || rect.bottom > window.innerHeight) {
      panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    const first = panel.querySelector(".select-trigger, input:not([type=hidden]):not([disabled]), textarea");
    if (first) first.focus({ preventScroll: true });
  }

  function closeFormPanel() {
    const panel = formPanel();
    if (!panel) return;
    setPanelVisible(panel, false);
    if (window.location.search) history.replaceState({}, "", window.location.pathname);
  }

  document.addEventListener("click", (event) => {
    const opener = event.target.closest("[data-form-open], [data-form-reveal]");
    if (opener) {
      event.preventDefault();
      openFormPanel(opener.getAttribute("data-form-open") || "");
      return;
    }
    const closer = event.target.closest("[data-form-close]");
    if (closer) {
      event.preventDefault();
      closeFormPanel();
      return;
    }
    const mixtureSell = event.target.closest("[data-sell-mixture]");
    if (mixtureSell) {
      event.preventDefault();
      const panel = formPanel();
      if (!panel) return;
      panel.dataset.price = mixtureSell.dataset.price || "0";
      const form = panel.querySelector("[data-sell-form]");
      if (form) {
        form.action = mixtureSell.dataset.action || form.action;
        const amount = form.querySelector('[name="amount"]');
        if (amount) amount.value = mixtureSell.dataset.price || "";
      }
      const label = panel.querySelector("[data-sell-name]");
      if (label) label.textContent = mixtureSell.dataset.label || mixtureSell.dataset.name || "";
      updateMixtureSalePreview(panel);
      openFormPanel("");
      return;
    }
    if (!event.target.closest(".select-wrap")) closeSelects();
  });

  function updateMixtureSalePreview(panel) {
    if (!panel) return;
    const form = panel.querySelector("[data-sell-form]");
    if (!form) return;
    const price = Number(panel.dataset.price || 0);
    const amountField = form.querySelector('[name="amount"]');
    const customerField = form.querySelector('[name="customer"]');
    const amount = Number(amountField ? amountField.value : 0) || 0;
    const customer = customerField ? customerField.value : "";
    const currency = panel.dataset.currency || "";
    const format = (value) => `${currency}${value.toFixed(2)}`;
    const changeNode = panel.querySelector("[data-mixture-change]");
    const info = panel.querySelector("[data-mixture-balance]");
    if (changeNode) changeNode.textContent = format(Math.max(amount - price, 0));
    if (!info) return;
    if (amount > price && customer) {
      info.textContent = "A customer sale cannot receive more than the total. Reduce the amount.";
      info.classList.remove("hidden");
    } else if (amount > 0 && amount < price) {
      info.textContent = customer
        ? `Balance due: ${format(price - amount)}`
        : "Choose a customer to allow a partial payment, or collect the full total.";
      info.classList.remove("hidden");
    } else {
      info.classList.add("hidden");
    }
  }

  document.addEventListener("input", (event) => {
    const form = event.target.closest("[data-sell-form]");
    if (form) updateMixtureSalePreview(form.closest("[data-form-panel]"));
  });
  document.addEventListener("change", (event) => {
    const form = event.target.closest("[data-sell-form]");
    if (form) updateMixtureSalePreview(form.closest("[data-form-panel]"));
  });

  document.addEventListener("scroll", (event) => {
    const target = event.target;
    if (target && target.closest && target.closest(".select-panel")) return;
    closeSelects();
  }, true);
  window.addEventListener("resize", () => closeSelects());

  /* ---------------- Dropdown navigation ---------------- */
  function closeDropdowns(except) {
    document.querySelectorAll("[data-dropdown-panel]").forEach((panel) => {
      if (panel !== except) {
        panel.hidden = true;
        const toggle = panel.parentElement.querySelector("[data-dropdown-toggle]");
        if (toggle) toggle.setAttribute("aria-expanded", "false");
      }
    });
  }

  document.addEventListener("click", (event) => {
    const toggle = event.target.closest("[data-dropdown-toggle]");
    if (toggle) {
      const panel = toggle.parentElement.querySelector("[data-dropdown-panel]");
      const isOpen = panel && !panel.hidden;
      closeDropdowns();
      if (panel && !isOpen) {
        panel.hidden = false;
        toggle.setAttribute("aria-expanded", "true");
      }
      return;
    }
    if (!event.target.closest("[data-dropdown]")) closeDropdowns();
  });

  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") {
      closeDropdowns();
      const mobile = document.querySelector("[data-mobile-menu]");
      if (mobile) mobile.classList.add("hidden");
    }
  });

  const mobileToggle = document.getElementById("mobile-menu-toggle");
  if (mobileToggle) {
    mobileToggle.addEventListener("click", () => {
      const menu = document.querySelector("[data-mobile-menu]");
      if (!menu) return;
      menu.classList.toggle("hidden");
      mobileToggle.setAttribute("aria-expanded", menu.classList.contains("hidden") ? "false" : "true");
    });
  }

  /* ---------------- AJAX page navigation ---------------- */
  function markActiveLinks() {
    const current = window.location.pathname;
    document.querySelectorAll("header a[data-nav]").forEach((link) => {
      const url = new URL(link.href, window.location.origin);
      const same = url.pathname === current && (url.search === window.location.search || !url.search);
      link.classList.toggle("is-active", same);
    });
  }

  function openPendingMixtureSale() {
    const id = new URLSearchParams(window.location.search).get("sell");
    if (!id) return;
    const button = Array.from(document.querySelectorAll("[data-sell-mixture]")).find(
      (node) => node.dataset.id === id
    );
    if (!button) return;
    button.click();
    history.replaceState({}, "", window.location.pathname);
  }

  function initPage() {
    markActiveLinks();
    closeDropdowns();
    document.body.classList.remove("menu-open");
    enhanceSelects(document);
    syncSelects(document);
    document.dispatchEvent(new CustomEvent("app:page-loaded"));
    openPendingMixtureSale();
  }

  async function loadPage(url, push = true) {
    setLoading(true);
    try {
      const response = await fetch(url, {
        headers: { "X-Requested-With": "XMLHttpRequest" },
        credentials: "same-origin",
      });
      if (!response.ok) {
        window.location.href = url;
        return;
      }
      const html = await response.text();
      const doc = new DOMParser().parseFromString(html, "text/html");
      const nextMain = doc.getElementById("app-main");
      const currentMain = document.getElementById("app-main");
      if (!nextMain || !currentMain) {
        window.location.href = url;
        return;
      }
      currentMain.replaceWith(document.importNode(nextMain, true));
      document.title = doc.title;
      if (push) history.pushState({}, "", url);
      window.scrollTo(0, 0);
      initPage();
    } catch (error) {
      window.location.href = url;
    } finally {
      setLoading(false);
    }
  }

  document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    const link = event.target.closest("a[data-nav]");
    if (!link) return;
    if (link.target || link.hasAttribute("download")) return;
    const url = new URL(link.href, window.location.origin);
    if (url.origin !== window.location.origin) return;
    event.preventDefault();
    loadPage(url.pathname + url.search);
  });

  window.addEventListener("popstate", () => loadPage(window.location.href, false));

  /* ---------------- List refresh & filters ---------------- */
  function listContainer() {
    return document.querySelector("[data-list-container]");
  }

  function filterParams() {
    const params = new URLSearchParams();
    const form = document.querySelector("[data-filter-form]");
    if (form) {
      new FormData(form).forEach((value, key) => {
        if (String(value).trim() !== "") params.set(key, value);
      });
    }
    return params;
  }

  async function refreshList() {
    const container = listContainer();
    if (!container) return;
    const url = new URL(container.dataset.listUrl || window.location.pathname, window.location.origin);
    const params = filterParams();
    params.forEach((value, key) => url.searchParams.set(key, value));
    url.searchParams.set("fragment", "list");
    try {
      const response = await fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } });
      if (!response.ok) return;
      container.innerHTML = await response.text();
    } catch (error) {
      /* keep the existing list */
    }
  }

  async function applyFilters(form, push = true) {
    const container = listContainer();
    if (!container) return;
    const url = new URL(form.dataset.listUrl || container.dataset.listUrl || window.location.pathname, window.location.origin);
    new FormData(form).forEach((value, key) => {
      if (String(value).trim() !== "") url.searchParams.set(key, value);
    });
    const fragmentUrl = new URL(url);
    fragmentUrl.searchParams.set("fragment", "list");
    setLoading(true);
    try {
      const response = await fetch(fragmentUrl, { headers: { "X-Requested-With": "XMLHttpRequest" } });
      if (!response.ok) return;
      container.innerHTML = await response.text();
      if (push) history.pushState({}, "", url.pathname + url.search);
    } finally {
      setLoading(false);
    }
  }

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-filter-form]");
    if (!form) return;
    event.preventDefault();
    applyFilters(form, true);
  });

  document.addEventListener("change", (event) => {
    const form = event.target.closest("form[data-filter-form]");
    if (!form) return;
    if (event.target.matches("select, input[type=date]")) applyFilters(form, true);
  });

  let searchTimer = null;
  document.addEventListener("input", (event) => {
    const form = event.target.closest("form[data-filter-form]");
    if (!form) return;
    if (!event.target.matches("input[type=search], input[name=q]")) return;
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => applyFilters(form, true), 350);
  });

  document.addEventListener("click", (event) => {
    const link = event.target.closest("a[data-page-link]");
    if (!link) return;
    event.preventDefault();
    const container = listContainer();
    if (!container) return;
    const url = new URL(link.href, window.location.origin);
    url.searchParams.set("fragment", "list");
    fetch(url, { headers: { "X-Requested-With": "XMLHttpRequest" } })
      .then((response) => (response.ok ? response.text() : null))
      .then((html) => {
        if (html === null) return;
        container.innerHTML = html;
        const clean = new URL(link.href, window.location.origin);
        history.pushState({}, "", clean.pathname + clean.search);
      });
  });

  /* ---------------- Form errors ---------------- */
  function clearFormErrors(form) {
    form.querySelectorAll(".field-error").forEach((node) => node.remove());
    const summary = form.querySelector("[data-form-errors]");
    if (summary) {
      summary.innerHTML = "";
      summary.classList.add("hidden");
    }
  }

  function showFormErrors(form, data) {
    clearFormErrors(form);
    const errors = (data && data.errors) || {};
    const general = errors._form || errors.__all__ || errors.non_field_errors || [];
    const summary = form.querySelector("[data-form-errors]");
    if (general.length && summary) {
      summary.innerHTML = general.map((message) => `<p>${escapeHtml(message)}</p>`).join("");
      summary.classList.remove("hidden");
    }
    Object.keys(errors).forEach((field) => {
      if (field.startsWith("_") || field === "non_field_errors") return;
      const wrapper = form.querySelector(`[data-field="${field}"]`);
      if (!wrapper) return;
      errors[field].forEach((message) => {
        const node = document.createElement("p");
        node.className = "field-error";
        node.textContent = message;
        wrapper.appendChild(node);
      });
    });
  }

  /* ---------------- AJAX forms ---------------- */
  async function submitForm(form) {
    const submitButton = form.querySelector('[type="submit"]');
    if (submitButton) {
      if (submitButton.dataset.busy === "true") return;
      submitButton.dataset.busy = "true";
      submitButton.disabled = true;
    }
    setLoading(true);
    const editing = !!form.querySelector('input[name="id"]');
    try {
      const response = await fetch(form.action || window.location.href, {
        method: "POST",
        body: new FormData(form),
        headers: {
          "X-Requested-With": "XMLHttpRequest",
          Accept: "application/json",
        },
        credentials: "same-origin",
      });
      let data = null;
      try {
        data = await response.json();
      } catch (error) {
        toast("The server returned an unexpected response.", "error");
        return;
      }
      if (response.ok && data && data.ok) {
        toast(data.message || "Saved.", "success");
        clearFormErrors(form);
        if (data.redirect) {
          await loadPage(data.redirect);
        } else if (data.refresh) {
          await loadPage(window.location.pathname + window.location.search);
        } else if (data.refresh_list) {
          if (editing) {
            await loadPage(window.location.pathname);
          } else {
            form.reset();
            syncSelects(form);
            const errors = form.querySelector("[data-form-errors]");
            if (errors) errors.classList.add("hidden");
            closeFormPanel();
            await refreshList();
          }
        }
      } else {
        showFormErrors(form, data);
        toast((data && data.message) || "Please check the form and try again.", "error");
      }
    } catch (error) {
      toast("Network error. Please check your connection and try again.", "error");
    } finally {
      setLoading(false);
      if (submitButton) {
        submitButton.dataset.busy = "false";
        submitButton.disabled = false;
      }
    }
  }

  document.addEventListener("submit", (event) => {
    const form = event.target.closest("form[data-ajax-form]");
    if (!form) return;
    event.preventDefault();
    submitForm(form);
  });

  /* ---------------- Deletes ---------------- */
  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-delete]");
    if (!button) return;
    event.preventDefault();
    const label = button.dataset.deleteLabel || "this record";
    if (!window.confirm(`Delete ${label}? This cannot be undone.`)) return;
    const body = new FormData();
    body.append("action", "delete");
    body.append("id", button.dataset.id);
    body.append("csrfmiddlewaretoken", csrfToken());
    setLoading(true);
    try {
      const response = await fetch(button.dataset.url || window.location.pathname, {
        method: "POST",
        body,
        headers: { "X-Requested-With": "XMLHttpRequest", Accept: "application/json" },
        credentials: "same-origin",
      });
      const data = await response.json().catch(() => null);
      if (response.ok && data && data.ok) {
        toast(data.message || "Deleted.", "success");
        if (window.location.search.includes("edit=")) {
          await loadPage(window.location.pathname);
        } else {
          await refreshList();
        }
      } else {
        toast((data && data.message) || "That record could not be deleted.", "error");
      }
    } catch (error) {
      toast("Network error while deleting.", "error");
    } finally {
      setLoading(false);
    }
  });

  /* ---------------- Print helper ---------------- */
  document.addEventListener("click", (event) => {
    const button = event.target.closest("[data-print]");
    if (!button) return;
    event.preventDefault();
    window.print();
  });

  document.addEventListener("DOMContentLoaded", initPage);

  window.AppUI = {
    toast,
    loadPage,
    refreshList,
    enhanceSelects,
    syncSelects,
    openFormPanel,
    closeFormPanel,
  };
})();
