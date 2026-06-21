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
                ${t.has_open_order ? `<span class="table-total-text">${formatCurrency(t.total - (t.partial_payment || 0))}</span>` : ''}
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
        if (data.partial_payment > 0) {
            document.getElementById('partial-info').style.display = 'block';
            document.getElementById('partial-value').textContent = formatCurrency(data.partial_payment);
        } else {
            document.getElementById('partial-info').style.display = 'none';
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
        const itemsHtml = pedido.items.map(item => `
            <div class="pedido-item">
                <div class="item-info">
                    <div class="item-name">${item.product_name}</div>
                    <div class="item-meta">${formatCurrency(item.unit_price)} cada | ${item.category}</div>
                </div>
                <div class="item-actions">
                    <button class="btn-remove" onclick="removeItemFromRound(${item.product_id}, ${pedido.id})">-</button>
                    <span class="qty">${item.quantity}</span>
                    <button class="btn-add" onclick="addItemToRound(${item.product_id}, ${pedido.id})">+</button>
                </div>
            </div>
        `).join('');

        let drinksHtml = '';
        if (pedido.drinks && pedido.drinks.length > 0) {
            drinksHtml = `
                <div class="pedido-drinks">
                    <div class="drinks-title">Checklist Bebidas</div>
                    ${pedido.drinks.map(d => `
                        <div class="drink-check">
                            <input type="checkbox" id="drink-p${pedido.id}-${d.product_id}"
                                   ${isDrinkChecked(pedido.id, d.product_id) ? 'checked' : ''}
                                   onchange="toggleDrinkCheck(${pedido.id}, ${d.product_id})">
                            <label for="drink-p${pedido.id}-${d.product_id}">${d.quantity}x ${d.product_name}</label>
                        </div>
                    `).join('')}
                </div>
            `;
        }

        return `
            <div class="pedido-group">
                <div class="pedido-header">
                    <span>Pedido #${pedido.round_number}</span>
                    <span class="pedido-time">${pedido.created_at}</span>
                </div>
                ${itemsHtml}
                ${drinksHtml}
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

// ====== CHECKLIST STATE (persisted to localStorage) ======
function checkedDrinksKey() {
    return 'lads_checked_drinks_' + (typeof TABLE_ID !== 'undefined' ? TABLE_ID : '0');
}

function loadCheckedDrinks() {
    try {
        return JSON.parse(localStorage.getItem(checkedDrinksKey()) || '{}');
    } catch { return {}; }
}

function saveCheckedDrinks(state) {
    localStorage.setItem(checkedDrinksKey(), JSON.stringify(state));
}

function drinkCheckKey(pedidoId, productId) {
    return pedidoId + '-' + productId;
}

function isDrinkChecked(pedidoId, productId) {
    const state = loadCheckedDrinks();
    return !!state[drinkCheckKey(pedidoId, productId)];
}

function toggleDrinkCheck(pedidoId, productId) {
    const state = loadCheckedDrinks();
    const key = drinkCheckKey(pedidoId, productId);
    state[key] = !state[key];
    saveCheckedDrinks(state);
}

// ====== ADD PEDIDO MODAL ======
let pedidoQuantities = {};

function showAddPedidoModal() {
    apiFetch(API_BASE + '/produtos')
        .then(r => r.json())
        .then(products => {
            pedidoQuantities = {};
            products.forEach(p => { pedidoQuantities[p.id] = 0; });

            const listHtml = products.map(p => `
                <div class="pedido-product-row">
                    <div class="prod-info">
                        <div class="prod-name">${p.name}</div>
                        <div class="prod-stock">Estoque: ${p.stock} | ${p.category}</div>
                        <div class="prod-price">${formatCurrency(p.price)}</div>
                    </div>
                    <div class="qty-control">
                        <button class="btn-sm btn-sm-remove" onclick="changePedidoQty(${p.id}, -1, ${p.stock})">-</button>
                        <input type="number" class="qty-input" id="pqty-${p.id}" value="0" min="0" max="${p.stock}" readonly>
                        <button class="btn-sm btn-sm-add" onclick="changePedidoQty(${p.id}, 1, ${p.stock})">+</button>
                    </div>
                </div>
            `).join('');

            document.getElementById('pedido-product-list').innerHTML = listHtml;
            document.getElementById('add-pedido-modal').style.display = 'flex';
        });
}

function changePedidoQty(productId, delta, maxStock) {
    let qty = (pedidoQuantities[productId] || 0) + delta;
    if (qty < 0) qty = 0;
    if (qty > maxStock) qty = maxStock;
    pedidoQuantities[productId] = qty;
    document.getElementById('pqty-' + productId).value = qty;
}

function closeAddPedidoModal() {
    document.getElementById('add-pedido-modal').style.display = 'none';
}

async function submitPedido() {
    const items = [];
    for (const [pid, qty] of Object.entries(pedidoQuantities)) {
        if (qty > 0) {
            items.push({ product_id: parseInt(pid), quantity: qty });
        }
    }
    if (items.length === 0) {
        document.getElementById('pedido-error').textContent = 'Selecione ao menos 1 item';
        document.getElementById('pedido-error').style.display = 'block';
        return;
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

async function registerPartialPayment() {
    const amount = parseFloat(document.getElementById('partial-payment-input').value);
    if (!amount || amount <= 0) { alert('Informe um valor válido'); return; }
    try {
        const res = await apiFetch(API_BASE + '/comanda/pagamento-parcial', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, amount })
        });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        document.getElementById('partial-payment-input').value = '';
        loadTableDetail();
    } catch (err) { alert('Erro ao registrar pagamento'); }
}

async function closeOrder(applyServiceCharge) {
    const msg = applyServiceCharge ? 'Fechar com acréscimo de 10%?' : 'Deseja realmente fechar a mesa?';
    if (!confirm(msg)) return;
    try {
        const res = await apiFetch(API_BASE + '/comanda/fechar', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, apply_service_charge: applyServiceCharge })
        });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        let alertMsg = 'Mesa fechada!\nTotal: ' + formatCurrency(data.total);
        if (data.service_charge_amount > 0) alertMsg += '\n+10% serviço: ' + formatCurrency(data.service_charge_amount);
        if (data.partial_payment > 0) alertMsg += '\n- Pago: ' + formatCurrency(data.partial_payment);
        alertMsg += '\nFinal: ' + formatCurrency(data.final_total);
        alert(alertMsg);
        localStorage.removeItem(checkedDrinksKey());
        window.location.href = '/';
    } catch (err) { alert('Erro ao fechar comanda'); }
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
                    ${s.service_charge_amount > 0 ? `<div class="sale-detail"><span>+10% serviço</span><span>${formatCurrency(s.service_charge_amount)}</span></div>` : ''}
                    ${s.partial_payment > 0 ? `<div class="sale-detail"><span>- Pagamento parcial</span><span>${formatCurrency(s.partial_payment)}</span></div>` : ''}
                    <div class="sale-total">${formatCurrency(s.final_total)}</div>
                </div>
            `).join('')}
        `;
    } catch (err) { container.innerHTML = '<div class="error-msg">Erro ao carregar vendas</div>'; }
}

async function dailyCloseReport() {
    const date = document.getElementById('sale-date-filter')?.value || new Date().toISOString().split('T')[0];
    try {
        const res = await apiFetch(API_BASE + '/financeiro/fechamento-diario', { method: 'POST', body: JSON.stringify({ date }) });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        const reportContent = document.getElementById('report-content');
        reportContent.innerHTML = `
            <p style="color:#888;font-size:13px;">Data: ${data.date} | Fechado por: ${data.closed_by}</p>
            <table class="report-table">
                <thead><tr><th>Mesa</th><th>Garçom</th><th>Total</th><th>10%</th><th>Pago</th><th>Final</th><th>Hora</th></tr></thead>
                <tbody>${data.orders.map(o => `
                    <tr>
                        <td>${o.table}</td><td>${o.waiter}</td>
                        <td>${formatCurrency(o.total)}</td><td>${formatCurrency(o.service_charge)}</td>
                        <td>${formatCurrency(o.partial_payment)}</td>
                        <td><strong>${formatCurrency(o.final_total)}</strong></td>
                        <td>${o.closed_at}</td>
                    </tr>
                `).join('')}</tbody>
            </table>
            <div class="report-summary">
                <h4>Resumo do Dia</h4>
                <div class="summary-row"><span>Vendas Brutas:</span><span>${formatCurrency(data.summary.total_sales)}</span></div>
                <div class="summary-row"><span>Taxa de Serviço:</span><span>${formatCurrency(data.summary.total_service_charge)}</span></div>
                <div class="summary-row"><span>Pagamentos Parciais:</span><span>${formatCurrency(data.summary.total_partial_payments)}</span></div>
                <div class="summary-row"><span>Total de Comandas:</span><span>${data.summary.orders_count}</span></div>
                <div class="summary-row summary-total"><span>Total Líquido:</span><span>${formatCurrency(data.summary.net_total)}</span></div>
            </div>
        `;
        document.getElementById('report-modal').style.display = 'flex';
    } catch (err) { alert('Erro ao gerar relatório'); }
}

function closeReport() { document.getElementById('report-modal').style.display = 'none'; }
