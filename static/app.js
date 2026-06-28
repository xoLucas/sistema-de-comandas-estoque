const API_BASE = '/api';

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
        .then(data => {
            if (data.detail) {
                localStorage.clear();
                window.location.href = '/login';
                return;
            }
            localStorage.setItem('lads_user', JSON.stringify(data));
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
    const listHtml = products.map(p => `
        <div class="pedido-product-row">
            <div class="prod-info">
                <div class="prod-name">${p.name}</div>
                <div class="prod-stock" id="pstock-${p.id}" data-cat="${p.category}">
                    Estoque: <strong>${p.stock}</strong> | ${p.category}
                </div>
                <div class="prod-price">${formatCurrency(p.price)}</div>
            </div>
            <div class="qty-control">
                <button class="btn-sm btn-sm-remove" onclick="changePedidoQty(${p.id}, -1)">-</button>
                <input type="number" class="qty-input" id="pqty-${p.id}" value="0" min="0" max="${p.stock}" readonly>
                <button class="btn-sm btn-sm-add" onclick="changePedidoQty(${p.id}, 1)">+</button>
            </div>
        </div>
    `).join('');

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
                const subtotal = qty * product.price;
                total += subtotal;
                selected.push({ ...product, qty, subtotal });
            }
        }
    }

    if (selected.length === 0) {
        document.getElementById('pedido-error').textContent = 'Selecione ao menos 1 item';
        document.getElementById('pedido-error').style.display = 'block';
        return;
    }

    const itemsHtml = selected.map(s => `
        <div class="review-item">
            <div class="review-info">
                <span class="review-qty">${s.qty}x</span>
                <span class="review-name">${s.name}</span>
            </div>
            <div class="review-meta">
                <span>${formatCurrency(s.price)} cada</span>
                <span class="review-subtotal">${formatCurrency(s.subtotal)}</span>
            </div>
        </div>
    `).join('');

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
    const total = apply ? subtotal * 1.10 : subtotal;
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
    const total = applyService ? subtotal * 1.10 : subtotal;
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
    const service = total * 0.10;
    const remainingProduct = Math.max(0, total - paid);
    const remainingService = Math.max(0, service - paidService);
    const final = remainingProduct + remainingService;

    document.getElementById('close-summary').innerHTML = `
        <div style="display:flex;justify-content:space-between;padding:6px 0;font-size:14px;color:var(--text-muted);">
            <span>Total Produtos</span><span>${formatCurrency(total)}</span>
        </div>
        <div style="display:flex;justify-content:space-between;padding:6px 0;font-size:14px;color:var(--text-muted);">
            <span>10% Serviço</span><span id="close-service-display">${formatCurrency(service)}</span>
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
    const service = apply ? total * 0.10 : 0;
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
        if (data.service_charge_amount > 0) alertMsg += '\n+10% serviço: ' + formatCurrency(data.service_charge_amount);
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
            <div class="stock-item-row">
                <div>
                    <div class="stock-name">${p.name}</div>
                    <div class="stock-meta">${p.category} | Mín: ${p.min_stock} | ${p.pct_of_min}%</div>
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
    apiFetch(API_BASE + '/produtos')
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
                    ${s.service_charge_amount > 0 ? `<div class="sale-detail"><span>+ 10% serviço</span><span>${formatCurrency(s.service_charge_amount)}</span></div>` : ''}
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
            <div class="summary-row"><span>Taxa de Serviço (10%)</span><span>${formatCurrency(data.summary.total_service_charge)}</span></div>
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
