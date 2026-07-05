const API_BASE = '/api';
const WS_BASE = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
let tableSocket = null;

function getToken() {
    return localStorage.getItem('lads_token');
}

function getStoredUser() {
    const raw = localStorage.getItem('lads_user');
    return raw ? JSON.parse(raw) : null;
}

async function apiFetch(url, options = {}) {
    const token = getToken();
    const headers = { ...options.headers, 'Content-Type': 'application/json' };
    if (token) headers['Authorization'] = 'Bearer ' + token;
    return fetch(url, { ...options, headers });
}

function formatCurrency(value) {
    return 'R$ ' + parseFloat(value || 0).toFixed(2).replace('.', ',');
}

function statusLabel(status) {
    const labels = { vazia: 'Vazia', ocupada: 'Ocupada', finalizada: 'Finalizada' };
    return labels[status] || status;
}

// ====== AUTH ======
function checkAuth(callback) {
    const user = getStoredUser();
    if (!user || !getToken()) {
        window.location.href = '/login';
        return;
    }
    apiFetch(API_BASE + '/auth/me')
        .then(r => r.json())
        .then(async (data) => {
            if (data.detail) {
                localStorage.clear();
                window.location.href = '/login';
                return;
            }
            localStorage.setItem('lads_user', JSON.stringify(data));
            await loadAppSettings();
            if (!data.is_registered && data.role === 'garcom') {
                showNameModal();
            }
            if (callback) callback(data);
        })
        .catch(() => { window.location.href = '/login'; });
}

function logout() {
    localStorage.clear();
    window.location.href = '/login';
}

function showNameModal() {
    document.getElementById('name-modal').style.display = 'flex';
}

function registerName() {
    const name = document.getElementById('register-name-input').value.trim();
    if (!name) { return; }
    apiFetch(API_BASE + '/auth/register-name', {
        method: 'POST',
        body: JSON.stringify({ name })
    })
    .then(r => r.json())
    .then(data => {
        if (!data.error && !data.detail) {
            const user = getStoredUser();
            user.name = data.name;
            user.is_registered = true;
            localStorage.setItem('lads_user', JSON.stringify(user));
            document.getElementById('name-modal').style.display = 'none';
        }
    });
}

function highlightNav(page) {
    document.querySelectorAll('.nav-item').forEach(el => el.classList.remove('active'));
    const nav = document.querySelector(`.nav-item[data-page="${page}"]`);
    if (nav) nav.classList.add('active');
}

function updateTableCard(t) {
    const grid = document.getElementById('table-grid');
    if (!grid) return;
    let card = grid.querySelector(`.table-card[href="/mesa/${t.id}"]`);
    const totalText = t.has_open_order ? formatCurrency(Math.max(0, t.total - (t.partial_payment || 0))) : '';
    if (!card) {
        card = document.createElement('a');
        card.href = '/mesa/' + t.id;
        grid.appendChild(card);
    }
    card.className = 'table-card status-' + t.status;
    if (t.is_balcao) card.classList.add('is-balcao');
    card.innerHTML = `
        <span class="table-label">${t.label}</span>
        <span class="table-status-tag">${statusLabel(t.status)}</span>
        ${totalText ? `<span class="table-total-text">${totalText}</span>` : ''}
    `;
}

function connectTablesWebSocket() {
    if (tableSocket) return;
    const token = getToken();
    if (!token) return;

    tableSocket = new WebSocket(`${WS_BASE}/mesas?token=${token}`);

    tableSocket.onopen = () => {
        console.log('WebSocket connected');
    };

    tableSocket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'table_update' && msg.data) {
                updateTableCard(msg.data);
            }
        } catch (err) {
            console.error('WS message error', err);
        }
    };

    tableSocket.onclose = () => {
        tableSocket = null;
        setTimeout(connectTablesWebSocket, 3000);
    };

    tableSocket.onerror = (err) => {
        console.error('WebSocket error', err);
    };
}

function closeTablesWebSocket() {
    if (tableSocket) {
        tableSocket.close();
        tableSocket = null;
    }
}

// ====== INDEX: TABLE GRID ======
async function loadTables() {
    const grid = document.getElementById('table-grid');
    if (!grid) return;
    try {
        const res = await apiFetch(API_BASE + '/mesas');
        const tables = await res.json();
        grid.innerHTML = '';
        tables.forEach(t => {
            const card = document.createElement('a');
            card.href = '/mesa/' + t.id;
            card.className = 'table-card status-' + t.status;
            if (t.is_balcao) card.classList.add('is-balcao');
            card.innerHTML = `
                <span class="table-label">${t.label}</span>
                <span class="table-status-tag">${statusLabel(t.status)}</span>
                ${t.has_open_order ? `<span class="table-total-text">${formatCurrency(Math.max(0, t.total - (t.partial_payment || 0)))}</span>` : ''}
            `;
            grid.appendChild(card);
        });
    } catch (err) {
        grid.innerHTML = '<div class="error-msg">Erro ao carregar mesas</div>';
    }
}

// ====== TABLE DETAIL ======
let currentTableData = null;

async function loadTableDetail(user) {
    if (typeof TABLE_ID === 'undefined') return;
    try {
        const res = await apiFetch(API_BASE + '/mesa/' + TABLE_ID);
        const data = await res.json();
        if (data.error) {
            document.getElementById('table-status').textContent = data.error;
            return;
        }
        currentTableData = data;

        document.getElementById('table-title').textContent = data.label;
        let statusText = 'Status: ' + statusLabel(data.status);
        if (data.waiter_name) statusText += ' | Garçom: ' + data.waiter_name;
        document.getElementById('table-status').textContent = statusText;

        if (data.customer_name) {
            document.getElementById('customer-name-input').value = data.customer_name;
        }

        document.getElementById('total-value').textContent = formatCurrency(data.total);
        const partialInfo = document.getElementById('partial-info');
        if (data.partial_payment > 0 || data.partial_service_charge > 0) {
            partialInfo.style.display = 'block';
            const svcPart = data.partial_service_charge > 0 ? ` (+ ${formatCurrency(data.partial_service_charge)} serviço)` : '';
            document.getElementById('partial-value').textContent = formatCurrency(data.partial_payment) + svcPart;
            const paidCount = countPaidItems();
            const totalItems = countTotalItems();
            document.getElementById('partial-detail').textContent =
                paidCount + ' de ' + totalItems + ' itens pagos';
        } else {
            partialInfo.style.display = 'none';
        }

        const openActions = document.getElementById('open-actions');
        const activeActions = document.getElementById('active-actions');
        const customerSection = document.getElementById('customer-section');

        if (data.status === 'vazia') {
            openActions.style.display = 'block';
            activeActions.style.display = 'none';
            customerSection.style.display = 'block';
        } else if (data.status === 'ocupada') {
            openActions.style.display = 'none';
            activeActions.style.display = 'block';
            customerSection.style.display = 'none';
            renderPedidos(data);
        } else {
            openActions.style.display = 'none';
            activeActions.style.display = 'block';
            customerSection.style.display = 'none';
            document.getElementById('pedidos-section').innerHTML = renderPedidosFinalizados(data);
            document.getElementById('close-actions').style.display = 'none';
            document.querySelector('.btn-pedido-full').style.display = 'none';
        }
    } catch (err) {
        document.getElementById('table-status').textContent = 'Erro ao carregar dados';
    }
}

function renderPedidos(data) {
    const container = document.getElementById('pedidos-section');

    if (!data.pedidos || data.pedidos.length === 0) {
        container.innerHTML = '<p class="empty-msg">Nenhum pedido realizado. Clique em "Adicionar Pedido".</p>';
        return;
    }

    container.innerHTML = data.pedidos.map(pedido => {
        const itemsHtml = pedido.items.map(item => {
            const paidQty = getPaidQty(item.id);
            const fullyPaid = paidQty >= item.quantity;
            const paidClass = fullyPaid ? 'partial-paid' : (paidQty > 0 ? 'partial-paid' : '');
            let paidBadge = '';
            if (fullyPaid) {
                paidBadge = ' <span style="color:var(--green);font-size:10px;">(PAGO)</span>';
            } else if (paidQty > 0) {
                paidBadge = ' <span style="color:var(--blue);font-size:10px;">(' + paidQty + '/' + item.quantity + ' pago)</span>';
            }
            return `
            <div class="pedido-item ${paidClass}">
                <div class="item-info">
                    <div class="item-name">${item.product_name}${paidBadge}</div>
                    <div class="item-meta">${formatCurrency(item.unit_price)} cada | ${item.category}</div>
                </div>
                <div class="item-actions">
                    <button class="btn-remove" onclick="removeItemFromRound(${item.product_id}, ${pedido.id})">-</button>
                    <span class="qty">${item.quantity}</span>
                    <button class="btn-add" onclick="addItemToRound(${item.product_id}, ${pedido.id})">+</button>
                </div>
            </div>
        `}).join('');

        return `
            <div class="pedido-group">
                <div class="pedido-header">
                    <span>Pedido #${pedido.round_number}</span>
                    <span class="pedido-time">${pedido.created_at}</span>
                </div>
                ${itemsHtml}
            </div>
        `;
    }).join('');
}

function renderPedidosFinalizados(data) {
    if (!data.pedidos || data.pedidos.length === 0) {
        return '<p class="empty-msg">Nenhum pedido registrado</p>';
    }
    return data.pedidos.map(pedido => {
        const itemsHtml = pedido.items.map(item => `
            <div class="pedido-item" style="opacity:0.7;">
                <div class="item-info">
                    <div class="item-name">${item.product_name}</div>
                    <div class="item-meta">${item.quantity}x ${formatCurrency(item.unit_price)}</div>
                </div>
                <div>${formatCurrency(item.quantity * item.unit_price)}</div>
            </div>
        `).join('');
        return `
            <div class="pedido-group">
                <div class="pedido-header">
                    <span>Pedido #${pedido.round_number}</span>
                    <span class="pedido-time">${pedido.created_at}</span>
                </div>
                ${itemsHtml}
            </div>
        `;
    }).join('');
}

// ====== ADD PEDIDO MODAL ======
let pedidoQuantities = {};
let pedidoInitialStock = {};
let pedidoProductsData = [];
let pedidoSelectionHtml = '';

function showAddPedidoModal() {
    apiFetch(API_BASE + '/produtos')
        .then(r => r.json())
        .then(products => {
            pedidoQuantities = {};
            pedidoInitialStock = {};
            pedidoProductsData = products;
            products.forEach(p => {
                pedidoQuantities[p.id] = 0;
                pedidoInitialStock[p.id] = p.stock;
            });

            pedidoSelectionHtml = buildPedidoSelectionView(products);
            document.getElementById('pedido-modal-content').innerHTML = pedidoSelectionHtml;
            document.getElementById('add-pedido-modal').style.display = 'flex';
        });
}

function buildPedidoSelectionView(products) {
    const listHtml = products.map(p => {
        const hasDiscount = p.discounted_price !== undefined && p.discounted_price < p.price;
        const priceHtml = hasDiscount
            ? `<div class="prod-price"><span class="prod-original-price">${formatCurrency(p.price)}</span> ${formatCurrency(p.discounted_price)} <span class="promo-badge">${p.active_promotion || 'Promoção'}</span></div>`
            : `<div class="prod-price">${formatCurrency(p.price)}</div>`;
        return `
        <div class="pedido-product-row">
            <div class="prod-info">
                <div class="prod-name">${p.name}</div>
                <div class="prod-stock" id="pstock-${p.id}" data-cat="${p.category}">
                    Estoque: <strong>${p.stock}</strong> | ${p.category}
                </div>
                ${priceHtml}
            </div>
            <div class="qty-control">
                <button class="btn-sm btn-sm-remove" onclick="changePedidoQty(${p.id}, -1)">-</button>
                <input type="number" class="qty-input" id="pqty-${p.id}" value="0" min="0" max="${p.stock}" readonly>
                <button class="btn-sm btn-sm-add" onclick="changePedidoQty(${p.id}, 1)">+</button>
            </div>
        </div>
    `;
    }).join('');

    return `
        <h3>Novo Pedido</h3>
        <div class="pedido-product-list">${listHtml}</div>
        <div style="display:flex;gap:8px;margin-top:12px;">
            <button onclick="reviewPedido()" class="btn-primary-full" style="flex:1;">Revisar Pedido</button>
            <button onclick="closeAddPedidoModal()" class="btn-secondary-full" style="flex:1;">Cancelar</button>
        </div>
        <p id="pedido-error" class="error-msg" style="display:none;"></p>
    `;
}

function changePedidoQty(productId, delta) {
    const maxStock = pedidoInitialStock[productId] || 0;
    let qty = (pedidoQuantities[productId] || 0) + delta;
    if (qty < 0) qty = 0;
    if (qty > maxStock) qty = maxStock;
    pedidoQuantities[productId] = qty;

    const remaining = maxStock - qty;
    const input = document.getElementById('pqty-' + productId);
    const stockEl = document.getElementById('pstock-' + productId);
    if (input) input.value = qty;
    if (stockEl) {
        const cat = stockEl.dataset.cat || '';
        stockEl.innerHTML = 'Estoque: <strong>' + remaining + '</strong> | ' + cat;
    }
}

function closeAddPedidoModal() {
    document.getElementById('add-pedido-modal').style.display = 'none';
}

function reviewPedido() {
    const selected = [];
    let total = 0;
    for (const [pid, qty] of Object.entries(pedidoQuantities)) {
        if (qty > 0) {
            const product = pedidoProductsData.find(p => p.id === parseInt(pid));
            if (product) {
                const unitPrice = product.discounted_price !== undefined ? product.discounted_price : product.price;
                const subtotal = qty * unitPrice;
                total += subtotal;
                selected.push({ ...product, qty, unitPrice, subtotal });
            }
        }
    }

    if (selected.length === 0) {
        document.getElementById('pedido-error').textContent = 'Selecione ao menos 1 item';
        document.getElementById('pedido-error').style.display = 'block';
        return;
    }

    const itemsHtml = selected.map(s => {
        const hasDiscount = s.unitPrice < s.price;
        const unitPriceHtml = hasDiscount
            ? `<span class="review-original-price">${formatCurrency(s.price)}</span> ${formatCurrency(s.unitPrice)}`
            : `${formatCurrency(s.unitPrice)}`;
        return `
        <div class="review-item">
            <div class="review-info">
                <span class="review-qty">${s.qty}x</span>
                <span class="review-name">${s.name}</span>
            </div>
            <div class="review-meta">
                <span>${unitPriceHtml} cada</span>
                <span class="review-subtotal">${formatCurrency(s.subtotal)}</span>
            </div>
        </div>
    `;
    }).join('');

    const reviewHtml = `
        <h3>Revisar Pedido</h3>
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:14px;">
            Confira os itens com o cliente antes de enviar.
        </p>
        <div class="review-list">${itemsHtml}</div>
        <div class="review-total">
            <span>Total do Pedido</span>
            <span>${formatCurrency(total)}</span>
        </div>
        <div style="display:flex;gap:8px;margin-top:14px;">
            <button onclick="confirmPedido()" class="btn-primary-full" style="flex:1;">Confirmar e Enviar</button>
            <button onclick="backToPedidoSelection()" class="btn-secondary-full" style="flex:1;">Voltar</button>
        </div>
        <p id="pedido-error" class="error-msg" style="display:none;"></p>
    `;

    document.getElementById('pedido-modal-content').innerHTML = reviewHtml;
}

function backToPedidoSelection() {
    document.getElementById('pedido-modal-content').innerHTML = pedidoSelectionHtml;
    for (const [pid, qty] of Object.entries(pedidoQuantities)) {
        const input = document.getElementById('pqty-' + pid);
        if (input) input.value = qty;
        const stockEl = document.getElementById('pstock-' + pid);
        if (stockEl) {
            const maxStock = pedidoInitialStock[pid] || 0;
            const remaining = maxStock - qty;
            const cat = stockEl.dataset.cat || '';
            stockEl.innerHTML = 'Estoque: <strong>' + remaining + '</strong> | ' + cat;
        }
    }
}

async function confirmPedido() {
    const items = [];
    for (const [pid, qty] of Object.entries(pedidoQuantities)) {
        if (qty > 0) {
            items.push({ product_id: parseInt(pid), quantity: qty });
        }
    }

    try {
        const res = await apiFetch(API_BASE + '/comanda/pedido', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, items })
        });
        const data = await res.json();
        if (data.error) {
            document.getElementById('pedido-error').textContent = data.error;
            document.getElementById('pedido-error').style.display = 'block';
            return;
        }
        closeAddPedidoModal();
        loadTableDetail();
    } catch (err) {
        document.getElementById('pedido-error').textContent = 'Erro ao criar pedido';
        document.getElementById('pedido-error').style.display = 'block';
    }
}

// ====== INDIVIDUAL ITEM ADJUSTMENT WITHIN A ROUND ======
async function addItemToRound(productId, roundId) {
    try {
        const res = await apiFetch(API_BASE + '/comanda/item', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, product_id: productId, quantity: 1, order_round_id: roundId })
        });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        loadTableDetail();
    } catch (err) { alert('Erro ao adicionar item'); }
}

async function removeItemFromRound(productId, roundId) {
    try {
        const res = await apiFetch(API_BASE + '/comanda/item', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, product_id: productId, quantity: -1, order_round_id: roundId })
        });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        loadTableDetail();
    } catch (err) { alert('Erro ao remover item'); }
}

// ====== PARTIAL PAYMENT ======
function paidItemsKey() {
    return 'lads_paid_items_' + (typeof TABLE_ID !== 'undefined' ? TABLE_ID : '0');
}

function loadPaidQtyMap() {
    try { return JSON.parse(localStorage.getItem(paidItemsKey()) || '{}'); } catch { return {}; }
}

function savePaidQtyMap(state) { localStorage.setItem(paidItemsKey(), JSON.stringify(state)); }

function getPaidQty(orderItemId) {
    return loadPaidQtyMap()[String(orderItemId)] || 0;
}

function addPaidQty(orderItemId, qty) {
    const state = loadPaidQtyMap();
    const current = state[String(orderItemId)] || 0;
    state[String(orderItemId)] = current + qty;
    savePaidQtyMap(state);
}

function countPaidItems() {
    if (!currentTableData || !currentTableData.pedidos) return 0;
    const state = loadPaidQtyMap();
    let count = 0;
    currentTableData.pedidos.forEach(p => p.items.forEach(i => {
        if ((state[String(i.id)] || 0) >= i.quantity) count++;
    }));
    return count;
}

function countTotalItems() {
    if (!currentTableData || !currentTableData.pedidos) return 0;
    let count = 0;
    currentTableData.pedidos.forEach(p => count += p.items.length);
    return count;
}

function showPartialPaymentModal() {
    if (!currentTableData || !currentTableData.pedidos) return;

    const state = loadPaidQtyMap();
    let rowsHtml = '';
    let hasUnpaid = false;

    currentTableData.pedidos.forEach(pedido => {
        pedido.items.forEach(item => {
            const paidQty = state[String(item.id)] || 0;
            const unpaidQty = item.quantity - paidQty;
            if (unpaidQty > 0) hasUnpaid = true;

            rowsHtml += `
                <div class="partial-item-row">
                    <div class="partial-info">
                        <div class="partial-name">${item.product_name}</div>
                        <div class="partial-meta">
                            Total: ${item.quantity}x | Pago: ${paidQty}x | Resta: <strong>${unpaidQty}</strong>x
                            &nbsp;|&nbsp; ${formatCurrency(item.unit_price)} cada
                        </div>
                    </div>
                    ${unpaidQty > 0 ? `
                    <div class="qty-control">
                        <button class="btn-sm btn-sm-remove" onclick="adjustPaidQty(${item.id}, -1, ${unpaidQty}, ${item.unit_price})">-</button>
                        <span class="qty-input" id="pp-qty-${item.id}" style="display:inline-flex;align-items:center;justify-content:center;width:48px;padding:8px 0;text-align:center;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:15px;font-weight:700;" data-unit-price="${item.unit_price}">0</span>
                        <button class="btn-sm btn-sm-add" onclick="adjustPaidQty(${item.id}, 1, ${unpaidQty}, ${item.unit_price})">+</button>
                    </div>
                    ` : `
                    <span style="color:var(--green);font-size:12px;font-weight:600;">Pago ✓</span>
                    `}
                </div>
            `;
        });
    });

    if (!hasUnpaid) {
        rowsHtml = '<p class="empty-msg">Todos os itens já foram pagos integralmente.</p>';
    }

    document.getElementById('partial-payment-items').innerHTML = rowsHtml;
    document.getElementById('partial-selected-total').textContent = formatCurrency(0);
    document.getElementById('partial-payment-modal').style.display = 'flex';
}

function adjustPaidQty(itemId, delta, maxQty, unitPrice) {
    const el = document.getElementById('pp-qty-' + itemId);
    if (!el) return;
    let qty = parseInt(el.textContent || '0') + delta;
    if (qty < 0) qty = 0;
    if (qty > maxQty) qty = maxQty;
    el.textContent = qty;
    updatePartialTotal();
}

function updatePartialTotal() {
    let subtotal = 0;
    document.querySelectorAll('#partial-payment-items .qty-input').forEach(el => {
        const qty = parseInt(el.textContent || '0');
        const unitPrice = parseFloat(el.dataset.unitPrice || 0);
        subtotal += qty * unitPrice;
    });
    const apply = document.getElementById('partial-service-charge')?.checked || false;
    const serviceChargePct = getSettingFloat('service_charge_pct', 10);
    const total = apply ? subtotal * (1 + serviceChargePct / 100) : subtotal;
    document.getElementById('partial-selected-total').textContent = formatCurrency(total);
}

function closePartialPaymentModal() {
    document.getElementById('partial-payment-modal').style.display = 'none';
}

async function submitPartialPayment() {
    let subtotal = 0;
    const itemsToPay = [];
    document.querySelectorAll('#partial-payment-items .qty-input').forEach(el => {
        const qty = parseInt(el.textContent || '0');
        if (qty > 0) {
            const itemId = parseInt(el.id.replace('pp-qty-', ''));
            const unitPrice = parseFloat(el.dataset.unitPrice || 0);
            subtotal += qty * unitPrice;
            itemsToPay.push({ itemId, qty });
        }
    });

    if (subtotal <= 0) {
        document.getElementById('partial-payment-error').textContent = 'Ajuste a quantidade de ao menos um item';
        document.getElementById('partial-payment-error').style.display = 'block';
        return;
    }

    const applyService = document.getElementById('partial-service-charge')?.checked || false;
    const serviceChargePct = getSettingFloat('service_charge_pct', 10);
    const total = applyService ? subtotal * (1 + serviceChargePct / 100) : subtotal;
    const pMethod = document.getElementById('partial-payment-method')?.value || 'dinheiro';

    try {
        const res = await apiFetch(API_BASE + '/comanda/pagamento-parcial', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, amount: total, payment_method: pMethod, apply_service_charge: applyService })
        });
        const data = await res.json();
        if (data.error) {
            document.getElementById('partial-payment-error').textContent = data.error;
            document.getElementById('partial-payment-error').style.display = 'block';
            return;
        }
        itemsToPay.forEach(({ itemId, qty }) => addPaidQty(itemId, qty));
        closePartialPaymentModal();
        loadTableDetail();
    } catch (err) {
        document.getElementById('partial-payment-error').textContent = 'Erro ao registrar pagamento';
        document.getElementById('partial-payment-error').style.display = 'block';
    }
}

// ====== OPEN / CLOSE ======
async function setCustomerName() {
    const name = document.getElementById('customer-name-input').value.trim();
    alert(name ? 'Cliente: ' + name : 'Nome opcional');
}

async function openOrder() {
    const customerName = document.getElementById('customer-name-input').value.trim() || null;
    try {
        const res = await apiFetch(API_BASE + '/comanda/abrir', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, customer_name: customerName })
        });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        loadTableDetail();
    } catch (err) { alert('Erro ao abrir comanda'); }
}

async function showCloseModal() {
    if (!currentTableData) return;

    const total = currentTableData.total || 0;
    const paid = currentTableData.partial_payment || 0;
    const paidService = currentTableData.partial_service_charge || 0;
    const serviceChargePct = getSettingFloat('service_charge_pct', 10);
    const service = 0;
    const serviceLabel = serviceChargePct + '% Serviço';
    const remainingProduct = Math.max(0, total - paid);
    const remainingService = Math.max(0, service - paidService);
    const final = remainingProduct + remainingService;

    document.getElementById('close-summary').innerHTML = `
        <div style="display:flex;justify-content:space-between;padding:6px 0;font-size:14px;color:var(--text-muted);">
            <span>Total Produtos</span><span>${formatCurrency(total)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:6px 0;font-size:14px;color:var(--text-muted);">
            <span>${serviceLabel}</span><span id="close-service-display">${formatCurrency(service)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:6px 0;font-size:14px;color:var(--text-muted);">
            <span>Já Pago (produtos)</span><span>- ${formatCurrency(paid)}</span>
        </div>
        ${paidService > 0 ? `<div style="display:flex;justify-content:space-between;padding:6px 0;font-size:14px;color:var(--text-muted);"><span>Já Pago (serviço)</span><span>- ${formatCurrency(paidService)}</span></div>` : ''}
        <div style="display:flex;justify-content:space-between;padding:10px 0;font-size:18px;font-weight:800;border-top:1px solid var(--border-accent);margin-top:4px;">
            <span>Total Final</span><span id="close-final-display" style="color:var(--accent);">${formatCurrency(final)}</span>
        </div>
    `;

    document.getElementById('apply-service-charge').checked = false;
    document.getElementById('close-payment-method').value = 'dinheiro';
    document.getElementById('close-modal').style.display = 'flex';
}

function updateCloseTotal() {
    const total = currentTableData.total || 0;
    const paid = currentTableData.partial_payment || 0;
    const paidService = currentTableData.partial_service_charge || 0;
    const apply = document.getElementById('apply-service-charge').checked;
    const serviceChargePct = getSettingFloat('service_charge_pct', 10);
    const service = apply ? total * (serviceChargePct / 100) : 0;
    const remainingProduct = Math.max(0, total - paid);
    const remainingService = Math.max(0, service - paidService);
    const final = remainingProduct + remainingService;

    document.getElementById('close-service-display').textContent = formatCurrency(service);
    document.getElementById('close-final-display').textContent = formatCurrency(final);
}

function closeCloseModal() {
    document.getElementById('close-modal').style.display = 'none';
}

async function confirmClose() {
    const applyServiceCharge = document.getElementById('apply-service-charge').checked;
    const paymentMethod = document.getElementById('close-payment-method').value;

    try {
        const res = await apiFetch(API_BASE + '/comanda/fechar', {
            method: 'POST',
            body: JSON.stringify({
                table_id: TABLE_ID,
                apply_service_charge: applyServiceCharge,
                payment_method: paymentMethod
            })
        });
        const data = await res.json();
        if (data.error) {
            document.getElementById('close-error').textContent = data.error;
            document.getElementById('close-error').style.display = 'block';
            return;
        }
        let alertMsg = 'Mesa fechada!\nTotal: ' + formatCurrency(data.total);
        if (data.service_charge_amount > 0) alertMsg += '\n+' + data.service_charge_pct + '% serviço: ' + formatCurrency(data.service_charge_amount);
        if (data.partial_payment > 0) alertMsg += '\n- Pago produtos: ' + formatCurrency(data.partial_payment);
        if (data.partial_service_charge > 0) alertMsg += '\n- Pago serviço: ' + formatCurrency(data.partial_service_charge);
        alertMsg += '\nFinal: ' + formatCurrency(data.final_total);
        alertMsg += '\nForma: ' + (data.payment_method || 'N/A');
        alert(alertMsg);
        localStorage.removeItem(paidItemsKey());
        window.location.href = '/';
    } catch (err) {
        document.getElementById('close-error').textContent = 'Erro ao fechar comanda';
        document.getElementById('close-error').style.display = 'block';
    }
}

// ====== STOCK ======
async function loadStock() {
    const container = document.getElementById('stock-items');
    if (!container) return;
    const category = document.getElementById('filter-category')?.value || '';
    const status = document.getElementById('filter-status')?.value || '';
    const sort = document.getElementById('sort-by')?.value || 'name';
    try {
        const params = new URLSearchParams();
        if (category) params.set('category', category);
        if (status) params.set('status', status);
        params.set('sort', sort);
        const res = await apiFetch(API_BASE + '/estoque?' + params.toString());
        const data = await res.json();
        document.getElementById('count-em_falta').textContent = data.counts.em_falta;
        document.getElementById('count-em_risco').textContent = data.counts.em_risco;
        document.getElementById('count-em_conformidade').textContent = data.counts.em_conformidade;
        const catSelect = document.getElementById('filter-category');
        if (catSelect && catSelect.options.length <= 1) {
            data.categories.forEach(c => {
                const opt = document.createElement('option');
                opt.value = c;
                opt.textContent = c;
                catSelect.appendChild(opt);
            });
        }
        container.innerHTML = data.items.map(p => `
            <div class="stock-item-row ${p.active ? '' : 'inactive'}" onclick="openProductDetail(${p.id})">
                <div>
                    <div class="stock-name">${p.code ? '[' + p.code + '] ' : ''}${p.name}</div>
                    <div class="stock-meta">${p.category} | Mín: ${p.min_stock} | ${p.pct_of_min}% | Custo: ${formatCurrency(p.cost)} | Venda: ${formatCurrency(p.price)}</div>
                </div>
                <div style="text-align:right;">
                    <span style="font-size:18px;font-weight:700;">${p.stock}</span>
                    <br>
                    <span class="stock-badge badge-${p.status}">${{em_falta:'Em Falta',em_risco:'Em Risco',em_conformidade:'OK'}[p.status]}</span>
                </div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = '<div class="error-msg">Erro ao carregar estoque</div>';
    }
}

let batchProducts = [];
function showBatchLoad() {
    apiFetch(API_BASE + '/produtos?active_only=true')
        .then(r => r.json())
        .then(products => {
            batchProducts = products.map(p => ({ ...p, loadQty: 0 }));
            const container = document.getElementById('batch-items');
            container.innerHTML = batchProducts.map((p, i) => `
                <div style="display:flex;align-items:center;justify-content:space-between;padding:8px 0;border-bottom:1px solid #222;">
                    <span style="font-size:13px;">${p.name} <span style="color:#888;">(atual: ${p.stock})</span></span>
                    <input type="number" value="0" min="0" style="width:70px;padding:6px;background:#222;color:#fff;border:1px solid #444;border-radius:6px;text-align:center;"
                           onchange="batchProducts[${i}].loadQty = parseInt(this.value) || 0">
                </div>
            `).join('');
            document.getElementById('batch-modal').style.display = 'flex';
        });
}

function closeBatchLoad() { document.getElementById('batch-modal').style.display = 'none'; }

async function submitBatchLoad() {
    const items = batchProducts.filter(p => p.loadQty > 0).map(p => ({ product_id: p.id, quantity: p.loadQty }));
    if (items.length === 0) { return; }
    try {
        const res = await apiFetch(API_BASE + '/estoque/carregamento', { method: 'POST', body: JSON.stringify({ items }) });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        document.getElementById('batch-modal').style.display = 'none';
        loadStock();
    } catch (err) { alert('Erro ao enviar carregamento'); }
}

// ====== PRODUCT DETAIL / EDIT ======
let currentProductId = null;
let productSuppliersCache = [];

function calculateProductPrice() {
    const cost = parseFloat(document.getElementById('product-cost')?.value) || 0;
    const margin = parseFloat(document.getElementById('product-margin')?.value) || 0;
    if (cost > 0 && margin >= 0) {
        const price = cost * (1 + margin / 100);
        document.getElementById('product-price').value = price.toFixed(2);
    }
}

function calculateProductMargin() {
    const cost = parseFloat(document.getElementById('product-cost')?.value) || 0;
    const price = parseFloat(document.getElementById('product-price')?.value) || 0;
    if (cost > 0 && price > 0) {
        const margin = ((price - cost) / cost) * 100;
        document.getElementById('product-margin').value = margin.toFixed(2);
    }
}

async function loadProductSuppliers() {
    try {
        const res = await apiFetch(API_BASE + '/fornecedores?active_only=true');
        productSuppliersCache = await res.json();
    } catch (err) {
        productSuppliersCache = [];
    }
}

function renderProductSuppliers(selectedIds = []) {
    const container = document.getElementById('product-suppliers');
    if (productSuppliersCache.length === 0) {
        container.innerHTML = '<span class="text-muted">Nenhum fornecedor ativo cadastrado</span>';
        return;
    }
    container.innerHTML = productSuppliersCache.map(s => `
        <label class="checkbox-row">
            <input type="checkbox" value="${s.id}" class="product-supplier-check" ${selectedIds.includes(s.id) ? 'checked' : ''}>
            <span>${s.name}</span>
        </label>
    `).join('');
}

async function openProductDetail(productId) {
    currentProductId = productId;
    await loadProductSuppliers();
    try {
        const res = await apiFetch(API_BASE + '/estoque/' + productId);
        const product = await res.json();
        if (product.error) { alert(product.error); return; }

        document.getElementById('product-modal-title').textContent = product.name;
        document.getElementById('product-id').value = product.id;
        document.getElementById('product-code').value = product.code || '';
        document.getElementById('product-name').value = product.name;
        document.getElementById('product-category').value = product.category;
        document.getElementById('product-cost').value = product.cost ? product.cost.toFixed(2) : '0.00';
        document.getElementById('product-margin').value = product.margin_pct ? product.margin_pct.toFixed(2) : '0.00';
        document.getElementById('product-price').value = product.price ? product.price.toFixed(2) : '0.00';
        document.getElementById('product-stock').value = product.stock;
        document.getElementById('product-min-stock').value = product.min_stock;

        const activeCheckbox = document.getElementById('product-active');
        activeCheckbox.checked = product.active;
        const activeLabel = document.getElementById('product-active-label');
        activeLabel.textContent = product.active ? 'Produto ativo' : 'Produto inativo';
        activeCheckbox.onchange = () => {
            activeLabel.textContent = activeCheckbox.checked ? 'Produto ativo' : 'Produto inativo';
        };

        renderProductSuppliers((product.suppliers || []).map(s => s.id));

        switchProductTab('info');
        document.getElementById('product-error').style.display = 'none';
        document.getElementById('product-modal').style.display = 'flex';
        loadProductHistory(productId);
    } catch (err) { alert('Erro ao abrir produto'); }
}

async function showProductModal() {
    currentProductId = null;
    await loadProductSuppliers();
    document.getElementById('product-modal-title').textContent = 'Novo Produto';
    document.getElementById('product-id').value = '';
    document.getElementById('product-code').value = '';
    document.getElementById('product-name').value = '';
    document.getElementById('product-category').value = '';
    document.getElementById('product-cost').value = '';
    document.getElementById('product-margin').value = '';
    document.getElementById('product-price').value = '';
    document.getElementById('product-stock').value = '';
    document.getElementById('product-min-stock').value = '10';

    const activeCheckbox = document.getElementById('product-active');
    activeCheckbox.checked = true;
    const activeLabel = document.getElementById('product-active-label');
    activeLabel.textContent = 'Produto ativo';
    activeCheckbox.onchange = () => {
        activeLabel.textContent = activeCheckbox.checked ? 'Produto ativo' : 'Produto inativo';
    };

    renderProductSuppliers([]);
    switchProductTab('info');
    document.getElementById('entries-list').innerHTML = '';
    document.getElementById('exits-list').innerHTML = '';
    document.getElementById('product-error').style.display = 'none';
    document.getElementById('product-modal').style.display = 'flex';
}

function closeProductModal() {
    document.getElementById('product-modal').style.display = 'none';
    currentProductId = null;
}

async function submitProduct() {
    const id = document.getElementById('product-id').value;
    const payload = {
        code: document.getElementById('product-code').value.trim() || null,
        name: document.getElementById('product-name').value.trim(),
        category: document.getElementById('product-category').value.trim(),
        cost: parseFloat(document.getElementById('product-cost').value) || 0,
        margin_pct: parseFloat(document.getElementById('product-margin').value) || 0,
        price: parseFloat(document.getElementById('product-price').value) || 0,
        stock: parseInt(document.getElementById('product-stock').value) || 0,
        min_stock: parseInt(document.getElementById('product-min-stock').value) || 0,
        active: document.getElementById('product-active').checked,
        supplier_ids: Array.from(document.querySelectorAll('.product-supplier-check:checked')).map(cb => parseInt(cb.value)),
    };

    if (!payload.name || !payload.category) {
        document.getElementById('product-error').textContent = 'Nome e categoria são obrigatórios';
        document.getElementById('product-error').style.display = 'block';
        return;
    }

    const url = API_BASE + '/estoque' + (id ? '/' + id : '');
    const method = id ? 'PUT' : 'POST';

    try {
        const res = await apiFetch(url, { method, body: JSON.stringify(payload) });
        const data = await res.json();
        if (data.error) {
            document.getElementById('product-error').textContent = data.error;
            document.getElementById('product-error').style.display = 'block';
            return;
        }
        closeProductModal();
        loadStock();
    } catch (err) {
        document.getElementById('product-error').textContent = 'Erro ao salvar produto';
        document.getElementById('product-error').style.display = 'block';
    }
}

async function submitProductMovement() {
    if (!currentProductId) return;
    const type = document.getElementById('movement-type').value;
    const quantity = parseInt(document.getElementById('movement-qty').value) || 0;
    const note = document.getElementById('movement-note').value.trim();

    if (quantity <= 0) {
        alert('Quantidade deve ser maior que zero');
        return;
    }

    try {
        const res = await apiFetch(API_BASE + '/estoque/' + currentProductId + '/movimentacao', {
            method: 'POST',
            body: JSON.stringify({ type, quantity, note })
        });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        document.getElementById('product-stock').value = data.product.stock;
        document.getElementById('movement-qty').value = '';
        document.getElementById('movement-note').value = '';
        loadProductHistory(currentProductId);
        loadStock();
    } catch (err) { alert('Erro ao registrar movimentação'); }
}

async function loadProductHistory(productId) {
    try {
        const res = await apiFetch(API_BASE + '/estoque/' + productId + '/historico');
        const data = await res.json();
        if (data.error) return;

        const entries = data.items.filter(h => h.type === 'entrada');
        const exits = data.items.filter(h => h.type === 'saida');

        const renderHistory = (items) => items.map(h => {
            const ref = h.table_id ? `Mesa ${h.table_id}` : (h.note || 'Movimentação manual');
            return `
            <div class="history-item">
                <div class="history-main">
                    <span class="history-qty ${h.type}">${h.type === 'saida' ? '-' : '+'}${h.quantity}</span>
                    <div style="min-width:0;">
                        <div class="history-note">${ref}</div>
                        ${h.note && h.table_id ? `<div class="history-subnote">${h.note}</div>` : ''}
                    </div>
                </div>
                <span class="history-date">${h.created_at ? new Date(h.created_at).toLocaleString('pt-BR') : ''}</span>
            </div>
        `}).join('');

        document.getElementById('entries-list').innerHTML = entries.length ? renderHistory(entries) : '<p class="empty-msg">Nenhuma entrada registrada</p>';
        document.getElementById('exits-list').innerHTML = exits.length ? renderHistory(exits) : '<p class="empty-msg">Nenhuma saída registrada</p>';
    } catch (err) {
        document.getElementById('entries-list').innerHTML = '<div class="error-msg">Erro ao carregar histórico</div>';
        document.getElementById('exits-list').innerHTML = '<div class="error-msg">Erro ao carregar histórico</div>';
    }
}

function switchProductTab(tab) {
    document.querySelectorAll('#product-modal .tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('#product-modal .tab-content').forEach(c => c.classList.remove('active'));
    document.querySelector(`#product-modal .tab-btn[onclick="switchProductTab('${tab}')"]`).classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');
}

// ====== FINANCIAL ======
async function loadDashboard() {
    try {
        const res = await apiFetch(API_BASE + '/financeiro/dashboard');
        const data = await res.json();
        if (data.error) return;
        document.getElementById('dash-today-total').textContent = formatCurrency(data.today.total);
        document.getElementById('dash-today-count').textContent = data.today.orders + ' comandas';
        document.getElementById('dash-week-total').textContent = formatCurrency(data.week.total);
        document.getElementById('dash-week-count').textContent = data.week.orders + ' comandas';
        document.getElementById('dash-month-total').textContent = formatCurrency(data.month.total);
        document.getElementById('dash-month-count').textContent = data.month.orders + ' comandas';
    } catch (err) {}
}

async function loadSales() {
    const container = document.getElementById('sales-list');
    if (!container) return;
    const dateFilter = document.getElementById('sale-date-filter')?.value || '';
    try {
        const params = dateFilter ? '?date_filter=' + dateFilter : '';
        const res = await apiFetch(API_BASE + '/financeiro/vendas' + params);
        const data = await res.json();
        if (data.error) { container.innerHTML = '<div class="error-msg">' + data.error + '</div>'; return; }
        if (data.sales.length === 0) { container.innerHTML = '<p class="empty-msg">Nenhuma venda no período</p>'; return; }
        container.innerHTML = `
            <div style="background:var(--color-secondary);border-radius:var(--radius);padding:12px;margin-bottom:12px;text-align:center;">
                <span style="font-size:13px;color:#888;">Total do dia: </span>
                <span style="font-size:18px;font-weight:700;color:var(--color-accent);">${formatCurrency(data.summary.total_sales)}</span>
                <span style="font-size:12px;color:#888;margin-left:8px;">(${data.summary.orders_count} comandas)</span>
            </div>
            ${data.sales.map(s => `
                <div class="sale-card">
                    <div class="sale-header">
                        <span class="sale-table">${s.is_balcao ? 'Balcão' : 'Mesa ' + s.table_number}</span>
                        <span class="sale-time">${s.closed_at ? s.closed_at.split('T')[1]?.substring(0,5) : ''}</span>
                    </div>
                    <div class="sale-detail"><span>Garçom: ${s.waiter_name}</span><span>${s.items_count} itens</span></div>
                    ${s.payment_method ? `<div class="sale-detail"><span>Pgto: ${({dinheiro:'Dinheiro',cartao_credito:'Crédito',cartao_debito:'Débito',pix:'Pix'})[s.payment_method] || s.payment_method}</span></div>` : ''}
                    <div class="sale-total">${formatCurrency(s.total)}</div>
                    ${s.service_charge_amount > 0 ? `<div class="sale-detail"><span>+ ${s.service_charge_pct}% serviço</span><span>${formatCurrency(s.service_charge_amount)}</span></div>` : ''}
                </div>
            `).join('')}
        `;
    } catch (err) { container.innerHTML = '<div class="error-msg">Erro ao carregar vendas</div>'; }
}

let lastReportDate = null;

async function dailyCloseReport() {
    const date = document.getElementById('sale-date-filter')?.value || new Date().toISOString().split('T')[0];
    lastReportDate = date;
    try {
        const res = await apiFetch(API_BASE + '/financeiro/fechamento-diario', { method: 'POST', body: JSON.stringify({ date }) });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        renderDailyReport(data);
        document.getElementById('report-modal').style.display = 'flex';
    } catch (err) { alert('Erro ao gerar relatório'); }
}

function renderDailyReport(data) {
    const methodLabels = {
        dinheiro: 'Dinheiro', cartao_credito: 'Crédito',
        cartao_debito: 'Débito', pix: 'Pix', nao_informado: 'Não Informado'
    };

    const methodRows = Object.entries(data.by_payment_method || {}).map(([method, vals]) => `
        <div style="margin-bottom:6px;">
            <div class="summary-row">
                <span>${vals.label || ((methodLabels[method] || method) + (vals.count > 0 ? ' (' + vals.count + ')' : ''))}</span>
                <span>${formatCurrency(vals.gross)}</span>
            </div>
            ${vals.fee > 0 ? `<div class="summary-row" style="color:var(--red);"><span>&nbsp;&nbsp;(-) Taxa ${vals.fee_pct}%</span><span>- ${formatCurrency(vals.fee)}</span></div>` : ''}
            ${vals.fee > 0 ? `<div class="summary-row" style="font-weight:600;"><span>&nbsp;&nbsp;Líquido</span><span>${formatCurrency(vals.net)}</span></div>` : ''}
        </div>
    `).join('');

    const waiterRows = Object.entries(data.by_waiter || {}).map(([waiter, vals]) => `
        <div class="summary-row">
            <span>${waiter}</span>
            <span>${formatCurrency(vals.service_charge)}</span>
        </div>
    `).join('');

    const tableRows = Object.entries(data.by_table || {}).map(([table, vals]) => `
        <div class="summary-row">
            <span>${table}</span>
            <span>${formatCurrency(vals.total)} (${vals.orders})</span>
        </div>
    `).join('');

    const itemRows = (data.items_ranking || []).slice(0, 10).map(item => `
        <div class="summary-row">
            <span>${item.name}</span>
            <span>${item.quantity}x ${formatCurrency(item.total)}</span>
        </div>
    `).join('');

    const hourRows = Object.entries(data.by_hour || {}).map(([hour, total]) => `
        <div class="summary-row">
            <span>${hour}</span>
            <span>${formatCurrency(total)}</span>
        </div>
    `).join('');

    document.getElementById('report-content').innerHTML = `
        <p style="color:var(--text-muted);font-size:13px;">Data: ${data.date} | Fechado por: ${data.closed_by}</p>

        <div class="report-summary">
            <h4>Resumo Geral</h4>
            <div class="summary-row"><span>Vendas Brutas</span><span>${formatCurrency(data.summary.total_sales)}</span></div>
            <div class="summary-row"><span>Taxa de Serviço</span><span>${formatCurrency(data.summary.total_service_charge)}</span></div>
            <div class="summary-row" style="color:var(--red);"><span>Taxas de Cartão</span><span>- ${formatCurrency(data.summary.total_card_fees)}</span></div>
            <div class="summary-row" style="font-weight:600;"><span>Total Bruto Recebido</span><span>${formatCurrency(data.summary.gross_total)}</span></div>
            <div class="summary-row summary-total"><span>Total Líquido no Caixa</span><span>${formatCurrency(data.summary.net_total)}</span></div>
            <div style="color:var(--text-muted);font-size:11px;margin-top:8px;">${data.summary.orders_count} comandas fechadas</div>
        </div>

        <div class="report-summary">
            <h4>Formas de Pagamento (Bruto / Líquido)</h4>
            ${methodRows}
        </div>

        <div class="report-summary">
            <h4>Taxa de Serviço por Garçom</h4>
            ${waiterRows}
        </div>

        <div class="report-summary">
            <h4>Vendas por Mesa</h4>
            ${tableRows}
        </div>

        <div class="report-summary">
            <h4>Top Itens Vendidos</h4>
            ${itemRows}
        </div>

        <div class="report-summary">
            <h4>Vendas por Hora</h4>
            ${hourRows}
        </div>
    `;
}

async function downloadPdfReport() {
    const date = lastReportDate || (document.getElementById('sale-date-filter')?.value || new Date().toISOString().split('T')[0]);
    try {
        const res = await apiFetch(API_BASE + '/financeiro/relatorio-pdf', { method: 'POST', body: JSON.stringify({ date }) });
        if (!res.ok) {
            const data = await res.json();
            alert(data.error || 'Erro ao gerar PDF');
            return;
        }
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `relatorio_ladsbeer_${date}.pdf`;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
    } catch (err) { alert('Erro ao baixar PDF'); }
}

function closeReport() { document.getElementById('report-modal').style.display = 'none'; }

// ====== SUPPLIERS ======
let supplierProductsCache = [];

async function loadSuppliers() {
    const container = document.getElementById('suppliers-list');
    if (!container) return;

    const search = document.getElementById('supplier-search')?.value.toLowerCase() || '';
    const activeFilter = document.getElementById('supplier-filter-active')?.value || '';

    try {
        const res = await apiFetch(API_BASE + '/fornecedores');
        const data = await res.json();
        if (data.error) {
            container.innerHTML = '<div class="error-msg">' + data.error + '</div>';
            return;
        }

        let suppliers = data;
        if (search) {
            suppliers = suppliers.filter(s => s.name.toLowerCase().includes(search));
        }
        if (activeFilter === 'true') {
            suppliers = suppliers.filter(s => s.active);
        } else if (activeFilter === 'false') {
            suppliers = suppliers.filter(s => !s.active);
        }

        if (suppliers.length === 0) {
            container.innerHTML = '<p class="empty-msg">Nenhum fornecedor encontrado</p>';
            return;
        }

        container.innerHTML = suppliers.map(s => `
            <div class="supplier-card ${s.active ? 'active' : 'inactive'}">
                <div class="supplier-header">
                    <span class="supplier-name">${s.name}</span>
                    <span class="supplier-status">
                        <span class="status-dot ${s.active ? 'green' : 'red'}"></span>
                        ${s.active ? 'Ativo' : 'Inativo'}
                    </span>
                </div>
                ${s.contact ? `<div class="supplier-contact">${s.contact}</div>` : ''}
                <div class="supplier-products">
                    ${s.products.length > 0 ? s.products.map(p => `<span class="supplier-product-tag">${p.name}</span>`).join('') : '<span class="text-muted">Nenhum produto vinculado</span>'}
                </div>
                <div class="supplier-actions">
                    <button onclick="editSupplier(${s.id})" class="btn-small">Editar</button>
                    <button onclick="deleteSupplier(${s.id})" class="btn-small btn-danger">Excluir</button>
                </div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = '<div class="error-msg">Erro ao carregar fornecedores</div>';
    }
}

async function loadSupplierProducts() {
    try {
        const res = await apiFetch(API_BASE + '/produtos');
        supplierProductsCache = await res.json();
    } catch (err) {
        supplierProductsCache = [];
    }
}

async function showSupplierModal(supplier = null) {
    await loadSupplierProducts();
    const container = document.getElementById('supplier-products');
    container.innerHTML = supplierProductsCache.map(p => `
        <label class="checkbox-row">
            <input type="checkbox" value="${p.id}" class="supplier-product-check">
            <span>${p.name} (${p.category})</span>
        </label>
    `).join('');

    document.getElementById('supplier-modal-title').textContent = supplier ? 'Editar Fornecedor' : 'Novo Fornecedor';
    document.getElementById('supplier-id').value = supplier ? supplier.id : '';
    document.getElementById('supplier-name').value = supplier ? supplier.name : '';
    document.getElementById('supplier-contact').value = supplier ? (supplier.contact || '') : '';
    const activeCheckbox = document.getElementById('supplier-active');
    activeCheckbox.checked = supplier ? supplier.active : true;
    const activeLabel = document.getElementById('supplier-active-label');
    activeLabel.textContent = activeCheckbox.checked ? 'Fornecedor ativo' : 'Fornecedor inativo';
    activeCheckbox.onchange = () => {
        activeLabel.textContent = activeCheckbox.checked ? 'Fornecedor ativo' : 'Fornecedor inativo';
    };

    document.querySelectorAll('.supplier-product-check').forEach(cb => {
        cb.checked = supplier && supplier.products.some(p => p.id == cb.value);
    });

    document.getElementById('supplier-error').style.display = 'none';
    document.getElementById('supplier-modal').style.display = 'flex';
}

function closeSupplierModal() {
    document.getElementById('supplier-modal').style.display = 'none';
}

async function submitSupplier() {
    const id = document.getElementById('supplier-id').value;
    const name = document.getElementById('supplier-name').value.trim();
    const contact = document.getElementById('supplier-contact').value.trim();
    const active = document.getElementById('supplier-active').checked;
    const productIds = Array.from(document.querySelectorAll('.supplier-product-check:checked')).map(cb => parseInt(cb.value));

    if (!name) {
        document.getElementById('supplier-error').textContent = 'Informe o nome do fornecedor';
        document.getElementById('supplier-error').style.display = 'block';
        return;
    }

    const payload = { name, contact, active, product_ids: productIds };
    const url = API_BASE + '/fornecedores' + (id ? '/' + id : '');
    const method = id ? 'PUT' : 'POST';

    try {
        const res = await apiFetch(url, { method, body: JSON.stringify(payload) });
        const data = await res.json();
        if (data.error) {
            document.getElementById('supplier-error').textContent = data.error;
            document.getElementById('supplier-error').style.display = 'block';
            return;
        }
        closeSupplierModal();
        loadSuppliers();
    } catch (err) {
        document.getElementById('supplier-error').textContent = 'Erro ao salvar fornecedor';
        document.getElementById('supplier-error').style.display = 'block';
    }
}

async function editSupplier(id) {
    try {
        const res = await apiFetch(API_BASE + '/fornecedores');
        const suppliers = await res.json();
        const supplier = suppliers.find(s => s.id == id);
        if (supplier) showSupplierModal(supplier);
    } catch (err) {
        alert('Erro ao carregar fornecedor');
    }
}

async function deleteSupplier(id) {
    if (!confirm('Deseja realmente excluir este fornecedor?')) return;
    try {
        const res = await apiFetch(API_BASE + '/fornecedores/' + id, { method: 'DELETE' });
        if (!res.ok) {
            const data = await res.json();
            alert(data.error || 'Erro ao excluir');
            return;
        }
        loadSuppliers();
    } catch (err) {
        alert('Erro ao excluir fornecedor');
    }
}

// ====== PROMOTIONS ======
let promotionProductsCache = [];

async function loadPromotions() {
    const container = document.getElementById('promotions-list');
    if (!container) return;
    try {
        const res = await apiFetch(API_BASE + '/promocoes');
        const promotions = await res.json();
        if (promotions.error) {
            container.innerHTML = '<div class="error-msg">' + promotions.error + '</div>';
            return;
        }

        const counts = { ativa: 0, agendada: 0, expirada: 0, desativada: 0 };
        promotions.forEach(p => counts[p.status] = (counts[p.status] || 0) + 1);
        document.getElementById('count-ativa').textContent = counts.ativa;
        document.getElementById('count-agendada').textContent = counts.agendada;
        document.getElementById('count-expirada').textContent = counts.expirada;
        document.getElementById('count-desativada').textContent = counts.desativada;

        if (promotions.length === 0) {
            container.innerHTML = '<p class="empty-msg">Nenhuma promoção cadastrada</p>';
            return;
        }

        const statusLabels = { ativa: 'Ativa', agendada: 'Agendada', expirada: 'Expirada', desativada: 'Desativada' };
        const statusColors = { ativa: 'green', agendada: 'yellow', expirada: 'orange', desativada: 'red' };

        container.innerHTML = promotions.map(p => {
            const period = formatPromotionPeriod(p.start_at, p.end_at);
            const discountedPrices = p.products.map(prod => {
                const promoPrice = prod.price * (1 - p.discount_pct / 100);
                return `<span class="promo-product">${prod.name}: ${formatCurrency(prod.price)} → <strong>${formatCurrency(promoPrice)}</strong></span>`;
            }).join('');

            return `
            <div class="promo-card ${p.status}">
                <div class="promo-header">
                    <div>
                        <div class="promo-name">${p.name}</div>
                        <div class="promo-period">${period}</div>
                    </div>
                    <span class="promo-status status-${statusColors[p.status]}">${statusLabels[p.status]}</span>
                </div>
                ${p.description ? `<div class="promo-desc">${p.description}</div>` : ''}
                <div class="promo-discount">${p.discount_pct}% OFF</div>
                <div class="promo-products">
                    ${p.products.length > 0 ? discountedPrices : '<span class="text-muted">Nenhum produto vinculado</span>'}
                </div>
                <div class="promo-actions">
                    <button onclick="editPromotion(${p.id})" class="btn-small">Editar</button>
                    <button onclick="deletePromotion(${p.id})" class="btn-small btn-danger">Excluir</button>
                </div>
            </div>
        `}).join('');
    } catch (err) {
        container.innerHTML = '<div class="error-msg">Erro ao carregar promoções</div>';
    }
}

function formatPromotionPeriod(start, end) {
    if (!start && !end) return 'Sem período definido';
    const fmt = (d) => d ? new Date(d).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';
    if (start && end) return `${fmt(start)} até ${fmt(end)}`;
    if (start) return `A partir de ${fmt(start)}`;
    return `Até ${fmt(end)}`;
}

async function loadPromotionProducts() {
    try {
        const res = await apiFetch(API_BASE + '/produtos?active_only=true');
        promotionProductsCache = await res.json();
    } catch (err) {
        promotionProductsCache = [];
    }
}

function updatePromotionSelectedCount() {
    const count = document.querySelectorAll('.promotion-product-check:checked').length;
    const el = document.getElementById('promotion-selected-count');
    if (el) el.textContent = `(${count} selecionados)`;
}

function renderPromotionProducts(selectedIds = []) {
    const container = document.getElementById('promotion-products');
    if (promotionProductsCache.length === 0) {
        container.innerHTML = '<span class="text-muted">Nenhum produto ativo</span>';
        updatePromotionSelectedCount();
        return;
    }
    container.innerHTML = promotionProductsCache.map(p => `
        <label class="checkbox-row">
            <input type="checkbox" value="${p.id}" class="promotion-product-check" ${selectedIds.includes(p.id) ? 'checked' : ''}>
            <span>${p.name} (${formatCurrency(p.price)})</span>
        </label>
    `).join('');
    container.querySelectorAll('.promotion-product-check').forEach(cb => {
        cb.addEventListener('change', updatePromotionSelectedCount);
    });
    updatePromotionSelectedCount();
}

async function showPromotionModal(promotion = null) {
    await loadPromotionProducts();
    document.getElementById('promotion-modal-title').textContent = promotion ? 'Editar Promoção' : 'Nova Promoção';
    document.getElementById('promotion-id').value = promotion ? promotion.id : '';
    document.getElementById('promotion-name').value = promotion ? promotion.name : '';
    document.getElementById('promotion-description').value = promotion ? (promotion.description || '') : '';
    document.getElementById('promotion-discount').value = promotion ? promotion.discount_pct : '';
    document.getElementById('promotion-start').value = promotion && promotion.start_at ? new Date(promotion.start_at).toISOString().slice(0, 16) : '';
    document.getElementById('promotion-end').value = promotion && promotion.end_at ? new Date(promotion.end_at).toISOString().slice(0, 16) : '';

    const activeCheckbox = document.getElementById('promotion-active');
    activeCheckbox.checked = promotion ? promotion.is_active : true;
    const activeLabel = document.getElementById('promotion-active-label');
    activeLabel.textContent = activeCheckbox.checked ? 'Promoção ativa' : 'Promoção inativa';
    activeCheckbox.onchange = () => {
        activeLabel.textContent = activeCheckbox.checked ? 'Promoção ativa' : 'Promoção inativa';
    };

    renderPromotionProducts(promotion ? promotion.products.map(p => p.id) : []);

    document.getElementById('promotion-error').style.display = 'none';
    document.getElementById('promotion-modal').style.display = 'flex';
}

function closePromotionModal() {
    document.getElementById('promotion-modal').style.display = 'none';
}

async function submitPromotion() {
    const id = document.getElementById('promotion-id').value;
    const toUtcIso = (localValue) => {
        if (!localValue) return null;
        return new Date(localValue).toISOString();
    };

    const payload = {
        name: document.getElementById('promotion-name').value.trim(),
        description: document.getElementById('promotion-description').value.trim() || null,
        discount_pct: parseFloat(document.getElementById('promotion-discount').value) || 0,
        start_at: toUtcIso(document.getElementById('promotion-start').value),
        end_at: toUtcIso(document.getElementById('promotion-end').value),
        is_active: document.getElementById('promotion-active').checked,
        product_ids: Array.from(document.querySelectorAll('.promotion-product-check:checked')).map(cb => parseInt(cb.value)),
    };

    if (!payload.name) {
        document.getElementById('promotion-error').textContent = 'Informe o nome da promoção';
        document.getElementById('promotion-error').style.display = 'block';
        return;
    }
    if (payload.discount_pct <= 0 || payload.discount_pct > 100) {
        document.getElementById('promotion-error').textContent = 'Informe um desconto entre 0,01% e 100%';
        document.getElementById('promotion-error').style.display = 'block';
        return;
    }
    if (payload.product_ids.length === 0) {
        document.getElementById('promotion-error').textContent = 'Selecione pelo menos um produto';
        document.getElementById('promotion-error').style.display = 'block';
        return;
    }

    const url = API_BASE + '/promocoes' + (id ? '/' + id : '');
    const method = id ? 'PUT' : 'POST';

    try {
        const res = await apiFetch(url, { method, body: JSON.stringify(payload) });
        const data = await res.json();
        if (data.error) {
            document.getElementById('promotion-error').textContent = data.error;
            document.getElementById('promotion-error').style.display = 'block';
            return;
        }
        closePromotionModal();
        loadPromotions();
    } catch (err) {
        document.getElementById('promotion-error').textContent = 'Erro ao salvar promoção';
        document.getElementById('promotion-error').style.display = 'block';
    }
}

async function editPromotion(id) {
    try {
        const res = await apiFetch(API_BASE + '/promocoes');
        const promotions = await res.json();
        const promotion = promotions.find(p => p.id == id);
        if (promotion) showPromotionModal(promotion);
    } catch (err) {
        alert('Erro ao carregar promoção');
    }
}

async function deletePromotion(id) {
    if (!confirm('Deseja realmente excluir esta promoção?')) return;
    try {
        const res = await apiFetch(API_BASE + '/promocoes/' + id, { method: 'DELETE' });
        if (!res.ok) {
            const data = await res.json();
            alert(data.error || 'Erro ao excluir');
            return;
        }
        loadPromotions();
    } catch (err) {
        alert('Erro ao excluir promoção');
    }
}

// ====== APP SETTINGS ======
let appSettings = null;

async function loadAppSettings() {
    try {
        const res = await apiFetch(API_BASE + '/configuracoes');
        const settings = await res.json();
        appSettings = {};
        settings.forEach(s => appSettings[s.key] = s.value);
    } catch (err) {
        appSettings = {};
    }
}

function getSetting(key, defaultValue) {
    defaultValue = defaultValue === undefined ? '' : defaultValue;
    return appSettings && appSettings[key] !== undefined ? appSettings[key] : defaultValue;
}

function getSettingFloat(key, defaultValue) {
    defaultValue = defaultValue === undefined ? 0 : defaultValue;
    const v = parseFloat(getSetting(key, defaultValue));
    return isNaN(v) ? defaultValue : v;
}

async function loadSettings() {
    const container = document.getElementById('settings-list');
    if (!container) return;
    try {
        const res = await apiFetch(API_BASE + '/configuracoes');
        const settings = await res.json();
        if (settings.error) {
            container.innerHTML = '<div class="error-msg">' + settings.error + '</div>';
            return;
        }
        appSettings = {};
        settings.forEach(s => appSettings[s.key] = s.value);

        container.innerHTML = settings.map(s => {
            const inputType = s.type === 'number' ? 'number' : 'text';
            const step = s.type === 'number' ? 'step="0.01"' : '';
            return `
            <div class="setting-card">
                <label class="input-label">${s.label}</label>
                <p class="setting-description">${s.description || ''}</p>
                <input type="${inputType}" ${step} id="setting-${s.key}" class="input-field" value="${s.value || ''}" onchange="submitSetting('${s.key}')">
            </div>
            `;
        }).join('');
    } catch (err) {
        container.innerHTML = '<div class="error-msg">Erro ao carregar configurações</div>';
    }
}

async function submitSetting(key) {
    const input = document.getElementById('setting-' + key);
    if (!input) return;
    const value = input.value;

    const errorEl = document.getElementById('settings-error');
    const successEl = document.getElementById('settings-success');
    errorEl.style.display = 'none';
    successEl.style.display = 'none';

    try {
        const res = await apiFetch(API_BASE + '/configuracoes/' + key, {
            method: 'PUT',
            body: JSON.stringify({ value })
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        appSettings[key] = value;
        successEl.style.display = 'block';
        setTimeout(() => { successEl.style.display = 'none'; }, 2000);
    } catch (err) {
        errorEl.textContent = 'Erro ao salvar configuração';
        errorEl.style.display = 'block';
    }
}
