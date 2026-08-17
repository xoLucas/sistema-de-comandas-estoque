const API_BASE = '/api';
const WS_BASE = (location.protocol === 'https:' ? 'wss://' : 'ws://') + location.host + '/ws';
let tableSocket = null;

const THEME_KEY = 'lads_theme_mode';
const THEME_DEFAULT = 'dark';

function applyTheme(mode) {
    const root = document.documentElement;
    if (!root) return;
    mode = mode === 'light' ? 'light' : 'dark';
    root.setAttribute('data-theme', mode);
    const metaThemeColor = document.querySelector('meta[name="theme-color"]');
    if (metaThemeColor) {
        metaThemeColor.setAttribute('content', mode === 'light' ? '#f6f8fa' : '#0d1117');
    }
}

function getStoredTheme() {
    try {
        return localStorage.getItem(THEME_KEY) || THEME_DEFAULT;
    } catch {
        return THEME_DEFAULT;
    }
}

function setStoredTheme(mode) {
    try {
        localStorage.setItem(THEME_KEY, mode === 'light' ? 'light' : 'dark');
    } catch {}
}

function toggleTheme() {
    const current = getStoredTheme();
    const next = current === 'light' ? 'dark' : 'light';
    applyTheme(next);
    setStoredTheme(next);
    return next;
}

function initTheme() {
    applyTheme(getStoredTheme());
}

function syncThemeFromSettings() {
    const settingValue = appSettings && appSettings['theme_mode'];
    if (settingValue) {
        applyTheme(settingValue);
        setStoredTheme(settingValue);
    }
}

async function toggleThemeSetting() {
    const nextMode = toggleTheme();
    const labelEl = document.getElementById('theme-mode-label');
    const btn = document.getElementById('setting-theme_mode');
    if (labelEl) {
        labelEl.textContent = nextMode === 'light' ? 'Modo Claro' : 'Modo Escuro';
    }
    if (btn) {
        const icon = nextMode === 'light' ? '<i class="bi bi-sun"></i>' : '<i class="bi bi-moon-stars"></i>';
        btn.innerHTML = icon + ' <span id="theme-mode-label">' + (nextMode === 'light' ? 'Modo Claro' : 'Modo Escuro') + '</span>';
    }
    if (appSettings) {
        appSettings['theme_mode'] = nextMode;
    }
    try {
        await apiFetch(API_BASE + '/configuracoes/theme_mode', {
            method: 'PUT',
            body: JSON.stringify({ value: nextMode })
        });
    } catch (err) {
        console.error('Error saving theme setting', err);
    }
}

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

function round(value, decimals = 2) {
    const factor = Math.pow(10, decimals);
    return Math.round((parseFloat(value || 0) + Number.EPSILON) * factor) / factor;
}

function statusLabel(status) {
    const labels = { vazia: 'Vazia', ocupada: 'Ocupada', finalizada: 'Finalizada' };
    return labels[status] || status;
}

function toLocalDateString(date) {
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().split('T')[0];
}

function toLocalDateTimeString(date) {
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

// ====== INPUT MASKS / VALIDATION HELPERS ======
function cleanNumbersInput(value) {
    return (value || '').replace(/\D/g, '');
}

function maskPhone(value) {
    const digits = cleanNumbersInput(value);
    if (digits.length > 11) return value;
    if (digits.length <= 10) {
        return digits.replace(/(\d{2})(\d{4})(\d{0,4})/, '($1) $2-$3').replace(/[-\s]$/, '');
    }
    return digits.replace(/(\d{2})(\d{5})(\d{0,4})/, '($1) $2-$3').replace(/[-\s]$/, '');
}

function maskCpfCnpj(value) {
    const digits = cleanNumbersInput(value);
    if (digits.length > 14) return value;
    if (digits.length <= 11) {
        return digits.replace(/(\d{3})(\d{3})(\d{3})(\d{0,2})/, '$1.$2.$3-$4').replace(/[.-]$/, '');
    }
    return digits.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{0,2})/, '$1.$2.$3/$4-$5').replace(/[./-]$/, '');
}

function maskContact(value) {
    const text = (value || '').trim();
    if (text.includes('@')) return text;
    return maskPhone(text);
}

function isValidEmail(value) {
    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test((value || '').trim());
}

function validateContactInput(value) {
    const text = (value || '').trim();
    if (!text) return true;
    if (text.includes('@')) return isValidEmail(text);
    const digits = cleanNumbersInput(text);
    return digits.length === 10 || digits.length === 11;
}

// ====== AUTH ======
let currentUser = null;

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
            currentUser = data;
            await loadAppSettings();
            updateNavVisibility();
            if (!data.is_registered && data.role === 'garcom') {
                showNameModal();
            }
            if (callback) callback(data);
        })
        .catch(() => { window.location.href = '/login'; });
}

function hasRole(...roles) {
    const user = currentUser || getStoredUser();
    return user && roles.includes(user.role);
}

function canViewFinancial() { return hasRole('gerente', 'caixa'); }
function canViewSuppliers() { return hasRole('gerente', 'estoquista', 'caixa'); }
function canViewPromotions() { return hasRole('gerente', 'caixa', 'estoquista', 'garcom'); }
function canManagePromotions() { return hasRole('gerente', 'caixa', 'estoquista'); }
function canViewSettings() { return hasRole('gerente'); }
function canViewEmployees() { return hasRole('gerente'); }
function canViewCustomers() { return hasRole('gerente', 'caixa', 'garcom'); }
function canCreateCustomer() { return hasRole('gerente', 'caixa', 'garcom'); }
function canEditCustomer() { return hasRole('gerente', 'caixa'); }
function canViewCustomerDashboard() { return hasRole('gerente', 'caixa'); }
function canManageStock() { return hasRole('gerente', 'estoquista', 'caixa'); }
function canViewProductCost() { return hasRole('gerente', 'caixa', 'estoquista'); }
function canManageCashRegister() { return hasRole('gerente', 'caixa'); }
function canManageConsignments() { return hasRole('gerente', 'caixa'); }
function canInitiateConsignment() { return hasRole('gerente', 'caixa', 'garcom'); }
function canViewDashboards() { return hasRole('gerente'); }

function updateNavVisibility() {
    const nav = document.getElementById('bottom-nav');
    if (!nav) return;
    const user = currentUser || getStoredUser();
    console.log('updateNavVisibility role:', user?.role);
    nav.querySelectorAll('[data-require]').forEach(el => {
        const req = el.dataset.require;
        let visible = false;
        if (req === 'financial') visible = canViewFinancial();
        else if (req === 'suppliers') visible = canViewSuppliers();
        else if (req === 'promotions') visible = canViewPromotions();
        else if (req === 'settings') visible = canViewSettings();
        else if (req === 'employees') visible = canViewEmployees();
        else if (req === 'customers') visible = canViewCustomers();
        else if (req === 'consignments') visible = canManageConsignments();
        else if (req === 'dashboards') visible = canViewDashboards();
        el.style.display = visible ? 'flex' : 'none';
    });
}

function requirePageAccess(allowedRoles, redirectTo = '/') {
    if (!currentUser || !allowedRoles.includes(currentUser.role)) {
        window.location.href = redirectTo;
        return false;
    }
    return true;
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
    const tableHref = t.is_balcao ? '/balcao/' + t.id : '/mesa/' + t.id;
    let card = grid.querySelector(`.table-card[href="${tableHref}"]`);
    const totalText = t.has_open_order ? formatCurrency(Math.max(0, t.total - (t.partial_payment || 0))) : '';
    const orderCountBadge = (!t.is_balcao && t.open_orders_count > 1) ? `<span class="table-order-count">${t.open_orders_count} comandas</span>` : '';
    if (!card) {
        card = document.createElement('a');
        card.href = tableHref;
        grid.appendChild(card);
    }
    card.className = 'table-card status-' + t.status;
    if (t.is_balcao) card.classList.add('is-balcao');
    card.innerHTML = `
        <span class="table-label">${t.label}</span>
        <span class="table-status-tag">${statusLabel(t.status)}</span>
        ${orderCountBadge}
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

// ====== NOTIFICATIONS ======
let notificationSocket = null;
let notifications = [];
let notificationIsManager = false;
let notificationPanelOpen = false;
let notificationFilter = 'active'; // active, resolved

// ====== STOCK ======
let stockSocket = null;

function connectNotificationsWebSocket() {
    if (notificationSocket) return;
    const token = getToken();
    if (!token) return;

    notificationSocket = new WebSocket(`${WS_BASE}/notifications?token=${token}`);

    notificationSocket.onopen = () => {
        console.log('Notifications WebSocket connected');
    };

    notificationSocket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            if (msg.type === 'notification' && msg.data) {
                const incoming = msg.data;
                const existing = notifications.find(n => n.id === incoming.id);
                if (existing) {
                    Object.assign(existing, incoming);
                } else {
                    notifications.unshift(incoming);
                }
                updateNotificationBadge();
                if (notificationPanelOpen) {
                    renderNotificationList();
                }
            }
        } catch (err) {
            console.error('Notifications WS message error', err);
        }
    };

    notificationSocket.onclose = () => {
        notificationSocket = null;
        setTimeout(connectNotificationsWebSocket, 3000);
    };

    notificationSocket.onerror = (err) => {
        console.error('Notifications WebSocket error', err);
    };
}

function closeNotificationsWebSocket() {
    if (notificationSocket) {
        notificationSocket.close();
        notificationSocket = null;
    }
}

function connectStockWebSocket() {
    if (stockSocket) return;
    const token = getToken();
    if (!token) return;

    stockSocket = new WebSocket(`${WS_BASE}/estoque?token=${token}`);

    stockSocket.onopen = () => {
        console.log('Stock WebSocket connected');
    };

    stockSocket.onmessage = (event) => {
        try {
            const msg = JSON.parse(event.data);
            console.log('[STOCK WS] received:', msg);
            if (msg.type === 'stock_update' && msg.data) {
                handleStockUpdate(msg.data);
            }
        } catch (err) {
            console.error('Stock WS message error', err);
        }
    };

    stockSocket.onclose = () => {
        stockSocket = null;
        setTimeout(connectStockWebSocket, 3000);
    };

    stockSocket.onerror = (err) => {
        console.error('Stock WebSocket error', err);
    };
}

function closeStockWebSocket() {
    if (stockSocket) {
        stockSocket.close();
        stockSocket = null;
    }
}

function handleStockUpdate(data) {
    const productId = data.product_id;
    const stock = data.stock;
    console.log('[STOCK WS] handleStockUpdate productId=', productId, 'stock=', stock);

    // Update pedido modal (mesa)
    if (typeof pedidoInitialStock !== 'undefined') {
        const currentQty = pedidoQuantities[productId] || 0;
        // stock is available stock; initial = available + reserved (pending)
        pedidoInitialStock[productId] = stock + currentQty;
        const input = document.getElementById('pqty-' + productId);
        const stockEl = document.getElementById('pstock-' + productId);
        const addBtn = document.getElementById('padd-btn-' + productId);
        if (stockEl) {
            const cat = stockEl.dataset.cat || '';
            const remaining = Math.max(0, stock);
            stockEl.innerHTML = 'Estoque: <strong>' + remaining + '</strong>' + (cat ? ' | ' + cat : '');
        }
        if (input) {
            input.max = stock + currentQty;
        }
        if (addBtn) {
            addBtn.disabled = stock <= 0;
        }
        if (typeof applyPedidoFilters === 'function') {
            applyPedidoFilters();
        }
    }

    // Update balcão grid
    const cardSelector = `.balcao-product-card[data-stock]`;
    const cards = document.querySelectorAll(cardSelector);
    cards.forEach(card => {
        const onclickAttr = card.getAttribute('onclick') || '';
        if (onclickAttr.includes('changeBalcaoQty(' + productId + ',')) {
            card.dataset.stock = stock;
            const stockEl = document.getElementById('bstock-' + productId);
            if (stockEl) {
                stockEl.innerHTML = 'Estoque: <strong>' + stock + '</strong>';
            }
            const input = document.getElementById('bqty-' + productId);
            if (input) {
                input.max = stock;
                if (parseInt(input.value) > stock) {
                    input.value = Math.max(1, stock);
                }
            }
        }
    });
    if (cards.length > 0 && typeof applyBalcaoFilters === 'function') {
        applyBalcaoFilters();
    }

    // Update estoque page
    if (document.getElementById('stock-list') && typeof loadStock === 'function') {
        loadStock();
    }

    // Update table detail view (comanda aberta na mesa)
    const tableStockEl = document.getElementById('table-stock-' + productId);
    const tableAddBtn = document.getElementById('table-add-btn-' + productId);
    if (tableStockEl) {
        console.log('[STOCK WS] updating table stock for product', productId, 'to', stock);
        tableStockEl.innerHTML = 'Estoque: <strong>' + Math.max(0, stock) + '</strong>';
    }
    if (tableAddBtn) {
        tableAddBtn.disabled = stock <= 0;
        console.log('[STOCK WS] table add button for product', productId, 'disabled=', stock <= 0);
    }
}

async function loadNotifications() {
    try {
        const res = await apiFetch(API_BASE + '/notifications');
        const data = await res.json();
        notifications = data.notifications || [];
        notificationIsManager = data.is_manager || false;
        updateNotificationBadge();
        if (notificationPanelOpen) {
            renderNotificationList();
        }
    } catch (err) {
        console.error('Error loading notifications', err);
    }
}

function updateNotificationBadge() {
    const badge = document.getElementById('notification-badge');
    if (!badge) return;
    const unreadCount = notifications.filter(n => n.status === 'unread').length;
    badge.textContent = unreadCount > 99 ? '99+' : unreadCount;
    badge.style.display = unreadCount > 0 ? 'flex' : 'none';
}

function toggleNotificationPanel(event) {
    if (event) event.stopPropagation();
    const panel = document.getElementById('notification-panel');
    const overlay = document.getElementById('notification-panel-overlay');
    if (!panel) return;

    if (notificationPanelOpen) {
        closeNotificationPanel();
        return;
    }

    notificationPanelOpen = true;
    panel.style.display = 'flex';
    if (overlay) overlay.style.display = 'block';
    const tabsContainer = document.getElementById('notification-filter-tabs');
    if (tabsContainer) tabsContainer.style.display = 'flex';
    renderNotificationTabs();
    renderNotificationList();
    loadNotifications();
}

function closeNotificationPanel(event) {
    if (event) event.stopPropagation();
    const panel = document.getElementById('notification-panel');
    const overlay = document.getElementById('notification-panel-overlay');
    const tabsContainer = document.getElementById('notification-filter-tabs');
    if (panel) panel.style.display = 'none';
    if (overlay) overlay.style.display = 'none';
    if (tabsContainer) tabsContainer.style.display = 'none';
    notificationPanelOpen = false;
}

function setNotificationFilter(filter) {
    notificationFilter = filter;
    renderNotificationTabs();
    renderNotificationList();
}

function renderNotificationTabs() {
    const tabsContainer = document.getElementById('notification-filter-tabs');
    if (!tabsContainer) return;
    tabsContainer.innerHTML = `
        <div class="tab ${notificationFilter === 'active' ? 'active' : ''}" onclick="setNotificationFilter('active')">Ativas</div>
        <div class="tab ${notificationFilter === 'resolved' ? 'active' : ''}" onclick="setNotificationFilter('resolved')">Resolvidas</div>
    `;
}

function renderNotificationList() {
    const list = document.getElementById('notification-list');
    if (!list) return;

    const filtered = notifications.filter(n => {
        if (notificationFilter === 'active') return n.status !== 'resolved';
        return n.status === 'resolved';
    });

    if (filtered.length === 0) {
        list.innerHTML = `<div class="notification-empty">${notificationFilter === 'active' ? 'Nenhuma notificação ativa' : 'Nenhuma notificação resolvida'}</div>`;
        return;
    }

    list.innerHTML = filtered.map(n => renderNotificationCard(n)).join('');
}

function renderNotificationCard(n) {
    const details = n.details || {};
    const items = details.items || [];
    const itemsHtml = items.length > 0
        ? `<div class="notification-card-items"><ul>${items.map(i => `<li>${i.quantity}x ${i.product_name || i.name || 'Item'}</li>`).join('')}</ul></div>`
        : '';

    const statusClass = n.status === 'unread' ? 'unread' : (n.status === 'resolved' ? 'resolved' : 'read');
    const time = n.created_at ? new Date(n.created_at).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '';

    let actions = '';
    if (n.status === 'resolved') {
        actions = `<div class="notification-status-text">Resolvido por ${n.resolution === 'reprint' ? 'reimpressão' : 'anotação manual'}</div>`;
    } else if (n.type === 'printer_failure' && notificationIsManager) {
        actions = `
            <div class="notification-card-actions">
                <button class="btn btn-primary" onclick="showReprintModal(${n.id}, event)">Reimprimir</button>
                <button class="btn btn-secondary" onclick="resolveNotification(${n.id}, 'manual_note', event)">Anotado</button>
            </div>
        `;
    } else if (n.type === 'printer_failure') {
        actions = `<div class="notification-status-text">Apenas gerente pode reimprimir</div>`;
    } else if (notificationIsManager) {
        actions = `
            <div class="notification-card-actions">
                <button class="btn btn-secondary" onclick="resolveNotification(${n.id}, 'manual_note', event)">Marcar como lida</button>
            </div>
        `;
    } else {
        actions = `<div class="notification-status-text">Apenas gerente pode marcar como lida</div>`;
    }

    const detailRows = [];
    if (details.table_label) detailRows.push(`<div class="detail-row"><span class="detail-label">Local</span><span class="detail-value">${details.table_label}</span></div>`);
    if (details.round_number) detailRows.push(`<div class="detail-row"><span class="detail-label">Pedido</span><span class="detail-value">#${details.round_number}</span></div>`);
    if (details.failed_printer_name) detailRows.push(`<div class="detail-row"><span class="detail-label">Impressora</span><span class="detail-value">${details.failed_printer_name}</span></div>`);
    if (details.customer_name) detailRows.push(`<div class="detail-row"><span class="detail-label">Cliente</span><span class="detail-value">${details.customer_name}</span></div>`);
    if (details.waiter_name) detailRows.push(`<div class="detail-row"><span class="detail-label">Garçom</span><span class="detail-value">${details.waiter_name}</span></div>`);
    if (details.observation) detailRows.push(`<div class="detail-row"><span class="detail-label">Observação</span><span class="detail-value">${escapeHtml(details.observation)}</span></div>`);

    const detailsHtml = detailRows.length > 0
        ? `<div class="notification-card-details">${detailRows.join('')}${itemsHtml}</div>`
        : itemsHtml;

    return `
        <div class="notification-card ${statusClass}" data-id="${n.id}" onclick="onNotificationCardClick(${n.id}, event)">
            <div class="notification-card-title">
                <span>${n.title}</span>
                ${n.status === 'unread' ? '<span style="color:var(--red);font-size:11px;font-weight:700">NOVO</span>' : ''}
            </div>
            <div class="notification-card-message">${n.message}</div>
            <div class="notification-card-time">${time}</div>
            ${detailsHtml}
            ${actions}
        </div>
    `;
}

async function onNotificationCardClick(id, event) {
    if (event) {
        const target = event.target;
        if (target.tagName === 'BUTTON' || target.closest('button')) return;
        if (target.tagName === 'SELECT' || target.closest('select')) return;
    }
    const notification = notifications.find(n => n.id === id);
    if (notification && notification.status === 'unread') {
        await markNotificationRead(id);
    }
}

async function markNotificationRead(id, event) {
    if (event) event.stopPropagation();
    try {
        const res = await apiFetch(API_BASE + '/notifications/' + id + '/read', { method: 'POST' });
        const data = await res.json();
        if (data.success) {
            const idx = notifications.findIndex(n => n.id === id);
            if (idx >= 0) notifications[idx] = data.notification;
            updateNotificationBadge();
            renderNotificationList();
        }
    } catch (err) {
        console.error('Error marking notification read', err);
    }
}

async function resolveNotification(id, resolution, event) {
    if (event) event.stopPropagation();
    if (!notificationIsManager) {
        alert('Apenas gerente pode resolver notificações');
        return;
    }
    try {
        const res = await apiFetch(API_BASE + '/notifications/' + id + '/resolve', {
            method: 'POST',
            body: JSON.stringify({ resolution })
        });
        const data = await res.json();
        if (data.success) {
            const idx = notifications.findIndex(n => n.id === id);
            if (idx >= 0) notifications[idx] = data.notification;
            updateNotificationBadge();
            renderNotificationList();
        } else {
            alert(data.error || 'Erro ao resolver notificação');
        }
    } catch (err) {
        console.error('Error resolving notification', err);
    }
}

function showReprintModal(notificationId, event) {
    if (event) event.stopPropagation();
    if (!notificationIsManager) {
        alert('Apenas gerente pode reimprimir');
        return;
    }
    const notification = notifications.find(n => n.id === notificationId);
    if (!notification) return;

    const details = notification.details || {};
    const failedPrinterId = details.failed_printer_id || '';
    const functionLabel = details.function === 'cozinha' ? 'Cozinha' : (details.function === 'bar' ? 'Bar' : 'Nota');

    const printers = [];
    [1, 2].forEach(id => {
        const name = getSetting('printer_' + id + '_name', 'Impressora ' + id);
        const ip = getSetting('printer_' + id + '_ip', '');
        if (ip && String(id) !== String(failedPrinterId)) {
            printers.push({ id: String(id), name });
        }
    });

    if (printers.length === 0) {
        alert('Nenhuma outra impressora configurada disponível.');
        return;
    }

    const options = printers.map(p => `<option value="${p.id}">${p.name}</option>`).join('');

    const modal = document.createElement('div');
    modal.className = 'modal reprint-modal';
    modal.id = 'reprint-modal-' + notificationId;
    modal.style.display = 'flex';
    modal.innerHTML = `
        <div class="modal-content" style="max-width:360px">
            <h3>Reimprimir ${functionLabel}</h3>
            <p style="font-size:13px;color:var(--text-muted);margin-bottom:12px">Escolha uma impressora diferente da que falhou.</p>
            <label style="display:block;font-size:13px;margin-bottom:6px;color:var(--text-muted)">Impressora</label>
            <select id="reprint-printer-${notificationId}" class="input-field" style="margin-bottom:16px">
                ${options}
            </select>
            <div style="display:flex;gap:8px">
                <button class="btn-secondary-full" onclick="document.getElementById('reprint-modal-${notificationId}').remove()">Cancelar</button>
                <button class="btn-primary-full" onclick="confirmReprint(${notificationId})">Reimprimir</button>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
}

function showLoadingModal(message) {
    hideLoadingModal();
    const modal = document.createElement('div');
    modal.className = 'modal loading-modal';
    modal.id = 'reprint-loading-modal';
    modal.style.display = 'flex';
    modal.innerHTML = `
        <div class="modal-content">
            <div class="spinner"></div>
            <p style="font-size:15px;font-weight:600;color:var(--text)">${message}</p>
            <p style="font-size:12px;color:var(--text-muted);margin-top:6px">Aguarde enquanto tentamos comunicar com a impressora.</p>
        </div>
    `;
    document.body.appendChild(modal);
}

function hideLoadingModal() {
    const modal = document.getElementById('reprint-loading-modal');
    if (modal) modal.remove();
}

async function confirmReprint(notificationId) {
    const select = document.getElementById('reprint-printer-' + notificationId);
    if (!select) return;
    const targetPrinterId = select.value;

    const reprintModal = document.getElementById('reprint-modal-' + notificationId);
    if (reprintModal) reprintModal.remove();

    showLoadingModal('Tentando comunicar com a impressora...');

    try {
        const res = await apiFetch(API_BASE + '/notifications/' + notificationId + '/reprint', {
            method: 'POST',
            body: JSON.stringify({ target_printer_id: targetPrinterId })
        });
        const data = await res.json();
        hideLoadingModal();

        if (data.success) {
            const idx = notifications.findIndex(n => n.id === notificationId);
            if (idx >= 0) {
                notifications[idx].status = 'resolved';
                notifications[idx].resolution = 'reprint';
            }
            updateNotificationBadge();
            renderNotificationList();
            alert(data.message || 'Reimpresso com sucesso');
        } else {
            alert(data.error || 'Erro ao reimprimir');
        }
    } catch (err) {
        hideLoadingModal();
        console.error('Error reprinting', err);
        alert('Erro ao reimprimir. Verifique a conexão e tente novamente.');
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
            card.href = t.is_balcao ? '/balcao/' + t.id : '/mesa/' + t.id;
            card.className = 'table-card status-' + t.status;
            if (t.is_balcao) card.classList.add('is-balcao');
            const orderCountBadge = (!t.is_balcao && t.open_orders_count > 1) ? `<span class="table-order-count">${t.open_orders_count} comandas</span>` : '';
            card.innerHTML = `
                <span class="table-label">${t.label}</span>
                <span class="table-status-tag">${statusLabel(t.status)}</span>
                ${orderCountBadge}
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
let currentOrderId = null;

function getCurrentOrder() {
    if (!currentTableData || !currentTableData.orders) return null;
    return currentTableData.orders.find(o => String(o.id) === String(currentOrderId)) || currentTableData.orders[0] || null;
}

function setCurrentOrderIdFromData() {
    if (!currentTableData || !currentTableData.orders || currentTableData.orders.length === 0) {
        currentOrderId = null;
        return;
    }
    const ids = currentTableData.orders.map(o => String(o.id));
    if (!currentOrderId || !ids.includes(String(currentOrderId))) {
        currentOrderId = currentTableData.orders[0].id;
    }
}

function renderOrderSelector() {
    const section = document.getElementById('order-selector-section');
    const select = document.getElementById('order-selector');
    if (!section || !select) return;

    if (!currentTableData || !currentTableData.orders || currentTableData.orders.length === 0) {
        section.style.display = 'none';
        return;
    }

    section.style.display = 'block';
    select.innerHTML = currentTableData.orders.map(o => {
        const label = (o.customer_name ? o.customer_name + ' - ' : '') + formatCurrency(o.total);
        const selected = String(o.id) === String(currentOrderId) ? 'selected' : '';
        return `<option value="${o.id}" ${selected}>Comanda #${o.id} - ${label}</option>`;
    }).join('');
}

function switchOrder(orderId) {
    currentOrderId = parseInt(orderId);
    renderOrderSelector();
    const order = getCurrentOrder();
    if (order) {
        renderPedidos({ pedidos: order.pedidos });
        updateTotalDisplay(order);
    }
}

function updateTotalDisplay(order) {
    order = order || getCurrentOrder() || currentTableData || {};
    document.getElementById('total-value').textContent = formatCurrency(order.total || 0);
    const partialInfo = document.getElementById('partial-info');
    if ((order.partial_payment || 0) > 0 || (order.partial_service_charge || 0) > 0) {
        partialInfo.style.display = 'block';
        const svcPart = (order.partial_service_charge || 0) > 0 ? ` (+ ${formatCurrency(order.partial_service_charge)} serviço)` : '';
        document.getElementById('partial-value').textContent = formatCurrency(order.partial_payment || 0) + svcPart;
        const paidCount = countPaidItems();
        const totalItems = countTotalItems();
        const remaining = Math.max(0, (order.total || 0) - (order.partial_payment || 0));
        document.getElementById('partial-detail').textContent =
            paidCount + ' de ' + totalItems + ' itens pagos | Resta produtos: ' + formatCurrency(remaining);
    } else {
        partialInfo.style.display = 'none';
    }
}

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
        setCurrentOrderIdFromData();

        document.getElementById('table-title').textContent = data.label;
        let statusText = 'Status: ' + statusLabel(data.status);
        if (data.waiter_name) statusText += ' | Garçom: ' + data.waiter_name;
        if (data.orders && data.orders.length > 1) statusText += ' | ' + data.orders.length + ' comandas';
        document.getElementById('table-status').textContent = statusText;

        const customerSection = document.getElementById('customer-section');
        const openActions = document.getElementById('open-actions');
        const activeActions = document.getElementById('active-actions');

        if (data.status === 'vazia' && (!data.orders || data.orders.length === 0)) {
            openActions.style.display = 'block';
            activeActions.style.display = 'none';
            customerSection.style.display = 'block';
            document.getElementById('order-selector-section').style.display = 'none';
            showNewOrderCreateActions(false);
            showNewOrderButton(false);
        } else {
            openActions.style.display = 'none';
            activeActions.style.display = 'block';
            customerSection.style.display = 'none';
            renderOrderSelector();
            showNewOrderCreateActions(false);
            showNewOrderButton(true);
            const order = getCurrentOrder();
            if (order) {
                renderPedidos({ pedidos: order.pedidos });
                updateTotalDisplay(order);
            } else {
                renderPedidos({ pedidos: [] });
                updateTotalDisplay({});
            }
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
                    <div class="item-stock" id="table-stock-${item.product_id}">Estoque: <strong>${item.product_stock}</strong></div>
                </div>
                <div class="item-actions">
                    <button class="btn-remove" onclick="removeItemFromRound(${item.product_id}, ${pedido.id})">-</button>
                    <span class="qty">${item.quantity}</span>
                    <button class="btn-add" id="table-add-btn-${item.product_id}" onclick="addItemToRound(${item.product_id}, ${pedido.id})" ${item.product_stock <= 0 ? 'disabled' : ''}>+</button>
                </div>
            </div>
            `;
        }).join('');

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
let currentPedidoCategory = 'TODOS';
let currentPedidoSearch = '';
let pedidoShowOnlyInStock = true;
let pedidoObservation = '';
let pedidoReserved = false;

let pendingOrderCancelling = false;

function showAddPedidoModal() {
    Promise.all([
        apiFetch(API_BASE + '/produtos').then(r => r.json()),
        apiFetch(API_BASE + '/categorias').then(r => r.json()),
        apiFetch(API_BASE + '/comanda/' + currentOrderId + '/pendentes').then(r => r.json())
    ])
        .then(([products, categories, pending]) => {
            pedidoQuantities = {};
            pedidoInitialStock = {};
            pedidoProductsData = products;
            currentPedidoCategory = 'TODOS';
            currentPedidoSearch = '';
            pedidoObservation = '';

            const pendingMap = {};
            (pending.items || []).forEach(item => {
                pendingMap[item.product_id] = item.quantity;
            });
            pedidoReserved = (pending.items || []).length > 0;

            products.forEach(p => {
                const pendingQty = pendingMap[p.id] || 0;
                pedidoQuantities[p.id] = pendingQty;
                // initial stock is the real available stock plus what is already reserved
                pedidoInitialStock[p.id] = p.stock + pendingQty;
            });

            pedidoSelectionHtml = buildPedidoSelectionView(products, categories);
            document.getElementById('pedido-modal-content').innerHTML = pedidoSelectionHtml;
            applyPedidoFilters();
            document.getElementById('add-pedido-modal').style.display = 'flex';
        });
}

function buildPedidoSelectionView(products, categories) {
    const categoryList = (categories || []).sort((a, b) => a.name.localeCompare(b.name));
    const categoryButtons = categoryList.map(c =>
        `<button type="button" class="category-btn" data-category="${c.name}" onclick="filterPedidoCategory(this)">${c.name}</button>`
    ).join('');

    const listHtml = products.map(p => {
        const hasDiscount = p.discounted_price !== undefined && p.discounted_price < p.price;
        const priceHtml = hasDiscount
            ? `<div class="prod-price"><span class="prod-original-price">${formatCurrency(p.price)}</span> ${formatCurrency(p.discounted_price)} <span class="promo-badge">${p.active_promotion || 'Promoção'}</span></div>`
            : `<div class="prod-price">${formatCurrency(p.price)}</div>`;
        const qty = pedidoQuantities[p.id] || 0;
        const available = (pedidoInitialStock[p.id] || 0) - qty;
        return `
        <div class="pedido-product-row" data-category="${p.category}">
            <div class="prod-info">
                <div class="prod-name">${p.name}</div>
                <div class="prod-stock" id="pstock-${p.id}" data-cat="${p.category}">
                    Estoque: <strong>${available}</strong>
                </div>
                ${priceHtml}
            </div>
            <div class="qty-control">
                <button class="btn-sm btn-sm-remove" onclick="changePedidoQty(${p.id}, -1)">-</button>
                <input type="number" class="qty-input" id="pqty-${p.id}" value="${qty}" min="0" max="${pedidoInitialStock[p.id] || 0}" readonly>
                <button class="btn-sm btn-sm-add" id="padd-btn-${p.id}" onclick="changePedidoQty(${p.id}, 1)" ${available <= 0 ? 'disabled' : ''}>+</button>
            </div>
        </div>
    `;
    }).join('');

    const stockFilterLabel = pedidoShowOnlyInStock ? 'Mostrar todos' : 'Mostrar apenas com estoque';

    return `
        <h3>Novo Pedido</h3>
        <div class="pedido-search-bar">
            <input type="text" id="pedido-search" class="input-field" placeholder="Buscar produto..." oninput="filterPedidoSearch(this.value)">
        </div>
        <div style="display:flex;gap:8px;align-items:center;margin-bottom:8px;flex-wrap:wrap;">
            <button type="button" id="pedido-stock-filter" class="btn-small" onclick="togglePedidoStockFilter()">${stockFilterLabel}</button>
        </div>
        <div class="category-filter">
            <button type="button" class="category-btn active" data-category="TODOS" onclick="filterPedidoCategory(this)">Todos</button>
            ${categoryButtons}
        </div>
        <div class="pedido-product-list" id="pedido-product-list">${listHtml}</div>
        <div style="display:flex;gap:8px;margin-top:12px;">
            <button onclick="reviewPedido()" class="btn-primary-full" style="flex:1;">Revisar Pedido</button>
            <button onclick="closeAddPedidoModal()" class="btn-secondary-full" style="flex:1;">Cancelar</button>
        </div>
        <p id="pedido-error" class="error-msg" style="display:none;"></p>
    `;
}

function applyPedidoFilters() {
    const q = currentPedidoSearch;
    const cat = currentPedidoCategory;
    document.querySelectorAll('#pedido-product-list .pedido-product-row').forEach(row => {
        const name = (row.querySelector('.prod-name')?.textContent || '').toLowerCase();
        const rowCat = row.dataset.category || '';
        const input = row.querySelector('.qty-input');
        const productId = input ? parseInt(input.id.replace('pqty-', '')) : null;
        const stock = productId ? ((pedidoInitialStock[productId] || 0) - (pedidoQuantities[productId] || 0)) : 0;
        const matchesSearch = !q || name.includes(q);
        const matchesCategory = cat === 'TODOS' || rowCat === cat;
        const matchesStock = !pedidoShowOnlyInStock || stock > 0;
        row.style.display = (matchesSearch && matchesCategory && matchesStock) ? '' : 'none';
    });
}

function togglePedidoStockFilter() {
    pedidoShowOnlyInStock = !pedidoShowOnlyInStock;
    const btn = document.getElementById('pedido-stock-filter');
    if (btn) btn.textContent = pedidoShowOnlyInStock ? 'Mostrar todos' : 'Mostrar apenas com estoque';
    applyPedidoFilters();
}

function filterPedidoCategory(btn) {
    currentPedidoCategory = btn.dataset.category;
    const modal = document.getElementById('pedido-modal-content');
    modal.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyPedidoFilters();
}

function filterPedidoSearch(value) {
    currentPedidoSearch = value.toLowerCase().trim();
    applyPedidoFilters();
}

async function changePedidoQty(productId, delta) {
    const btn = document.getElementById('padd-btn-' + productId);
    if (btn) btn.disabled = true;

    try {
        const res = await apiFetch(API_BASE + '/pedido-pendente/item', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, order_id: currentOrderId, product_id: productId, quantity: delta })
        });
        const data = await res.json();
        if (data.error) {
            if (data.error === 'caixa_fechado') {
                showCashRegisterClosedModal();
                return;
            }
            alert(data.error);
            return;
        }

        const currentQty = pedidoQuantities[productId] || 0;
        const newQty = Math.max(0, currentQty + delta);
        pedidoQuantities[productId] = newQty;
        // initial stock = available returned by API + reserved quantity
        pedidoInitialStock[productId] = (data.stock_remaining !== undefined ? data.stock_remaining : 0) + newQty;

        const input = document.getElementById('pqty-' + productId);
        const stockEl = document.getElementById('pstock-' + productId);
        const addBtn = document.getElementById('padd-btn-' + productId);
        const remaining = pedidoInitialStock[productId] - newQty;
        if (input) input.value = newQty;
        if (stockEl) {
            const cat = stockEl.dataset.cat || '';
            stockEl.innerHTML = 'Estoque: <strong>' + remaining + '</strong>' + (cat ? ' | ' + cat : '');
        }
        if (addBtn) addBtn.disabled = remaining <= 0;

        pedidoReserved = Object.values(pedidoQuantities).some(q => q > 0);
        applyPedidoFilters();
    } catch (err) {
        alert('Erro ao atualizar quantidade');
    } finally {
        const addBtn = document.getElementById('padd-btn-' + productId);
        if (addBtn) {
            const remaining = (pedidoInitialStock[productId] || 0) - (pedidoQuantities[productId] || 0);
            addBtn.disabled = remaining <= 0;
        }
    }
}

async function closeAddPedidoModal() {
    if (pendingOrderCancelling) return;
    pendingOrderCancelling = true;

    try {
        await apiFetch(API_BASE + '/pedido-pendente/cancelar', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, order_id: currentOrderId })
        });
    } catch (err) {
        console.error('Erro ao cancelar pedido pendente', err);
    } finally {
        pendingOrderCancelling = false;
        pedidoReserved = false;
        document.getElementById('add-pedido-modal').style.display = 'none';
    }
}

// Release any pending reservation if the waiter leaves the page with the
// order modal open (mobile hardware back button, closing the tab, etc.).
window.addEventListener('pagehide', () => {
    if (!pedidoReserved || typeof TABLE_ID === 'undefined') return;
    try {
        const token = getToken();
        fetch(API_BASE + '/pedido-pendente/cancelar', {
            method: 'POST',
            keepalive: true,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': token ? 'Bearer ' + token : ''
            },
            body: JSON.stringify({ table_id: TABLE_ID, order_id: currentOrderId })
        });
    } catch (err) {
        // Best-effort only; ignore failures during unload.
    }
});

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
        const errorEl = document.getElementById('pedido-error');
        if (errorEl) {
            errorEl.textContent = 'Selecione ao menos 1 item';
            errorEl.style.display = 'block';
        }
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
        <div style="margin-top:12px;">
            <label class="input-label">Observação do pedido</label>
            <textarea id="pedido-observation" class="input-field" rows="2" maxlength="255" placeholder="Ex.: sem cebola, bem passado, sem gelo..." oninput="pedidoObservation = this.value" style="resize:none;width:100%;">${escapeHtml(pedidoObservation)}</textarea>
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
            stockEl.innerHTML = 'Estoque: <strong>' + remaining + '</strong>' + (cat ? ' | ' + cat : '');
        }
        const addBtn = document.getElementById('padd-btn-' + pid);
        if (addBtn) addBtn.disabled = remaining <= 0;
    }
}

async function confirmPedido() {
    try {
        const observationEl = document.getElementById('pedido-observation');
        const observation = (observationEl ? observationEl.value : pedidoObservation).trim();
        const res = await apiFetch(API_BASE + '/pedido-pendente/confirmar', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, order_id: currentOrderId, observation: observation || null })
        });
        const data = await res.json();
        if (data.error) {
            if (data.error === 'caixa_fechado') {
                showCashRegisterClosedModal();
                return;
            }
            const errorEl = document.getElementById('pedido-error');
            if (errorEl) {
                errorEl.textContent = data.error;
                errorEl.style.display = 'block';
            }
            return;
        }
        pedidoObservation = '';
        pedidoReserved = false;
        document.getElementById('add-pedido-modal').style.display = 'none';
        loadTableDetail();
    } catch (err) {
        const errorEl = document.getElementById('pedido-error');
        if (errorEl) {
            errorEl.textContent = 'Erro ao confirmar pedido';
            errorEl.style.display = 'block';
        }
    }
}

// ====== INDIVIDUAL ITEM ADJUSTMENT WITHIN A ROUND ======
function updateTableItemStockLocal(productId, stock) {
    const stockEl = document.getElementById('table-stock-' + productId);
    const addBtn = document.getElementById('table-add-btn-' + productId);
    if (stockEl) {
        stockEl.innerHTML = 'Estoque: <strong>' + Math.max(0, stock) + '</strong>';
    }
    if (addBtn) {
        addBtn.disabled = stock <= 0;
    }
}

async function addItemToRound(productId, roundId) {
    try {
        const res = await apiFetch(API_BASE + '/comanda/item', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, order_id: currentOrderId, product_id: productId, quantity: 1, order_round_id: roundId })
        });
        const data = await res.json();
        if (data.error) {
            if (data.error === 'caixa_fechado') {
                showCashRegisterClosedModal();
                return;
            }
            alert(data.error);
            return;
        }
        await loadTableDetail();
        if (data.stock_remaining !== undefined) {
            updateTableItemStockLocal(productId, data.stock_remaining);
        }
    } catch (err) { alert('Erro ao adicionar item'); }
}

async function removeItemFromRound(productId, roundId) {
    try {
        const res = await apiFetch(API_BASE + '/comanda/item', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID, order_id: currentOrderId, product_id: productId, quantity: -1, order_round_id: roundId })
        });
        const data = await res.json();
        if (data.error) {
            if (data.error === 'caixa_fechado') {
                showCashRegisterClosedModal();
                return;
            }
            alert(data.error);
            return;
        }
        await loadTableDetail();
        if (data.stock_remaining !== undefined) {
            updateTableItemStockLocal(productId, data.stock_remaining);
        }
    } catch (err) { alert('Erro ao remover item'); }
}

// ====== PARTIAL PAYMENT ======
let partialPaymentMode = 'value'; // 'value' | 'items'

function paidItemsKey() {
    return 'lads_paid_items_' + (typeof TABLE_ID !== 'undefined' ? TABLE_ID : '0') + '_' + (currentOrderId || '0');
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

function getCurrentOrderPedidos() {
    const order = getCurrentOrder();
    return order ? order.pedidos : (currentTableData ? currentTableData.pedidos : []);
}

function countPaidItems() {
    const pedidos = getCurrentOrderPedidos();
    if (!pedidos) return 0;
    const state = loadPaidQtyMap();
    let count = 0;
    pedidos.forEach(p => p.items.forEach(i => {
        if ((state[String(i.id)] || 0) >= i.quantity) count++;
    }));
    return count;
}

function countTotalItems() {
    const pedidos = getCurrentOrderPedidos();
    if (!pedidos) return 0;
    let count = 0;
    pedidos.forEach(p => count += p.items.length);
    return count;
}

function getRemainingAmount(includeServiceCharge = false) {
    const order = getCurrentOrder() || currentTableData || {};
    const total = order.total || 0;
    const paid = order.partial_payment || 0;
    const serviceChargePct = getSettingFloat('service_charge_pct', 10);
    const remainingProduct = Math.max(0, total - paid);
    const remainingService = includeServiceCharge ? remainingProduct * (serviceChargePct / 100) : 0;
    return {
        product: remainingProduct,
        service: remainingService,
        total: remainingProduct + remainingService
    };
}

function switchPartialMode(mode) {
    partialPaymentMode = mode;
    document.getElementById('tab-by-value').classList.toggle('active', mode === 'value');
    document.getElementById('tab-by-items').classList.toggle('active', mode === 'items');
    document.getElementById('partial-value-mode').style.display = mode === 'value' ? 'block' : 'none';
    document.getElementById('partial-items-mode').style.display = mode === 'items' ? 'block' : 'none';
    updatePartialPaymentSummary();
}

function renderPartialPaymentItems() {
    const container = document.getElementById('partial-payment-items');
    const pedidos = getCurrentOrderPedidos();
    if (!container || !pedidos) return;

    const state = loadPaidQtyMap();
    let rowsHtml = '';
    let hasUnpaid = false;

    pedidos.forEach(pedido => {
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
                        <button class="btn-sm btn-sm-remove" onclick="adjustPartialPaidQty(${item.id}, -1, ${unpaidQty}, ${item.unit_price})">-</button>
                        <span class="qty-input" id="pp-qty-${item.id}" style="display:inline-flex;align-items:center;justify-content:center;width:48px;padding:8px 0;text-align:center;background:var(--bg);border:1px solid var(--border);border-radius:8px;color:var(--text);font-size:15px;font-weight:700;" data-unit-price="${item.unit_price}">0</span>
                        <button class="btn-sm btn-sm-add" onclick="adjustPartialPaidQty(${item.id}, 1, ${unpaidQty}, ${item.unit_price})">+</button>
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

    container.innerHTML = rowsHtml;
}

function adjustPartialPaidQty(itemId, delta, maxQty, unitPrice) {
    const el = document.getElementById('pp-qty-' + itemId);
    if (!el) return;
    let qty = parseInt(el.textContent || '0') + delta;
    if (qty < 0) qty = 0;
    if (qty > maxQty) qty = maxQty;
    el.textContent = qty;
    updatePartialPaymentSummary();
}

function getItemsPaymentSubtotal() {
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
    return { subtotal, itemsToPay };
}

function populateCardMachineSelect(prefix) {
    const machine1Name = getSetting('card_machine_1_name', 'Maquininha 1');
    const machine2Name = getSetting('card_machine_2_name', 'Maquininha 2');
    const select = document.getElementById(prefix + '-card-machine');
    if (select) {
        select.innerHTML = `
            <option value="1">${escapeHtml(machine1Name)}</option>
            <option value="2">${escapeHtml(machine2Name)}</option>
        `;
    }
}

function isCardMethod(method) {
    return method === 'cartao_credito' || method === 'cartao_debito';
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function showPartialPaymentModal() {
    const order = getCurrentOrder();
    if (!order) return;

    document.getElementById('partial-total-account').textContent = formatCurrency(order.total || 0);
    document.getElementById('partial-already-paid').textContent = formatCurrency((order.partial_payment || 0) + (order.partial_service_charge || 0));

    document.getElementById('partial-deduct-amount').value = '';
    document.getElementById('partial-tendered-amount').value = '';
    document.getElementById('partial-payment-method').value = 'dinheiro';
    document.getElementById('partial-service-charge').checked = false;

    populateCardMachineSelect('partial');
    renderPartialPaymentItems();
    switchPartialMode('value');
    document.getElementById('partial-payment-modal').style.display = 'flex';
}

function updatePartialPaymentSummary() {
    const applyService = document.getElementById('partial-service-charge')?.checked || false;
    const remaining = getRemainingAmount(applyService);
    document.getElementById('partial-remaining').textContent = formatCurrency(remaining.total);

    let amount = 0;
    if (partialPaymentMode === 'value') {
        amount = parseFloat(document.getElementById('partial-deduct-amount')?.value || 0);
    } else {
        const { subtotal } = getItemsPaymentSubtotal();
        const serviceChargePct = getSettingFloat('service_charge_pct', 10);
        amount = applyService ? subtotal * (1 + serviceChargePct / 100) : subtotal;
        document.getElementById('partial-selected-total').textContent = formatCurrency(amount);
    }

    const method = document.getElementById('partial-payment-method')?.value || 'dinheiro';
    const cashSection = document.getElementById('partial-cash-section');
    const machineSection = document.getElementById('partial-card-machine-section');
    if (cashSection) cashSection.style.display = method === 'dinheiro' ? 'block' : 'none';
    if (machineSection) machineSection.style.display = isCardMethod(method) ? 'block' : 'none';

    const tenderedInput = document.getElementById('partial-tendered-amount');
    const tendered = parseFloat(tenderedInput?.value || 0);

    if (method === 'dinheiro' && tenderedInput) {
        const change = Math.max(0, tendered - amount);
        document.getElementById('partial-change').textContent = formatCurrency(change);
    }
}

function closePartialPaymentModal() {
    document.getElementById('partial-payment-modal').style.display = 'none';
}

async function submitPartialPayment() {
    const method = document.getElementById('partial-payment-method')?.value || 'dinheiro';
    const tenderedInput = document.getElementById('partial-tendered-amount');
    const applyService = document.getElementById('partial-service-charge')?.checked || false;
    const cardMachine = isCardMethod(method) ? (document.getElementById('partial-card-machine')?.value || '1') : null;
    const errorEl = document.getElementById('partial-payment-error');

    let amount = 0;
    let itemsToPay = [];

    if (partialPaymentMode === 'value') {
        amount = parseFloat(document.getElementById('partial-deduct-amount')?.value || 0);
        if (amount <= 0) {
            errorEl.textContent = 'Informe o valor a abater';
            errorEl.style.display = 'block';
            return;
        }
    } else {
        const itemsResult = getItemsPaymentSubtotal();
        amount = itemsResult.subtotal;
        itemsToPay = itemsResult.itemsToPay;
        if (amount <= 0) {
            errorEl.textContent = 'Selecione ao menos um item';
            errorEl.style.display = 'block';
            return;
        }
        if (applyService) {
            const serviceChargePct = getSettingFloat('service_charge_pct', 10);
            amount = amount * (1 + serviceChargePct / 100);
        }
    }

    const tendered = parseFloat(tenderedInput?.value || 0);
    const remaining = getRemainingAmount(applyService);

    if (amount > remaining.total + 0.01) {
        errorEl.textContent = 'O valor não pode ser maior que o restante da conta';
        errorEl.style.display = 'block';
        return;
    }

    if (method === 'dinheiro' && tendered > 0 && tendered < amount) {
        errorEl.textContent = 'O valor pago em dinheiro não pode ser menor que o valor a abater';
        errorEl.style.display = 'block';
        return;
    }

    try {
        const res = await apiFetch(API_BASE + '/comanda/pagamento-parcial', {
            method: 'POST',
            body: JSON.stringify({
                table_id: TABLE_ID,
                order_id: currentOrderId,
                amount: round(amount, 2),
                payment_method: method,
                card_machine: cardMachine,
                apply_service_charge: applyService
            })
        });
        const rawText = await res.text();
        let data = {};
        try { data = JSON.parse(rawText); } catch (e) {
            console.error('Resposta não é JSON:', rawText);
            throw new Error('Resposta inesperada do servidor');
        }
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        itemsToPay.forEach(({ itemId, qty }) => addPaidQty(itemId, qty));
        closePartialPaymentModal();
        loadTableDetail();
    } catch (err) {
        console.error('Erro pagamento parcial:', err);
        errorEl.textContent = 'Erro ao registrar pagamento: ' + (err.message || 'tente novamente');
        errorEl.style.display = 'block';
    }
}

// ====== OPEN / CLOSE ======
async function setCustomerName() {
    const name = document.getElementById('customer-name-input').value.trim();
    alert(name ? 'Cliente: ' + name : 'Nome opcional');
}

function showNewOrderButton(show) {
    const btn = document.getElementById('btn-new-order');
    if (btn) btn.style.display = show ? 'inline-block' : 'none';
}

function showNewOrderCreateActions(show) {
    const actions = document.getElementById('new-order-create-actions');
    if (actions) actions.style.display = show ? 'flex' : 'none';
}

function startNewOrder() {
    const customerSection = document.getElementById('customer-section');
    if (customerSection) customerSection.style.display = 'block';
    showNewOrderCreateActions(true);
    showNewOrderButton(false);
    const input = document.getElementById('customer-name-input');
    if (input) setTimeout(() => input.focus(), 50);
}

function cancelNewOrder() {
    const customerSection = document.getElementById('customer-section');
    const isTableEmpty = currentTableData && currentTableData.status === 'vazia' && (!currentTableData.orders || currentTableData.orders.length === 0);
    if (customerSection) customerSection.style.display = isTableEmpty ? 'block' : 'none';
    clearSelectedCustomer();
    showNewOrderCreateActions(false);
    showNewOrderButton(true);
}

async function openOrder() {
    const customerName = document.getElementById('customer-name-input').value.trim() || null;
    try {
        const res = await apiFetch(API_BASE + '/comanda/abrir', {
            method: 'POST',
            body: JSON.stringify({
                table_id: TABLE_ID,
                customer_id: selectedTableCustomerId,
                customer_name: selectedTableCustomerId ? null : customerName
            })
        });
        const rawText = await res.text();
        let data = {};
        try { data = JSON.parse(rawText); } catch (e) { throw new Error('Resposta inesperada do servidor'); }
        if (data.error || data.detail) {
            if (data.error === 'caixa_fechado') {
                showCashRegisterClosedModal();
                return;
            }
            alert(data.error || data.detail);
            return;
        }
        selectedTableCustomerId = null;
        const input = document.getElementById('customer-name-input');
        if (input) input.value = '';
        updateSelectedCustomerUI();
        currentOrderId = data.order_id || null;
        loadTableDetail();
    } catch (err) { alert('Erro ao abrir comanda'); }
}

async function createNewOrder() {
    const customerName = document.getElementById('customer-name-input').value.trim() || null;
    try {
        const res = await apiFetch(API_BASE + '/comanda/abrir', {
            method: 'POST',
            body: JSON.stringify({
                table_id: TABLE_ID,
                customer_id: selectedTableCustomerId,
                customer_name: selectedTableCustomerId ? null : customerName
            })
        });
        const rawText = await res.text();
        let data = {};
        try { data = JSON.parse(rawText); } catch (e) { throw new Error('Resposta inesperada do servidor'); }
        if (data.error || data.detail) {
            if (data.error === 'caixa_fechado') {
                showCashRegisterClosedModal();
                return;
            }
            alert(data.error || data.detail);
            return;
        }
        selectedTableCustomerId = null;
        const input = document.getElementById('customer-name-input');
        if (input) input.value = '';
        updateSelectedCustomerUI();
        currentOrderId = data.order_id || null;
        showNewOrderCreateActions(false);
        showNewOrderButton(true);
        loadTableDetail();
    } catch (err) { alert('Erro ao criar nova comanda'); }
}

let closeWaiterCache = [];
let selectedCloseWaiterId = null;

async function loadCloseWaiters() {
    try {
        const res = await apiFetch(API_BASE + '/funcionarios?active_only=true');
        const data = await res.json();
        closeWaiterCache = (data && !data.error) ? data : [];
    } catch (err) {
        closeWaiterCache = [];
    }
}

function searchCloseWaiter(query) {
    const el = document.getElementById('close-waiter-suggestions');
    if (!el) return;
    const q = (query || '').trim().toLowerCase();
    if (!q) {
        el.style.display = 'none';
        return;
    }
    const matches = closeWaiterCache.filter(e => (e.name || '').toLowerCase().includes(q));
    renderCloseWaiterSuggestions(matches);
}

async function showAllCloseWaiters() {
    const input = document.getElementById('close-waiter-input');
    if (input) input.value = '';
    selectedCloseWaiterId = null;
    if (closeWaiterCache.length === 0) await loadCloseWaiters();
    renderCloseWaiterSuggestions(closeWaiterCache);
}

function renderCloseWaiterSuggestions(employees) {
    const el = document.getElementById('close-waiter-suggestions');
    if (!el) return;
    if (!employees || employees.length === 0) {
        el.innerHTML = '<div class="autocomplete-empty">Nenhum funcionário encontrado</div>';
        el.style.display = 'block';
        return;
    }
    el.innerHTML = employees.map(e => `
        <div class="autocomplete-item" onclick="selectCloseWaiter(${e.id})">
            <span>${escapeHtml(e.name)}</span>
            <span class="autocomplete-meta">${escapeHtml(e.role || '')}</span>
        </div>
    `).join('');
    el.style.display = 'block';
}

function selectCloseWaiter(id) {
    const emp = closeWaiterCache.find(e => e.id === id);
    selectedCloseWaiterId = id;
    const input = document.getElementById('close-waiter-input');
    if (input) input.value = emp ? emp.name : '';
    hideCloseWaiterSuggestions();
}

function clearCloseWaiter() {
    selectedCloseWaiterId = null;
    const input = document.getElementById('close-waiter-input');
    if (input) input.value = '';
}

function hideCloseWaiterSuggestions() {
    const el = document.getElementById('close-waiter-suggestions');
    if (el) el.style.display = 'none';
}

document.addEventListener('click', (e) => {
    const section = document.getElementById('close-waiter-section');
    if (section && !section.contains(e.target)) {
        hideCloseWaiterSuggestions();
    }
});

async function showCloseModal() {
    const order = getCurrentOrder();
    if (!order) return;

    const total = order.total || 0;
    const paid = order.partial_payment || 0;
    const paidService = order.partial_service_charge || 0;
    const serviceChargePct = getSettingFloat('service_charge_pct', 10);
    const service = 0;
    const serviceLabel = serviceChargePct + '% Serviço';
    const remainingProduct = Math.max(0, total - paid);
    const remainingService = Math.max(0, service - paidService);
    const final = remainingProduct + remainingService;

    document.getElementById('close-summary').innerHTML = `
        <div class="payment-summary">
            <div class="summary-row"><span>Total Produtos</span><span>${formatCurrency(total)}</span></div>
            <div class="summary-row"><span>${serviceLabel}</span><span id="close-service-display">${formatCurrency(service)}</span></div>
            <div class="summary-row"><span>Já Pago (produtos)</span><span>- ${formatCurrency(paid)}</span></div>
            ${paidService > 0 ? `<div class="summary-row"><span>Já Pago (serviço)</span><span>- ${formatCurrency(paidService)}</span></div>` : ''}
            <div class="summary-row" style="font-weight:700;font-size:15px;color:var(--text);border-top:1px solid var(--border-accent);padding-top:8px;margin-top:6px;">
                <span>Total Final</span><span id="close-final-display" style="color:var(--accent);">${formatCurrency(final)}</span>
            </div>
        </div>
    `;

    document.getElementById('apply-service-charge').checked = false;
    document.getElementById('close-payment-method').value = 'dinheiro';

    populateCardMachineSelect('close');

    document.getElementById('close-tendered-amount').value = remainingProduct.toFixed(2);

    const isManager = hasRole('gerente');
    const waiterSection = document.getElementById('close-waiter-section');
    if (waiterSection) waiterSection.style.display = isManager ? 'block' : 'none';
    selectedCloseWaiterId = null;
    const waiterInput = document.getElementById('close-waiter-input');
    if (waiterInput) waiterInput.value = '';
    hideCloseWaiterSuggestions();
    if (isManager) loadCloseWaiters();

    updateCloseTotal();
    document.getElementById('close-modal').style.display = 'flex';
}

function updateCloseTotal() {
    const order = getCurrentOrder() || currentTableData || {};
    const total = order.total || 0;
    const paid = order.partial_payment || 0;
    const apply = document.getElementById('apply-service-charge').checked;
    const serviceChargePct = getSettingFloat('service_charge_pct', 10);
    const remainingProduct = Math.max(0, total - paid);
    const service = apply ? remainingProduct * (serviceChargePct / 100) : 0;
    const final = remainingProduct + service;

    document.getElementById('close-service-display').textContent = formatCurrency(service);
    document.getElementById('close-final-display').textContent = formatCurrency(final);

    const method = document.getElementById('close-payment-method')?.value || 'dinheiro';
    const cashSection = document.getElementById('close-cash-section');
    const machineSection = document.getElementById('close-card-machine-section');
    if (cashSection) cashSection.style.display = method === 'dinheiro' ? 'block' : 'none';
    if (machineSection) machineSection.style.display = isCardMethod(method) ? 'block' : 'none';

    const tenderedInput = document.getElementById('close-tendered-amount');
    if (method === 'dinheiro' && tenderedInput) {
        const tendered = parseFloat(tenderedInput.value || 0);
        const change = Math.max(0, tendered - final);
        document.getElementById('close-change').textContent = formatCurrency(change);
    }
}

function closeCloseModal() {
    selectedCloseWaiterId = null;
    hideCloseWaiterSuggestions();
    document.getElementById('close-modal').style.display = 'none';
}

function openFiadoFromCloseModal() {
    const order = getCurrentOrder();
    if (!order) return;
    closeCloseModal();
    const currentCustomerId = currentTableData?.customer_id || order.customer_id || null;
    const currentCustomerName = currentTableData?.customer_name || order.customer_name || '';
    showFiadoModal(order.id, currentCustomerId, currentCustomerName);
}

let printReceiptDraft = null;
let printReceiptEditing = false;

function buildPrintReceiptDraftFromOrder(order) {
    const items = [];
    (order.pedidos || []).forEach(pedido => {
        (pedido.items || []).forEach(item => {
            items.push({
                product_name: item.product_name,
                quantity: item.quantity,
                unit_price: item.unit_price,
                subtotal: item.subtotal != null ? item.subtotal : (item.quantity * item.unit_price),
            });
        });
    });

    const total = items.reduce((sum, i) => sum + (Number(i.subtotal) || 0), 0);
    const partialPayment = Number(order.partial_payment || 0);
    const serviceChargePct = Number(order.service_charge_pct || getSettingFloat('service_charge_pct', 10) || 0);
    const remainingProduct = Math.max(0, total - partialPayment);
    const serviceChargeAmount = remainingProduct * (serviceChargePct / 100);
    const finalTotal = remainingProduct + serviceChargeAmount;
    const tableLabel = (currentTableData && currentTableData.label)
        ? currentTableData.label
        : (typeof TABLE_ID !== 'undefined' ? ('Mesa ' + TABLE_ID) : 'Mesa');

    return {
        order_id: order.id,
        table_label: tableLabel,
        customer_name: order.customer_name || '',
        items,
        total: Math.round(total * 100) / 100,
        service_charge_pct: serviceChargePct,
        service_charge_amount: Math.round(serviceChargeAmount * 100) / 100,
        partial_payment: partialPayment,
        final_total: Math.round(finalTotal * 100) / 100,
        payment_method: order.payment_method || '',
        apply_service_charge: serviceChargePct > 0,
    };
}

function recalculatePrintReceiptDraft() {
    if (!printReceiptDraft) return;
    printReceiptDraft.items.forEach(item => {
        const qty = parseFloat(item.quantity) || 0;
        const unit = parseFloat(item.unit_price) || 0;
        item.quantity = qty;
        item.unit_price = unit;
        item.subtotal = Math.round(qty * unit * 100) / 100;
    });
    printReceiptDraft.total = Math.round(
        printReceiptDraft.items.reduce((sum, i) => sum + (Number(i.subtotal) || 0), 0) * 100
    ) / 100;
    const remaining = Math.max(0, printReceiptDraft.total - (printReceiptDraft.partial_payment || 0));
    if (printReceiptDraft.apply_service_charge) {
        const pct = parseFloat(printReceiptDraft.service_charge_pct) || 0;
        printReceiptDraft.service_charge_pct = pct;
        printReceiptDraft.service_charge_amount = Math.round(remaining * (pct / 100) * 100) / 100;
    } else {
        printReceiptDraft.service_charge_amount = 0;
    }
    printReceiptDraft.final_total = Math.round(
        (remaining + (printReceiptDraft.service_charge_amount || 0)) * 100
    ) / 100;
}

function renderPrintReceiptView() {
    if (!printReceiptDraft) return;
    const d = printReceiptDraft;
    const itemsHtml = d.items.length
        ? d.items.map(item => `
            <div class="summary-row" style="align-items:flex-start;">
                <span>${item.quantity}x ${item.product_name}<br>
                    <span style="font-size:11px;color:var(--text-muted);">${formatCurrency(item.unit_price)} cada</span>
                </span>
                <span>${formatCurrency(item.subtotal)}</span>
            </div>
        `).join('')
        : '<p class="empty-msg">Nenhum item na nota</p>';

    document.getElementById('print-receipt-view').innerHTML = `
        <div class="payment-summary" style="margin-bottom:12px;">
            <div class="summary-row"><span>Comanda</span><span>#${d.order_id}</span></div>
            <div class="summary-row"><span>Mesa</span><span>${d.table_label || '-'}</span></div>
            <div class="summary-row"><span>Cliente</span><span>${d.customer_name || '—'}</span></div>
        </div>
        <div class="payment-summary" style="margin-bottom:12px;">
            <div style="font-size:12px;color:var(--text-muted);margin-bottom:8px;font-weight:700;">ITENS</div>
            ${itemsHtml}
        </div>
        <div class="payment-summary">
            <div class="summary-row"><span>Subtotal</span><span>${formatCurrency(d.total)}</span></div>
            ${d.service_charge_amount > 0 ? `<div class="summary-row"><span>Taxa serviço (${d.service_charge_pct}%)</span><span>${formatCurrency(d.service_charge_amount)}</span></div>` : ''}
            ${d.partial_payment > 0 ? `<div class="summary-row"><span>Já pago</span><span>- ${formatCurrency(d.partial_payment)}</span></div>` : ''}
            <div class="summary-row" style="font-weight:700;border-top:1px solid var(--border);padding-top:8px;margin-top:6px;">
                <span>Total a imprimir</span><span style="color:var(--accent);">${formatCurrency(d.final_total)}</span>
            </div>
        </div>
    `;
}

function renderPrintReceiptEdit() {
    if (!printReceiptDraft) return;
    const d = printReceiptDraft;
    const itemsHtml = d.items.map((item, idx) => `
        <div class="print-receipt-edit-row" data-idx="${idx}">
            <input type="text" class="input-field" value="${(item.product_name || '').replace(/"/g, '&quot;')}"
                   placeholder="Nome do item" oninput="updatePrintReceiptItem(${idx}, 'product_name', this.value)">
            <div class="form-row" style="gap:8px;margin-top:6px;">
                <div class="form-col">
                    <label class="input-label">Qtd</label>
                    <input type="number" class="input-field" min="0" step="1" value="${item.quantity}"
                           oninput="updatePrintReceiptItem(${idx}, 'quantity', this.value)">
                </div>
                <div class="form-col">
                    <label class="input-label">Preço unit.</label>
                    <input type="number" class="input-field" min="0" step="0.01" value="${Number(item.unit_price).toFixed(2)}"
                           oninput="updatePrintReceiptItem(${idx}, 'unit_price', this.value)">
                </div>
                <div class="form-col" style="max-width:90px;">
                    <label class="input-label">Subtotal</label>
                    <div style="padding:10px 0;font-weight:700;font-size:13px;">${formatCurrency(item.subtotal)}</div>
                </div>
                <button type="button" class="btn-icon-danger" title="Remover da impressão" onclick="removePrintReceiptItem(${idx})" style="margin-top:18px;"><i class="bi bi-x-lg"></i></button>
            </div>
        </div>
    `).join('');

    document.getElementById('print-receipt-edit').innerHTML = `
        <div class="form-row" style="margin-bottom:10px;">
            <div class="form-col">
                <label class="input-label">Cliente (só na impressão)</label>
                <input type="text" class="input-field" id="print-receipt-customer" value="${(d.customer_name || '').replace(/"/g, '&quot;')}"
                       oninput="printReceiptDraft.customer_name = this.value">
            </div>
            <div class="form-col">
                <label class="input-label">Mesa / local</label>
                <input type="text" class="input-field" id="print-receipt-table" value="${(d.table_label || '').replace(/"/g, '&quot;')}"
                       oninput="printReceiptDraft.table_label = this.value">
            </div>
        </div>
        <div style="margin-bottom:10px;">
            <label class="input-label">Itens da nota (impressão)</label>
            <div id="print-receipt-edit-items">${itemsHtml || '<p class="empty-msg">Nenhum item</p>'}</div>
            <button type="button" onclick="addPrintReceiptItem()" class="btn-secondary-full" style="margin-top:8px;">+ Adicionar linha</button>
        </div>
        <div style="margin-bottom:10px;">
            <label style="display:flex;align-items:center;gap:10px;font-size:14px;cursor:pointer;">
                <input type="checkbox" id="print-receipt-service" ${d.apply_service_charge ? 'checked' : ''}
                       onchange="updatePrintReceiptService(this.checked)" style="width:18px;height:18px;accent-color:var(--accent);">
                Incluir taxa de serviço (${d.service_charge_pct || 0}%)
            </label>
        </div>
        <div class="payment-summary">
            <div class="summary-row"><span>Subtotal</span><span id="print-edit-total">${formatCurrency(d.total)}</span></div>
            <div class="summary-row" id="print-edit-service-row" style="${d.service_charge_amount > 0 ? '' : 'display:none;'}">
                <span>Taxa serviço</span><span id="print-edit-service">${formatCurrency(d.service_charge_amount)}</span>
            </div>
            ${d.partial_payment > 0 ? `<div class="summary-row"><span>Já pago</span><span>- ${formatCurrency(d.partial_payment)}</span></div>` : ''}
            <div class="summary-row" style="font-weight:700;border-top:1px solid var(--border);padding-top:8px;margin-top:6px;">
                <span>Total a imprimir</span><span id="print-edit-final" style="color:var(--accent);">${formatCurrency(d.final_total)}</span>
            </div>
        </div>
    `;
}

function updatePrintReceiptItem(idx, field, value) {
    if (!printReceiptDraft || !printReceiptDraft.items[idx]) return;
    if (field === 'product_name') {
        printReceiptDraft.items[idx].product_name = value;
    } else if (field === 'quantity') {
        printReceiptDraft.items[idx].quantity = parseFloat(value) || 0;
    } else if (field === 'unit_price') {
        printReceiptDraft.items[idx].unit_price = parseFloat(value) || 0;
    }
    recalculatePrintReceiptDraft();
    const row = document.querySelector(`.print-receipt-edit-row[data-idx="${idx}"]`);
    if (row) {
        const sub = row.querySelector('.form-col:nth-child(3) div');
        if (sub) sub.textContent = formatCurrency(printReceiptDraft.items[idx].subtotal);
    }
    const totalEl = document.getElementById('print-edit-total');
    const serviceEl = document.getElementById('print-edit-service');
    const serviceRow = document.getElementById('print-edit-service-row');
    const finalEl = document.getElementById('print-edit-final');
    if (totalEl) totalEl.textContent = formatCurrency(printReceiptDraft.total);
    if (serviceEl) serviceEl.textContent = formatCurrency(printReceiptDraft.service_charge_amount);
    if (serviceRow) serviceRow.style.display = printReceiptDraft.service_charge_amount > 0 ? '' : 'none';
    if (finalEl) finalEl.textContent = formatCurrency(printReceiptDraft.final_total);
}

function removePrintReceiptItem(idx) {
    if (!printReceiptDraft) return;
    printReceiptDraft.items.splice(idx, 1);
    recalculatePrintReceiptDraft();
    renderPrintReceiptEdit();
}

function addPrintReceiptItem() {
    if (!printReceiptDraft) return;
    printReceiptDraft.items.push({
        product_name: '',
        quantity: 1,
        unit_price: 0,
        subtotal: 0,
    });
    renderPrintReceiptEdit();
}

function updatePrintReceiptService(checked) {
    if (!printReceiptDraft) return;
    printReceiptDraft.apply_service_charge = !!checked;
    if (checked && !(printReceiptDraft.service_charge_pct > 0)) {
        printReceiptDraft.service_charge_pct = getSettingFloat('service_charge_pct', 10);
    }
    recalculatePrintReceiptDraft();
    renderPrintReceiptEdit();
}

function togglePrintReceiptEdit(editing) {
    printReceiptEditing = !!editing;
    document.getElementById('print-receipt-view').style.display = editing ? 'none' : 'block';
    document.getElementById('print-receipt-edit').style.display = editing ? 'block' : 'none';
    document.getElementById('print-receipt-edit-btn').style.display = editing ? 'none' : '';
    document.getElementById('print-receipt-back-btn').style.display = editing ? '' : 'none';
    document.getElementById('print-receipt-title').textContent = editing ? 'Modificar Nota (só impressão)' : 'Prévia da Nota';
    document.getElementById('print-receipt-error').style.display = 'none';
    if (editing) {
        renderPrintReceiptEdit();
    } else {
        recalculatePrintReceiptDraft();
        renderPrintReceiptView();
    }
    setTimeout(updateScrollHelperVisibility, 50);
}

function showPrintReceiptModal() {
    const order = getCurrentOrder();
    if (!order) {
        alert('Nenhuma comanda selecionada');
        return;
    }
    printReceiptDraft = buildPrintReceiptDraftFromOrder(order);
    printReceiptEditing = false;
    document.getElementById('print-receipt-error').style.display = 'none';
    togglePrintReceiptEdit(false);
    document.getElementById('print-receipt-modal').style.display = 'flex';
    setTimeout(updateScrollHelperVisibility, 50);
}

function closePrintReceiptModal() {
    document.getElementById('print-receipt-modal').style.display = 'none';
    printReceiptDraft = null;
    printReceiptEditing = false;
}

async function printOrderReceipt() {
    showPrintReceiptModal();
}

async function confirmPrintReceipt() {
    if (!printReceiptDraft) return;
    const errorEl = document.getElementById('print-receipt-error');
    errorEl.style.display = 'none';

    if (printReceiptEditing) {
        recalculatePrintReceiptDraft();
    }

    const items = (printReceiptDraft.items || [])
        .filter(i => (parseFloat(i.quantity) || 0) > 0 && (i.product_name || '').trim())
        .map(i => ({
            product_name: (i.product_name || '').trim(),
            quantity: parseFloat(i.quantity) || 0,
            unit_price: parseFloat(i.unit_price) || 0,
            subtotal: parseFloat(i.subtotal) || 0,
        }));

    if (items.length === 0) {
        errorEl.textContent = 'A nota precisa ter ao menos 1 item válido';
        errorEl.style.display = 'block';
        return;
    }

    recalculatePrintReceiptDraft();
    const payload = {
        items,
        customer_name: printReceiptDraft.customer_name || '',
        table_label: printReceiptDraft.table_label || '',
        total: printReceiptDraft.total,
        service_charge_pct: printReceiptDraft.apply_service_charge ? printReceiptDraft.service_charge_pct : 0,
        service_charge_amount: printReceiptDraft.apply_service_charge ? printReceiptDraft.service_charge_amount : 0,
        partial_payment: printReceiptDraft.partial_payment || 0,
        final_total: printReceiptDraft.final_total,
        payment_method: printReceiptDraft.payment_method || null,
    };

    try {
        const res = await apiFetch(API_BASE + '/comanda/' + printReceiptDraft.order_id + '/imprimir-nota', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closePrintReceiptModal();
        alert(data.message || 'Nota enviada para impressora');
    } catch (err) {
        errorEl.textContent = 'Erro ao imprimir nota';
        errorEl.style.display = 'block';
    }
}

function showCashRegisterClosedModal() {
    document.getElementById('cash-register-initial').value = '';
    document.getElementById('cash-register-closed-error').style.display = 'none';
    document.getElementById('cash-register-closed-modal').style.display = 'flex';
}

function closeCashRegisterClosedModal() {
    document.getElementById('cash-register-closed-modal').style.display = 'none';
}

async function openCashRegisterFromTable() {
    const input = document.getElementById('cash-register-initial');
    const errorEl = document.getElementById('cash-register-closed-error');
    const initialCash = parseFloat(input?.value || 0);

    if (isNaN(initialCash) || initialCash < 0) {
        errorEl.textContent = 'Informe um valor inicial válido';
        errorEl.style.display = 'block';
        return;
    }

    try {
        const res = await apiFetch(API_BASE + '/caixa/abrir', {
            method: 'POST',
            body: JSON.stringify({ initial_cash: initialCash })
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closeCashRegisterClosedModal();
        alert('Caixa aberto com sucesso! Você pode continuar lançando pedidos.');
    } catch (err) {
        errorEl.textContent = 'Erro ao abrir caixa';
        errorEl.style.display = 'block';
    }
}

async function confirmClose() {
    const applyServiceCharge = document.getElementById('apply-service-charge').checked;
    const paymentMethod = document.getElementById('close-payment-method').value;
    const cardMachine = isCardMethod(paymentMethod) ? (document.getElementById('close-card-machine')?.value || '1') : null;
    const errorEl = document.getElementById('close-error');
    const tenderedInput = document.getElementById('close-tendered-amount');
    const tendered = tenderedInput ? parseFloat(tenderedInput.value) : 0;

    try {
        const res = await apiFetch(API_BASE + '/comanda/fechar', {
            method: 'POST',
            body: JSON.stringify({
                table_id: TABLE_ID,
                order_id: currentOrderId,
                apply_service_charge: applyServiceCharge,
                payment_method: paymentMethod,
                card_machine: cardMachine,
                amount: paymentMethod === 'dinheiro' ? tendered : null,
                waiter_id: selectedCloseWaiterId || null
            })
        });
        const data = await res.json();
        if (data.error || data.detail) {
            errorEl.textContent = data.error || data.detail || 'Erro ao fechar comanda';
            errorEl.style.display = 'block';
            return;
        }
        let alertMsg = 'Comanda fechada!\nTotal: ' + formatCurrency(data.total);
        if (data.service_charge_amount > 0) alertMsg += '\n+' + data.service_charge_pct + '% serviço: ' + formatCurrency(data.service_charge_amount);
        if (data.partial_payment > 0) alertMsg += '\n- Pago produtos: ' + formatCurrency(data.partial_payment);
        if (data.partial_service_charge > 0) alertMsg += '\n- Pago serviço: ' + formatCurrency(data.partial_service_charge);
        alertMsg += '\nFinal: ' + formatCurrency(data.final_total);
        alertMsg += '\nForma: ' + (data.payment_method || 'N/A');
        alert(alertMsg);
        closeCloseModal();
        loadTableDetail();
    } catch (err) {
        errorEl.textContent = 'Erro ao fechar comanda';
        errorEl.style.display = 'block';
    }
}

// ====== CATEGORIES ======
let categoriesCache = [];
let editingCategoryId = null;

async function loadCategories() {
    try {
        const res = await apiFetch(API_BASE + '/categorias');
        categoriesCache = await res.json();
    } catch (err) {
        categoriesCache = [];
    }
}

function getCategories() {
    return categoriesCache;
}

function renderCategorySelect(selected = '') {
    const select = document.getElementById('product-category');
    if (!select) return;
    const current = select.value || selected;
    select.innerHTML = '<option value="">Selecione uma categoria...</option>';
    categoriesCache.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.name;
        opt.textContent = c.name + (c.printer ? ` (${c.printer === 'cozinha' ? 'Cozinha' : 'Bar'})` : '');
        if (c.name === current) opt.selected = true;
        select.appendChild(opt);
    });
}

async function renderStockCategoryFilter() {
    const select = document.getElementById('filter-category');
    if (!select) return;
    const current = select.value;
    select.innerHTML = '<option value="">Todas Categorias</option>';
    categoriesCache.forEach(c => {
        const opt = document.createElement('option');
        opt.value = c.name;
        opt.textContent = c.name;
        if (c.name === current) opt.selected = true;
        select.appendChild(opt);
    });
}

function renderCategoryList() {
    const container = document.getElementById('category-list');
    if (!container) return;
    if (categoriesCache.length === 0) {
        container.innerHTML = '<div class="text-muted" style="padding:10px 0;">Nenhuma categoria cadastrada.</div>';
        return;
    }
    container.innerHTML = categoriesCache.map(c => `
        <div class="category-row">
            <div class="category-info">
                <div class="category-name">${c.name}</div>
                <div class="category-printer">${c.printer ? (c.printer === 'cozinha' ? 'Impressora: Cozinha' : 'Impressora: Bar') : 'Impressora: Automática'}</div>
            </div>
            <div style="display:flex;gap:6px;flex-shrink:0;">
                <button onclick="startEditCategory(${c.id})" class="btn-small" title="Editar" style="padding:8px 12px;"><i class="bi bi-pencil"></i></button>
                <button onclick="deleteCategory(${c.id})" class="btn-icon-danger" title="Excluir"><i class="bi bi-x-lg"></i></button>
            </div>
        </div>
    `).join('');
}

function setCategoryFormMode(isEdit) {
    const label = document.getElementById('category-form-label');
    const submitBtn = document.getElementById('category-submit-btn');
    const cancelBtn = document.getElementById('category-cancel-btn');
    if (!label || !submitBtn || !cancelBtn) return;
    label.textContent = isEdit ? 'Editar Categoria' : 'Nova Categoria';
    submitBtn.textContent = isEdit ? 'Salvar Alterações' : 'Adicionar Categoria';
    cancelBtn.style.display = isEdit ? 'block' : 'none';
}

function startEditCategory(categoryId) {
    const category = categoriesCache.find(c => c.id === categoryId);
    if (!category) return;
    editingCategoryId = categoryId;
    document.getElementById('new-category-name').value = category.name;
    document.getElementById('new-category-printer').value = category.printer || '';
    setCategoryFormMode(true);
    const errorEl = document.getElementById('category-error');
    if (errorEl) errorEl.style.display = 'none';
}

function cancelEditCategory() {
    editingCategoryId = null;
    document.getElementById('new-category-name').value = '';
    document.getElementById('new-category-printer').value = '';
    setCategoryFormMode(false);
    const errorEl = document.getElementById('category-error');
    if (errorEl) errorEl.style.display = 'none';
}

async function showCategoryModal() {
    await loadCategories();
    renderCategoryList();
    editingCategoryId = null;
    document.getElementById('new-category-name').value = '';
    document.getElementById('new-category-printer').value = '';
    setCategoryFormMode(false);
    const errorEl = document.getElementById('category-error');
    if (errorEl) errorEl.style.display = 'none';
    document.getElementById('category-modal').style.display = 'flex';
}

function closeCategoryModal() {
    document.getElementById('category-modal').style.display = 'none';
    editingCategoryId = null;
}

async function submitNewCategory() {
    const nameInput = document.getElementById('new-category-name');
    const printerInput = document.getElementById('new-category-printer');
    const errorEl = document.getElementById('category-error');
    const name = nameInput.value.trim();
    if (!name) {
        errorEl.textContent = 'Nome da categoria é obrigatório';
        errorEl.style.display = 'block';
        return;
    }
    try {
        const url = API_BASE + '/categorias' + (editingCategoryId ? '/' + editingCategoryId : '');
        const method = editingCategoryId ? 'PUT' : 'POST';
        const res = await apiFetch(url, {
            method,
            body: JSON.stringify({ name, printer: printerInput.value || null })
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        nameInput.value = '';
        printerInput.value = '';
        errorEl.style.display = 'none';
        editingCategoryId = null;
        setCategoryFormMode(false);
        await loadCategories();
        renderCategoryList();
        renderCategorySelect();
        renderStockCategoryFilter();
    } catch (err) {
        errorEl.textContent = editingCategoryId ? 'Erro ao atualizar categoria' : 'Erro ao criar categoria';
        errorEl.style.display = 'block';
    }
}

async function deleteCategory(categoryId) {
    if (!confirm('Excluir esta categoria? Produtos vinculados não serão afetados, mas ela não aparecerá mais nas listas.')) return;
    try {
        const res = await apiFetch(API_BASE + '/categorias/' + categoryId, { method: 'DELETE' });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        await loadCategories();
        renderCategoryList();
        renderCategorySelect();
        renderStockCategoryFilter();
    } catch (err) { alert('Erro ao excluir categoria'); }
}

// ====== STOCK ======
async function loadStock() {
    const container = document.getElementById('stock-items');
    if (!container) return;
    const category = document.getElementById('filter-category')?.value || '';
    const status = document.getElementById('filter-status')?.value || '';
    const search = document.getElementById('filter-search')?.value || '';
    const sort = document.getElementById('sort-by')?.value || 'name';
    const showInactive = document.getElementById('filter-show-inactive')?.checked || false;
    try {
        if (categoriesCache.length === 0) {
            await loadCategories();
        }
        renderStockCategoryFilter();

        const params = new URLSearchParams();
        if (category) params.set('category', category);
        if (status) params.set('status', status);
        if (search) params.set('search', search);
        if (showInactive) params.set('show_inactive', 'true');
        params.set('sort', sort);
        const res = await apiFetch(API_BASE + '/estoque?' + params.toString());
        const data = await res.json();
        document.getElementById('count-em_falta').textContent = data.counts.em_falta;
        document.getElementById('count-em_risco').textContent = data.counts.em_risco;
        document.getElementById('count-em_conformidade').textContent = data.counts.em_conformidade;

        document.querySelectorAll('.manager-only').forEach(el => {
            el.style.display = canManageStock() ? 'block' : 'none';
        });

        const showCost = canViewProductCost();
        const canOpenDetail = canManageStock();
        container.innerHTML = data.items.map(p => {
            const costInfo = showCost ? ` | Custo: ${formatCurrency(p.cost)}` : '';
            const clickAttr = canOpenDetail ? `onclick="openProductDetail(${p.id})"` : '';
            const cursorClass = canOpenDetail ? '' : 'readonly';
            const printerLabel = p.printer ? ({ cozinha: 'Cozinha', bar: 'Bar' }[p.printer] || p.printer) : 'Automático';
            const packInfo = p.is_pack
                ? ` | Engradado de ${p.pack_size}x ${p.pack_unit_product_name || 'unidade'} | Estoque unitário não exibido`
                : '';
            const stockLabel = p.is_pack ? 'engradados' : 'unidades';
            const inactiveBadge = !p.active ? '<span style="font-size:10px;background:#666;color:#fff;padding:2px 6px;border-radius:4px;margin-left:6px;">INATIVO</span>' : '';
            return `
            <div class="stock-item-row ${p.active ? '' : 'inactive'} ${cursorClass}" ${clickAttr}>
                <div class="stock-info">
                    <div class="stock-name">${p.code ? '[' + p.code + '] ' : ''}${p.name} ${p.is_pack ? '<span style="font-size:11px;background:var(--accent);color:#000;padding:2px 6px;border-radius:4px;margin-left:6px;">ENGRADADO</span>' : ''}${inactiveBadge}</div>
                    <div class="stock-meta">${p.category} | Mín: ${p.min_stock} | ${p.pct_of_min}%${costInfo} | Venda: ${formatCurrency(p.price)} | Impressora: ${printerLabel}${packInfo}</div>
                </div>
                <div class="stock-qty-col">
                    <span style="font-size:18px;font-weight:700;">${p.stock}</span>
                    <br>
                    <span style="font-size:11px;color:var(--text-muted);">${stockLabel}</span>
                    <br>
                    <span class="stock-badge badge-${p.status}">${{em_falta:'Em Falta',em_risco:'Em Risco',em_conformidade:'OK'}[p.status]}</span>
                </div>
            </div>
        `;
        }).join('');
    } catch (err) {
        container.innerHTML = '<div class="error-msg">Erro ao carregar estoque</div>';
    }
}

let batchProducts = [];
let currentBatchCategory = 'TODOS';
let currentBatchSearch = '';

function showBatchLoad() {
    Promise.all([
        apiFetch(API_BASE + '/produtos?active_only=true').then(r => r.json()),
        apiFetch(API_BASE + '/categorias').then(r => r.json())
    ])
        .then(([products, categories]) => {
            batchProducts = products.map(p => ({ ...p, loadQty: 0 }));
            currentBatchCategory = 'TODOS';
            currentBatchSearch = '';

            const categoryList = (categories || []).sort((a, b) => a.name.localeCompare(b.name));
            const categoryButtons = categoryList.map(c =>
                `<button type="button" class="category-btn" data-category="${c.name}" onclick="filterBatchCategory(this)">${c.name}</button>`
            ).join('');
            const catFilter = document.getElementById('batch-category-filter');
            catFilter.innerHTML = `
                <button type="button" class="category-btn active" data-category="TODOS" onclick="filterBatchCategory(this)">Todos</button>
                ${categoryButtons}
            `;

            const searchInput = document.getElementById('batch-search');
            if (searchInput) searchInput.value = '';

            const container = document.getElementById('batch-items');
            container.innerHTML = batchProducts.map((p, i) => {
                const packBadge = p.is_pack ? `<span style="font-size:10px;background:var(--accent);color:#000;padding:1px 5px;border-radius:4px;margin-left:4px;">ENGRADADO</span>` : '';
                const unitInfo = p.is_pack ? `<span style="color:#888;">(${p.pack_size} un/engradado)</span>` : '';
                return `
                <div class="pedido-product-row batch-product-row" data-category="${p.category || ''}">
                    <div class="prod-info">
                        <div class="prod-name">${p.name}${packBadge}</div>
                        <div class="prod-stock">Estoque atual: <strong>${p.stock}</strong> ${unitInfo}</div>
                    </div>
                    <input type="number" class="qty-input" value="0" min="0"
                           style="width:70px;"
                           onchange="batchProducts[${i}].loadQty = parseInt(this.value) || 0"
                           oninput="batchProducts[${i}].loadQty = parseInt(this.value) || 0">
                </div>
            `;
            }).join('');

            document.getElementById('batch-error').style.display = 'none';
            document.getElementById('batch-modal').style.display = 'flex';
            setTimeout(updateScrollHelperVisibility, 100);
        });
}

function applyBatchFilters() {
    const q = currentBatchSearch;
    const cat = currentBatchCategory;
    document.querySelectorAll('#batch-items .batch-product-row').forEach(row => {
        const name = (row.querySelector('.prod-name')?.textContent || '').toLowerCase();
        const rowCat = row.dataset.category || '';
        const matchesSearch = !q || name.includes(q);
        const matchesCategory = cat === 'TODOS' || rowCat === cat;
        row.style.display = (matchesSearch && matchesCategory) ? '' : 'none';
    });
}

function filterBatchCategory(btn) {
    currentBatchCategory = btn.dataset.category;
    const filter = document.getElementById('batch-category-filter');
    filter.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyBatchFilters();
}

function filterBatchSearch(value) {
    currentBatchSearch = value.toLowerCase().trim();
    applyBatchFilters();
}

function closeBatchLoad() {
    document.getElementById('batch-modal').style.display = 'none';
    currentBatchCategory = 'TODOS';
    currentBatchSearch = '';
}

async function submitBatchLoad() {
    const items = batchProducts.filter(p => p.loadQty > 0).map(p => ({ product_id: p.id, quantity: p.loadQty }));
    if (items.length === 0) {
        const errorEl = document.getElementById('batch-error');
        errorEl.textContent = 'Informe a quantidade de ao menos 1 produto';
        errorEl.style.display = 'block';
        return;
    }
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
    if (cost > 0 && margin >= 0 && margin < 100) {
        const price = cost / (1 - margin / 100);
        document.getElementById('product-price').value = price.toFixed(2);
    }
}

function calculateProductMargin() {
    const cost = parseFloat(document.getElementById('product-cost')?.value) || 0;
    const price = parseFloat(document.getElementById('product-price')?.value) || 0;
    if (cost > 0 && price > 0) {
        const margin = ((price - cost) / price) * 100;
        document.getElementById('product-margin').value = margin.toFixed(2);
    }
}

let packUnitProductsCache = [];
async function loadPackUnitProducts() {
    try {
        const res = await apiFetch(API_BASE + '/produtos?active_only=true');
        const products = await res.json();
        packUnitProductsCache = products.filter(p => !p.is_pack);
    } catch (err) {
        packUnitProductsCache = [];
    }
}

function renderPackUnitSelect(selectedId = null) {
    const select = document.getElementById('product-pack-unit');
    select.innerHTML = '<option value="">Selecione o item unitário</option>';
    packUnitProductsCache.forEach(p => {
        const opt = document.createElement('option');
        opt.value = p.id;
        opt.textContent = `${p.name} (estoque: ${p.stock})`;
        if (selectedId && p.id === selectedId) opt.selected = true;
        select.appendChild(opt);
    });
}

function togglePackFields() {
    const isPack = document.getElementById('product-is-pack').checked;
    document.getElementById('pack-fields').style.display = isPack ? 'block' : 'none';
    const stockInput = document.getElementById('product-stock');
    if (isPack) {
        stockInput.value = '0';
        stockInput.disabled = true;
        stockInput.title = 'Estoque de engradado é calculado pelo item unitário vinculado';
    } else {
        stockInput.disabled = false;
        stockInput.title = '';
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
    await Promise.all([loadProductSuppliers(), loadPackUnitProducts(), loadCategories()]);
    renderCategorySelect();
    try {
        const res = await apiFetch(API_BASE + '/estoque/' + productId);
        const product = await res.json();
        if (product.error) { alert(product.error); return; }

        document.getElementById('product-modal-title').textContent = product.name;
        document.getElementById('product-id').value = product.id;
        document.getElementById('product-code').value = product.code || '';
        document.getElementById('product-name').value = product.name;
        renderCategorySelect(product.category);
        document.getElementById('product-printer').value = product.printer || '';
        document.getElementById('product-cost').value = product.cost ? product.cost.toFixed(2) : '0.00';
        document.getElementById('product-margin').value = product.margin_pct ? product.margin_pct.toFixed(2) : '0.00';
        document.getElementById('product-price').value = product.price ? product.price.toFixed(2) : '0.00';
        document.getElementById('product-stock').value = product.stock;
        document.getElementById('product-min-stock').value = product.min_stock;

        const isPackCheckbox = document.getElementById('product-is-pack');
        isPackCheckbox.checked = !!product.is_pack;
        document.getElementById('product-pack-size').value = product.pack_size || '';
        renderPackUnitSelect(product.pack_unit_product_id);
        togglePackFields();

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
    await Promise.all([loadProductSuppliers(), loadPackUnitProducts(), loadCategories()]);
    renderCategorySelect();
    document.getElementById('product-modal-title').textContent = 'Novo Produto';
    document.getElementById('product-id').value = '';
    document.getElementById('product-code').value = '';
    document.getElementById('product-name').value = '';
    document.getElementById('product-printer').value = '';
    document.getElementById('product-cost').value = '';
    document.getElementById('product-margin').value = '';
    document.getElementById('product-price').value = '';
    document.getElementById('product-stock').value = '';
    document.getElementById('product-min-stock').value = '10';
    document.getElementById('product-is-pack').checked = false;
    document.getElementById('product-pack-size').value = '';
    renderPackUnitSelect(null);
    togglePackFields();

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
    const isPack = document.getElementById('product-is-pack').checked;
    const packUnitId = parseInt(document.getElementById('product-pack-unit').value) || null;
    const packSize = parseInt(document.getElementById('product-pack-size').value) || 0;

    if (isPack) {
        if (!packUnitId) {
            document.getElementById('product-error').textContent = 'Selecione o produto unitário vinculado ao engradado';
            document.getElementById('product-error').style.display = 'block';
            return;
        }
        if (packSize < 2) {
            document.getElementById('product-error').textContent = 'Engradado deve conter pelo menos 2 unidades';
            document.getElementById('product-error').style.display = 'block';
            return;
        }
    }

    const payload = {
        code: document.getElementById('product-code').value.trim() || null,
        name: document.getElementById('product-name').value.trim(),
        category: document.getElementById('product-category').value.trim(),
        printer: document.getElementById('product-printer').value || null,
        cost: parseFloat(document.getElementById('product-cost').value) || 0,
        margin_pct: parseFloat(document.getElementById('product-margin').value) || 0,
        price: parseFloat(document.getElementById('product-price').value) || 0,
        stock: isPack ? 0 : (parseInt(document.getElementById('product-stock').value) || 0),
        min_stock: parseInt(document.getElementById('product-min-stock').value) || 0,
        active: document.getElementById('product-active').checked,
        supplier_ids: Array.from(document.querySelectorAll('.product-supplier-check:checked')).map(cb => parseInt(cb.value)),
        pack_unit_product_id: isPack ? packUnitId : null,
        pack_size: isPack ? packSize : 1,
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
        document.getElementById('dash-today-consignments').textContent = (data.today.consignments || 0) + ' consignados (' + formatCurrency(data.today.consignments_total || 0) + ')';
        document.getElementById('dash-week-total').textContent = formatCurrency(data.week.total);
        document.getElementById('dash-week-count').textContent = data.week.orders + ' comandas';
        document.getElementById('dash-week-consignments').textContent = (data.week.consignments || 0) + ' consignados (' + formatCurrency(data.week.consignments_total || 0) + ')';
        document.getElementById('dash-month-total').textContent = formatCurrency(data.month.total);
        document.getElementById('dash-month-count').textContent = data.month.orders + ' comandas';
        document.getElementById('dash-month-consignments').textContent = (data.month.consignments || 0) + ' consignados (' + formatCurrency(data.month.consignments_total || 0) + ')';
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
            ${data.sales.map((s, idx) => {
                const orderTotal = round(s.total + s.service_charge_amount, 2);
                const remainingPaidAtClose = round(s.final_total, 2);
                const paidInPartials = round(s.partial_payment + s.partial_service_charge, 2);
                return `
                <div class="sale-card" onclick="openSaleDetailModal(${idx})" style="cursor:pointer;">
                    <div class="sale-header">
                        <span class="sale-table">${s.is_balcao ? 'Balcão' : 'Mesa ' + s.table_number}</span>
                        <span class="sale-time">${s.closed_at ? _fmtDateTime(s.closed_at) : ''}</span>
                    </div>
                    <div class="sale-details">
                        <div class="sale-detail"><span>Garçom: ${s.waiter_name || 'N/A'}</span><span>${s.items_count} itens</span></div>
                        ${s.customer_name ? `<div class="sale-detail"><span>Cliente: ${s.customer_name}</span></div>` : ''}
                        <div class="sale-detail"><span>Forma fechamento: ${s.payment_method_label || s.payment_method}</span>${s.card_machine ? `<span style="font-size:11px;">${s.card_machine}</span>` : ''}</span></div>
                        ${paidInPartials > 0 ? `<div class="sale-detail" style="color:var(--accent);"><span>Pago em parciais</span><span>${formatCurrency(paidInPartials)}</span></div>` : ''}
                        ${remainingPaidAtClose > 0 ? `<div class="sale-detail" style="color:var(--green);"><span>Pago no fechamento</span><span>${formatCurrency(remainingPaidAtClose)}</span></div>` : ''}
                        ${s.service_charge_amount > 0 ? `<div class="sale-detail"><span>+ ${s.service_charge_pct}% serviço</span><span>${formatCurrency(s.service_charge_amount)}</span></div>` : ''}
                    </div>
                    <div class="sale-total">${formatCurrency(orderTotal)}</div>
                </div>
                `;
            }).join('')}
        `;
        window._lastSalesData = data.sales;
    } catch (err) { container.innerHTML = '<div class="error-msg">Erro ao carregar vendas</div>'; }
}

function openSaleDetailModal(index) {
    const sales = window._lastSalesData || [];
    const s = sales[index];
    if (!s) return;
    document.getElementById('sale-detail-title').textContent = 'Comanda #' + s.order_id;
    const methodLabels = {
        dinheiro: 'Dinheiro', cartao_credito: 'Crédito',
        cartao_debito: 'Débito', pix: 'Pix', nao_informado: 'Não Informado'
    };
    const formatCard = (m) => m ? ` (${m})` : '';
    const totalPaid = round(s.total + s.service_charge_amount, 2);
    const paidInPartials = round(s.partial_payment + s.partial_service_charge, 2);
    const paidAtClose = round(s.final_total, 2);
    const paymentRows = (s.payment_details || []).map(p => {
        const label = p.method_label || methodLabels[p.method] || p.method;
        const prefix = p.type === 'parcial' ? 'Parcial' : 'Fechamento';
        return `<div class="summary-row"><span>${prefix} - ${label}${formatCard(p.card_machine)}</span><span>${formatCurrency(p.amount)}</span></div>`;
    }).join('');
    const itemRows = (s.items || []).map(i => `
        <div class="summary-row" style="font-size:12px;">
            <span>${i.quantity}x ${i.product_name}</span>
            <span>${formatCurrency(i.total)}</span>
        </div>
    `).join('');
    document.getElementById('sale-detail-content').innerHTML = `
        <div class="report-summary">
            <div class="summary-row"><span>Mesa</span><span>${s.is_balcao ? 'Balcão' : 'Mesa ' + s.table_number}</span></div>
            <div class="summary-row"><span>Garçom</span><span>${s.waiter_name || 'N/A'}</span></div>
            ${s.customer_name ? `<div class="summary-row"><span>Cliente</span><span>${s.customer_name}</span></div>` : ''}
            <div class="summary-row"><span>Itens</span><span>${s.items_count}</span></div>
            <div class="summary-row"><span>Total produtos</span><span>${formatCurrency(s.total)}</span></div>
            ${s.service_charge_amount > 0 ? `<div class="summary-row"><span>Taxa serviço (${s.service_charge_pct}%)</span><span>${formatCurrency(s.service_charge_amount)}</span></div>` : ''}
            <div class="summary-row" style="font-weight:600;"><span>Total pago</span><span>${formatCurrency(totalPaid)}</span></div>
            <div class="summary-row"><span>Hora fechamento</span><span>${s.closed_at ? _fmtDateTime(s.closed_at) : '-'}</span></div>
        </div>
        <h4 style="margin:16px 0 8px;font-size:14px;">Pagamentos</h4>
        <div class="report-summary">
            ${paymentRows || '<p class="empty-msg">Nenhum pagamento registrado</p>'}
            <div class="summary-row" style="border-top:1px solid var(--border);margin-top:6px;padding-top:6px;">
                <span>Pago em parciais</span>
                <span>${formatCurrency(paidInPartials)}</span>
            </div>
            <div class="summary-row">
                <span>Pago no fechamento</span>
                <span>${formatCurrency(paidAtClose)}</span>
            </div>
            <div class="summary-row" style="font-weight:600;">
                <span>Total</span>
                <span>${formatCurrency(totalPaid)}</span>
            </div>
        </div>
        <h4 style="margin:16px 0 8px;font-size:14px;">Itens</h4>
        <div class="report-summary">
            ${itemRows || '<p class="empty-msg">Nenhum item</p>'}
        </div>
    `;
    document.getElementById('sale-detail-modal').style.display = 'flex';
}

function closeSaleDetailModal() {
    document.getElementById('sale-detail-modal').style.display = 'none';
}

let lastReportDate = null;

async function dailyCloseReport() {
    const date = document.getElementById('sale-date-filter')?.value || toLocalDateString(new Date());
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
    lastReportSessionId = null;
    document.getElementById('report-modal-title').textContent = 'Relatório de Fechamento Diário';
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
            <h4>Resultado do Dia</h4>
            <div class="profit-cards">
                <div class="profit-card gross">
                    <span class="profit-label">Lucro Bruto</span>
                    <span class="profit-value">${formatCurrency(data.summary.gross_profit)}</span>
                    <span class="profit-sub">Vendas - Custo dos produtos</span>
                </div>
                <div class="profit-card net">
                    <span class="profit-label">Lucro Líquido</span>
                    <span class="profit-value">${formatCurrency(data.summary.net_profit)}</span>
                    <span class="profit-sub">Lucro bruto - Taxas e despesas</span>
                </div>
            </div>
        </div>

        <div class="report-summary">
            <h4>Resumo Financeiro</h4>
            <div class="summary-row"><span>Vendas Brutas</span><span>${formatCurrency(data.summary.total_sales)}</span></div>
            <div class="summary-row" style="color:var(--red);"><span>Custo dos Produtos Vendidos</span><span>- ${formatCurrency(data.summary.total_cogs)}</span></div>
            <div class="summary-row" style="border-top:1px solid var(--border-color);padding-top:8px;margin-top:8px;font-weight:700;color:var(--green);"><span>Lucro Bruto</span><span>${formatCurrency(data.summary.gross_profit)}</span></div>
            <div style="height:8px;"></div>
            <div class="summary-row" style="color:var(--red);"><span>Taxas de Cartão</span><span>- ${formatCurrency(data.summary.total_card_fees)}</span></div>
            <div class="summary-row" style="color:var(--red);"><span>Despesas / Diárias</span><span>- ${formatCurrency(data.summary.total_expenses)}</span></div>
            ${data.summary.perdas_total ? `<div class="summary-row" style="color:var(--red);font-size:12px;padding-left:12px;"><span>Perdas (saídas manuais)</span><span>- ${formatCurrency(data.summary.perdas_total)}</span></div>` : ''}
            <div class="summary-row" style="font-weight:700;color:var(--accent);"><span>Lucro Líquido</span><span>${formatCurrency(data.summary.net_profit)}</span></div>
            <div style="color:var(--text-muted);font-size:11px;margin-top:12px;">
                ${data.summary.orders_count} comandas${data.summary.consignments_count ? ' + ' + data.summary.consignments_count + ' consignados' : ''}
            </div>
        </div>

        <div class="report-summary">
            <h4>Formas de Pagamento (Bruto / Líquido)</h4>
            ${methodRows}
        </div>

        ${data.expenses && data.expenses.length > 0 ? `
        <div class="report-summary">
            <h4>Despesas e Perdas do Dia</h4>
            ${data.expenses.map(e => `
                <div class="summary-row" style="color:var(--red);"><span>${e.description}</span><span>- ${formatCurrency(e.amount)}</span></div>
            `).join('')}
        </div>
        ` : ''}

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
    let body, filename;
    if (lastReportSessionId) {
        body = JSON.stringify({ session_id: lastReportSessionId });
        filename = `relatorio_ladsbeer_sessao_${lastReportSessionId}.pdf`;
    } else {
        const date = lastReportDate || (document.getElementById('sale-date-filter')?.value || toLocalDateString(new Date()));
        body = JSON.stringify({ date });
        filename = `relatorio_ladsbeer_${date}.pdf`;
    }
    try {
        const res = await apiFetch(API_BASE + '/financeiro/relatorio-pdf', { method: 'POST', body });
        if (!res.ok) {
            const data = await res.json();
            alert(data.error || 'Erro ao gerar PDF');
            return;
        }
        const blob = await res.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        a.remove();
        window.URL.revokeObjectURL(url);
    } catch (err) { alert('Erro ao baixar PDF'); }
}

function closeReport() { document.getElementById('report-modal').style.display = 'none'; }

let activeCashSession = null;

async function loadCashRegisterStatus() {
    if (!canManageCashRegister()) return;
    try {
        const res = await apiFetch(API_BASE + '/caixa/ativo');
        const data = await res.json();
        if (data.error) { showCashMessage(data.error); return; }

        const dot = document.getElementById('cash-status-dot');
        const text = document.getElementById('cash-status-text');
        const info = document.getElementById('cash-register-info');
        const btnOpen = document.getElementById('btn-open-cash');
        const btnSangria = document.getElementById('btn-sangria');
        const btnSuprimento = document.getElementById('btn-suprimento');
        const btnPartial = document.getElementById('btn-partial-report');
        const btnClose = document.getElementById('btn-close-cash');

        activeCashSession = data.active ? data.session : null;

        if (data.active && data.session) {
            dot.className = 'status-dot open';
            text.textContent = 'Caixa Aberto';
            text.style.color = 'var(--green)';
            info.style.display = 'grid';
            document.getElementById('cash-opened-at').textContent = _fmtDateTime(data.session.opened_at);
            document.getElementById('cash-opened-by').textContent = data.session.opened_by;
            document.getElementById('cash-initial').textContent = formatCurrency(data.session.initial_cash);

            const sangria = data.session.total_sangria || 0;
            const suprimento = data.session.total_suprimento || 0;
            const cashInflows = data.session.cash_inflows || 0;
            const expectedCash = data.session.expected_cash || 0;

            const movementLines = [];
            if (cashInflows > 0) movementLines.push(`<div><span class="label">Entradas (dinheiro):</span> <span style="color:var(--green)">+ ${formatCurrency(cashInflows)}</span></div>`);
            if (sangria > 0) movementLines.push(`<div><span class="label">Sangria:</span> <span style="color:var(--red)">- ${formatCurrency(sangria)}</span></div>`);
            if (suprimento > 0) movementLines.push(`<div><span class="label">Suprimento:</span> <span style="color:var(--green)">+ ${formatCurrency(suprimento)}</span></div>`);
            movementLines.push(`<div style="font-weight:600;margin-top:4px;"><span class="label">Caixa esperado:</span> <span>${formatCurrency(expectedCash)}</span></div>`);

            const existingMovementInfo = info.querySelector('.cash-movement-info');
            if (existingMovementInfo) existingMovementInfo.remove();
            if (movementLines.length > 0) {
                const movementDiv = document.createElement('div');
                movementDiv.className = 'cash-movement-info';
                movementDiv.style.gridColumn = '1 / -1';
                movementDiv.style.marginTop = '8px';
                movementDiv.style.paddingTop = '8px';
                movementDiv.style.borderTop = '1px solid var(--border)';
                movementDiv.innerHTML = movementLines.join('');
                info.appendChild(movementDiv);
            }

            btnOpen.style.display = 'none';
            btnSangria.style.display = 'inline-block';
            btnSuprimento.style.display = 'inline-block';
            btnPartial.style.display = 'inline-block';
            btnClose.style.display = 'inline-block';
            showCashMessage('Caixa aberto. As vendas a partir de agora serão contabilizadas nesta sessão.');
        } else {
            dot.className = 'status-dot closed';
            text.textContent = 'Caixa Fechado';
            text.style.color = 'var(--red)';
            info.style.display = 'none';
            btnOpen.style.display = 'inline-block';
            btnSangria.style.display = 'none';
            btnSuprimento.style.display = 'none';
            btnPartial.style.display = 'none';
            btnClose.style.display = 'none';
            showCashMessage('Nenhum caixa aberto. Abra o caixa para iniciar a contabilização do dia.');
        }
    } catch (err) { showCashMessage('Erro ao verificar status do caixa'); }
}

function showCashMessage(msg) {
    const el = document.getElementById('cash-register-message');
    if (el) el.textContent = msg;
}

function _fmtDateTime(iso) {
    if (!iso) return '-';
    const d = new Date(iso);
    return d.toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}

function openCashRegisterModal() {
    document.getElementById('open-cash-modal').style.display = 'flex';
    document.getElementById('open-initial-cash').value = '';
    document.getElementById('open-cash-error').style.display = 'none';
}

function closeOpenCashModal() {
    document.getElementById('open-cash-modal').style.display = 'none';
}

async function submitOpenCashRegister() {
    const initialCash = parseFloat(document.getElementById('open-initial-cash').value || 0);
    const errorEl = document.getElementById('open-cash-error');
    if (isNaN(initialCash) || initialCash < 0) {
        errorEl.textContent = 'Informe um valor inicial válido';
        errorEl.style.display = 'block';
        return;
    }
    try {
        const res = await apiFetch(API_BASE + '/caixa/abrir', { method: 'POST', body: JSON.stringify({ initial_cash: initialCash }) });
        const data = await res.json();
        if (data.error) { errorEl.textContent = data.error; errorEl.style.display = 'block'; return; }
        closeOpenCashModal();
        await loadCashRegisterStatus();
        loadDashboard();
        loadSales();
    } catch (err) {
        errorEl.textContent = 'Erro ao abrir caixa';
        errorEl.style.display = 'block';
    }
}

function closeCashRegisterModal() {
    document.getElementById('close-cash-modal').style.display = 'flex';
    document.getElementById('close-observations').value = '';
    document.getElementById('close-cash-error').style.display = 'none';

    const expectedCash = activeCashSession?.expected_cash ?? 0;
    const finalInput = document.getElementById('close-final-cash');
    finalInput.value = expectedCash > 0 ? expectedCash.toFixed(2) : '';

    let hint = document.getElementById('close-expected-cash-hint');
    if (!hint) {
        hint = document.createElement('p');
        hint.id = 'close-expected-cash-hint';
        hint.className = 'cash-hint';
        hint.style.fontSize = '13px';
        hint.style.color = 'var(--text-muted)';
        hint.style.marginTop = '8px';
        finalInput.parentNode.insertBefore(hint, finalInput.nextSibling);
    }
    hint.textContent = `Caixa esperado: ${formatCurrency(expectedCash)}`;
}

function closeCloseCashModal() {
    document.getElementById('close-cash-modal').style.display = 'none';
}

async function submitCloseCashRegister() {
    const finalCash = parseFloat(document.getElementById('close-final-cash').value || 0);
    const observations = document.getElementById('close-observations').value.trim();
    const errorEl = document.getElementById('close-cash-error');
    if (isNaN(finalCash) || finalCash < 0) {
        errorEl.textContent = 'Informe um valor final válido';
        errorEl.style.display = 'block';
        return;
    }
    try {
        const closeRes = await apiFetch(API_BASE + '/caixa/fechar', { method: 'POST', body: JSON.stringify({ final_cash: finalCash, observations }) });
        const closeData = await closeRes.json();
        if (closeData.error) { errorEl.textContent = closeData.error; errorEl.style.display = 'block'; return; }

        const sessionId = closeData.session?.id;
        const reportRes = await apiFetch(API_BASE + '/financeiro/sessao/' + sessionId + '/relatorio-final');
        const reportData = await reportRes.json();
        if (reportData.error) { alert(reportData.error); return; }

        closeCloseCashModal();
        renderSessionReport(reportData);
        document.getElementById('report-modal').style.display = 'flex';
        await loadCashRegisterStatus();
        loadDashboard();
        loadSales();
    } catch (err) {
        errorEl.textContent = 'Erro ao fechar caixa';
        errorEl.style.display = 'block';
    }
}

async function partialReport() {
    try {
        const res = await apiFetch(API_BASE + '/financeiro/relatorio-parcial', { method: 'POST' });
        const data = await res.json();
        if (data.error) { alert(data.error); return; }
        renderSessionReport(data);
        document.getElementById('report-modal').style.display = 'flex';
    } catch (err) { alert('Erro ao gerar relatório parcial'); }
}

function openSangriaModal() {
    document.getElementById('sangria-modal').style.display = 'flex';
    document.getElementById('sangria-amount').value = '';
    document.getElementById('sangria-note').value = '';
    document.getElementById('sangria-error').style.display = 'none';
}

function closeSangriaModal() {
    document.getElementById('sangria-modal').style.display = 'none';
}

function openSuprimentoModal() {
    document.getElementById('suprimento-modal').style.display = 'flex';
    document.getElementById('suprimento-amount').value = '';
    document.getElementById('suprimento-note').value = '';
    document.getElementById('suprimento-error').style.display = 'none';
}

function closeSuprimentoModal() {
    document.getElementById('suprimento-modal').style.display = 'none';
}

async function submitCashMovement(type) {
    const isSangria = type === 'sangria';
    const amountEl = document.getElementById(isSangria ? 'sangria-amount' : 'suprimento-amount');
    const noteEl = document.getElementById(isSangria ? 'sangria-note' : 'suprimento-note');
    const errorEl = document.getElementById(isSangria ? 'sangria-error' : 'suprimento-error');
    const amount = parseFloat(amountEl.value || 0);

    if (isNaN(amount) || amount <= 0) {
        errorEl.textContent = 'Informe um valor maior que zero';
        errorEl.style.display = 'block';
        return;
    }

    try {
        const res = await apiFetch(API_BASE + '/caixa/movimentacoes', {
            method: 'POST',
            body: JSON.stringify({ type, amount, note: noteEl.value.trim() || null })
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        if (isSangria) closeSangriaModal(); else closeSuprimentoModal();
        await loadCashRegisterStatus();
        showCashMessage((isSangria ? 'Sangria' : 'Suprimento') + ' registrada com sucesso.');
    } catch (err) {
        errorEl.textContent = 'Erro ao registrar movimentação';
        errorEl.style.display = 'block';
    }
}

function renderSessionReport(data) {
    const title = data.report_type === 'final' ? 'Relatório Final de Caixa' : 'Relatório Parcial de Caixa';
    document.getElementById('report-modal-title').textContent = title;

    const session = data.session || {};
    const cash = data.cash_summary || {};
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
        <div class="summary-row"><span>${waiter}</span><span>${formatCurrency(vals.service_charge)}</span></div>
    `).join('');

    const tableRows = Object.entries(data.by_table || {}).map(([table, vals]) => `
        <div class="summary-row"><span>${table}</span><span>${formatCurrency(vals.total)} (${vals.orders})</span></div>
    `).join('');

    const itemRows = (data.items_ranking || []).slice(0, 10).map(item => `
        <div class="summary-row"><span>${item.name}</span><span>${item.quantity}x ${formatCurrency(item.total)}</span></div>
    `).join('');

    const hourRows = Object.entries(data.by_hour || {}).map(([hour, total]) => `
        <div class="summary-row"><span>${hour}</span><span>${formatCurrency(total)}</span></div>
    `).join('');

    const discrepancyHtml = cash.discrepancy !== null && cash.discrepancy !== undefined
        ? `<div class="summary-row" style="font-weight:700;color:${cash.discrepancy >= 0 ? 'var(--green)' : 'var(--red)'};"><span>${cash.discrepancy >= 0 ? 'Sobra' : 'Falta'}</span><span>${formatCurrency(Math.abs(cash.discrepancy))}</span></div>`
        : '<div class="summary-row" style="color:var(--text-muted);"><span>Diferença</span><span>Aguardando fechamento</span></div>';

    document.getElementById('report-content').innerHTML = `
        <p style="color:var(--text-muted);font-size:13px;">
            Caixa: ${_fmtDateTime(session.opened_at)} ${session.closed_at ? 'até ' + _fmtDateTime(session.closed_at) : '(em aberto)'}
            ${session.opened_by ? ' | Aberto por: ' + session.opened_by : ''}
            ${session.closed_by ? ' | Fechado por: ' + session.closed_by : ''}
        </p>

        <div class="report-summary">
            <h4>Resultado do Período</h4>
            <div class="profit-cards">
                <div class="profit-card gross">
                    <span class="profit-label">Lucro Bruto</span>
                    <span class="profit-value">${formatCurrency(data.summary.gross_profit)}</span>
                    <span class="profit-sub">Vendas - Custo dos produtos</span>
                </div>
                <div class="profit-card net">
                    <span class="profit-label">Lucro Líquido</span>
                    <span class="profit-value">${formatCurrency(data.summary.net_profit)}</span>
                    <span class="profit-sub">Lucro bruto - Taxas e despesas</span>
                </div>
            </div>
        </div>

        <div class="report-summary">
            <h4>Resumo Financeiro</h4>
            <div class="summary-row"><span>Vendas Brutas</span><span>${formatCurrency(data.summary.total_sales)}</span></div>
            <div class="summary-row" style="color:var(--red);"><span>Custo dos Produtos Vendidos</span><span>- ${formatCurrency(data.summary.total_cogs)}</span></div>
            <div class="summary-row" style="border-top:1px solid var(--border-color);padding-top:8px;margin-top:8px;font-weight:700;color:var(--green);"><span>Lucro Bruto</span><span>${formatCurrency(data.summary.gross_profit)}</span></div>
            <div style="height:8px;"></div>
            <div class="summary-row"><span>Taxa de Serviço</span><span>${formatCurrency(data.summary.total_service_charge)}</span></div>
            <div class="summary-row" style="color:var(--red);"><span>Taxas de Cartão</span><span>- ${formatCurrency(data.summary.total_card_fees)}</span></div>
            <div class="summary-row" style="color:var(--red);"><span>Despesas / Diárias</span><span>- ${formatCurrency(data.summary.total_expenses)}</span></div>
            ${data.summary.perdas_total ? `<div class="summary-row" style="color:var(--red);font-size:12px;padding-left:12px;"><span>Perdas (saídas manuais)</span><span>- ${formatCurrency(data.summary.perdas_total)}</span></div>` : ''}
            <div class="summary-row" style="font-weight:700;color:var(--accent);"><span>Lucro Líquido</span><span>${formatCurrency(data.summary.net_profit)}</span></div>
            <div style="color:var(--text-muted);font-size:11px;margin-top:12px;">
                ${data.summary.orders_count} comandas${data.summary.consignments_count ? ' + ' + data.summary.consignments_count + ' consignados' : ''}
            </div>
            ${data.summary.consignments_count ? `
            <div style="height:8px;"></div>
            <div class="summary-row"><span>Consignado (período)</span><span>${formatCurrency(data.summary.consignments_total)}</span></div>
            <div class="summary-row" style="color:var(--green);"><span>Pago</span><span>${formatCurrency(data.summary.consignments_paid)}</span></div>
            <div class="summary-row" style="color:var(--red);"><span>Saldo Devedor</span><span>${formatCurrency(data.summary.consignments_balance)}</span></div>
            ` : ''}
        </div>

        <div class="report-summary">
            <h4>Fechamento de Caixa</h4>
            <div class="summary-row"><span>Dinheiro Inicial</span><span>${formatCurrency(cash.initial_cash)}</span></div>
            <div class="summary-row"><span>Entradas em Dinheiro</span><span>${formatCurrency(cash.cash_inflows)}</span></div>
            ${cash.total_sangria ? `<div class="summary-row" style="color:var(--red);"><span>Sangria (cofre)</span><span>- ${formatCurrency(cash.total_sangria)}</span></div>` : ''}
            ${cash.total_suprimento ? `<div class="summary-row" style="color:var(--green);"><span>Suprimento (troco)</span><span>+ ${formatCurrency(cash.total_suprimento)}</span></div>` : ''}
            <div class="summary-row" style="font-weight:700;"><span>Dinheiro Esperado</span><span>${formatCurrency(cash.expected_cash)}</span></div>
            ${cash.final_cash !== null && cash.final_cash !== undefined ? `<div class="summary-row"><span>Dinheiro Contado</span><span>${formatCurrency(cash.final_cash)}</span></div>` : ''}
            ${discrepancyHtml}
        </div>

        <div class="report-summary">
            <h4>Formas de Pagamento (Bruto / Líquido)</h4>
            ${methodRows}
        </div>

        ${data.expenses && data.expenses.length > 0 ? `
        <div class="report-summary">
            <h4>Despesas e Perdas do Período</h4>
            ${data.expenses.map(e => `
                <div class="summary-row" style="color:var(--red);"><span>${e.description}</span><span>- ${formatCurrency(e.amount)}</span></div>
            `).join('')}
        </div>
        ` : ''}

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

    lastReportDate = null;
    lastReportSessionId = session.id || null;
}

let lastReportSessionId = null;

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

        const canManage = canManagePromotions();
        document.querySelectorAll('.promo-manager-only').forEach(el => {
            el.style.display = canManage ? 'block' : 'none';
        });

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

            const actions = canManage ? `
                <div class="promo-actions">
                    <button onclick="editPromotion(${p.id})" class="btn-small">Editar</button>
                    <button onclick="deletePromotion(${p.id})" class="btn-small btn-danger">Excluir</button>
                </div>
            ` : '';

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
                ${actions}
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
    const toLocalIso = (localValue) => {
        if (!localValue) return null;
        return localValue;
    };

    const payload = {
        name: document.getElementById('promotion-name').value.trim(),
        description: document.getElementById('promotion-description').value.trim() || null,
        discount_pct: parseFloat(document.getElementById('promotion-discount').value) || 0,
        start_at: toLocalIso(document.getElementById('promotion-start').value),
        end_at: toLocalIso(document.getElementById('promotion-end').value),
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
        syncThemeFromSettings();
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

const SETTINGS_GROUPS = [
    {
        id: 'appearance',
        label: 'Aparência',
        icon: '<i class="bi bi-palette"></i>',
        keys: ['theme_mode']
    },
    {
        id: 'store',
        label: 'Dados do Estabelecimento',
        icon: '<i class="bi bi-shop"></i>',
        keys: ['store_name', 'store_address', 'store_phone', 'store_cnpj', 'ticket_header', 'ticket_footer']
    },
    {
        id: 'service',
        label: 'Taxas e Serviço',
        icon: '<i class="bi bi-receipt"></i>',
        keys: ['service_charge_pct']
    },
    {
        id: 'card_machines',
        label: 'Maquininhas de Cartão',
        icon: '<i class="bi bi-credit-card"></i>',
        keys: [
            'card_machine_1_name', 'card_machine_1_debit_fee', 'card_machine_1_credit_fee',
            'card_machine_2_name', 'card_machine_2_debit_fee', 'card_machine_2_credit_fee'
        ]
    },
    {
        id: 'auto_cash',
        label: 'Caixa Automático',
        icon: '<i class="bi bi-clock-history"></i>',
        keys: ['auto_open_enabled', 'auto_open_time', 'auto_close_enabled', 'auto_close_time', 'auto_report_email']
    },
    {
        id: 'smtp',
        label: 'Email (SMTP)',
        icon: '<i class="bi bi-envelope-at"></i>',
        keys: ['smtp_host', 'smtp_port', 'smtp_user', 'smtp_password', 'smtp_from']
    },
    {
        id: 'printers',
        label: 'Impressoras Térmicas',
        icon: '<i class="bi bi-printer"></i>',
        keys: [
            'printer_1_name', 'printer_1_ip', 'printer_1_port', 'printer_1_width',
            'printer_2_name', 'printer_2_ip', 'printer_2_port', 'printer_2_width',
            'printer_nota', 'printer_cozinha', 'printer_bar'
        ]
    }
];

function _getSettingInputHtml(s) {
    if (s.key === 'theme_mode') {
        const isLight = s.value === 'light';
        const icon = isLight ? '<i class="bi bi-sun"></i>' : '<i class="bi bi-moon-stars"></i>';
        const label = isLight ? 'Modo Claro' : 'Modo Escuro';
        return `
            <button type="button" id="setting-${s.key}" class="btn-secondary" onclick="toggleThemeSetting()" style="display:inline-flex;align-items:center;gap:8px;">
                ${icon} <span id="theme-mode-label">${label}</span>
            </button>`;
    }
    if (s.type === 'boolean') {
        const checked = s.value && s.value.toString().toLowerCase() === 'true' ? 'checked' : '';
        return `
            <label class="setting-toggle">
                <input type="checkbox" id="setting-${s.key}" ${checked} onchange="submitSetting('${s.key}')">
                <span class="toggle-slider"></span>
                <span class="toggle-label">Ativado</span>
            </label>`;
    }
    if (['printer_nota', 'printer_cozinha', 'printer_bar'].includes(s.key)) {
        const printer1Name = appSettings['printer_1_name'] || 'Impressora 1';
        const printer2Name = appSettings['printer_2_name'] || 'Impressora 2';
        const val1 = s.value === '1' ? 'selected' : '';
        const val2 = s.value === '2' ? 'selected' : '';
        return `
            <select id="setting-${s.key}" class="select-field" onchange="submitSetting('${s.key}')">
                <option value="1" ${val1}>${escapeHtml(printer1Name)}</option>
                <option value="2" ${val2}>${escapeHtml(printer2Name)}</option>
            </select>`;
    }
    const inputType = s.type === 'number' ? 'number' : 'text';
    const step = s.type === 'number' ? 'step="0.01"' : '';
    const placeholder = s.type === 'password' || s.key.includes('password') ? 'placeholder="••••••••"' : '';
    const typeAttr = s.key.includes('password') ? 'password' : inputType;
    const maskAttr = s.key === 'store_phone' ? ' oninput="this.value = maskPhone(this.value)"' :
                     s.key === 'store_cnpj' ? ' oninput="this.value = maskCpfCnpj(this.value)"' :
                     ['auto_report_email', 'smtp_user', 'smtp_from'].includes(s.key) ? ' type="email"' : '';
    return `<input type="${typeAttr}" ${step} ${placeholder} id="setting-${s.key}" class="input-field" value="${s.value || ''}" onchange="submitSetting('${s.key}')"${maskAttr}>`;
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
        const settingsMap = {};
        settings.forEach(s => {
            appSettings[s.key] = s.value;
            settingsMap[s.key] = s;
        });

        const hiddenKeys = [
            'card_fee_debit_pct', 'card_fee_credit_pct',
            'thermal_printer_enabled', 'thermal_printer_ip', 'thermal_printer_port', 'thermal_printer_width'
        ];
        hiddenKeys.forEach(k => delete settingsMap[k]);

        const orphanKeys = Object.keys(settingsMap).filter(k => !SETTINGS_GROUPS.some(g => g.keys.includes(k)));

        let html = '';

        SETTINGS_GROUPS.forEach(group => {
            const groupSettings = group.keys.map(k => settingsMap[k]).filter(Boolean);
            if (groupSettings.length === 0) return;

            html += `
            <div class="settings-group-card" id="settings-group-${group.id}">
                <div class="settings-group-header">
                    <span class="settings-group-icon">${group.icon}</span>
                    <div>
                        <h3 class="settings-group-title">${group.label}</h3>
                    </div>
                </div>
                <div class="settings-group-body">
                    ${groupSettings.map(s => `
                        <div class="setting-row">
                            <div class="setting-info">
                                <label class="input-label">${s.label}</label>
                                <p class="setting-description">${s.description || ''}</p>
                            </div>
                            <div class="setting-control">
                                ${_getSettingInputHtml(s)}
                                <span class="setting-status" id="setting-status-${s.key}"></span>
                            </div>
                        </div>
                    `).join('')}
                </div>
            </div>
            `;
        });

        if (orphanKeys.length > 0) {
            html += `
            <div class="settings-group-card" id="settings-group-outras">
                <div class="settings-group-header">
                    <span class="settings-group-icon">⚙️</span>
                    <div>
                        <h3 class="settings-group-title">Outras Configurações</h3>
                    </div>
                </div>
                <div class="settings-group-body">
                    ${orphanKeys.map(k => {
                        const s = settingsMap[k];
                        return `
                        <div class="setting-row">
                            <div class="setting-info">
                                <label class="input-label">${s.label}</label>
                                <p class="setting-description">${s.description || ''}</p>
                            </div>
                            <div class="setting-control">
                                ${_getSettingInputHtml(s)}
                                <span class="setting-status" id="setting-status-${s.key}"></span>
                            </div>
                        </div>
                        `;
                    }).join('')}
                </div>
            </div>
            `;
        }

        container.innerHTML = html;

        populateSettingsSidebar(settingsMap, orphanKeys);
        syncThemeFromSettings();
    } catch (err) {
        container.innerHTML = '<div class="error-msg">Erro ao carregar configurações</div>';
    }
}

function populateSettingsSidebar(settingsMap, orphanKeys) {
    const nav = document.getElementById('settings-nav');
    if (!nav) return;

    let navHtml = '';
    SETTINGS_GROUPS.forEach(group => {
        const groupSettings = group.keys.map(k => settingsMap[k]).filter(Boolean);
        if (groupSettings.length === 0) return;
        navHtml += `<button class="settings-nav-btn" data-group="${group.id}" onclick="scrollToSettingGroup('${group.id}')">${group.icon} ${group.label}</button>`;
    });
    if (orphanKeys.length > 0) {
        navHtml += `<button class="settings-nav-btn" data-group="outras" onclick="scrollToSettingGroup('outras')">⚙️ Outras</button>`;
    }

    const crudGroups = [
        { id: 'mesas', icon: '<i class="bi bi-table"></i>', label: 'Mesas' },
        { id: 'usuarios', icon: '<i class="bi bi-person-lock"></i>', label: 'Usuários' },
        { id: 'backup', icon: '<i class="bi bi-download"></i>', label: 'Backup' },
    ];
    crudGroups.forEach(group => {
        const card = document.getElementById('settings-group-' + group.id);
        if (card) {
            navHtml += `<button class="settings-nav-btn" data-group="${group.id}" onclick="scrollToSettingGroup('${group.id}')">${group.icon} ${group.label}</button>`;
        }
    });

    nav.innerHTML = navHtml;

    setupSettingsScrollObserver();
}

function scrollToSettingGroup(groupId) {
    const target = document.getElementById('settings-group-' + groupId);
    const main = document.getElementById('settings-main');
    if (!target || !main) return;

    const mainRect = main.getBoundingClientRect();
    const targetRect = target.getBoundingClientRect();
    const offset = targetRect.top - mainRect.top + main.scrollTop - 20;
    if (main.scrollHeight > main.clientHeight) {
        main.scrollTo({ top: offset, behavior: 'smooth' });
    } else {
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    document.querySelectorAll('.settings-nav-btn').forEach(b => b.classList.remove('active'));
    const btn = document.querySelector(`.settings-nav-btn[data-group="${groupId}"]`);
    if (btn) btn.classList.add('active');
}

function setupSettingsScrollObserver() {
    const main = document.getElementById('settings-main');
    if (!main) return;

    const cards = main.querySelectorAll('.settings-group-card');
    if (cards.length === 0) return;

    const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
            if (entry.isIntersecting) {
                const groupId = entry.target.id.replace('settings-group-', '');
                document.querySelectorAll('.settings-nav-btn').forEach(b => {
                    b.classList.toggle('active', b.dataset.group === groupId);
                });
            }
        });
    }, { root: main, threshold: 0.3, rootMargin: '-40px 0px -60% 0px' });

    cards.forEach(card => observer.observe(card));
}

async function submitSetting(key) {
    const input = document.getElementById('setting-' + key);
    const statusEl = document.getElementById('setting-status-' + key);
    if (!input) return;
    const value = input.type === 'checkbox' ? (input.checked ? 'true' : 'false') : input.value;

    const errorEl = document.getElementById('settings-error');
    const successEl = document.getElementById('settings-success');
    errorEl.style.display = 'none';
    successEl.style.display = 'none';
    if (statusEl) {
        statusEl.textContent = 'Salvando...';
        statusEl.className = 'setting-status saving';
    }

    try {
        const res = await apiFetch(API_BASE + '/configuracoes/' + key, {
            method: 'PUT',
            body: JSON.stringify({ value })
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            if (statusEl) {
                statusEl.textContent = 'Erro';
                statusEl.className = 'setting-status error';
            }
            return;
        }
        appSettings[key] = value;
        successEl.style.display = 'block';
        setTimeout(() => { successEl.style.display = 'none'; }, 2000);
        if (statusEl) {
            statusEl.textContent = 'Salvo';
            statusEl.className = 'setting-status saved';
            setTimeout(() => {
                if (statusEl.textContent === 'Salvo') {
                    statusEl.textContent = '';
                    statusEl.className = 'setting-status';
                }
            }, 2000);
        }
    } catch (err) {
        errorEl.textContent = 'Erro ao salvar configuração';
        errorEl.style.display = 'block';
        if (statusEl) {
            statusEl.textContent = 'Erro';
            statusEl.className = 'setting-status error';
        }
    }
}

// ====== EMPLOYEES ======
let employeesCache = [];

function formatDateTimeLocal(date) {
    return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

async function loadEmployees() {
    const container = document.getElementById('employees-list');
    if (!container) return;

    const search = document.getElementById('employee-search')?.value.toLowerCase() || '';
    const activeFilter = document.getElementById('employee-filter-active')?.value || '';

    try {
        let url = API_BASE + '/funcionarios';
        if (activeFilter === 'true') url += '?active_only=true';
        const res = await apiFetch(url);
        employeesCache = await res.json();

        const filtered = employeesCache.filter(e =>
            e.name.toLowerCase().includes(search) ||
            (e.nickname && e.nickname.toLowerCase().includes(search)) ||
            (e.contact && e.contact.toLowerCase().includes(search)) ||
            e.role.toLowerCase().includes(search)
        );

        if (filtered.length === 0) {
            container.innerHTML = '<p class="empty-msg">Nenhum funcionário encontrado</p>';
            return;
        }

        container.innerHTML = filtered.map(e => `
            <div class="employee-card ${e.active ? '' : 'inactive'}">
                <div class="employee-header">
                    <div>
                        <div class="employee-name">${e.name} ${e.nickname ? '(' + e.nickname + ')' : ''}</div>
                        <div class="employee-meta">${e.role} | ${e.age ? e.age + ' anos' : ''} ${e.contact ? ' | ' + e.contact : ''}</div>
                    </div>
                    <span class="employee-status ${e.active ? 'active' : 'inactive'}">${e.active ? 'Ativo' : 'Inativo'}</span>
                </div>
                <div class="employee-actions">
                    <button onclick="showDailyPaymentModal(${e.id}, '${e.name.replace(/'/g, "\\'")}')" class="btn-small">Pagar Diária</button>
                    <button onclick="showEmployeeHistory(${e.id})" class="btn-small">Histórico</button>
                    <button onclick="editEmployee(${e.id})" class="btn-small">Editar</button>
                    <button onclick="deleteEmployee(${e.id})" class="btn-small btn-danger">Excluir</button>
                </div>
                <div id="employee-history-${e.id}" class="employee-history" style="display:none;"></div>
            </div>
        `).join('');
    } catch (err) {
        container.innerHTML = '<div class="error-msg">Erro ao carregar funcionários</div>';
    }
}

function showEmployeeModal(employee = null) {
    document.getElementById('employee-modal-title').textContent = employee ? 'Editar Funcionário' : 'Novo Funcionário';
    document.getElementById('employee-id').value = employee ? employee.id : '';
    document.getElementById('employee-name').value = employee ? employee.name : '';
    document.getElementById('employee-age').value = employee && employee.age ? employee.age : '';
    document.getElementById('employee-nickname').value = employee && employee.nickname ? employee.nickname : '';
    document.getElementById('employee-contact').value = employee && employee.contact ? employee.contact : '';
    document.getElementById('employee-role').value = employee ? employee.role : '';
    document.getElementById('employee-active').checked = employee ? employee.active : true;

    const loginSection = document.getElementById('login-section');
    if (employee && employee.has_login) {
        loginSection.style.display = 'none';
    } else {
        loginSection.style.display = 'block';
        document.getElementById('employee-create-login').checked = false;
        document.getElementById('login-fields').style.display = 'none';
        document.getElementById('employee-username').value = '';
        document.getElementById('employee-password').value = '';
        document.getElementById('employee-login-role').value = 'garcom';
    }

    document.getElementById('employee-error').style.display = 'none';
    document.getElementById('employee-modal').style.display = 'flex';
}

function closeEmployeeModal() {
    document.getElementById('employee-modal').style.display = 'none';
}

async function submitEmployee() {
    const id = document.getElementById('employee-id').value;
    const errorEl = document.getElementById('employee-error');
    errorEl.style.display = 'none';

    const payload = {
        name: document.getElementById('employee-name').value.trim(),
        age: parseInt(document.getElementById('employee-age').value) || null,
        nickname: document.getElementById('employee-nickname').value.trim() || null,
        contact: document.getElementById('employee-contact').value.trim() || null,
        role: document.getElementById('employee-role').value.trim(),
        active: document.getElementById('employee-active').checked,
    };

    if (!payload.name || !payload.role) {
        errorEl.textContent = 'Nome e função são obrigatórios';
        errorEl.style.display = 'block';
        return;
    }

    if (!id && document.getElementById('employee-create-login').checked) {
        payload.create_login = true;
        payload.username = document.getElementById('employee-username').value.trim();
        payload.password = document.getElementById('employee-password').value;
        payload.login_role = document.getElementById('employee-login-role').value;

        if (!payload.username || !payload.password) {
            errorEl.textContent = 'Usuário e senha são obrigatórios para criar login';
            errorEl.style.display = 'block';
            return;
        }
    }

    const url = API_BASE + '/funcionarios' + (id ? '/' + id : '');
    const method = id ? 'PUT' : 'POST';

    try {
        const res = await apiFetch(url, { method, body: JSON.stringify(payload) });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closeEmployeeModal();
        loadEmployees();
    } catch (err) {
        errorEl.textContent = 'Erro ao salvar funcionário';
        errorEl.style.display = 'block';
    }
}

async function editEmployee(id) {
    const employee = employeesCache.find(e => e.id == id);
    if (employee) showEmployeeModal(employee);
}

async function deleteEmployee(id) {
    if (!confirm('Deseja realmente excluir este funcionário?')) return;
    try {
        const res = await apiFetch(API_BASE + '/funcionarios/' + id, { method: 'DELETE' });
        if (!res.ok) {
            const data = await res.json();
            alert(data.error || 'Erro ao excluir');
            return;
        }
        loadEmployees();
    } catch (err) {
        alert('Erro ao excluir funcionário');
    }
}

function showDailyPaymentModal(employeeId, employeeName) {
    document.getElementById('daily-payment-employee-id').value = employeeId;
    document.getElementById('daily-payment-employee-name').textContent = employeeName;
    document.getElementById('daily-payment-amount').value = '';
    document.getElementById('daily-payment-date').value = formatDateTimeLocal(new Date());
    document.getElementById('daily-payment-notes').value = '';
    document.getElementById('daily-payment-error').style.display = 'none';
    document.getElementById('daily-payment-modal').style.display = 'flex';
}

function closeDailyPaymentModal() {
    document.getElementById('daily-payment-modal').style.display = 'none';
}

async function submitDailyPayment() {
    const employeeId = document.getElementById('daily-payment-employee-id').value;
    const amount = parseFloat(document.getElementById('daily-payment-amount').value) || 0;
    const dateValue = document.getElementById('daily-payment-date').value;
    const notes = document.getElementById('daily-payment-notes').value.trim() || null;
    const errorEl = document.getElementById('daily-payment-error');
    errorEl.style.display = 'none';

    if (amount <= 0) {
        errorEl.textContent = 'Informe um valor maior que zero';
        errorEl.style.display = 'block';
        return;
    }
    if (!dateValue) {
        errorEl.textContent = 'Informe a data do pagamento';
        errorEl.style.display = 'block';
        return;
    }

    try {
        const res = await apiFetch(API_BASE + '/funcionarios/diaria', {
            method: 'POST',
            body: JSON.stringify({
                employee_id: parseInt(employeeId),
                amount: amount,
                payment_date: dateValue,
                notes: notes,
            })
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closeDailyPaymentModal();
        showEmployeeHistory(employeeId);
    } catch (err) {
        errorEl.textContent = 'Erro ao registrar diária';
        errorEl.style.display = 'block';
    }
}

async function showEmployeeHistory(employeeId) {
    const historyEl = document.getElementById('employee-history-' + employeeId);
    if (!historyEl) return;

    const isVisible = historyEl.style.display === 'block';
    if (isVisible) {
        historyEl.style.display = 'none';
        return;
    }

    try {
        const res = await apiFetch(API_BASE + '/funcionarios/' + employeeId);
        const data = await res.json();
        if (data.error) {
            historyEl.innerHTML = '<div class="error-msg">' + data.error + '</div>';
            historyEl.style.display = 'block';
            return;
        }

        const totalRes = await apiFetch(API_BASE + '/funcionarios/' + employeeId + '/total-diarias');
        const totalData = await totalRes.json();

        const payments = data.daily_payments || [];
        const listHtml = payments.length === 0
            ? '<p class="empty-msg" style="margin-top:8px;">Nenhuma diária paga</p>'
            : payments.map(p => `
                <div class="history-row">
                    <span>${new Date(p.payment_date).toLocaleString('pt-BR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' })}</span>
                    <span>${formatCurrency(p.amount)}</span>
                    <span style="font-size:11px;color:var(--text-muted);">${p.notes || ''}</span>
                </div>
            `).join('');

        historyEl.innerHTML = `
            <div class="history-total">Total pago: ${formatCurrency(totalData.total_paid)}</div>
            <div class="history-list">${listHtml}</div>
        `;
        historyEl.style.display = 'block';
    } catch (err) {
        historyEl.innerHTML = '<div class="error-msg">Erro ao carregar histórico</div>';
        historyEl.style.display = 'block';
    }
}

// ====== CUSTOMERS ======
let customersCache = [];

async function loadCustomers() {
    const container = document.getElementById('customers-list');
    if (!container) return;

    const search = document.getElementById('customer-search')?.value.toLowerCase() || '';
    const activeFilter = document.getElementById('customer-filter-active')?.value || '';
    const typeFilter = document.getElementById('customer-filter-type')?.value || '';
    const sortBy = document.getElementById('customer-sort')?.value || 'name';

    container.innerHTML = '<div class="loading">Carregando...</div>';

    try {
        let url = API_BASE + '/clientes';
        const params = [];
        if (activeFilter === 'active') params.push('active_only=true');
        if (activeFilter === 'inactive') params.push('active_only=false');
        if (typeFilter) params.push('customer_type=' + encodeURIComponent(typeFilter));
        if (search) params.push('search=' + encodeURIComponent(search));
        if (params.length) url += '?' + params.join('&');

        const res = await apiFetch(url);
        const data = await res.json();
        if (data.error) {
            container.innerHTML = '<div class="error-msg">' + data.error + '</div>';
            return;
        }
        customersCache = data;

        if (customersCache.length === 0) {
            container.innerHTML = '<p class="empty-msg">Nenhum cliente encontrado</p>';
            return;
        }

        const summaryPromises = customersCache.map(async c => {
            try {
                const r = await apiFetch(API_BASE + '/clientes/' + c.id + '/resumo');
                const s = await r.json();
                return { customer: c, summary: s.error ? { total_spent: 0, visit_count: 0, last_visit: null } : s };
            } catch (err) {
                return { customer: c, summary: { total_spent: 0, visit_count: 0, last_visit: null } };
            }
        });
        const merged = await Promise.all(summaryPromises);

        merged.sort((a, b) => {
            if (sortBy === 'name') {
                return a.customer.name.localeCompare(b.customer.name);
            }
            if (sortBy === 'total_spent') {
                return (b.summary.total_spent || 0) - (a.summary.total_spent || 0);
            }
            if (sortBy === 'visit_count') {
                return (b.summary.visit_count || 0) - (a.summary.visit_count || 0);
            }
            if (sortBy === 'last_visit') {
                const da = a.summary.last_visit ? new Date(a.summary.last_visit) : new Date(0);
                const db = b.summary.last_visit ? new Date(b.summary.last_visit) : new Date(0);
                return db - da;
            }
            return 0;
        });

        container.innerHTML = merged.map(({ customer: c, summary }) => {
            const lastVisitText = summary.last_visit
                ? new Date(summary.last_visit).toLocaleDateString('pt-BR')
                : '-';
            return `
            <div class="customer-card ${c.active ? '' : 'inactive'}">
                <div class="customer-info">
                    <div class="customer-name">${c.name} ${c.customer_type === 'pj' ? '(PJ)' : ''}</div>
                    <div class="customer-meta">
                        ${c.phone ? c.phone + ' | ' : ''}
                        ${c.document ? c.document + ' | ' : ''}
                        ${c.email ? c.email : ''}
                    </div>
                    <div class="customer-meta" style="margin-top:4px;">
                        Faturamento: <strong>${formatCurrency(summary.total_spent || 0)}</strong> |
                        Visitas: <strong>${summary.visit_count || 0}</strong> |
                        Última: <strong>${lastVisitText}</strong>
                    </div>
                </div>
                <div class="customer-actions">
                    ${canViewCustomerDashboard() ? `<button onclick="openCustomerDashboard(${c.id})" class="btn-small">Dashboard</button>` : ''}
                    ${canEditCustomer() ? `<button onclick="editCustomer(${c.id})" class="btn-small">Editar</button>` : ''}
                    ${canEditCustomer() ? `<button onclick="deleteCustomer(${c.id})" class="btn-small btn-danger">Excluir</button>` : ''}
                </div>
            </div>
        `}).join('');
    } catch (err) {
        container.innerHTML = '<div class="error-msg">Erro ao carregar clientes</div>';
    }
}

async function loadCustomerSummary(customerId) {
    try {
        const res = await apiFetch(API_BASE + '/clientes/' + customerId + '/resumo');
        const data = await res.json();
        if (data.error) return;
        const totalEl = document.getElementById('customer-total-' + customerId);
        const visitsEl = document.getElementById('customer-visits-' + customerId);
        if (totalEl) totalEl.textContent = formatCurrency(data.total_spent);
        if (visitsEl) visitsEl.textContent = data.visit_count + (data.visit_count === 1 ? ' visita' : ' visitas');
    } catch (err) {}
}

let customerSavedCallback = null;

function showCustomerModal(customer = null, onSaved = null) {
    customerSavedCallback = onSaved || null;
    document.getElementById('customer-modal-title').textContent = customer ? 'Editar Cliente' : 'Novo Cliente';
    document.getElementById('customer-id').value = customer ? customer.id : '';
    document.getElementById('customer-name').value = customer ? customer.name : '';
    document.getElementById('customer-phone').value = customer ? customer.phone || '' : '';
    document.getElementById('customer-email').value = customer ? customer.email || '' : '';
    document.getElementById('customer-document').value = customer ? customer.document || '' : '';
    document.getElementById('customer-birth-date').value = customer && customer.birth_date ? customer.birth_date : '';
    document.getElementById('customer-type').value = customer ? customer.customer_type || 'pf' : 'pf';
    document.getElementById('customer-notes').value = customer ? customer.notes || '' : '';
    document.getElementById('customer-active').checked = customer ? customer.active : true;
    document.getElementById('customer-error').style.display = 'none';
    document.getElementById('customer-modal').style.display = 'flex';
}

function closeCustomerModal() {
    document.getElementById('customer-modal').style.display = 'none';
    customerSavedCallback = null;
}

async function submitCustomer() {
    const id = document.getElementById('customer-id').value;
    const errorEl = document.getElementById('customer-error');
    errorEl.style.display = 'none';

    const payload = {
        name: document.getElementById('customer-name').value.trim(),
        phone: document.getElementById('customer-phone').value.trim() || null,
        email: document.getElementById('customer-email').value.trim() || null,
        document: document.getElementById('customer-document').value.trim() || null,
        birth_date: document.getElementById('customer-birth-date').value || null,
        customer_type: document.getElementById('customer-type').value,
        notes: document.getElementById('customer-notes').value.trim() || null,
        active: document.getElementById('customer-active').checked,
    };

    if (!payload.name) {
        errorEl.textContent = 'Nome é obrigatório';
        errorEl.style.display = 'block';
        return;
    }

    try {
        const res = await apiFetch(API_BASE + '/clientes' + (id ? '/' + id : ''), {
            method: id ? 'PUT' : 'POST',
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        const callback = customerSavedCallback;
        closeCustomerModal();
        if (typeof callback === 'function') {
            callback(data);
        } else if (document.getElementById('customers-list')) {
            loadCustomers();
        }
    } catch (err) {
        errorEl.textContent = 'Erro ao salvar cliente';
        errorEl.style.display = 'block';
    }
}

async function editCustomer(id) {
    const customer = customersCache.find(c => c.id === id);
    if (customer) showCustomerModal(customer);
}

function hideCreateCustomerButtonsIfNoPermission() {
    if (canCreateCustomer()) return;
    document.querySelectorAll('.create-customer-inline-btn').forEach(el => el.style.display = 'none');
}

function getCreateCustomerButtonHtml(onclick, label = 'Cadastrar novo cliente') {
    if (!canCreateCustomer()) return '';
    return `<button type="button" class="btn-link" onclick="${onclick}" style="font-size:12px;color:var(--text-muted);padding:0;background:none;border:none;cursor:pointer;text-decoration:underline;">${label}</button>`;
}

function openCreateCustomerForFiado() {
    showCustomerModal(null, (newCustomer) => {
        fiadoCustomerId = newCustomer.id;
        document.getElementById('fiado-customer-id').value = newCustomer.id;
        document.getElementById('fiado-customer-name').value = newCustomer.name;
        document.getElementById('fiado-customer-suggestions').style.display = 'none';
    });
}

function openCreateCustomerForBalcao() {
    showCustomerModal(null, (newCustomer) => {
        balcaoCurrentCustomerId = newCustomer.id;
        balcaoCurrentCustomerName = newCustomer.name;
        document.getElementById('balcao-customer-id').value = newCustomer.id;
        document.getElementById('balcao-customer-name').value = newCustomer.name;
        document.getElementById('balcao-customer-suggestions').style.display = 'none';
    });
}

function openCreateCustomerForConsignment() {
    showCustomerModal(null, (newCustomer) => {
        newConsignmentCustomerId = newCustomer.id;
        document.getElementById('new-consignment-customer-id').value = newCustomer.id;
        document.getElementById('new-consignment-customer-name').value = newCustomer.name;
        document.getElementById('new-consignment-customer-suggestions').style.display = 'none';
    });
}

function openCreateCustomerForNewOrder() {
    showCustomerModal(null, (newCustomer) => {
        selectedTableCustomerId = newCustomer.id;
        const input = document.getElementById('customer-name-input');
        if (input) input.value = newCustomer.name;
        updateSelectedCustomerUI();
        hideCustomerSuggestions();
    });
}

async function deleteCustomer(id) {
    if (!confirm('Deseja realmente excluir este cliente?')) return;
    try {
        const res = await apiFetch(API_BASE + '/clientes/' + id, { method: 'DELETE' });
        const data = await res.json();
        if (data.error) {
            alert(data.error);
            return;
        }
        loadCustomers();
    } catch (err) {
        alert('Erro ao excluir cliente');
    }
}

async function openCustomerDashboard(customerId) {
    const customer = customersCache.find(c => c.id === customerId);
    document.getElementById('dashboard-customer-name').textContent = customer ? 'Dashboard: ' + customer.name : 'Dashboard do Cliente';
    document.getElementById('customer-dashboard-modal').style.display = 'flex';
    await loadCustomerSummaryForDashboard(customerId);
    await loadCustomerDashboard(customerId);
    await loadCustomerOrders(customerId, 1);
    await loadCustomerItems(customerId);
}

async function loadCustomerSummaryForDashboard(customerId) {
    try {
        const res = await apiFetch(API_BASE + '/clientes/' + customerId + '/resumo');
        const data = await res.json();
        if (data.error) return;
        document.getElementById('dash-total-spent').textContent = formatCurrency(data.total_spent);
        document.getElementById('dash-visit-count').textContent = data.visit_count;
        document.getElementById('dash-last-visit').textContent = data.last_visit
            ? new Date(data.last_visit).toLocaleString('pt-BR', { day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit' })
            : '-';
    } catch (err) {}
}

async function loadCustomerDashboard(customerId) {
    const yearSelect = document.getElementById('dashboard-year');
    let selectedYear = yearSelect ? yearSelect.value : '';

    try {
        const url = API_BASE + '/clientes/' + customerId + '/dashboard' + (selectedYear ? '?year=' + selectedYear : '');
        const res = await apiFetch(url);
        const data = await res.json();
        if (data.error) {
            alert(data.error);
            return;
        }

        if (yearSelect) {
            const currentYear = new Date().getFullYear();
            const minYear = data.year;
            yearSelect.innerHTML = '';
            for (let y = currentYear; y >= minYear; y--) {
                const opt = document.createElement('option');
                opt.value = y;
                opt.textContent = y;
                if (String(y) === String(data.year)) opt.selected = true;
                yearSelect.appendChild(opt);
            }
        }

        renderBarChart('month-chart', data.by_month, 'label', 'count', 'total');
        renderBarChart('weekday-chart', data.by_weekday, 'label', 'count', 'total');
    } catch (err) {
        alert('Erro ao carregar dashboard');
    }
}

let customerDashboardCharts = {};

function renderBarChart(containerId, data, labelKey, countKey, totalKey) {
    const container = document.getElementById(containerId);
    if (!container) return;

    if (customerDashboardCharts[containerId]) {
        customerDashboardCharts[containerId].destroy();
        delete customerDashboardCharts[containerId];
    }

    container.innerHTML = '<canvas id="' + containerId + '-canvas"></canvas>';
    const canvas = document.getElementById(containerId + '-canvas');
    if (!canvas) return;

    const labels = data.map(d => d[labelKey]);
    const counts = data.map(d => d[countKey] || 0);

    const ctx = canvas.getContext('2d');
    customerDashboardCharts[containerId] = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: labels,
            datasets: [{
                label: 'Visitas',
                data: counts,
                backgroundColor: DASHBOARD_COLORS.primary,
                borderColor: DASHBOARD_COLORS.primary,
                borderWidth: 0,
                borderRadius: 6,
                borderSkipped: false,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    backgroundColor: 'rgba(13, 17, 23, 0.95)',
                    titleColor: DASHBOARD_COLORS.text,
                    bodyColor: DASHBOARD_COLORS.text,
                    borderColor: 'rgba(255,255,255,0.1)',
                    borderWidth: 1,
                    padding: 10,
                    displayColors: false,
                    callbacks: {
                        label: function(context) {
                            const item = data[context.dataIndex];
                            return 'Visitas: ' + (item[countKey] || 0);
                        },
                        afterLabel: function(context) {
                            const item = data[context.dataIndex];
                            return 'Total gasto: ' + formatCurrency(item[totalKey] || 0);
                        }
                    }
                }
            },
            scales: {
                x: {
                    ticks: { color: DASHBOARD_COLORS.text, font: { size: 11 } },
                    grid: { display: false }
                },
                y: {
                    beginAtZero: true,
                    ticks: { color: DASHBOARD_COLORS.text, font: { size: 11 }, precision: 0 },
                    grid: { color: DASHBOARD_COLORS.grid }
                }
            }
        }
    });
}

function closeCustomerDashboardModal() {
    document.getElementById('customer-dashboard-modal').style.display = 'none';
}

// ====== CUSTOMER ORDER HISTORY (COMANDAS) ======
let customerOrdersCustomerId = null;
let customerOrdersPage = 1;
let customerOrdersData = [];

async function loadCustomerOrders(customerId, page) {
    const listEl = document.getElementById('customer-orders-list');
    const pagEl = document.getElementById('customer-orders-pagination');
    if (!listEl) return;

    customerOrdersCustomerId = customerId;
    customerOrdersPage = page || 1;
    listEl.innerHTML = '<div class="loading">Carregando...</div>';
    if (pagEl) pagEl.innerHTML = '';

    try {
        const res = await apiFetch(API_BASE + '/clientes/' + customerId + '/comandas?page=' + customerOrdersPage + '&page_size=10');
        const data = await res.json();
        if (data.error) {
            listEl.innerHTML = '<div class="error-msg">' + data.error + '</div>';
            return;
        }

        customerOrdersData = data.sales || [];
        if (customerOrdersData.length === 0) {
            listEl.innerHTML = '<p class="empty-msg">Nenhuma comanda registrada</p>';
            return;
        }

        listEl.innerHTML = customerOrdersData.map((s, idx) => {
            const orderTotal = round(s.total + s.service_charge_amount, 2);
            return `
            <div class="sale-card" onclick="openCustomerOrderDetail(${idx})" style="cursor:pointer;">
                <div class="sale-header">
                    <span class="sale-table">Comanda #${s.order_id} - ${s.is_balcao ? 'Balcão' : 'Mesa ' + s.table_number}</span>
                    <span class="sale-time">${s.closed_at ? _fmtDateTime(s.closed_at) : '-'}</span>
                </div>
                <div class="sale-total">${formatCurrency(orderTotal)}</div>
            </div>
            `;
        }).join('');

        renderCustomerOrdersPagination(data.pagination);
    } catch (err) {
        listEl.innerHTML = '<div class="error-msg">Erro ao carregar comandas</div>';
    }
}

function renderCustomerOrdersPagination(pagination) {
    const pagEl = document.getElementById('customer-orders-pagination');
    if (!pagEl || !pagination) return;

    const start = (pagination.page - 1) * pagination.page_size + 1;
    const end = Math.min(pagination.page * pagination.page_size, pagination.total);

    pagEl.innerHTML = `
        <span class="customer-orders-pagination-info">Mostrando ${start}-${end} de ${pagination.total}</span>
        <div class="customer-orders-pagination-buttons">
            <button class="btn-small" onclick="loadCustomerOrders(customerOrdersCustomerId, ${pagination.page - 1})" ${pagination.page <= 1 ? 'disabled' : ''}>Anterior</button>
            <button class="btn-small" onclick="loadCustomerOrders(customerOrdersCustomerId, ${pagination.page + 1})" ${pagination.page >= pagination.total_pages ? 'disabled' : ''}>Próxima</button>
        </div>
    `;
}

function openCustomerOrderDetail(index) {
    const sale = customerOrdersData[index];
    if (!sale) return;
    window._lastSalesData = customerOrdersData;
    openSaleDetailModal(index);
}

// ====== CUSTOMER ITEM RANKING ======
let customerItemsCustomerId = null;
let customerItemsRanking = [];

async function loadCustomerItems(customerId) {
    customerItemsCustomerId = customerId;
    const valueEl = document.getElementById('customer-top-item-value');
    const subEl = document.getElementById('customer-top-item-sub');

    try {
        const res = await apiFetch(API_BASE + '/clientes/' + customerId + '/itens-consumo');
        const data = await res.json();
        if (data.error) {
            if (valueEl) valueEl.textContent = '-';
            if (subEl) subEl.textContent = '';
            return;
        }
        customerItemsRanking = data.items || [];
        const top = customerItemsRanking[0];
        if (top) {
            if (valueEl) valueEl.textContent = top.product_name;
            if (subEl) subEl.textContent = top.quantity + 'x consumido' + (top.total > 0 ? ' · ' + formatCurrency(top.total) : '');
        } else {
            if (valueEl) valueEl.textContent = 'Nenhum consumo registrado';
            if (subEl) subEl.textContent = '';
        }
    } catch (err) {
        if (valueEl) valueEl.textContent = '-';
        if (subEl) subEl.textContent = '';
    }
}

function openCustomerItemsRanking() {
    const modal = document.getElementById('customer-items-ranking-modal');
    const contentEl = document.getElementById('customer-items-ranking-content');
    if (!modal || !contentEl) return;

    if (customerItemsRanking.length === 0) {
        contentEl.innerHTML = '<p class="empty-msg">Nenhum consumo registrado</p>';
    } else {
        contentEl.innerHTML = customerItemsRanking.map((it, idx) => `
            <div class="summary-row">
                <span>${idx + 1}. ${escapeHtml(it.product_name)}</span>
                <span>${it.quantity}x · ${formatCurrency(it.total)}</span>
            </div>
        `).join('');
    }
    modal.style.display = 'flex';
}

function closeCustomerItemsRanking() {
    const modal = document.getElementById('customer-items-ranking-modal');
    if (modal) modal.style.display = 'none';
}

// ====== TABLE CUSTOMER AUTOCOMPLETE ======
let selectedTableCustomerId = null;
let customerSearchDebounce = null;

async function searchCustomerSuggestions(query) {
    const suggestionsEl = document.getElementById('customer-suggestions');
    if (!suggestionsEl) return;

    if (!query.trim()) {
        suggestionsEl.style.display = 'none';
        return;
    }

    clearTimeout(customerSearchDebounce);
    customerSearchDebounce = setTimeout(async () => {
        try {
            const res = await apiFetch(API_BASE + '/clientes?active_only=true&search=' + encodeURIComponent(query.trim()));
            const data = await res.json();
            if (data.error) {
                suggestionsEl.style.display = 'none';
                return;
            }
            renderCustomerSuggestions(data);
        } catch (err) {
            suggestionsEl.style.display = 'none';
        }
    }, 250);
}

async function showAllCustomerSuggestions() {
    const input = document.getElementById('customer-name-input');
    if (input) input.value = '';
    selectedTableCustomerId = null;
    updateSelectedCustomerUI();

    try {
        const res = await apiFetch(API_BASE + '/clientes?active_only=true');
        const data = await res.json();
        if (data.error) return;
        renderCustomerSuggestions(data);
    } catch (err) {}
}

function renderCustomerSuggestions(customers) {
    const suggestionsEl = document.getElementById('customer-suggestions');
    if (!suggestionsEl) return;

    if (customers.length === 0) {
        suggestionsEl.innerHTML = '<div class="autocomplete-empty">Nenhum cliente encontrado. ' + getCreateCustomerButtonHtml('openCreateCustomerForNewOrder()') + ' ou use o nome digitado manualmente.</div>';
        suggestionsEl.style.display = 'block';
        return;
    }

    suggestionsEl.innerHTML = customers.map(c => `
        <div class="autocomplete-item" onclick="selectCustomerForTable(${c.id}, '${c.name.replace(/'/g, "\\'")}')">
            <span>${c.name}</span>
            <span class="autocomplete-meta">${c.phone || ''} ${c.document ? '| ' + c.document : ''}</span>
        </div>
    `).join('');
    suggestionsEl.style.display = 'block';
}

function selectCustomerForTable(id, name) {
    selectedTableCustomerId = id;
    const input = document.getElementById('customer-name-input');
    if (input) input.value = name;
    updateSelectedCustomerUI();
    hideCustomerSuggestions();
}

function clearSelectedCustomer() {
    selectedTableCustomerId = null;
    const input = document.getElementById('customer-name-input');
    if (input) input.value = '';
    updateSelectedCustomerUI();
}

function updateSelectedCustomerUI() {
    const selectedEl = document.getElementById('customer-selected');
    const selectedNameEl = document.getElementById('customer-selected-name');
    const input = document.getElementById('customer-name-input');
    if (!selectedEl || !input) return;

    if (selectedTableCustomerId) {
        selectedNameEl.textContent = input.value;
        selectedEl.style.display = 'flex';
    } else {
        selectedEl.style.display = 'none';
    }
}

function hideCustomerSuggestions() {
    const suggestionsEl = document.getElementById('customer-suggestions');
    if (suggestionsEl) suggestionsEl.style.display = 'none';
}

document.addEventListener('click', (e) => {
    const section = document.getElementById('customer-section');
    if (section && !section.contains(e.target)) {
        hideCustomerSuggestions();
    }
});

async function setCustomerName() {
    const input = document.getElementById('customer-name-input');
    const name = input ? input.value.trim() : '';
    alert(name ? 'Cliente: ' + name : 'Nome opcional');
}

// ESC closes open modals and panels for a smooth desktop experience.
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;

    const notificationPanel = document.getElementById('notification-panel');
    if (notificationPanel && notificationPanel.style.display !== 'none') {
        closeNotificationPanel();
        return;
    }

    const visibleModals = Array.from(document.querySelectorAll('.modal'))
        .filter(m => m.style.display !== 'none' && m.id !== 'name-modal');
    if (visibleModals.length === 0) return;

    // Close the last (topmost) visible modal so stacked modals close one by one.
    const topModal = visibleModals[visibleModals.length - 1];

    // The "Novo Pedido" modal holds a pending reservation that must be released
    // when closed without confirming the order.
    if (topModal.id === 'add-pedido-modal') {
        closeAddPedidoModal();
        return;
    }

    topModal.style.display = 'none';
});

// ===== SCROLL HELPER =====
function getActiveModalContent() {
    const visibleModal = Array.from(document.querySelectorAll('.modal'))
        .find(m => m.style.display !== 'none' && m.id !== 'name-modal');
    if (!visibleModal) return null;
    return visibleModal.querySelector('.modal-content');
}

function scrollToTop() {
    const modalContent = getActiveModalContent();
    if (modalContent) {
        modalContent.scrollTo({ top: 0, behavior: 'smooth' });
    } else {
        window.scrollTo({ top: 0, behavior: 'smooth' });
    }
}

function scrollToBottom() {
    const modalContent = getActiveModalContent();
    if (modalContent) {
        modalContent.scrollTo({ top: modalContent.scrollHeight, behavior: 'smooth' });
    } else {
        window.scrollTo({ top: document.documentElement.scrollHeight, behavior: 'smooth' });
    }
}

function updateScrollHelperVisibility() {
    const helper = document.getElementById('scroll-helper');
    if (!helper) return;

    const modalContent = getActiveModalContent();
    let scrollable = false;
    if (modalContent) {
        scrollable = modalContent.scrollHeight > modalContent.clientHeight + 2;
    } else {
        scrollable = document.documentElement.scrollHeight > window.innerHeight + 2;
    }

    helper.classList.toggle('visible', scrollable);
}

function initScrollHelper() {
    updateScrollHelperVisibility();
    window.addEventListener('resize', updateScrollHelperVisibility);

    const modalObserver = new MutationObserver(() => {
        updateScrollHelperVisibility();
    });
    modalObserver.observe(document.body, { attributes: true, subtree: true, attributeFilter: ['style'] });

    // Also re-check after a short delay when content may have changed.
    setTimeout(updateScrollHelperVisibility, 500);
}

// ====== CONSIGNMENTS ======
let consignmentsCache = [];
let consignmentDetailCache = null;

const CONSIGNMENT_STATUS_LABELS = {
    pendente: 'Pendente',
    pago: 'Pago',
    cancelado: 'Cancelado',
};

const CONSIGNMENT_TYPE_LABELS = {
    pf: 'Pessoa Física',
    pj: 'Pessoa Jurídica',
};

const PAYMENT_METHOD_LABELS = {
    dinheiro: 'Dinheiro',
    pix: 'Pix',
    cartao_credito: 'Cartão de Crédito',
    cartao_debito: 'Cartão de Débito',
};

function initConsignmentsPage() {
    if (!requirePageAccess(['gerente', 'caixa'])) return;
    highlightNav('consignados');
    loadConsignments();
}

async function loadConsignments() {
    const container = document.getElementById('consignments-list');
    if (!container) return;

    const statusFilter = document.getElementById('consignment-status-filter')?.value || 'todos';
    const typeFilter = document.getElementById('consignment-type-filter')?.value || '';
    const search = document.getElementById('consignment-search')?.value.trim() || '';
    const sortBy = document.getElementById('consignment-sort')?.value || 'created_at';
    const sortOrder = document.getElementById('consignment-sort-order')?.value || 'desc';

    container.innerHTML = '<div class="loading">Carregando...</div>';

    try {
        const params = [];
        if (statusFilter) params.push('status=' + encodeURIComponent(statusFilter));
        if (typeFilter) params.push('order_type=' + encodeURIComponent(typeFilter));
        if (search) params.push('search=' + encodeURIComponent(search));
        params.push('sort_by=' + encodeURIComponent(sortBy));
        params.push('sort_order=' + encodeURIComponent(sortOrder));
        const url = API_BASE + '/consignados?' + params.join('&');

        const res = await apiFetch(url);
        const data = await res.json();
        if (data.error) {
            container.innerHTML = '<div class="error-msg">' + data.error + '</div>';
            return;
        }
        consignmentsCache = data;

        if (data.length === 0) {
            container.innerHTML = '<p class="empty-msg">Nenhum consignado encontrado</p>';
            return;
        }

        container.innerHTML = data.map(c => {
            const statusClass = c.status === 'pendente' ? 'status-pendente' : (c.status === 'pago' ? 'status-pago' : 'status-cancelado');
            const badge = c.pending_days > 0 && c.status === 'pendente'
                ? `<span class="consignment-days">${c.pending_days} dia${c.pending_days > 1 ? 's' : ''}</span>`
                : '';
            return `
            <div class="consignment-card ${statusClass}" onclick="if(!event.target.closest('button'))openConsignmentDetail(${c.id})" style="cursor:pointer;">
                <div class="consignment-info">
                    <div class="consignment-header">
                        <span class="consignment-name">${c.customer_name}</span>
                        <span class="consignment-type ${c.order_type === 'pj' ? 'type-pj' : 'type-pf'}">${CONSIGNMENT_TYPE_LABELS[c.order_type] || c.order_type}</span>
                    </div>
                    <div class="consignment-meta">
                        ${c.customer_phone ? c.customer_phone + ' | ' : ''}
                        ${c.customer_document ? c.customer_document : ''}
                    </div>
                    <div class="consignment-values">
                        <span>Total: <strong>${formatCurrency(c.total)}</strong></span>
                        <span>Pago: <strong>${formatCurrency(c.amount_paid)}</strong></span>
                        <span>Saldo: <strong>${formatCurrency(c.balance)}</strong></span>
                        ${badge}
                    </div>
                    <div class="consignment-status">
                        <span class="status-badge ${statusClass}">${CONSIGNMENT_STATUS_LABELS[c.status] || c.status}</span>
                        <span class="consignment-date">${c.created_at ? new Date(c.created_at).toLocaleDateString('pt-BR') : '-'}</span>
                    </div>
                </div>
                <div class="consignment-actions">
                    ${c.status !== 'cancelado' ? `<button onclick="editConsignment(${c.id})" class="btn-small btn-edit">Editar</button>` : ''}
                    ${c.status !== 'cancelado' && c.amount_paid === 0 ? `<button onclick="cancelConsignment(${c.id})" class="btn-small btn-danger">Cancelar</button>` : ''}
                </div>
            </div>
        `}).join('');
    } catch (err) {
        container.innerHTML = '<div class="error-msg">Erro ao carregar consignados</div>';
    }
}

async function openConsignmentDetail(consignmentId) {
    try {
        const res = await apiFetch(API_BASE + '/consignados/' + consignmentId);
        const data = await res.json();
        if (data.error) {
            alert(data.error);
            return;
        }
        consignmentDetailCache = data;
        document.getElementById('consignment-detail-title').textContent = 'Consignado #' + data.id;
        document.getElementById('consignment-detail-customer').textContent = data.customer_name || '-';
        document.getElementById('consignment-detail-type').textContent = CONSIGNMENT_TYPE_LABELS[data.order_type] || data.order_type;
        document.getElementById('consignment-detail-status').textContent = CONSIGNMENT_STATUS_LABELS[data.status] || data.status;
        document.getElementById('consignment-detail-total').textContent = formatCurrency(data.total);
        document.getElementById('consignment-detail-paid').textContent = formatCurrency(data.amount_paid);
        document.getElementById('consignment-detail-balance').textContent = formatCurrency(data.balance);
        document.getElementById('consignment-detail-days').textContent = data.pending_days + ' dia' + (data.pending_days > 1 ? 's' : '');
        document.getElementById('consignment-detail-due').textContent = data.due_date ? new Date(data.due_date).toLocaleDateString('pt-BR') : '-';
        document.getElementById('consignment-detail-notes').textContent = data.notes || '-';
        document.getElementById('consignment-detail-waiter').textContent = data.waiter_name || '-';
        document.getElementById('consignment-detail-created').textContent = data.created_at ? new Date(data.created_at).toLocaleString('pt-BR') : '-';

        const itemsEl = document.getElementById('consignment-detail-items');
        itemsEl.innerHTML = data.items.map(item => `
            <div class="detail-item">
                <span>${item.quantity}x ${item.product_name}</span>
                <span>${formatCurrency(item.subtotal)}</span>
            </div>
        `).join('');

        const paymentsEl = document.getElementById('consignment-detail-payments');
        if (data.payments && data.payments.length > 0) {
            paymentsEl.innerHTML = data.payments.map(p => `
                <div class="detail-payment">
                    <span>${PAYMENT_METHOD_LABELS[p.payment_method] || p.payment_method} ${p.card_machine ? '(Máq. ' + p.card_machine + ')' : ''}</span>
                    <span><strong>${formatCurrency(p.amount)}</strong> em ${p.created_at ? new Date(p.created_at).toLocaleDateString('pt-BR') : '-'}</span>
                </div>
            `).join('');
        } else {
            paymentsEl.innerHTML = '<p class="empty-msg">Nenhum pagamento registrado</p>';
        }

        const payBtn = document.getElementById('consignment-detail-pay-btn');
        if (payBtn) payBtn.style.display = data.status === 'pendente' ? 'inline-block' : 'none';

        document.getElementById('consignment-detail-modal').style.display = 'flex';
    } catch (err) {
        alert('Erro ao carregar detalhes');
    }
}

function closeConsignmentDetailModal() {
    document.getElementById('consignment-detail-modal').style.display = 'none';
    consignmentDetailCache = null;
}

async function openConsignmentPaymentModal(consignmentId) {
    if (!consignmentDetailCache || consignmentDetailCache.id !== consignmentId) {
        await openConsignmentDetail(consignmentId);
    }
    if (!consignmentDetailCache) return;
    document.getElementById('consignment-payment-id').value = consignmentDetailCache.id;
    document.getElementById('consignment-payment-balance').textContent = formatCurrency(consignmentDetailCache.balance);
    document.getElementById('consignment-payment-amount').value = consignmentDetailCache.balance.toFixed(2);
    document.getElementById('consignment-payment-method').value = 'dinheiro';
    document.getElementById('consignment-payment-card-machine').value = '1';
    document.getElementById('consignment-payment-error').style.display = 'none';
    document.getElementById('consignment-payment-card-section').style.display = 'none';
    document.getElementById('consignment-payment-modal').style.display = 'flex';
}

function closeConsignmentPaymentModal() {
    document.getElementById('consignment-payment-modal').style.display = 'none';
}

function onConsignmentPaymentMethodChange() {
    const method = document.getElementById('consignment-payment-method').value;
    const cardSection = document.getElementById('consignment-payment-card-section');
    cardSection.style.display = method.startsWith('cartao') ? 'block' : 'none';
}

async function submitConsignmentPayment() {
    const id = document.getElementById('consignment-payment-id').value;
    const errorEl = document.getElementById('consignment-payment-error');
    errorEl.style.display = 'none';

    const payload = {
        amount: parseFloat(document.getElementById('consignment-payment-amount').value) || 0,
        payment_method: document.getElementById('consignment-payment-method').value,
        card_machine: document.getElementById('consignment-payment-card-machine').value,
        notes: document.getElementById('consignment-payment-notes').value.trim() || null,
    };

    if (!payload.amount || payload.amount <= 0) {
        errorEl.textContent = 'Informe um valor válido';
        errorEl.style.display = 'block';
        return;
    }

    try {
        const res = await apiFetch(API_BASE + '/consignados/' + id + '/pagamento', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closeConsignmentPaymentModal();
        closeConsignmentDetailModal();
        loadConsignments();
    } catch (err) {
        errorEl.textContent = 'Erro ao registrar pagamento';
        errorEl.style.display = 'block';
    }
}

async function cancelConsignment(consignmentId) {
    if (!confirm('Deseja realmente cancelar este consignado? O estoque será devolvido.')) return;
    try {
        const res = await apiFetch(API_BASE + '/consignados/' + consignmentId + '/cancelar', { method: 'POST' });
        const data = await res.json();
        if (data.error) {
            alert(data.error);
            return;
        }
        closeConsignmentDetailModal();
        loadConsignments();
    } catch (err) {
        alert('Erro ao cancelar');
    }
}

function editConsignment(consignmentId) {
    const c = consignmentsCache.find(item => item.id === consignmentId);
    if (!c) return;
    document.getElementById('consignment-edit-id').value = c.id;
    document.getElementById('consignment-edit-type').value = c.order_type;
    document.getElementById('consignment-edit-due').value = c.due_date || '';
    document.getElementById('consignment-edit-notes').value = c.notes || '';
    document.getElementById('consignment-edit-modal').style.display = 'flex';
}

function closeConsignmentEditModal() {
    document.getElementById('consignment-edit-modal').style.display = 'none';
}

async function submitConsignmentEdit() {
    const id = document.getElementById('consignment-edit-id').value;
    const errorEl = document.getElementById('consignment-edit-error');
    errorEl.style.display = 'none';

    const payload = {
        order_type: document.getElementById('consignment-edit-type').value,
        due_date: document.getElementById('consignment-edit-due').value || null,
        notes: document.getElementById('consignment-edit-notes').value.trim() || null,
    };

    try {
        const res = await apiFetch(API_BASE + '/consignados/' + id, {
            method: 'PUT',
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closeConsignmentEditModal();
        loadConsignments();
    } catch (err) {
        errorEl.textContent = 'Erro ao salvar';
        errorEl.style.display = 'block';
    }
}

function showNewConsignmentModal() {
    if (!canManageConsignments()) {
        alert('Acesso restrito');
        return;
    }
    document.getElementById('new-consignment-customer-id').value = '';
    document.getElementById('new-consignment-customer-name').value = '';
    document.getElementById('new-consignment-type').value = 'pf';
    document.getElementById('new-consignment-due').value = '';
    document.getElementById('new-consignment-notes').value = '';
    document.getElementById('new-consignment-items').innerHTML = '';
    document.getElementById('new-consignment-error').style.display = 'none';
    document.getElementById('new-consignment-modal').style.display = 'flex';
}

function closeNewConsignmentModal() {
    document.getElementById('new-consignment-modal').style.display = 'none';
}

let newConsignmentCustomerId = null;
let consignmentCustomerSearchDebounce = null;

function renderConsignmentCustomerSuggestions(customers) {
    const suggestionsEl = document.getElementById('new-consignment-customer-suggestions');
    if (!suggestionsEl) return;
    if (customers.length === 0) {
        suggestionsEl.innerHTML = '<div class="autocomplete-empty">Nenhum cliente encontrado. ' + getCreateCustomerButtonHtml('openCreateCustomerForConsignment()') + '</div>';
        suggestionsEl.style.display = 'block';
        return;
    }
    suggestionsEl.innerHTML = customers.map(c => `
        <div class="autocomplete-item" onclick="selectConsignmentCustomer(${c.id}, '${c.name.replace(/'/g, "\\'")}')">
            <span>${c.name}</span>
            <span class="autocomplete-meta">${c.phone || ''} ${c.document ? '| ' + c.document : ''}</span>
        </div>
    `).join('');
    suggestionsEl.style.display = 'block';
}

async function searchConsignmentCustomer(query) {
    const suggestionsEl = document.getElementById('new-consignment-customer-suggestions');
    if (!suggestionsEl) return;
    if (!query.trim()) {
        suggestionsEl.style.display = 'none';
        return;
    }
    clearTimeout(consignmentCustomerSearchDebounce);
    consignmentCustomerSearchDebounce = setTimeout(async () => {
        try {
            const res = await apiFetch(API_BASE + '/clientes?active_only=true&search=' + encodeURIComponent(query.trim()));
            const data = await res.json();
            if (data.error) {
                suggestionsEl.style.display = 'none';
                return;
            }
            renderConsignmentCustomerSuggestions(data);
        } catch (err) {
            suggestionsEl.style.display = 'none';
        }
    }, 250);
}

async function showAllConsignmentCustomerSuggestions() {
    const input = document.getElementById('new-consignment-customer-name');
    if (input) input.value = '';
    newConsignmentCustomerId = null;
    document.getElementById('new-consignment-customer-id').value = '';

    try {
        const res = await apiFetch(API_BASE + '/clientes?active_only=true');
        const data = await res.json();
        if (data.error) return;
        renderConsignmentCustomerSuggestions(data);
    } catch (err) {}
}

function selectConsignmentCustomer(id, name) {
    newConsignmentCustomerId = id;
    document.getElementById('new-consignment-customer-id').value = id;
    document.getElementById('new-consignment-customer-name').value = name;
    document.getElementById('new-consignment-customer-suggestions').style.display = 'none';
}

function hideConsignmentCustomerSuggestions() {
    const suggestionsEl = document.getElementById('new-consignment-customer-suggestions');
    if (suggestionsEl) suggestionsEl.style.display = 'none';
}

document.addEventListener('click', (e) => {
    const modal = document.getElementById('new-consignment-modal');
    if (modal && !modal.contains(e.target)) {
        hideConsignmentCustomerSuggestions();
    }
});

let newConsignmentItems = [];
let consignmentQuantities = {};
let consignmentProductsData = [];
let consignmentInitialStock = {};
let consignmentSelectionHtml = '';
let currentConsignmentCategory = 'TODOS';
let currentConsignmentSearch = '';
let consignmentSearchDebounce = null;

function openConsignmentItemSelection() {
    Promise.all([
        apiFetch(API_BASE + '/produtos').then(r => r.json()),
        apiFetch(API_BASE + '/categorias').then(r => r.json())
    ])
        .then(([products, categories]) => {
            consignmentQuantities = {};
            consignmentInitialStock = {};
            consignmentProductsData = products;
            currentConsignmentCategory = 'TODOS';
            currentConsignmentSearch = '';
            products.forEach(p => {
                consignmentQuantities[p.id] = 0;
                consignmentInitialStock[p.id] = p.stock;
            });

            consignmentSelectionHtml = buildConsignmentSelectionView(products, categories);
            document.getElementById('consignment-item-selection-content').innerHTML = consignmentSelectionHtml;
            document.getElementById('consignment-item-selection-modal').style.display = 'flex';
        });
}

function buildConsignmentSelectionView(products, categories) {
    const categoryList = (categories || []).sort((a, b) => a.name.localeCompare(b.name));
    const categoryButtons = categoryList.map(c =>
        `<button type="button" class="category-btn" data-category="${c.name}" onclick="filterConsignmentCategory(this)">${c.name}</button>`
    ).join('');

    const listHtml = products.map(p => {
        const hasDiscount = p.discounted_price !== undefined && p.discounted_price < p.price;
        const priceHtml = hasDiscount
            ? `<div class="prod-price"><span class="prod-original-price">${formatCurrency(p.price)}</span> ${formatCurrency(p.discounted_price)} <span class="promo-badge">${p.active_promotion || 'Promoção'}</span></div>`
            : `<div class="prod-price">${formatCurrency(p.price)}</div>`;
        return `
        <div class="pedido-product-row" data-category="${p.category}">
            <div class="prod-info">
                <div class="prod-name">${p.name}</div>
                <div class="prod-stock" id="cstock-${p.id}" data-cat="${p.category}">
                    Estoque: <strong>${p.stock}</strong>
                </div>
                ${priceHtml}
            </div>
            <div class="qty-control">
                <button class="btn-sm btn-sm-remove" onclick="changeConsignmentQty(${p.id}, -1)">-</button>
                <input type="number" class="qty-input" id="cqty-${p.id}" value="0" min="0" max="${p.stock}" readonly>
                <button class="btn-sm btn-sm-add" onclick="changeConsignmentQty(${p.id}, 1)">+</button>
            </div>
        </div>
    `;
    }).join('');

    return `
        <h3>Adicionar Itens ao Consignado</h3>
        <div class="pedido-search-bar">
            <input type="text" id="consignment-search" class="input-field" placeholder="Buscar produto..." oninput="filterConsignmentSearch(this.value)">
        </div>
        <div class="category-filter">
            <button type="button" class="category-btn active" data-category="TODOS" onclick="filterConsignmentCategory(this)">Todos</button>
            ${categoryButtons}
        </div>
        <div class="pedido-product-list" id="consignment-product-list">${listHtml}</div>
        <div style="display:flex;gap:8px;margin-top:12px;">
            <button onclick="reviewConsignmentSelection()" class="btn-primary-full" style="flex:1;">Revisar Itens</button>
            <button onclick="closeConsignmentItemSelection()" class="btn-secondary-full" style="flex:1;">Cancelar</button>
        </div>
        <p id="consignment-selection-error" class="error-msg" style="display:none;"></p>
    `;
}

function applyConsignmentFilters() {
    const q = currentConsignmentSearch;
    const cat = currentConsignmentCategory;
    document.querySelectorAll('#consignment-product-list .pedido-product-row').forEach(row => {
        const name = (row.querySelector('.prod-name')?.textContent || '').toLowerCase();
        const rowCat = row.dataset.category || '';
        const matchesSearch = !q || name.includes(q);
        const matchesCategory = cat === 'TODOS' || rowCat === cat;
        row.style.display = (matchesSearch && matchesCategory) ? '' : 'none';
    });
}

function filterConsignmentCategory(btn) {
    currentConsignmentCategory = btn.dataset.category;
    const modal = document.getElementById('consignment-item-selection-content');
    modal.querySelectorAll('.category-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyConsignmentFilters();
}

function filterConsignmentSearch(value) {
    clearTimeout(consignmentSearchDebounce);
    consignmentSearchDebounce = setTimeout(() => {
        currentConsignmentSearch = value.toLowerCase().trim();
        applyConsignmentFilters();
    }, 250);
}

function changeConsignmentQty(productId, delta) {
    const maxStock = consignmentInitialStock[productId] || 0;
    let qty = (consignmentQuantities[productId] || 0) + delta;
    if (qty < 0) qty = 0;
    if (qty > maxStock) qty = maxStock;
    consignmentQuantities[productId] = qty;

    const remaining = maxStock - qty;
    const input = document.getElementById('cqty-' + productId);
    const stockEl = document.getElementById('cstock-' + productId);
    if (input) input.value = qty;
    if (stockEl) {
        const cat = stockEl.dataset.cat || '';
        stockEl.innerHTML = 'Estoque: <strong>' + remaining + '</strong> | ' + cat;
    }
}

function closeConsignmentItemSelection() {
    document.getElementById('consignment-item-selection-modal').style.display = 'none';
}

function reviewConsignmentSelection() {
    const selected = [];
    let total = 0;
    for (const [pid, qty] of Object.entries(consignmentQuantities)) {
        if (qty > 0) {
            const product = consignmentProductsData.find(p => p.id === parseInt(pid));
            if (product) {
                const unitPrice = product.discounted_price !== undefined ? product.discounted_price : product.price;
                const subtotal = qty * unitPrice;
                total += subtotal;
                selected.push({ ...product, qty, unitPrice, subtotal });
            }
        }
    }

    const errorEl = document.getElementById('consignment-selection-error');
    if (selected.length === 0) {
        errorEl.textContent = 'Selecione ao menos 1 item';
        errorEl.style.display = 'block';
        return;
    }
    errorEl.style.display = 'none';

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
        <h3>Revisar Itens do Consignado</h3>
        <p style="font-size:13px;color:var(--text-muted);margin-bottom:14px;">
            Confira os itens antes de adicionar ao consignado.
        </p>
        <div class="review-list">${itemsHtml}</div>
        <div class="review-total">
            <span>Total dos Itens</span>
            <span>${formatCurrency(total)}</span>
        </div>
        <div style="display:flex;gap:8px;margin-top:14px;">
            <button onclick="confirmConsignmentItems()" class="btn-primary-full" style="flex:1;">Confirmar e Adicionar</button>
            <button onclick="backToConsignmentSelection()" class="btn-secondary-full" style="flex:1;">Voltar</button>
        </div>
        <p id="consignment-selection-error" class="error-msg" style="display:none;"></p>
    `;

    document.getElementById('consignment-item-selection-content').innerHTML = reviewHtml;
}

function backToConsignmentSelection() {
    document.getElementById('consignment-item-selection-content').innerHTML = consignmentSelectionHtml;
    for (const [pid, qty] of Object.entries(consignmentQuantities)) {
        const input = document.getElementById('cqty-' + pid);
        if (input) input.value = qty;
        const stockEl = document.getElementById('cstock-' + pid);
        if (stockEl) {
            const maxStock = consignmentInitialStock[pid] || 0;
            const remaining = maxStock - qty;
            const cat = stockEl.dataset.cat || '';
            stockEl.innerHTML = 'Estoque: <strong>' + remaining + '</strong> | ' + cat;
        }
    }
}

function confirmConsignmentItems() {
    for (const [pid, qty] of Object.entries(consignmentQuantities)) {
        if (qty > 0) {
            const product = consignmentProductsData.find(p => p.id === parseInt(pid));
            if (product) {
                const unitPrice = product.discounted_price !== undefined ? product.discounted_price : product.price;
                const existing = newConsignmentItems.find(i => i.product_id === product.id);
                if (existing) {
                    existing.quantity += qty;
                    existing.subtotal = round(existing.quantity * existing.unit_price, 2);
                } else {
                    newConsignmentItems.push({
                        product_id: product.id,
                        name: product.name,
                        quantity: qty,
                        unit_price: unitPrice,
                        subtotal: round(qty * unitPrice, 2),
                    });
                }
            }
        }
    }
    renderNewConsignmentItems();
    closeConsignmentItemSelection();
}

function renderNewConsignmentItems() {
    const container = document.getElementById('new-consignment-items-list');
    if (!container) return;
    if (newConsignmentItems.length === 0) {
        container.innerHTML = '<p class="empty-msg">Nenhum item adicionado</p>';
    } else {
        container.innerHTML = newConsignmentItems.map((item, idx) => `
            <div class="consignment-item-row">
                <div style="flex:1;">
                    <div style="font-weight:600;">${item.name}</div>
                    <div style="font-size:12px;color:var(--text-muted);">${item.quantity}x ${formatCurrency(item.unit_price)}</div>
                </div>
                <div style="font-weight:700;">${formatCurrency(item.subtotal)}</div>
                <button type="button" onclick="removeNewConsignmentItem(${idx})" class="btn-small btn-danger" style="margin-left:8px;">Remover</button>
            </div>
        `).join('');
    }
    updateNewConsignmentTotal();
}

function removeNewConsignmentItem(index) {
    newConsignmentItems.splice(index, 1);
    renderNewConsignmentItems();
}

function updateNewConsignmentTotal() {
    const total = newConsignmentItems.reduce((sum, i) => sum + (i.subtotal || 0), 0);
    const el = document.getElementById('new-consignment-total');
    if (el) el.textContent = formatCurrency(total);
}

function showNewConsignmentModal() {
    if (!canManageConsignments()) {
        alert('Acesso restrito');
        return;
    }
    document.getElementById('new-consignment-customer-id').value = '';
    document.getElementById('new-consignment-customer-name').value = '';
    document.getElementById('new-consignment-type').value = 'pf';
    document.getElementById('new-consignment-due').value = '';
    document.getElementById('new-consignment-notes').value = '';
    document.getElementById('new-consignment-error').style.display = 'none';
    newConsignmentItems = [];
    newConsignmentCustomerId = null;
    renderNewConsignmentItems();
    document.getElementById('new-consignment-modal').style.display = 'flex';
}

async function submitNewConsignment() {
    const errorEl = document.getElementById('new-consignment-error');
    errorEl.style.display = 'none';

    const customerId = parseInt(document.getElementById('new-consignment-customer-id').value) || newConsignmentCustomerId;
    if (!customerId) {
        errorEl.textContent = 'Selecione um cliente cadastrado';
        errorEl.style.display = 'block';
        return;
    }
    if (newConsignmentItems.length === 0) {
        errorEl.textContent = 'Adicione ao menos um item';
        errorEl.style.display = 'block';
        return;
    }

    const items = newConsignmentItems.map(i => ({
        product_id: i.product_id,
        quantity: i.quantity,
        unit_price: i.unit_price,
    }));

    const payload = {
        customer_id: customerId,
        order_type: document.getElementById('new-consignment-type').value,
        due_date: document.getElementById('new-consignment-due').value || null,
        notes: document.getElementById('new-consignment-notes').value.trim() || null,
        items: items,
    };

    try {
        const res = await apiFetch(API_BASE + '/consignados', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closeNewConsignmentModal();
        loadConsignments();
    } catch (err) {
        errorEl.textContent = 'Erro ao criar consignado';
        errorEl.style.display = 'block';
    }
}

// ====== TABLE TO CONSIGNMENT (FIADO) ======
let fiadoOrderId = null;
let fiadoCustomerId = null;
let fiadoCustomerSearchDebounce = null;

function showFiadoModal(orderId, currentCustomerId, currentCustomerName) {
    if (!canInitiateConsignment()) {
        alert('Acesso restrito');
        return;
    }
    fiadoOrderId = orderId;
    fiadoCustomerId = currentCustomerId || null;
    document.getElementById('fiado-order-id').value = orderId;
    document.getElementById('fiado-customer-id').value = currentCustomerId || '';
    document.getElementById('fiado-customer-name').value = currentCustomerName || '';
    document.getElementById('fiado-error').style.display = 'none';
    document.getElementById('fiado-modal').style.display = 'flex';
}

function closeFiadoModal() {
    document.getElementById('fiado-modal').style.display = 'none';
    fiadoOrderId = null;
    fiadoCustomerId = null;
}

function renderFiadoCustomerSuggestions(customers) {
    const suggestionsEl = document.getElementById('fiado-customer-suggestions');
    if (!suggestionsEl) return;
    if (customers.length === 0) {
        suggestionsEl.innerHTML = '<div class="autocomplete-empty">Nenhum cliente encontrado. ' + getCreateCustomerButtonHtml('openCreateCustomerForFiado()') + '</div>';
        suggestionsEl.style.display = 'block';
        return;
    }
    suggestionsEl.innerHTML = customers.map(c => `
        <div class="autocomplete-item" onclick="selectFiadoCustomer(${c.id}, '${c.name.replace(/'/g, "\\'")}')">
            <span>${c.name}</span>
            <span class="autocomplete-meta">${c.phone || ''} ${c.document ? '| ' + c.document : ''}</span>
        </div>
    `).join('');
    suggestionsEl.style.display = 'block';
}

async function searchFiadoCustomer(query) {
    const suggestionsEl = document.getElementById('fiado-customer-suggestions');
    if (!suggestionsEl) return;
    if (!query.trim()) {
        suggestionsEl.style.display = 'none';
        return;
    }
    clearTimeout(fiadoCustomerSearchDebounce);
    fiadoCustomerSearchDebounce = setTimeout(async () => {
        try {
            const res = await apiFetch(API_BASE + '/clientes?active_only=true&search=' + encodeURIComponent(query.trim()));
            const data = await res.json();
            if (data.error) {
                suggestionsEl.style.display = 'none';
                return;
            }
            renderFiadoCustomerSuggestions(data);
        } catch (err) {
            suggestionsEl.style.display = 'none';
        }
    }, 250);
}

async function showAllFiadoCustomerSuggestions() {
    const input = document.getElementById('fiado-customer-name');
    if (input) input.value = '';
    fiadoCustomerId = null;
    document.getElementById('fiado-customer-id').value = '';

    try {
        const res = await apiFetch(API_BASE + '/clientes?active_only=true');
        const data = await res.json();
        if (data.error) return;
        renderFiadoCustomerSuggestions(data);
    } catch (err) {}
}

function selectFiadoCustomer(id, name) {
    fiadoCustomerId = id;
    document.getElementById('fiado-customer-id').value = id;
    document.getElementById('fiado-customer-name').value = name;
    document.getElementById('fiado-customer-suggestions').style.display = 'none';
}

function hideFiadoCustomerSuggestions() {
    const suggestionsEl = document.getElementById('fiado-customer-suggestions');
    if (suggestionsEl) suggestionsEl.style.display = 'none';
}

document.addEventListener('click', (e) => {
    const modal = document.getElementById('fiado-modal');
    if (modal && !modal.contains(e.target)) {
        hideFiadoCustomerSuggestions();
    }
});

async function submitFiado() {
    const errorEl = document.getElementById('fiado-error');
    errorEl.style.display = 'none';

    const customerId = parseInt(document.getElementById('fiado-customer-id').value) || fiadoCustomerId;
    if (!customerId) {
        errorEl.textContent = 'Selecione ou cadastre um cliente para vincular ao fiado.';
        errorEl.style.display = 'block';
        return;
    }

    try {
        const res = await apiFetch(API_BASE + '/comanda/' + fiadoOrderId + '/converter-fiado', {
            method: 'POST',
            body: JSON.stringify({ customer_id: customerId }),
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closeFiadoModal();
        window.location.href = '/consignados';
    } catch (err) {
        errorEl.textContent = 'Erro ao gerar consignado';
        errorEl.style.display = 'block';
    }
}


// ====== BALCAO PDV ======
let balcaoQuantities = {};
let balcaoProductsData = [];
let balcaoInitialStock = {};
let balcaoCurrentOrder = null;
let balcaoCurrentCustomerId = null;
let balcaoCurrentCustomerName = null;
const FICHA_MODE_KEY = 'lads_balcao_ficha_mode';
let balcaoFichaMode = localStorage.getItem(FICHA_MODE_KEY) === 'true';
let balcaoCurrentCategory = 'TODOS';
let balcaoCurrentSearch = '';
let balcaoSearchDebounce = null;
let balcaoShowOnlyInStock = true;

function toggleBalcaoFichaMode() {
    balcaoFichaMode = !balcaoFichaMode;
    localStorage.setItem(FICHA_MODE_KEY, String(balcaoFichaMode));
    updateFichaModeButton();
}

function updateFichaModeButton() {
    const btn = document.getElementById('btn-balcao-ficha-mode');
    if (!btn) return;
    btn.textContent = 'Modo Ficha: ' + (balcaoFichaMode ? 'ON' : 'OFF');
    if (balcaoFichaMode) {
        btn.classList.add('active');
        btn.style.background = 'var(--accent)';
        btn.style.color = '#fff';
    } else {
        btn.classList.remove('active');
        btn.style.background = '';
        btn.style.color = '';
    }
}

async function loadBalcaoDetail() {
    try {
        const res = await apiFetch(API_BASE + '/mesa/' + TABLE_ID);
        const data = await res.json();
        if (data.error) {
            alert(data.error);
            return;
        }
        document.getElementById('balcao-title').textContent = 'BALCÃO';
        document.getElementById('balcao-status').textContent = data.status === 'vazia' ? 'Pronto para atender' : 'Comanda aberta';
        if (!data.order_id) {
            await openBalcaoOrder();
            return;
        }
        balcaoCurrentOrder = data;
        balcaoCurrentCustomerId = data.customer_id || null;
        balcaoCurrentCustomerName = data.customer_name || null;
        renderBalcaoCustomerDisplay();
        renderBalcaoCart(data);
        loadBalcaoProducts();
    } catch (err) {
        console.error('Erro ao carregar balcão', err);
    }
}

async function openBalcaoOrder() {
    try {
        const res = await apiFetch(API_BASE + '/comanda/abrir', {
            method: 'POST',
            body: JSON.stringify({ table_id: TABLE_ID }),
        });
        const data = await res.json();
        if (data.error) {
            if (data.error === 'caixa_fechado') {
                showBalcaoCashRegisterClosedModal();
                return;
            }
            alert(data.error);
            return;
        }
        await loadBalcaoDetail();
    } catch (err) {
        alert('Erro ao abrir comanda do balcão');
    }
}

async function loadBalcaoProducts() {
    const listEl = document.getElementById('balcao-product-list');
    if (!listEl) return;
    try {
        const [productsRes, categoriesRes] = await Promise.all([
            apiFetch(API_BASE + '/produtos'),
            apiFetch(API_BASE + '/categorias'),
        ]);
        const products = await productsRes.json();
        const categories = await categoriesRes.json();
        const previousSteps = {};
        products.forEach(p => {
            const input = document.getElementById('bqty-' + p.id);
            previousSteps[p.id] = input ? input.value : '1';
        });
        balcaoProductsData = products;
        balcaoQuantities = {};
        balcaoInitialStock = {};
        products.forEach(p => {
            balcaoQuantities[p.id] = 0;
            balcaoInitialStock[p.id] = p.stock;
        });
        renderBalcaoProductGrid(products, categories);
        renderBalcaoCategoryFilter(categories);
        products.forEach(p => {
            const input = document.getElementById('bqty-' + p.id);
            if (input) input.value = previousSteps[p.id] || '1';
        });
    } catch (err) {
        listEl.innerHTML = '<div class="error-msg">Erro ao carregar produtos</div>';
    }
}

function renderBalcaoCategoryFilter(categories) {
    const container = document.getElementById('balcao-category-filter');
    if (!container) return;
    const sorted = (categories || []).sort((a, b) => a.name.localeCompare(b.name));
    container.innerHTML = `
        <button type="button" class="category-btn active" data-category="TODOS" onclick="filterBalcaoCategory(this)">Todos</button>
        ${sorted.map(c => `<button type="button" class="category-btn" data-category="${c.name}" onclick="filterBalcaoCategory(this)">${c.name}</button>`).join('')}
    `;
}

function renderBalcaoProductGrid(products, categories) {
    const listEl = document.getElementById('balcao-product-list');
    if (!listEl) return;
    if (products.length === 0) {
        listEl.innerHTML = '<p class="empty-msg">Nenhum produto disponível</p>';
        return;
    }
    const btn = document.getElementById('balcao-stock-filter');
    if (btn) btn.textContent = balcaoShowOnlyInStock ? 'Mostrar todos' : 'Mostrar apenas com estoque';
    listEl.innerHTML = products.map(p => {
        const hasDiscount = p.discounted_price !== undefined && p.discounted_price < p.price;
        const priceHtml = hasDiscount
            ? `<div class="prod-price"><span class="prod-original-price">${formatCurrency(p.price)}</span> ${formatCurrency(p.discounted_price)} <span class="promo-badge">${p.active_promotion || 'Promoção'}</span></div>`
            : `<div class="prod-price">${formatCurrency(p.price)}</div>`;
        return `
        <div class="balcao-product-card" data-category="${p.category}" data-name="${p.name.toLowerCase()}" data-stock="${p.stock}">
            <div class="balcao-product-info">
                <div class="prod-name">${p.name}</div>
                <div class="prod-stock" id="bstock-${p.id}" data-cat="${p.category}">Estoque: <strong>${p.stock}</strong></div>
                ${priceHtml}
            </div>
            <div class="qty-control">
                <button class="btn-sm btn-sm-remove" onclick="changeBalcaoQty(${p.id}, -1)">-</button>
                <input type="number" class="qty-input" id="bqty-${p.id}" value="1" min="1" max="${p.stock}" title="Quantidade por clique">
                <button class="btn-sm btn-sm-add" onclick="changeBalcaoQty(${p.id}, 1)">+</button>
            </div>
        </div>
    `;
    }).join('');
    applyBalcaoFilters();
}

function filterBalcaoCategory(btn) {
    balcaoCurrentCategory = btn.dataset.category;
    document.querySelectorAll('#balcao-category-filter .category-btn').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    applyBalcaoFilters();
}

function filterBalcaoSearch(value) {
    clearTimeout(balcaoSearchDebounce);
    balcaoSearchDebounce = setTimeout(() => {
        balcaoCurrentSearch = value.toLowerCase().trim();
        applyBalcaoFilters();
    }, 250);
}

function clearBalcaoSearch() {
    const input = document.getElementById('balcao-search');
    if (input) input.value = '';
    balcaoCurrentSearch = '';
    applyBalcaoFilters();
}

function applyBalcaoFilters() {
    document.querySelectorAll('.balcao-product-card').forEach(card => {
        const name = card.dataset.name || '';
        const cat = card.dataset.category || '';
        const stock = parseInt(card.dataset.stock || '0');
        const matchesSearch = !balcaoCurrentSearch || name.includes(balcaoCurrentSearch);
        const matchesCategory = balcaoCurrentCategory === 'TODOS' || cat === balcaoCurrentCategory;
        const matchesStock = !balcaoShowOnlyInStock || stock > 0;
        card.style.display = (matchesSearch && matchesCategory && matchesStock) ? '' : 'none';
    });
}

function toggleBalcaoStockFilter() {
    balcaoShowOnlyInStock = !balcaoShowOnlyInStock;
    const btn = document.getElementById('balcao-stock-filter');
    if (btn) btn.textContent = balcaoShowOnlyInStock ? 'Mostrar todos' : 'Mostrar apenas com estoque';
    applyBalcaoFilters();
}

async function changeBalcaoQty(productId, delta) {
    if (!balcaoCurrentOrder || !balcaoCurrentOrder.order_id) {
        alert('Nenhuma comanda aberta');
        return;
    }
    const input = document.getElementById('bqty-' + productId);
    const stepQty = parseInt(input ? input.value : 1) || 1;
    if (stepQty <= 0) {
        alert('Quantidade por clique deve ser pelo menos 1');
        return;
    }
    const quantity = delta > 0 ? stepQty : -stepQty;

    try {
        const res = await apiFetch(API_BASE + '/comanda/item', {
            method: 'POST',
            body: JSON.stringify({
                table_id: TABLE_ID,
                order_id: balcaoCurrentOrder.order_id,
                product_id: productId,
                quantity: quantity,
            }),
        });
        const data = await res.json();
        if (data.error) {
            if (data.error === 'caixa_fechado') {
                showBalcaoCashRegisterClosedModal();
                return;
            }
            alert(data.error);
            return;
        }
        await loadBalcaoDetail();
        const stockEl = document.getElementById('bstock-' + productId);
        if (stockEl && data.stock_remaining !== undefined) {
            stockEl.innerHTML = 'Estoque: <strong>' + data.stock_remaining + '</strong>';
            const card = stockEl.closest('.balcao-product-card');
            if (card) card.dataset.stock = data.stock_remaining;
        }
    } catch (err) {
        alert('Erro ao atualizar item');
    }
}

async function clearBalcaoQuantities() {
    if (!balcaoCurrentOrder || !balcaoCurrentOrder.order_id) {
        return;
    }
    if (!confirm('Deseja cancelar a comanda atual e limpar todos os itens?')) {
        return;
    }
    try {
        const res = await apiFetch(API_BASE + '/comanda/' + balcaoCurrentOrder.order_id + '/cancelar', {
            method: 'POST',
        });
        const data = await res.json();
        if (data.error) {
            alert(data.error);
            return;
        }
        await openBalcaoOrder();
    } catch (err) {
        alert('Erro ao cancelar comanda');
    }
}

function renderBalcaoCart(order) {
    const itemsContainer = document.getElementById('balcao-cart-items');
    const totalEl = document.getElementById('balcao-total');
    const orderNumberEl = document.getElementById('balcao-order-number');
    if (!itemsContainer || !totalEl) return;

    orderNumberEl.textContent = order && order.order_id ? '#' + order.order_id : '';

    const pedidos = order && order.pedidos ? order.pedidos : [];
    const allItems = [];
    pedidos.forEach(pedido => {
        pedido.items.forEach(item => {
            allItems.push(item);
        });
    });

    if (allItems.length === 0) {
        itemsContainer.innerHTML = '<p class="empty-msg">Nenhum item na comanda</p>';
    } else {
        itemsContainer.innerHTML = allItems.map(item => `
            <div class="balcao-cart-item">
                <div style="flex:1;">
                    <div style="font-weight:600;">${item.product_name}</div>
                    <div style="font-size:12px;color:var(--text-muted);">${item.quantity}x ${formatCurrency(item.unit_price)}</div>
                </div>
                <div style="font-weight:700;">${formatCurrency(item.subtotal)}</div>
            </div>
        `).join('');
    }

    const total = order && order.total ? order.total : 0;
    totalEl.textContent = formatCurrency(total);
}

function renderBalcaoCustomerDisplay() {
    const el = document.getElementById('balcao-customer-display');
    const btn = document.getElementById('btn-balcao-customer');
    if (!el || !btn) return;
    if (balcaoCurrentCustomerName) {
        el.textContent = 'Cliente: ' + balcaoCurrentCustomerName;
        el.style.display = 'block';
        btn.textContent = 'Trocar Cliente';
    } else {
        el.style.display = 'none';
        btn.textContent = 'Cliente';
    }
}

function showBalcaoCloseModal() {
    if (!balcaoCurrentOrder || !balcaoCurrentOrder.order_id || !balcaoCurrentOrder.total) {
        alert('Comanda vazia');
        return;
    }
    document.getElementById('balcao-close-total').textContent = formatCurrency(balcaoCurrentOrder.total);
    document.getElementById('balcao-close-method').value = 'dinheiro';
    document.getElementById('balcao-close-tendered').value = balcaoCurrentOrder.total.toFixed(2);
    updateBalcaoChange();
    document.getElementById('balcao-close-card-section').style.display = 'none';
    document.getElementById('balcao-close-cash-section').style.display = 'block';
    document.getElementById('balcao-close-error').style.display = 'none';
    document.getElementById('balcao-close-modal').style.display = 'flex';
}

function closeBalcaoCloseModal() {
    document.getElementById('balcao-close-modal').style.display = 'none';
}

function updateBalcaoCloseMethod() {
    const method = document.getElementById('balcao-close-method').value;
    const cardSection = document.getElementById('balcao-close-card-section');
    const cashSection = document.getElementById('balcao-close-cash-section');
    if (method === 'cartao_credito' || method === 'cartao_debito') {
        cardSection.style.display = 'block';
        cashSection.style.display = 'none';
    } else if (method === 'pix') {
        cardSection.style.display = 'none';
        cashSection.style.display = 'none';
    } else {
        cardSection.style.display = 'none';
        cashSection.style.display = 'block';
    }
}

function updateBalcaoChange() {
    const total = balcaoCurrentOrder ? balcaoCurrentOrder.total : 0;
    const tendered = parseFloat(document.getElementById('balcao-close-tendered').value) || 0;
    const change = Math.max(0, tendered - total);
    document.getElementById('balcao-close-change').textContent = formatCurrency(change);
}

async function confirmBalcaoClose() {
    const errorEl = document.getElementById('balcao-close-error');
    errorEl.style.display = 'none';
    if (!balcaoCurrentOrder || !balcaoCurrentOrder.order_id) return;

    const method = document.getElementById('balcao-close-method').value;
    const cardMachine = document.getElementById('balcao-close-card-machine').value;
    const tendered = parseFloat(document.getElementById('balcao-close-tendered').value) || 0;

    if (method === 'dinheiro' && tendered < balcaoCurrentOrder.total) {
        errorEl.textContent = 'Valor recebido menor que o total';
        errorEl.style.display = 'block';
        return;
    }

    const orderId = balcaoCurrentOrder.order_id;
    try {
        const res = await apiFetch(API_BASE + '/comanda/fechar', {
            method: 'POST',
            body: JSON.stringify({
                table_id: TABLE_ID,
                order_id: orderId,
                apply_service_charge: false,
                payment_method: method,
                card_machine: (method === 'cartao_credito' || method === 'cartao_debito') ? cardMachine : null,
                amount: method === 'dinheiro' ? tendered : null,
                ficha_mode: balcaoFichaMode,
            }),
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closeBalcaoCloseModal();
        const receiptMsg = data.receipt_result && data.receipt_result.success
            ? data.receipt_result.message || 'Nota enviada para impressão'
            : (data.receipt_result && data.receipt_result.error ? 'Erro na nota: ' + data.receipt_result.error : '');
        if (receiptMsg) {
            alert(receiptMsg);
        }
        await openBalcaoOrder();
    } catch (err) {
        errorEl.textContent = 'Erro ao finalizar venda';
        errorEl.style.display = 'block';
    }
}

async function printBalcaoReceipt() {
    if (!balcaoCurrentOrder || !balcaoCurrentOrder.order_id) {
        alert('Nenhuma comanda aberta');
        return;
    }
    await printBalcaoReceiptById(balcaoCurrentOrder.order_id, balcaoCurrentOrder.payment_method);
}

async function printBalcaoReceiptById(orderId, paymentMethod) {
    try {
        const res = await apiFetch(API_BASE + '/comanda/' + orderId + '/imprimir-nota', {
            method: 'POST',
            body: JSON.stringify({ payment_method: paymentMethod || null }),
        });
        const data = await res.json();
        if (data.error) {
            alert(data.error);
            return;
        }
    } catch (err) {
        alert('Erro ao imprimir nota');
    }
}

function showBalcaoCashRegisterClosedModal() {
    document.getElementById('balcao-cash-register-initial').value = '';
    document.getElementById('balcao-cash-register-closed-error').style.display = 'none';
    document.getElementById('balcao-cash-register-closed-modal').style.display = 'flex';
}

function closeBalcaoCashRegisterClosedModal() {
    document.getElementById('balcao-cash-register-closed-modal').style.display = 'none';
}

async function openCashRegisterFromBalcao() {
    const initial = parseFloat(document.getElementById('balcao-cash-register-initial').value) || 0;
    const errorEl = document.getElementById('balcao-cash-register-closed-error');
    errorEl.style.display = 'none';
    try {
        const res = await apiFetch(API_BASE + '/caixa/abrir', {
            method: 'POST',
            body: JSON.stringify({ initial_cash: initial }),
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closeBalcaoCashRegisterClosedModal();
        await openBalcaoOrder();
    } catch (err) {
        errorEl.textContent = 'Erro ao abrir caixa';
        errorEl.style.display = 'block';
    }
}

function openBalcaoCustomerModal() {
    document.getElementById('balcao-customer-id').value = balcaoCurrentCustomerId || '';
    document.getElementById('balcao-customer-name').value = balcaoCurrentCustomerName || '';
    document.getElementById('balcao-customer-suggestions').style.display = 'none';
    document.getElementById('balcao-customer-modal').style.display = 'flex';
}

function closeBalcaoCustomerModal() {
    document.getElementById('balcao-customer-modal').style.display = 'none';
}

let balcaoCustomerSearchDebounce = null;

function renderBalcaoCustomerSuggestions(customers) {
    const suggestionsEl = document.getElementById('balcao-customer-suggestions');
    if (!suggestionsEl) return;
    if (customers.length === 0) {
        suggestionsEl.innerHTML = '<div class="autocomplete-empty">Nenhum cliente encontrado. ' + getCreateCustomerButtonHtml('openCreateCustomerForBalcao()') + '</div>';
        suggestionsEl.style.display = 'block';
        return;
    }
    suggestionsEl.innerHTML = customers.map(c => `
        <div class="autocomplete-item" onclick="selectBalcaoCustomer(${c.id}, '${c.name.replace(/'/g, "\\'")}')">
            <span>${c.name}</span>
            <span class="autocomplete-meta">${c.phone || ''} ${c.document ? '| ' + c.document : ''}</span>
        </div>
    `).join('');
    suggestionsEl.style.display = 'block';
}

async function searchBalcaoCustomer(query) {
    const suggestionsEl = document.getElementById('balcao-customer-suggestions');
    if (!suggestionsEl) return;
    if (!query.trim()) {
        suggestionsEl.style.display = 'none';
        return;
    }
    clearTimeout(balcaoCustomerSearchDebounce);
    balcaoCustomerSearchDebounce = setTimeout(async () => {
        try {
            const res = await apiFetch(API_BASE + '/clientes?active_only=true&search=' + encodeURIComponent(query.trim()));
            const data = await res.json();
            if (data.error) {
                suggestionsEl.style.display = 'none';
                return;
            }
            renderBalcaoCustomerSuggestions(data);
        } catch (err) {
            suggestionsEl.style.display = 'none';
        }
    }, 250);
}

async function showAllBalcaoCustomers() {
    document.getElementById('balcao-customer-name').value = '';
    document.getElementById('balcao-customer-id').value = '';
    try {
        const res = await apiFetch(API_BASE + '/clientes?active_only=true');
        const data = await res.json();
        if (data.error) return;
        renderBalcaoCustomerSuggestions(data);
    } catch (err) {}
}

function selectBalcaoCustomer(id, name) {
    document.getElementById('balcao-customer-id').value = id;
    document.getElementById('balcao-customer-name').value = name;
    document.getElementById('balcao-customer-suggestions').style.display = 'none';
}

async function confirmBalcaoCustomer() {
    const customerId = parseInt(document.getElementById('balcao-customer-id').value) || null;
    const customerName = document.getElementById('balcao-customer-name').value.trim() || null;
    if (!customerId && !customerName) {
        closeBalcaoCustomerModal();
        return;
    }
    try {
        let data;
        if (balcaoCurrentOrder && balcaoCurrentOrder.order_id) {
            const res = await apiFetch(API_BASE + '/comanda/' + balcaoCurrentOrder.order_id + '/cliente', {
                method: 'POST',
                body: JSON.stringify({
                    customer_id: customerId,
                    customer_name: customerName,
                }),
            });
            data = await res.json();
        } else {
            const res = await apiFetch(API_BASE + '/comanda/abrir', {
                method: 'POST',
                body: JSON.stringify({
                    table_id: TABLE_ID,
                    customer_id: customerId,
                    customer_name: customerName,
                }),
            });
            data = await res.json();
        }
        if (data.error) {
            if (data.error === 'caixa_fechado') {
                showBalcaoCashRegisterClosedModal();
                return;
            }
            alert(data.error);
            return;
        }
        balcaoCurrentCustomerId = data.customer_id || customerId;
        balcaoCurrentCustomerName = data.customer_name || customerName || null;
        renderBalcaoCustomerDisplay();
        closeBalcaoCustomerModal();
        await loadBalcaoDetail();
    } catch (err) {
        alert('Erro ao vincular cliente');
    }
}

async function clearBalcaoCustomer() {
    balcaoCurrentCustomerId = null;
    balcaoCurrentCustomerName = null;
    try {
        if (balcaoCurrentOrder && balcaoCurrentOrder.order_id) {
            await apiFetch(API_BASE + '/comanda/' + balcaoCurrentOrder.order_id + '/cliente', {
                method: 'POST',
                body: JSON.stringify({ customer_id: null, customer_name: null }),
            });
        } else {
            await apiFetch(API_BASE + '/comanda/abrir', {
                method: 'POST',
                body: JSON.stringify({ table_id: TABLE_ID }),
            });
        }
        renderBalcaoCustomerDisplay();
        closeBalcaoCustomerModal();
        await loadBalcaoDetail();
    } catch (err) {
        alert('Erro ao remover cliente');
    }
}

document.addEventListener('click', (e) => {
    const modal = document.getElementById('balcao-customer-modal');
    if (modal && modal.style.display === 'flex' && !modal.contains(e.target)) {
        document.getElementById('balcao-customer-suggestions').style.display = 'none';
    }
});

function connectBalcaoWebSocket() {
    if (tableSocket) {
        const existingOnMessage = tableSocket.onmessage;
        tableSocket.onmessage = (event) => {
            if (existingOnMessage) existingOnMessage(event);
            try {
                const msg = JSON.parse(event.data);
                if (msg.type === 'table_update' && msg.data && String(msg.data.id) === String(TABLE_ID)) {
                    loadBalcaoDetail();
                }
            } catch (err) {}
        };
    }
}


// ====== DASHBOARDS ======
let dashboardCurrentTab = 'geral';
let dashboardCurrentData = {};
let dashboardEstoqueTableFilter = '';
let dashboardEstoqueProductFilter = '';
let dashboardEstoquePage = 1;
const DASHBOARD_ESTOQUE_PAGE_SIZE = 20;
let dashboardGestaoPage = 1;
const DASHBOARD_GESTAO_PAGE_SIZE = 50;
let dashboardCharts = {};

const DASHBOARD_COLORS = {
    primary: '#F7A046',
    secondary: '#4A9EFF',
    success: '#3CBC81',
    danger: '#E63946',
    warning: '#F7C948',
    info: '#7B68EE',
    text: '#E0E0E0',
    grid: 'rgba(255,255,255,0.1)',
};

function initDashboards() {
    if (!document.getElementById('dashboards-page')) return;
    if (!canViewDashboards()) {
        window.location.href = '/';
        return;
    }
    populateDashboardYearSelect();
    const today = toLocalDateString(new Date());
    const start = toLocalDateString(new Date(Date.now() - 6 * 24 * 60 * 60 * 1000));
    document.getElementById('dashboard-start-date').value = start;
    document.getElementById('dashboard-end-date').value = today;
    setActivePeriodChip('7d');
    loadDashboardData(dashboardCurrentTab);
}

function switchDashboardTab(tab) {
    dashboardCurrentTab = tab;
    dashboardGestaoPage = 1;
    document.querySelectorAll('.dashboards-nav-btn').forEach(btn => btn.classList.remove('active'));
    const activeBtn = document.querySelector(`.dashboards-nav-btn[data-tab="${tab}"]`);
    if (activeBtn) activeBtn.classList.add('active');

    const today = toLocalDateString(new Date());
    const start = toLocalDateString(new Date(Date.now() - 6 * 24 * 60 * 60 * 1000));
    document.getElementById('dashboard-start-date').value = start;
    document.getElementById('dashboard-end-date').value = today;
    setActivePeriodChip('7d');

    loadDashboardData(tab);
}

function formatDashboardDate(date) {
    return toLocalDateString(date);
}

function setActivePeriodChip(period) {
    document.querySelectorAll('.period-chip').forEach(chip => {
        chip.classList.toggle('active', chip.dataset.period === period);
    });
    const yearSelect = document.getElementById('dashboard-year-select');
    if (yearSelect) yearSelect.value = '';
}

function setDashboardPeriod(period) {
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    let start = new Date(today);
    let end = new Date(today);

    switch (period) {
        case 'today':
            break;
        case '7d':
            start.setDate(today.getDate() - 6);
            break;
        case '30d':
            start.setDate(today.getDate() - 29);
            break;
        case '90d':
            start.setDate(today.getDate() - 89);
            break;
        case '12m':
            start.setMonth(today.getMonth() - 11);
            start.setDate(1);
            break;
        case 'last_year':
            const lastYear = today.getFullYear() - 1;
            start = new Date(lastYear, 0, 1);
            end = new Date(lastYear, 11, 31);
            break;
        default:
            return;
    }

    document.getElementById('dashboard-start-date').value = formatDashboardDate(start);
    document.getElementById('dashboard-end-date').value = formatDashboardDate(end);
    setActivePeriodChip(period);
    dashboardGestaoPage = 1;
    loadDashboardData(dashboardCurrentTab);
}

function setDashboardYear(year) {
    if (!year) return;
    const y = parseInt(year);
    document.getElementById('dashboard-start-date').value = `${y}-01-01`;
    document.getElementById('dashboard-end-date').value = `${y}-12-31`;
    setActivePeriodChip(null);
    dashboardGestaoPage = 1;
    loadDashboardData(dashboardCurrentTab);
}

function populateDashboardYearSelect() {
    const select = document.getElementById('dashboard-year-select');
    if (!select) return;
    const currentYear = new Date().getFullYear();
    const startYear = 2023;
    for (let y = currentYear; y >= startYear; y--) {
        const option = document.createElement('option');
        option.value = y;
        option.textContent = y;
        select.appendChild(option);
    }
}

function applyDashboardDateFilter() {
    setActivePeriodChip(null);
    dashboardGestaoPage = 1;
    loadDashboardData(dashboardCurrentTab);
}

async function loadDashboardData(tab) {
    const content = document.getElementById('dashboards-content');
    if (!content) return;
    content.innerHTML = '<div class="loading-msg">Carregando...</div>';
    const start = document.getElementById('dashboard-start-date').value;
    const end = document.getElementById('dashboard-end-date').value;
    const params = [];
    if (start) params.push('start_date=' + encodeURIComponent(start));
    if (end) params.push('end_date=' + encodeURIComponent(end));
    if (tab === 'estoque') {
        if (dashboardEstoqueTableFilter) params.push('table_id=' + encodeURIComponent(dashboardEstoqueTableFilter));
        if (dashboardEstoqueProductFilter) params.push('product_id=' + encodeURIComponent(dashboardEstoqueProductFilter));
        params.push('page=' + encodeURIComponent(dashboardEstoquePage));
        params.push('page_size=' + encodeURIComponent(DASHBOARD_ESTOQUE_PAGE_SIZE));
    }
    if (tab === 'gestao') {
        params.push('page=' + encodeURIComponent(dashboardGestaoPage));
        params.push('page_size=' + encodeURIComponent(DASHBOARD_GESTAO_PAGE_SIZE));
    }
    const url = API_BASE + '/dashboards/' + tab + (params.length ? '?' + params.join('&') : '');
    try {
        const res = await apiFetch(url);
        const data = await res.json();
        if (data.error) {
            content.innerHTML = '<div class="error-msg">' + data.error + '</div>';
            return;
        }
        dashboardCurrentData[tab] = data;
        if (tab === 'geral') renderDashboardGeral(data);
        else if (tab === 'vendas') renderDashboardVendas(data);
        else if (tab === 'estoque') renderDashboardEstoque(data);
        else if (tab === 'clientes') renderDashboardClientes(data);
        else if (tab === 'funcionarios') renderDashboardFuncionarios(data);
        else if (tab === 'gestao') renderDashboardGestao(data);
    } catch (err) {
        content.innerHTML = '<div class="error-msg">Erro ao carregar dashboard</div>';
    }
}

function exportDashboardCSV() {
    const tab = dashboardCurrentTab;
    const start = document.getElementById('dashboard-start-date').value;
    const end = document.getElementById('dashboard-end-date').value;
    const params = ['format=csv'];
    if (start) params.push('start_date=' + encodeURIComponent(start));
    if (end) params.push('end_date=' + encodeURIComponent(end));
    const url = API_BASE + '/dashboards/' + tab + '?' + params.join('&');
    window.open(url, '_blank');
}

function destroyDashboardCharts() {
    Object.values(dashboardCharts).forEach(chart => chart.destroy());
    dashboardCharts = {};
}

function createDashboardCard(title, value, sub) {
    return `
        <div class="dashboards-card">
            <div class="dashboards-label">${title}</div>
            <div class="dashboards-value">${value}</div>
            ${sub ? `<div class="dashboards-sub">${sub}</div>` : ''}
        </div>
    `;
}

function renderDashboardGeral(data) {
    const content = document.getElementById('dashboards-content');
    destroyDashboardCharts();
    const cards = [
        createDashboardCard('Faturamento', formatCurrency(data.sales?.total || 0), `${data.sales?.orders_count || 0} comandas`),
        createDashboardCard('Taxa de Serviço', formatCurrency(data.sales?.service_charge || 0), '10% incluído'),
        createDashboardCard('Comandas Abertas', data.open_orders?.count || 0, formatCurrency(data.open_orders?.total || 0)),
        createDashboardCard('Consignados Pendentes', data.consignments?.pending_count || 0, formatCurrency(data.consignments?.pending_total || 0)),
        createDashboardCard('Consignados no Período', data.consignments?.period_count || 0, formatCurrency(data.consignments?.period_total || 0)),
        createDashboardCard('Produtos em Falta', data.stock?.counts?.em_falta || 0, `${data.stock?.counts?.em_risco || 0} em risco`),
    ];

    const periodText = `Período: ${data.period?.start || ''} a ${data.period?.end || ''}`;
    content.innerHTML = `
        <div class="dashboard-section-title">${periodText}</div>
        <div class="dashboard-cards-grid">${cards.join('')}</div>
        <div class="dashboard-charts-grid">
            <div class="dashboard-chart-card">
                <h4>Vendas por Hora</h4>
                <div class="chart-wrapper"><canvas id="chart-sales-by-hour"></canvas></div>
            </div>
            <div class="dashboard-chart-card">
                <h4>Formas de Pagamento</h4>
                <div class="chart-wrapper"><canvas id="chart-payment-methods"></canvas></div>
            </div>
        </div>
        <div class="dashboard-section-title">Top Produtos</div>
        <div class="dashboard-table-card">
            <table class="dashboard-table">
                <thead><tr><th>Produto</th><th>Qtd</th><th>Total</th></tr></thead>
                <tbody>${(data.top_products || []).map(p => `<tr><td>${p.name}</td><td>${p.quantity}</td><td>${formatCurrency(p.total)}</td></tr>`).join('')}</tbody>
            </table>
        </div>
    `;

    const hourLabels = (data.sales_by_hour || []).map(h => h.hour);
    const hourValues = (data.sales_by_hour || []).map(h => h.total);
    const ctxHour = document.getElementById('chart-sales-by-hour');
    if (ctxHour) {
        dashboardCharts.salesByHour = new Chart(ctxHour, {
            type: 'line',
            data: {
                labels: hourLabels,
                datasets: [{
                    label: 'Faturamento',
                    data: hourValues,
                    borderColor: DASHBOARD_COLORS.primary,
                    backgroundColor: 'rgba(247, 160, 70, 0.2)',
                    fill: true,
                    tension: 0.3,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: DASHBOARD_COLORS.text }, grid: { color: DASHBOARD_COLORS.grid } },
                    y: { beginAtZero: true, ticks: { color: DASHBOARD_COLORS.text }, grid: { color: DASHBOARD_COLORS.grid } },
                }
            }
        });
    }

    const ctxPayment = document.getElementById('chart-payment-methods');
    if (ctxPayment) {
        dashboardCharts.paymentMethods = new Chart(ctxPayment, {
            type: 'doughnut',
            data: {
                labels: (data.payment_methods || []).map(p => p.label),
                datasets: [{
                    data: (data.payment_methods || []).map(p => p.total),
                    backgroundColor: [
                        DASHBOARD_COLORS.primary,
                        DASHBOARD_COLORS.secondary,
                        DASHBOARD_COLORS.success,
                        DASHBOARD_COLORS.warning,
                        DASHBOARD_COLORS.danger,
                    ],
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'right', labels: { color: DASHBOARD_COLORS.text } } }
            }
        });
    }
}

function renderDashboardVendas(data) {
    const content = document.getElementById('dashboards-content');
    destroyDashboardCharts();
    const cards = [
        createDashboardCard('Faturamento', formatCurrency(data.summary?.total_sales || 0), `${data.summary?.orders_count || 0} comandas`),
        createDashboardCard('Ticket Médio', formatCurrency(data.summary?.ticket_medio || 0), 'por comanda'),
    ];

    content.innerHTML = `
        <div class="dashboard-section-title">Período: ${data.period?.start || ''} a ${data.period?.end || ''}</div>
        <div class="dashboard-cards-grid">${cards.join('')}</div>
        <div class="dashboard-charts-grid">
            <div class="dashboard-chart-card wide">
                <h4>Vendas por Dia</h4>
                <div class="chart-wrapper"><canvas id="chart-sales-by-day"></canvas></div>
            </div>
        </div>
        <div class="dashboard-charts-grid">
            <div class="dashboard-chart-card">
                <h4>Por Categoria</h4>
                <div class="chart-wrapper"><canvas id="chart-by-category"></canvas></div>
            </div>
            <div class="dashboard-chart-card">
                <h4>Por Forma de Pagamento</h4>
                <div class="chart-wrapper"><canvas id="chart-by-payment"></canvas></div>
            </div>
        </div>
        <div class="dashboard-section-title">Ranking de Produtos</div>
        <div class="dashboard-table-card">
            <table class="dashboard-table">
                <thead><tr><th>Produto</th><th>Qtd</th><th>Total</th></tr></thead>
                <tbody>${(data.by_product || []).map(p => `<tr><td>${p.name}</td><td>${p.quantity}</td><td>${formatCurrency(p.total)}</td></tr>`).join('')}</tbody>
            </table>
        </div>
        <div class="dashboard-section-title">Por Garçom</div>
        <div class="dashboard-table-card">
            <table class="dashboard-table">
                <thead><tr><th>Garçom</th><th>Comandas</th><th>Total</th></tr></thead>
                <tbody>${(data.by_waiter || []).map(w => `<tr><td>${w.name}</td><td>${w.orders}</td><td>${formatCurrency(w.total)}</td></tr>`).join('')}</tbody>
            </table>
        </div>
    `;

    const ctxDay = document.getElementById('chart-sales-by-day');
    if (ctxDay) {
        dashboardCharts.salesByDay = new Chart(ctxDay, {
            type: 'bar',
            data: {
                labels: (data.sales_by_day || []).map(d => d.date),
                datasets: [{
                    label: 'Faturamento',
                    data: (data.sales_by_day || []).map(d => d.total),
                    backgroundColor: DASHBOARD_COLORS.primary,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: DASHBOARD_COLORS.text }, grid: { color: DASHBOARD_COLORS.grid } },
                    y: { ticks: { color: DASHBOARD_COLORS.text }, grid: { color: DASHBOARD_COLORS.grid } },
                }
            }
        });
    }

    const ctxCategory = document.getElementById('chart-by-category');
    if (ctxCategory) {
        dashboardCharts.byCategory = new Chart(ctxCategory, {
            type: 'bar',
            data: {
                labels: (data.by_category || []).map(c => c.category),
                datasets: [{
                    label: 'Total',
                    data: (data.by_category || []).map(c => c.total),
                    backgroundColor: DASHBOARD_COLORS.secondary,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                indexAxis: 'y',
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: DASHBOARD_COLORS.text }, grid: { color: DASHBOARD_COLORS.grid } },
                    y: { ticks: { color: DASHBOARD_COLORS.text }, grid: { color: DASHBOARD_COLORS.grid } },
                }
            }
        });
    }

    const ctxPayment = document.getElementById('chart-by-payment');
    if (ctxPayment) {
        dashboardCharts.byPayment = new Chart(ctxPayment, {
            type: 'pie',
            data: {
                labels: (data.by_payment || []).map(p => p.label),
                datasets: [{
                    data: (data.by_payment || []).map(p => p.total),
                    backgroundColor: [
                        DASHBOARD_COLORS.primary,
                        DASHBOARD_COLORS.secondary,
                        DASHBOARD_COLORS.success,
                        DASHBOARD_COLORS.warning,
                        DASHBOARD_COLORS.danger,
                    ],
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'right', labels: { color: DASHBOARD_COLORS.text } } }
            }
        });
    }
}

function renderDashboardEstoque(data) {
    const content = document.getElementById('dashboards-content');
    destroyDashboardCharts();
    const cards = [
        createDashboardCard('Produtos em Conformidade', data.status_counts?.em_conformidade || 0, 'ok'),
        createDashboardCard('Produtos em Risco', data.status_counts?.em_risco || 0, 'atenção'),
        createDashboardCard('Produtos em Falta', data.status_counts?.em_falta || 0, 'urgente'),
        createDashboardCard('Custo do Estoque', formatCurrency(data.total_stock_cost || 0), 'valor atual'),
    ];

    content.innerHTML = `
        <div class="dashboard-cards-grid">${cards.join('')}</div>
        <div class="dashboard-charts-grid">
            <div class="dashboard-chart-card">
                <h4>Status do Estoque</h4>
                <div class="chart-wrapper"><canvas id="chart-stock-status"></canvas></div>
            </div>
        </div>
        <div class="dashboard-section-title">Produtos em Falta</div>
        <div class="dashboard-table-card">
            <table class="dashboard-table">
                <thead><tr><th>Produto</th><th>Categoria</th><th>Estoque</th><th>Mínimo</th></tr></thead>
                <tbody>${(data.out_items || []).map(p => `<tr><td>${p.name}</td><td>${p.category}</td><td>${p.stock}</td><td>${p.min_stock}</td></tr>`).join('')}</tbody>
            </table>
        </div>
        <div class="dashboard-section-title">Produtos em Risco</div>
        <div class="dashboard-table-card">
            <table class="dashboard-table">
                <thead><tr><th>Produto</th><th>Categoria</th><th>Estoque</th><th>Mínimo</th></tr></thead>
                <tbody>${(data.risk_items || []).map(p => `<tr><td>${p.name}</td><td>${p.category}</td><td>${p.stock}</td><td>${p.min_stock}</td></tr>`).join('')}</tbody>
            </table>
        </div>
        <div class="dashboard-section-title">Últimas Movimentações</div>
        <div class="dashboard-filters" style="display:flex;gap:8px;align-items:center;margin-bottom:12px;flex-wrap:wrap;">
            <select id="dashboard-estoque-table-filter" class="input-field" onchange="setDashboardEstoqueTableFilter(this.value)" style="min-width:140px;">
                <option value="">Todas as mesas</option>
            </select>
            <select id="dashboard-estoque-product-filter" class="input-field" onchange="setDashboardEstoqueProductFilter(this.value)" style="min-width:180px;">
                <option value="">Todos os produtos</option>
            </select>
            <button type="button" class="btn-small" onclick="clearDashboardEstoqueFilters()">Limpar</button>
        </div>
        <div class="dashboard-table-card">
            <table class="dashboard-table">
                <thead><tr><th>Produto</th><th>Tipo</th><th>Qtd</th><th>Nota</th><th>Data</th></tr></thead>
                <tbody>${(data.recent_movements || []).map(m => `<tr><td>${m.product_name}</td><td>${m.type}</td><td>${m.quantity}</td><td>${m.note || ''}</td><td>${m.created_at ? new Date(m.created_at).toLocaleString('pt-BR') : ''}</td></tr>`).join('')}</tbody>
            </table>
        </div>
        ${renderDashboardEstoquePagination(data.movements_pagination)}
    `;

    const ctxStatus = document.getElementById('chart-stock-status');
    if (ctxStatus) {
        dashboardCharts.stockStatus = new Chart(ctxStatus, {
            type: 'doughnut',
            data: {
                labels: ['Conformidade', 'Risco', 'Falta'],
                datasets: [{
                    data: [
                        data.status_counts?.em_conformidade || 0,
                        data.status_counts?.em_risco || 0,
                        data.status_counts?.em_falta || 0,
                    ],
                    backgroundColor: [
                        DASHBOARD_COLORS.success,
                        DASHBOARD_COLORS.warning,
                        DASHBOARD_COLORS.danger,
                    ],
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { position: 'right', labels: { color: DASHBOARD_COLORS.text } } }
            }
        });
    }

    loadDashboardEstoqueFilters();
}

async function loadDashboardEstoqueFilters() {
    const tableSelect = document.getElementById('dashboard-estoque-table-filter');
    const productSelect = document.getElementById('dashboard-estoque-product-filter');
    if (!tableSelect || !productSelect) return;

    try {
        const [tablesRes, productsRes] = await Promise.all([
            apiFetch(API_BASE + '/mesas'),
            apiFetch(API_BASE + '/produtos?active_only=false')
        ]);
        const tables = await tablesRes.json();
        const products = await productsRes.json();

        tableSelect.innerHTML = '<option value="">Todas as mesas</option>' +
            tables.map(t => `<option value="${t.id}" ${String(t.id) === dashboardEstoqueTableFilter ? 'selected' : ''}>${t.label}</option>`).join('');

        productSelect.innerHTML = '<option value="">Todos os produtos</option>' +
            products.map(p => `<option value="${p.id}" ${String(p.id) === dashboardEstoqueProductFilter ? 'selected' : ''}>${p.name}</option>`).join('');
    } catch (err) {
        console.error('Erro ao carregar filtros do dashboard de estoque', err);
    }
}

function setDashboardEstoqueTableFilter(value) {
    dashboardEstoqueTableFilter = value;
    dashboardEstoquePage = 1;
    loadDashboardData('estoque');
}

function setDashboardEstoqueProductFilter(value) {
    dashboardEstoqueProductFilter = value;
    dashboardEstoquePage = 1;
    loadDashboardData('estoque');
}

function clearDashboardEstoqueFilters() {
    dashboardEstoqueTableFilter = '';
    dashboardEstoqueProductFilter = '';
    dashboardEstoquePage = 1;
    const tableSelect = document.getElementById('dashboard-estoque-table-filter');
    const productSelect = document.getElementById('dashboard-estoque-product-filter');
    if (tableSelect) tableSelect.value = '';
    if (productSelect) productSelect.value = '';
    loadDashboardData('estoque');
}

function renderDashboardEstoquePagination(pagination) {
    if (!pagination) return '';
    const { page, page_size, total, total_pages } = pagination;
    const hasPrev = page > 1;
    const hasNext = page < total_pages;
    const start = total === 0 ? 0 : (page - 1) * page_size + 1;
    const end = Math.min(page * page_size, total);
    return `
        <div class="dashboard-pagination" style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;flex-wrap:wrap;gap:8px;">
            <span style="font-size:12px;color:var(--text-muted);">${start}-${end} de ${total}</span>
            <div style="display:flex;gap:8px;">
                <button type="button" class="btn-small" onclick="changeDashboardEstoquePage(${page - 1})" ${hasPrev ? '' : 'disabled'}>Anterior</button>
                <button type="button" class="btn-small" onclick="changeDashboardEstoquePage(${page + 1})" ${hasNext ? '' : 'disabled'}>Próxima</button>
            </div>
        </div>
    `;
}

function changeDashboardEstoquePage(newPage) {
    dashboardEstoquePage = newPage;
    loadDashboardData('estoque');
}

function renderDashboardClientes(data) {
    const content = document.getElementById('dashboards-content');
    destroyDashboardCharts();
    const cards = [
        createDashboardCard('Consignados Pendentes', formatCurrency(data.pending_total || 0), `${data.pending_count || 0} clientes`),
        createDashboardCard('Top Cliente', (data.top_customers || [])[0]?.name || '-', formatCurrency((data.top_customers || [])[0]?.total || 0)),
        createDashboardCard('Aniversariantes do Mês', (data.birthdays || []).length, 'clientes'),
    ];

    content.innerHTML = `
        <div class="dashboard-cards-grid">${cards.join('')}</div>
        <div class="dashboard-section-title">Clientes Inadimplentes</div>
        <div class="dashboard-table-card">
            <table class="dashboard-table">
                <thead><tr><th>Cliente</th><th>Total</th><th>Saldo Devedor</th><th>Data</th></tr></thead>
                <tbody>${(data.pending_consignments || []).map(c => `<tr><td>${c.customer_name}</td><td>${formatCurrency(c.total)}</td><td>${formatCurrency(c.balance)}</td><td>${c.created_at ? new Date(c.created_at).toLocaleDateString('pt-BR') : ''}</td></tr>`).join('')}</tbody>
            </table>
        </div>
        <div class="dashboard-section-title">Top Clientes</div>
        <div class="dashboard-table-card">
            <table class="dashboard-table">
                <thead><tr><th>Cliente</th><th>Comandas</th><th>Total</th></tr></thead>
                <tbody>${(data.top_customers || []).map(c => `<tr><td>${c.name}</td><td>${c.orders}</td><td>${formatCurrency(c.total)}</td></tr>`).join('')}</tbody>
            </table>
        </div>
        <div class="dashboard-section-title">Aniversariantes do Mês</div>
        <div class="dashboard-table-card">
            <table class="dashboard-table">
                <thead><tr><th>Cliente</th><th>Data</th><th>Telefone</th></tr></thead>
                <tbody>${(data.birthdays || []).map(c => `<tr><td>${c.name}</td><td>${c.birth_date ? new Date(c.birth_date).toLocaleDateString('pt-BR') : ''}</td><td>${c.phone || ''}</td></tr>`).join('')}</tbody>
            </table>
        </div>
    `;
}

function renderDashboardFuncionarios(data) {
    const content = document.getElementById('dashboards-content');
    destroyDashboardCharts();
    const cards = [
        createDashboardCard('Garçom do Período', (data.by_waiter || [])[0]?.name || '-', formatCurrency((data.by_waiter || [])[0]?.total || 0)),
        createDashboardCard('Total de Comandas', (data.by_waiter || []).reduce((a, b) => a + b.orders, 0), 'no período'),
    ];

    content.innerHTML = `
        <div class="dashboard-section-title">Período: ${data.period?.start || ''} a ${data.period?.end || ''}</div>
        <div class="dashboard-cards-grid">${cards.join('')}</div>
        <div class="dashboard-charts-grid">
            <div class="dashboard-chart-card wide">
                <h4>Vendas por Garçom</h4>
                <div class="chart-wrapper"><canvas id="chart-waiters"></canvas></div>
            </div>
        </div>
        <div class="dashboard-charts-grid">
            <div class="dashboard-chart-card wide">
                <h4>Vendas por Hora</h4>
                <div class="chart-wrapper"><canvas id="chart-peak-hours"></canvas></div>
            </div>
        </div>
        <div class="dashboard-section-title">Ranking de Garçons</div>
        <div class="dashboard-table-card">
            <table class="dashboard-table">
                <thead><tr><th>Garçom</th><th>Comandas</th><th>Total</th><th>Ticket Médio</th></tr></thead>
                <tbody>${(data.by_waiter || []).map(w => `<tr><td>${w.name}</td><td>${w.orders}</td><td>${formatCurrency(w.total)}</td><td>${formatCurrency(w.ticket_medio)}</td></tr>`).join('')}</tbody>
            </table>
        </div>
    `;

    const ctxWaiters = document.getElementById('chart-waiters');
    if (ctxWaiters) {
        dashboardCharts.waiters = new Chart(ctxWaiters, {
            type: 'bar',
            data: {
                labels: (data.by_waiter || []).map(w => w.name),
                datasets: [{
                    label: 'Total',
                    data: (data.by_waiter || []).map(w => w.total),
                    backgroundColor: DASHBOARD_COLORS.info,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: DASHBOARD_COLORS.text }, grid: { color: DASHBOARD_COLORS.grid } },
                    y: { ticks: { color: DASHBOARD_COLORS.text }, grid: { color: DASHBOARD_COLORS.grid } },
                }
            }
        });
    }

    const ctxPeak = document.getElementById('chart-peak-hours');
    if (ctxPeak) {
        dashboardCharts.peakHours = new Chart(ctxPeak, {
            type: 'line',
            data: {
                labels: (data.by_hour || []).map(h => h.hour),
                datasets: [{
                    label: 'Faturamento',
                    data: (data.by_hour || []).map(h => h.total),
                    borderColor: DASHBOARD_COLORS.success,
                    backgroundColor: 'rgba(60, 188, 129, 0.2)',
                    fill: true,
                    tension: 0.3,
                }]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: { legend: { display: false } },
                scales: {
                    x: { ticks: { color: DASHBOARD_COLORS.text }, grid: { color: DASHBOARD_COLORS.grid } },
                    y: { ticks: { color: DASHBOARD_COLORS.text }, grid: { color: DASHBOARD_COLORS.grid } },
                }
            }
        });
    }
}

function renderDashboardGestao(data) {
    const content = document.getElementById('dashboards-content');
    destroyDashboardCharts();

    const cashPosition = data.cash_position || 0;
    const posClass = cashPosition >= 0 ? 'positive' : 'negative';

    const movements = data.movements || [];
    const rows = movements.map(m => {
        const isEntrada = m.type === 'entrada';
        const typeClass = isEntrada ? 'mov-type-entrada' : 'mov-type-saida';
        const valClass = isEntrada ? 'gestao-val-entrada' : 'gestao-val-saida';
        const sign = isEntrada ? '+' : '-';
        const canDelete = m.source === 'manual' && hasRole('gerente');
        const autoTag = m.source === 'automatico' ? '<span class="gestao-auto-tag">automático</span>' : '';
        return `
        <tr>
            <td><span class="${typeClass}">${isEntrada ? 'Entrada' : 'Saída'}</span></td>
            <td>${escapeHtml(m.title)}${autoTag}</td>
            <td class="${valClass}">${sign}${formatCurrency(m.amount)}</td>
            <td>${escapeHtml(m.created_by || '-')}</td>
            <td>${m.created_at ? _fmtDateTime(m.created_at) : '-'}</td>
            <td>${escapeHtml(m.observation || '')}</td>
            <td>${canDelete ? `<button class="btn-icon-danger" onclick="deleteGestaoMovement(${m.id})" title="Excluir"><i class="bi bi-trash"></i></button>` : ''}</td>
        </tr>`;
    }).join('');

    content.innerHTML = `
        <div class="dashboard-section-title">Período: ${data.period?.start || ''} a ${data.period?.end || ''}</div>
        <div class="dashboard-cards-grid">
            <div class="dashboards-card">
                <div class="dashboards-label">Lucro Líquido do Período</div>
                <div class="dashboards-value">${formatCurrency(data.net_profit || 0)}</div>
                <div class="dashboards-sub">Faturamento: ${formatCurrency(data.total_sales || 0)}</div>
            </div>
        </div>
        <div class="gestao-cash-position ${posClass}">
            <div class="gestao-cash-position-label">Posição de Caixa</div>
            <div class="gestao-cash-position-value">${formatCurrency(cashPosition)}</div>
        </div>
        <div class="gestao-toolbar">
            <div class="dashboard-section-title">Histórico de Entradas e Saídas</div>
            <button class="btn-primary" onclick="openGestaoMovementModal()"><i class="bi bi-plus-lg"></i> Nova Movimentação</button>
        </div>
        <div class="dashboard-table-card" style="margin-top:12px;">
            ${movements.length === 0
                ? '<div class="empty-msg" style="padding:12px;text-align:center;">Nenhuma movimentação registrada</div>'
                : `<table class="dashboard-table">
                    <thead><tr><th>Tipo</th><th>Título</th><th>Valor</th><th>Usuário</th><th>Data/Hora</th><th>Observação</th><th></th></tr></thead>
                    <tbody>${rows}</tbody>
                </table>`}
        </div>
        ${renderGestaoPagination(data.movements_pagination)}
    `;
}

function renderGestaoPagination(pagination) {
    if (!pagination) return '';
    const { page, page_size, total, total_pages } = pagination;
    const hasPrev = page > 1;
    const hasNext = page < total_pages;
    const start = total === 0 ? 0 : (page - 1) * page_size + 1;
    const end = Math.min(page * page_size, total);
    return `
        <div class="dashboard-pagination" style="display:flex;justify-content:space-between;align-items:center;margin-top:12px;flex-wrap:wrap;gap:8px;">
            <span style="font-size:12px;color:var(--text-muted);">${start}-${end} de ${total}</span>
            <div style="display:flex;gap:8px;">
                <button type="button" class="btn-small" onclick="changeDashboardGestaoPage(${page - 1})" ${hasPrev ? '' : 'disabled'}>Anterior</button>
                <button type="button" class="btn-small" onclick="changeDashboardGestaoPage(${page + 1})" ${hasNext ? '' : 'disabled'}>Próxima</button>
            </div>
        </div>
    `;
}

function changeDashboardGestaoPage(newPage) {
    dashboardGestaoPage = newPage;
    loadDashboardData('gestao');
}

function openGestaoMovementModal() {
    const modal = document.getElementById('gestao-movement-modal');
    if (!modal) return;
    document.getElementById('gestao-movement-type').value = 'entrada';
    document.getElementById('gestao-movement-title').value = '';
    document.getElementById('gestao-movement-amount').value = '';
    document.getElementById('gestao-movement-observation').value = '';
    document.getElementById('gestao-movement-error').style.display = 'none';
    modal.style.display = 'flex';
}

function closeGestaoMovementModal() {
    const modal = document.getElementById('gestao-movement-modal');
    if (modal) modal.style.display = 'none';
}

async function submitGestaoMovement() {
    const errorEl = document.getElementById('gestao-movement-error');
    const type = document.getElementById('gestao-movement-type').value;
    const title = document.getElementById('gestao-movement-title').value.trim();
    const amount = parseFloat(document.getElementById('gestao-movement-amount').value);
    const observation = document.getElementById('gestao-movement-observation').value.trim() || null;

    if (!title) {
        errorEl.textContent = 'Informe um título para a movimentação';
        errorEl.style.display = 'block';
        return;
    }
    if (!amount || amount <= 0) {
        errorEl.textContent = 'Informe um valor maior que zero';
        errorEl.style.display = 'block';
        return;
    }

    try {
        const res = await apiFetch(API_BASE + '/caixa/posicao/movimentacoes', {
            method: 'POST',
            body: JSON.stringify({ type, title, amount, observation })
        });
        const data = await res.json();
        if (data.error) {
            errorEl.textContent = data.error;
            errorEl.style.display = 'block';
            return;
        }
        closeGestaoMovementModal();
        dashboardGestaoPage = 1;
        loadDashboardData('gestao');
    } catch (err) {
        errorEl.textContent = 'Erro ao salvar movimentação';
        errorEl.style.display = 'block';
    }
}

async function deleteGestaoMovement(id) {
    if (!confirm('Deseja excluir esta movimentação?')) return;
    try {
        const res = await apiFetch(API_BASE + '/caixa/posicao/movimentacoes/' + id, { method: 'DELETE' });
        const data = await res.json();
        if (data.error) {
            alert(data.error);
            return;
        }
        loadDashboardData('gestao');
    } catch (err) {
        alert('Erro ao excluir movimentação');
    }
}


/* -------------------------------------------------------------
   Settings CRUDs: Tables, Users, Backup
   ------------------------------------------------------------- */

function setupSettingsModalKeyboard() {
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            const userModal = document.getElementById('settings-user-modal');
            if (userModal && userModal.style.display !== 'none') closeUserModal();
        }
    });
}

async function loadSettingsTables() {
    const list = document.getElementById('settings-tables-list');
    if (!list) return;
    try {
        const res = await apiFetch(API_BASE + '/mesas/admin');
        const tables = await res.json();
        if (tables.error) {
            list.innerHTML = '<div class="error-msg">' + tables.error + '</div>';
            return;
        }
        if (tables.length === 0) {
            list.innerHTML = '<div class="setting-description">Nenhuma mesa cadastrada.</div>';
            return;
        }
        list.innerHTML = '<div class="table-grid">' + tables.map(t => {
            if (t.active) {
                return `
            <div class="table-card">
                <span class="table-number">${t.number}</span>
                <button class="table-delete" onclick="deleteTable(${t.id})" title="Arquivar"><i class="bi bi-x-lg"></i></button>
            </div>`;
            }
            return `
            <div class="table-card archived">
                <span class="table-number">${t.number}</span>
                <button class="table-restore" onclick="restoreTable(${t.id})" title="Reativar"><i class="bi bi-arrow-counterclockwise"></i></button>
            </div>`;
        }).join('') + '</div>';
    } catch (err) {
        list.innerHTML = '<div class="error-msg">Erro ao carregar mesas</div>';
    }
}

async function addTable() {
    const input = document.getElementById('settings-new-table-number');
    if (!input || !input.value) return;
    const number = parseInt(input.value, 10);
    if (isNaN(number) || number < 1) {
        showSettingsError('Número de mesa inválido');
        return;
    }
    try {
        const res = await apiFetch(API_BASE + '/mesas', {
            method: 'POST',
            body: JSON.stringify({ number })
        });
        const data = await res.json();
        if (data.error) {
            showSettingsError(data.error);
            return;
        }
        input.value = '';
        loadSettingsTables();
        showSettingsSuccess('Mesa adicionada');
    } catch (err) {
        showSettingsError('Erro ao adicionar mesa');
    }
}

async function deleteTable(id) {
    if (!confirm('Deseja arquivar esta mesa?')) return;
    try {
        const res = await apiFetch(API_BASE + '/mesas/' + id, { method: 'DELETE' });
        const data = await res.json();
        if (data.error) {
            showSettingsError(data.error);
            return;
        }
        loadSettingsTables();
        showSettingsSuccess('Mesa arquivada');
    } catch (err) {
        showSettingsError('Erro ao arquivar mesa');
    }
}

async function restoreTable(id) {
    if (!confirm('Deseja reativar esta mesa?')) return;
    try {
        const res = await apiFetch(API_BASE + '/mesas/' + id + '/reativar', { method: 'POST' });
        const data = await res.json();
        if (data.error) {
            showSettingsError(data.error);
            return;
        }
        loadSettingsTables();
        showSettingsSuccess('Mesa reativada');
    } catch (err) {
        showSettingsError('Erro ao reativar mesa');
    }
}

async function loadSettingsUsers() {
    const list = document.getElementById('settings-users-list');
    if (!list) return;
    try {
        const res = await apiFetch(API_BASE + '/auth/users');
        const users = await res.json();
        if (users.error) {
            list.innerHTML = '<div class="error-msg">' + users.error + '</div>';
            return;
        }
        if (users.length === 0) {
            list.innerHTML = '<div class="setting-description">Nenhum usuário cadastrado.</div>';
            return;
        }
        const roleLabels = { gerente: 'Gerente', caixa: 'Caixa', garcom: 'Garçom', estoquista: 'Estoquista' };
        list.innerHTML = '<div class="user-list">' + users.map(u => {
            const initials = (u.name || u.username).split(' ').map(s => s[0]).slice(0, 2).join('').toUpperCase();
            return `
            <div class="user-card ${u.is_active ? '' : 'user-inactive'}">
                <div class="user-avatar">${escapeHtml(initials)}</div>
                <div class="user-details">
                    <div class="user-name">${escapeHtml(u.name || u.username)}</div>
                    <div class="user-meta">${escapeHtml(u.username)} &bull; ${roleLabels[u.role] || u.role}</div>
                </div>
                <div class="user-actions">
                    <label class="toggle-switch" title="Ativo">
                        <input type="checkbox" ${u.is_active ? 'checked' : ''} onchange="toggleUserActive(${u.id}, this.checked)">
                        <span class="toggle-switch-slider"></span>
                    </label>
                    <button class="btn-icon-danger" onclick="deleteUser(${u.id})" title="Excluir"><i class="bi bi-x-lg"></i></button>
                </div>
            </div>
            `;
        }).join('') + '</div>';
    } catch (err) {
        list.innerHTML = '<div class="error-msg">Erro ao carregar usuários</div>';
    }
}

function openUserModal() {
    document.getElementById('settings-user-id').value = '';
    document.getElementById('settings-user-name').value = '';
    document.getElementById('settings-user-username').value = '';
    document.getElementById('settings-user-password').value = '';
    document.getElementById('settings-user-role').value = 'garcom';
    document.getElementById('settings-user-active').checked = true;
    document.getElementById('settings-user-modal-title').textContent = 'Novo Usuário';
    document.getElementById('settings-user-error').style.display = 'none';
    document.getElementById('settings-user-modal').style.display = 'flex';
}

function closeUserModal() {
    document.getElementById('settings-user-modal').style.display = 'none';
}

async function saveUser() {
    const id = document.getElementById('settings-user-id').value;
    const name = document.getElementById('settings-user-name').value.trim();
    const username = document.getElementById('settings-user-username').value.trim();
    const password = document.getElementById('settings-user-password').value;
    const role = document.getElementById('settings-user-role').value;
    const is_active = document.getElementById('settings-user-active').checked;
    const errorEl = document.getElementById('settings-user-error');
    if (!name || !username || (!id && !password)) {
        errorEl.textContent = 'Preencha nome, login e senha.';
        errorEl.style.display = 'block';
        return;
    }
    try {
        const payload = { name, username, role, is_active };
        if (password) payload.password = password;
        const res = await apiFetch(API_BASE + '/auth/users', {
            method: 'POST',
            body: JSON.stringify(payload)
        });
        const data = await res.json();
        if (data.error || data.detail) {
            errorEl.textContent = data.error || data.detail || 'Erro ao salvar';
            errorEl.style.display = 'block';
            return;
        }
        closeUserModal();
        loadSettingsUsers();
        showSettingsSuccess('Usuário salvo');
    } catch (err) {
        errorEl.textContent = 'Erro ao salvar usuário.';
        errorEl.style.display = 'block';
    }
}

async function toggleUserActive(id, is_active) {
    try {
        const res = await apiFetch(API_BASE + '/auth/users/' + id + '/ativo', {
            method: 'PATCH',
            body: JSON.stringify({ is_active })
        });
        const data = await res.json();
        if (data.error) {
            showSettingsError(data.error);
            loadSettingsUsers();
            return;
        }
        showSettingsSuccess('Usuário atualizado');
    } catch (err) {
        showSettingsError('Erro ao atualizar usuário');
        loadSettingsUsers();
    }
}

async function deleteUser(id) {
    if (!confirm('Deseja excluir este usuário?')) return;
    try {
        const res = await apiFetch(API_BASE + '/auth/users/' + id, { method: 'DELETE' });
        const data = await res.json();
        if (data.error) {
            showSettingsError(data.error);
            return;
        }
        loadSettingsUsers();
        showSettingsSuccess('Usuário excluído');
    } catch (err) {
        showSettingsError('Erro ao excluir usuário');
    }
}

async function exportBackup() {
    const status = document.getElementById('backup-status');
    if (status) {
        status.textContent = 'Gerando...';
        status.className = 'setting-status saving';
    }
    try {
        const entitiesRes = await apiFetch(API_BASE + '/backup/entidades');
        const entities = await entitiesRes.json();
        if (entities.error) {
            if (status) {
                status.textContent = entities.error;
                status.className = 'setting-status error';
            }
            return;
        }
        const keys = entities.map(e => e.key);
        const res = await apiFetch(API_BASE + '/backup/exportar', {
            method: 'POST',
            body: JSON.stringify({ entities: keys })
        });
        const data = await res.json();
        if (data.error || data.detail) {
            if (status) {
                status.textContent = data.error || data.detail || 'Erro ao exportar';
                status.className = 'setting-status error';
            }
            return;
        }
        const byteString = atob(data.content_base64);
        const bytes = new Uint8Array(byteString.length);
        for (let i = 0; i < byteString.length; i++) {
            bytes[i] = byteString.charCodeAt(i);
        }
        const blob = new Blob([bytes], { type: 'application/zip' });
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = data.filename || 'backup.zip';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
        if (status) {
            status.textContent = 'Exportado com sucesso';
            status.className = 'setting-status success';
        }
    } catch (err) {
        if (status) {
            status.textContent = 'Erro ao exportar';
            status.className = 'setting-status error';
        }
    }
}

function showSettingsError(message) {
    const el = document.getElementById('settings-error');
    if (el) {
        el.textContent = message;
        el.style.display = 'block';
        setTimeout(() => { el.style.display = 'none'; }, 4000);
    }
}

function showSettingsSuccess(message) {
    const el = document.getElementById('settings-success');
    if (el) {
        el.textContent = message;
        el.style.display = 'block';
        setTimeout(() => { el.style.display = 'none'; }, 4000);
    }
}

