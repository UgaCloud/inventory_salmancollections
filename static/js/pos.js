/* Point of sale: persistent cart, search, bulk millilitres and checkout. */
(function () {
  "use strict";

  const STORAGE_KEY = "boutique-pos-cart-v1";
  const money = (value) => Number(value || 0).toFixed(2);
  const decimal = (value) => {
    const number = Number(value);
    return Number.isFinite(number) ? number : 0;
  };

  function loadCart() {
    try {
      const raw = window.localStorage.getItem(STORAGE_KEY);
      const parsed = raw ? JSON.parse(raw) : [];
      return Array.isArray(parsed) ? parsed : [];
    } catch (error) {
      return [];
    }
  }

  function saveCart(cart) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(cart));
    } catch (error) {
      /* storage may be unavailable */
    }
  }

  let cart = loadCart();
  let root = null;
  let cfg = window.APP_CONFIG || {};

  function linePrice(item) {
    if (item.type === "mixture") return decimal(item.price);
    const quantity = decimal(item.qty);
    if (Array.isArray(item.presets)) {
      const preset = item.presets.find((entry) => decimal(entry.ml) === quantity);
      if (preset) return decimal(preset.price);
    }
    return decimal(item.price) * quantity;
  }

  function totals() {
    const subtotal = cart.reduce((sum, item) => sum + linePrice(item), 0);
    const discountInput = document.getElementById("pos-discount");
    const discount = Math.min(Math.max(decimal(discountInput ? discountInput.value : 0), 0), subtotal);
    const total = Math.max(subtotal - discount, 0);
    return { subtotal, discount, total };
  }

  function unitLabel(item) {
    if (item.type === "mixture") return "mixture";
    if (item.unit === "ml") return "ml";
    if (item.unit === "pair") return "pairs";
    if (item.unit === "bottle") return "bottle(s)";
    return "pcs";
  }

  function renderCart() {
    const container = document.getElementById("pos-cart-items");
    if (!container) return;
    if (!cart.length) {
      container.innerHTML = `
        <div class="rounded-xl border border-dashed border-slate-300 px-4 py-8 text-center text-sm text-slate-500">
          <p class="font-medium text-slate-600">The cart is empty</p>
          <p class="mt-1 text-xs">Search or tap a product to start a sale.</p>
        </div>`;
    } else {
      container.innerHTML = cart
        .map((item, index) => {
          const presets = Array.isArray(item.presets) ? item.presets : [];
          const presetButtons = item.unit === "ml"
            ? presets
                .map(
                  (preset) => `<button type="button" class="badge ${decimal(preset.ml) === decimal(item.qty) ? "badge-indigo" : "badge-slate"}" data-preset-qty data-index="${index}" data-qty="${preset.ml}">${decimal(preset.ml)}ml · ${cfg.currency || ""}${money(preset.price)}</button>`
                )
                .join("")
            : "";
          const stepper = item.type === "mixture"
            ? `<span class="text-xs text-slate-500">Prepared mixture</span>`
            : `<div class="flex items-center gap-1">
                 <button type="button" class="btn btn-secondary btn-sm px-2" data-cart-dec data-index="${index}" aria-label="Decrease quantity">&minus;</button>
                 <input class="qty-input" data-cart-qty data-index="${index}" inputmode="decimal" value="${item.qty}" aria-label="Quantity for ${item.name}">
                 <button type="button" class="btn btn-secondary btn-sm px-2" data-cart-inc data-index="${index}" aria-label="Increase quantity">+</button>
                 <span class="text-xs text-slate-500">${unitLabel(item)}</span>
               </div>`;
          return `
            <div class="cart-row" data-cart-row="${index}">
              <div class="flex items-start justify-between gap-2">
                <div class="min-w-0">
                  <p class="truncate text-sm font-medium text-slate-800">${item.name}</p>
                  <p class="text-xs text-slate-500">${cfg.currency || ""}${money(item.price)} per ${item.type === "mixture" ? "mixture" : unitLabel(item).replace(/\(s\)/, "")}${item.stock !== undefined && item.unit === "ml" ? ` · ${item.stock}ml available` : ""}</p>
                </div>
                <button type="button" class="icon-btn" data-cart-remove data-index="${index}" aria-label="Remove ${item.name}">&times;</button>
              </div>
              <div class="mt-2 flex items-center justify-between gap-2">
                ${stepper}
                <span class="text-sm font-semibold tabular-nums">${cfg.currency || ""}${money(linePrice(item))}</span>
              </div>
              ${presetButtons ? `<div class="mt-2 flex flex-wrap gap-1">${presetButtons}</div>` : ""}
            </div>`;
        })
        .join("");
    }
    const subtotalNode = document.getElementById("pos-subtotal");
    const totalNode = document.getElementById("pos-total");
    const countNode = document.getElementById("pos-count");
    const totalsValue = totals();
    if (subtotalNode) subtotalNode.textContent = `${cfg.currency || ""}${money(totalsValue.subtotal)}`;
    if (totalNode) totalNode.textContent = `${cfg.currency || ""}${money(totalsValue.total)}`;
    if (countNode) countNode.textContent = String(cart.reduce((sum, item) => sum + (item.type === "mixture" ? 1 : 1), 0));
    updateChange();
    saveCart(cart);
  }

  function updateChange() {
    const amountNode = document.getElementById("pos-amount");
    const changeNode = document.getElementById("pos-change");
    const balanceNode = document.getElementById("pos-balance");
    const customerNode = document.getElementById("pos-customer");
    if (!amountNode) return;
    const { total } = totals();
    const amount = decimal(amountNode.value);
    const difference = amount - total;
    if (changeNode) changeNode.textContent = `${cfg.currency || ""}${money(Math.max(difference, 0))}`;
    if (balanceNode) {
      const hasCustomer = customerNode && customerNode.value;
      if (difference < 0 && hasCustomer) {
        balanceNode.textContent = `Balance due: ${cfg.currency || ""}${money(-difference)}`;
        balanceNode.classList.remove("hidden");
      } else if (difference < 0) {
        balanceNode.textContent = "Choose a customer to allow a partial payment, or collect the full amount.";
        balanceNode.classList.remove("hidden");
      } else {
        balanceNode.classList.add("hidden");
      }
    }
  }

  function addProduct(dataset) {
    const kind = dataset.kind || "standard";
    const presets = dataset.presets ? JSON.parse(dataset.presets) : [];
    const defaultQty = kind === "bulk_perfume" && presets.length ? presets[0].ml : 1;
    const existing = cart.find((item) => item.type === "product" && String(item.id) === String(dataset.id));
    if (existing && kind !== "bulk_perfume") {
      existing.qty = decimal(existing.qty) + 1;
    } else if (existing) {
      existing.qty = decimal(existing.qty) + decimal(defaultQty);
    } else {
      cart.push({
        type: "product",
        id: dataset.id,
        name: dataset.name,
        kind: kind,
        unit: dataset.unit || "pcs",
        price: dataset.price,
        stock: dataset.stock,
        sku: dataset.sku || "",
        presets: presets,
        qty: defaultQty,
      });
    }
    renderCart();
  }

  function addMixture(dataset) {
    if (cart.some((item) => item.type === "mixture" && String(item.id) === String(dataset.id))) {
      window.AppUI && window.AppUI.toast("That mixture is already in the cart.", "info");
      return;
    }
    cart.push({
      type: "mixture",
      id: dataset.id,
      name: dataset.name,
      price: dataset.price,
      qty: 1,
      unit: "mixture",
      stock: undefined,
    });
    renderCart();
  }

  async function loadCatalogue() {
    const search = document.getElementById("pos-search");
    const category = document.getElementById("pos-category");
    const container = document.getElementById("pos-catalogue");
    if (!container) return;
    const params = new URLSearchParams();
    if (search && search.value.trim()) params.set("q", search.value.trim());
    if (category && category.value) params.set("category", category.value);
    const response = await fetch(`${cfg.catalogueUrl}?${params.toString()}`, {
      headers: { "X-Requested-With": "XMLHttpRequest" },
    });
    if (!response.ok) return;
    container.innerHTML = await response.text();
  }

  function bind() {
    const catalogue = document.getElementById("pos-catalogue");
    if (catalogue) {
      catalogue.addEventListener("click", (event) => {
        const productButton = event.target.closest("[data-add-product]");
        if (productButton) {
          addProduct(productButton.dataset);
          return;
        }
      });
    }

    // Prepared mixtures sit outside the catalogue panel, so bind them at app level.
    if (root && root.dataset.mixturesBound !== "true") {
      root.dataset.mixturesBound = "true";
      root.addEventListener("click", (event) => {
        const mixtureButton = event.target.closest("[data-add-mixture]");
        if (!mixtureButton) return;
        addMixture(mixtureButton.dataset);
      });
    }

    const searchForm = document.getElementById("pos-search-form");
    if (searchForm) {
      searchForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const input = document.getElementById("pos-search");
        if (!input) return;
        loadCatalogue().then(() => {
          const query = input.value.trim();
          if (!query) return;
          const match = document.querySelector(`#pos-catalogue .pos-card[data-barcode="${CSS.escape(query)}"]`);
          if (match) {
            addProduct(match.dataset);
            input.value = "";
            loadCatalogue();
          }
        });
      });
    }

    let searchTimer = null;
    const search = document.getElementById("pos-search");
    if (search) {
      search.addEventListener("input", () => {
        clearTimeout(searchTimer);
        searchTimer = setTimeout(loadCatalogue, 300);
      });
    }

    const category = document.getElementById("pos-category");
    if (category) category.addEventListener("change", loadCatalogue);

    document.querySelectorAll("[data-pos-category]").forEach((button) => {
      button.addEventListener("click", () => {
        const select = document.getElementById("pos-category");
        if (select) {
          select.value = button.dataset.posCategory || "";
          select.dispatchEvent(new Event("change", { bubbles: true }));
        }
        document.querySelectorAll("[data-pos-category]").forEach((other) => {
          other.classList.toggle("badge-indigo", other === button);
          other.classList.toggle("badge-slate", other !== button);
        });
      });
    });

    const cartItems = document.getElementById("pos-cart-items");
    if (cartItems) {
      cartItems.addEventListener("click", (event) => {
        const remove = event.target.closest("[data-cart-remove]");
        if (remove) {
          cart.splice(Number(remove.dataset.index), 1);
          renderCart();
          return;
        }
        const increment = event.target.closest("[data-cart-inc]");
        if (increment) {
          const item = cart[Number(increment.dataset.index)];
          if (item) {
            item.qty = decimal(item.qty) + 1;
            renderCart();
          }
          return;
        }
        const decrement = event.target.closest("[data-cart-dec]");
        if (decrement) {
          const item = cart[Number(decrement.dataset.index)];
          if (item) {
            const next = decimal(item.qty) - 1;
            if (next <= 0) cart.splice(Number(decrement.dataset.index), 1);
            else item.qty = next;
            renderCart();
          }
          return;
        }
        const preset = event.target.closest("[data-preset-qty]");
        if (preset) {
          const item = cart[Number(preset.dataset.index)];
          if (item) {
            item.qty = preset.dataset.qty;
            renderCart();
          }
        }
      });

      cartItems.addEventListener("change", (event) => {
        const input = event.target.closest("[data-cart-qty]");
        if (!input) return;
        const item = cart[Number(input.dataset.index)];
        if (!item) return;
        const value = decimal(input.value);
        if (value <= 0) {
          cart.splice(Number(input.dataset.index), 1);
        } else {
          item.qty = value;
        }
        renderCart();
      });
    }

    ["pos-discount", "pos-amount", "pos-customer", "pos-method"].forEach((id) => {
      const node = document.getElementById(id);
      if (!node) return;
      node.addEventListener("change", updateChange);
      node.addEventListener("input", updateChange);
    });

    const checkoutButton = document.getElementById("pos-checkout");
    if (checkoutButton) checkoutButton.addEventListener("click", checkout);

    const clearButton = document.getElementById("pos-clear");
    if (clearButton) {
      clearButton.addEventListener("click", () => {
        if (cart.length && !window.confirm("Clear the cart?")) return;
        cart = [];
        renderCart();
      });
    }

    const newSaleButton = document.getElementById("pos-new-sale");
    if (newSaleButton) {
      newSaleButton.addEventListener("click", () => {
        const result = document.getElementById("pos-result");
        if (result) result.classList.add("hidden");
        renderCart();
      });
    }
  }

  async function checkout() {
    if (!cart.length) {
      window.AppUI && window.AppUI.toast("Add a product to the cart first.", "info");
      return;
    }
    const button = document.getElementById("pos-checkout");
    const amountInput = document.getElementById("pos-amount");
    const methodSelect = document.getElementById("pos-method");
    const customerSelect = document.getElementById("pos-customer");
    const discountInput = document.getElementById("pos-discount");
    const noteInput = document.getElementById("pos-note");
    if (!amountInput || !methodSelect) return;
    const amount = decimal(amountInput.value);
    if (amount <= 0) {
      window.AppUI && window.AppUI.toast("Enter the amount received.", "error");
      amountInput.focus();
      return;
    }
    const { discount } = totals();
    const payload = {
      items: cart.map((item) =>
        item.type === "mixture"
          ? { mixture_id: Number(item.id) }
          : { product_id: Number(item.id), quantity: item.qty }
      ),
      customer_id: customerSelect && customerSelect.value ? Number(customerSelect.value) : null,
      discount: String(discount),
      note: noteInput ? noteInput.value : "",
      payments: [{ method_id: Number(methodSelect.value), amount: String(amount) }],
    };
    if (button) {
      button.disabled = true;
      button.dataset.busy = "true";
    }
    try {
      const response = await fetch(cfg.checkoutUrl, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "X-CSRFToken": document.querySelector('meta[name="csrf-token"]').content,
          "X-Requested-With": "XMLHttpRequest",
        },
        credentials: "same-origin",
        body: JSON.stringify(payload),
      });
      const data = await response.json().catch(() => null);
      if (response.ok && data && data.ok) {
        cart = [];
        renderCart();
        const result = document.getElementById("pos-result");
        if (result) {
          result.classList.remove("hidden");
          result.querySelector("[data-result-message]").textContent = data.message;
          result.querySelector("[data-result-change]").textContent = `${cfg.currency || ""}${money(data.change)}`;
          const receiptLink = result.querySelector("[data-result-receipt]");
          if (receiptLink) receiptLink.href = data.receipt_url;
        }
        if (amountInput) amountInput.value = "";
        if (discountInput) discountInput.value = "";
        if (noteInput) noteInput.value = "";
        window.AppUI && window.AppUI.toast(data.message, "success");
        loadCatalogue();
      } else {
        window.AppUI && window.AppUI.toast((data && data.message) || "The sale could not be completed.", "error");
      }
    } catch (error) {
      window.AppUI && window.AppUI.toast("Network error while completing the sale.", "error");
    } finally {
      if (button) {
        button.disabled = false;
        button.dataset.busy = "false";
      }
    }
  }

  function addRequestedMixture() {
    const params = new URLSearchParams(window.location.search);
    const id = params.get("add_mixture");
    if (!id) return;
    const button = Array.from(document.querySelectorAll("[data-add-mixture]")).find(
      (node) => node.dataset.id === id
    );
    if (button) button.click();
    history.replaceState({}, "", window.location.pathname);
  }

  function init() {
    root = document.getElementById("pos-app");
    if (!root) return;
    cfg = window.APP_CONFIG || cfg;
    if (root.dataset.posReady !== "true") {
      root.dataset.posReady = "true";
      bind();
    }
    renderCart();
    addRequestedMixture();
  }

  document.addEventListener("DOMContentLoaded", init);
  document.addEventListener("app:page-loaded", init);
})();
