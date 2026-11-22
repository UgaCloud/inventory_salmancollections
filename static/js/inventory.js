/* Inventory page helpers: purchase lines, packing filter, mixture builder. */
(function () {
  "use strict";

  const currency = (window.APP_CONFIG && window.APP_CONFIG.currency) || "";
  const num = (value) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : 0;
  };
  const money = (value) => num(value).toFixed(2);

  /* ---------------- Purchase receiving lines ---------------- */
  function initPurchaseLines() {
    const form = document.getElementById("receive-form");
    const template = document.getElementById("purchase-line-template");
    if (!form || !template || form.dataset.linesReady === "true") return;
    form.dataset.linesReady = "true";

    const body = form.querySelector("[data-purchase-lines]");
    const addButton = document.getElementById("add-purchase-line");

    function recalc(row) {
      if (!row) return;
      const quantity = num((row.querySelector('input[name="quantity"]') || {}).value);
      const cost = num((row.querySelector('input[name="unit_cost"]') || {}).value);
      const target = row.querySelector("[data-line-amount]");
      if (target) target.textContent = quantity && cost ? `${currency}${money(quantity * cost)}` : "—";
    }

    if (body) {
      body.addEventListener("input", (event) => {
        if (event.target.matches('input[name="quantity"], input[name="unit_cost"]')) {
          recalc(event.target.closest("tr"));
        }
      });
      body.addEventListener("click", (event) => {
        const remove = event.target.closest("[data-remove-line]");
        if (!remove) return;
        const rows = body.querySelectorAll("tr.purchase-line");
        if (rows.length <= 1) {
          const row = remove.closest("tr");
          row.querySelectorAll("input").forEach((input) => (input.value = ""));
          row.querySelectorAll("select").forEach((select) => (select.value = ""));
          if (window.AppUI) window.AppUI.syncSelects(row);
          recalc(row);
        } else {
          remove.closest("tr").remove();
        }
      });
    }

    if (addButton && body) {
      addButton.addEventListener("click", () => {
        const node = template.content.firstElementChild.cloneNode(true);
        body.appendChild(node);
        if (window.AppUI) window.AppUI.enhanceSelects(node);
        const select = node.querySelector(".select-trigger") || node.querySelector("select");
        if (select) select.focus();
      });
    }
  }

  /* ---------------- Pack from bulk: only linked packed products ---------------- */
  function initPack() {
    const bulkSelect = document.getElementById("id_bulk_product");
    const packedSelect = document.getElementById("id_packed_product");
    if (!bulkSelect || !packedSelect || bulkSelect.dataset.bound === "true") return;
    bulkSelect.dataset.bound = "true";

    const endpoint = bulkSelect.dataset.optionsUrl || "/inventory/pack/options/";

    async function load(preserve) {
      const current = preserve ? packedSelect.value : "";
      packedSelect.innerHTML = '<option value="">Loading…</option>';
      try {
        const response = await fetch(`${endpoint}?bulk=${encodeURIComponent(bulkSelect.value)}`, {
          headers: { "X-Requested-With": "XMLHttpRequest" },
        });
        if (!response.ok) throw new Error("failed");
        const data = await response.json();
        packedSelect.innerHTML = '<option value="">Choose a packed product…</option>';
        (data.options || []).forEach((option) => {
          const node = document.createElement("option");
          node.value = option.id;
          node.textContent = `${option.name}${option.size ? ` — ${option.size}ml` : ""} (stock ${option.stock})`;
          packedSelect.appendChild(node);
        });
        if (current) packedSelect.value = current;
        if (window.AppUI) window.AppUI.syncSelects(packedSelect.parentElement);
      } catch (error) {
        packedSelect.innerHTML = '<option value="">Could not load packed products</option>';
      }
    }

    if (bulkSelect.value) load(true);
    bulkSelect.addEventListener("change", () => load(false));
  }

  /* ---------------- Mixture builder ---------------- */
  function initMixtures() {
    const container = document.getElementById("mixture-components");
    const template = document.getElementById("mixture-row-template");
    const addButton = document.getElementById("add-component");
    if (!container || !template || container.dataset.bound === "true") return;
    container.dataset.bound = "true";

    function updatePreview() {
      let totalMl = 0;
      let totalCost = 0;
      container.querySelectorAll("[data-mixture-row]").forEach((row) => {
        const select = row.querySelector("[data-component-product]");
        const mlInput = row.querySelector("[data-component-ml]");
        const ml = num(mlInput && mlInput.value);
        const option = select && select.selectedOptions ? select.selectedOptions[0] : null;
        const costPerMl = option ? num(option.dataset.cost) : 0;
        totalMl += ml;
        totalCost += ml * costPerMl;
      });
      const priceInput = document.getElementById("id_price");
      const price = num(priceInput && priceInput.value);
      const profit = price - totalCost;
      const margin = price > 0 ? (profit / price) * 100 : 0;
      const set = (key, value) => {
        const node = document.querySelector(`[data-preview="${key}"]`);
        if (node) node.textContent = value;
      };
      set("ml", `${totalMl.toFixed(3).replace(/\.?0+$/, "") || 0} ml`);
      set("cost", `${currency}${money(totalCost)}`);
      set("profit", `${currency}${money(profit)}`);
      set("margin", `${margin.toFixed(1)}%`);
    }

    container.addEventListener("input", (event) => {
      if (event.target.matches("[data-component-ml]")) updatePreview();
    });
    container.addEventListener("change", (event) => {
      if (event.target.matches("[data-component-product]")) updatePreview();
    });
    container.addEventListener("click", (event) => {
      const remove = event.target.closest("[data-remove-component]");
      if (!remove) return;
      const rows = container.querySelectorAll("[data-mixture-row]");
      if (rows.length <= 2) {
        const row = remove.closest("[data-mixture-row]");
        row.querySelectorAll("select").forEach((select) => (select.value = ""));
        row.querySelectorAll("input").forEach((input) => (input.value = ""));
        if (window.AppUI) window.AppUI.syncSelects(row);
      } else {
        remove.closest("[data-mixture-row]").remove();
      }
      updatePreview();
    });

    if (addButton) {
      addButton.addEventListener("click", () => {
        const node = template.content.firstElementChild.cloneNode(true);
        container.appendChild(node);
        if (window.AppUI) window.AppUI.enhanceSelects(node);
        const select = node.querySelector(".select-trigger") || node.querySelector("select");
        if (select) select.focus();
      });
    }

    const priceInput = document.getElementById("id_price");
    if (priceInput) priceInput.addEventListener("input", updatePreview);
    updatePreview();
  }

  function init() {
    initPurchaseLines();
    initPack();
    initMixtures();
  }

  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("app:page-loaded", init);
  document.addEventListener("app:drawer-loaded", init);
})();
