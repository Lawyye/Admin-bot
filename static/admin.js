// === GLOBALS ===
let allRequests = [];
let filterSearch = "";
let filterStatus = "";

// === TOOLS ===
function escapeHtml(str) {
    return str.replace(/[&<>"']/g, m => ({
        '&': '&',
        '<': '<',
        '>': '>',
        '"': '"',
        "'": '''
    })[m]);
}

function notify(msg, type = "info") {
    const el = document.createElement('div');
    el.className = 'notification show ' + type;
    el.innerText = msg;
    document.body.appendChild(el);
    setTimeout(() => el.remove(), 3000);
}

// === LOGOUT ===
function logout() {
    fetch('/admin/logout', {
        method: 'POST',
        credentials: 'same-origin'
    })
    .then(response => {
        if (response.redirected) {
            window.location.href = response.url;
        } else {
            alert('Ошибка выхода. Попробуйте обновить страницу.');
        }
    })
    .catch(error => {
        console.error('Ошибка выхода:', error);
        notify('Не удалось выйти', 'error');
    });
}

function showLoading(isLoading) {
    const table = document.getElementById('requests-table');
    if (isLoading) {
        table.innerHTML = '<tr><td colspan="8" style="text-align:center;padding:40px;color:#999;">Загрузка данных...</td></tr>';
    }
}

// === LOAD DATA ===
async function loadRequests() {
    showLoading(true);
    try {
        console.log("Loading requests...");
        const res = await fetch(`/admin/api/requests?search=${encodeURIComponent(filterSearch)}&status_f=${encodeURIComponent(filterStatus)}`);
        if (!res.ok) throw new Error(`HTTP error! status: ${res.status}`);
        const data = await res.json();
        console.log("Received data:", data);
        allRequests = data.requests || [];
        renderRequests();
        updateStats();
    } catch (e) {
        console.error("Error loading requests:", e);
        notify("Ошибка загрузки заявок: " + e.message, "error");
    } finally {
        showLoading(false);
    }
}

function updateStats() {
    document.getElementById("stat-new").textContent = allRequests.filter(r => r.status === "new").length;
    document.getElementById("stat-inwork").textContent = allRequests.filter(r => r.status === "inwork").length;
    document.getElementById("stat-done").textContent = allRequests.filter(r => r.status === "done").length;
    document.getElementById("stat-total").textContent = allRequests.length;
}

function renderRequests() {
    const tbody = document.getElementById("requests-table");
    tbody.innerHTML = "";

    for (const req of allRequests) {
        const row = document.createElement("tr");

        const docLinks = (req.documents || []).map(doc => 
            `<a href="/admin/download/${doc.file_id}" class="doc-btn" download>${escapeHtml(doc.file_name)}</a>`
        ).join("<br>");

        row.innerHTML = `
            <td>${req.id}</td>
            <td>${req.created_at}</td>
            <td>${escapeHtml(req.name)}</td>
            <td>${escapeHtml(req.phone)}</td>
            <td>${escapeHtml(req.message)}</td>
            <td>
                <form onsubmit="return updateStatus(event, ${req.id})">
                    <select name="status">
                        <option value="new" ${req.status === "new" ? "selected" : ""}>new</option>
                        <option value="inwork" ${req.status === "inwork" ? "selected" : ""}>inwork</option>
                        <option value="done" ${req.status === "done" ? "selected" : ""}>done</option>
                    </select>
                    <input type="hidden" name="id" value="${req.id}">
                    <button type="submit">OK</button>
                </form>
            </td>
            <td>${docLinks}</td>
            <td><button onclick="showReplyModal(${req.user_id})">Ответить</button></td>
        `;
        tbody.appendChild(row);
    }
}

function updateStatus(event, reqId) {
    event.preventDefault();
    const form = event.target;
    const data = new FormData(form);
    fetch("/admin/status", {
        method: "POST",
        body: data
    }).then(() => {
        notify("Статус обновлён!", "success");
        loadRequests();
    });
    return false;
}

function showReplyModal(userId) {
    document.getElementById("reply-user-id").value = userId;
    document.getElementById("reply-modal").classList.add("active");
}

function closeReplyModal() {
    document.getElementById("reply-modal").classList.remove("active");
    document.getElementById("reply-form").reset();
}

document.getElementById("reply-form").onsubmit = function(e) {
    e.preventDefault();
    const form = e.target;
    const data = new FormData(form);
    fetch("/admin/reply", {
        method: "POST",
        body: data
    }).then(() => {
        closeReplyModal();
        notify("Ответ отправлен!", "success");
    });
};

// === FILTERS ===
document.getElementById("search").addEventListener("input", function () {
    filterSearch = this.value;
    loadRequests();
});
document.getElementById("status-filter").addEventListener("change", function () {
    filterStatus = this.value;
    loadRequests();
});
document.getElementById("mobile-search").addEventListener("input", function () {
    filterSearch = this.value;
    loadRequests();
});
document.getElementById("mobile-status-filter").addEventListener("change", function () {
    filterStatus = this.value;
    loadRequests();
});

// === INTERVAL + THEME + MENU ===
setInterval(loadRequests, 5000);
window.addEventListener("load", loadRequests);

function toggleTheme() {
    document.body.classList.toggle("dark-theme");
    const isDark = document.body.classList.contains("dark-theme");
    localStorage.setItem("theme", isDark ? "dark" : "light");
    document.getElementById("theme-icon").textContent = isDark ? "☀️" : "🌙";
}

// Обновлённая функция toggleMobileMenu()
function toggleMobileMenu() {
    const menu = document.getElementById('mobileMenu');
    const toggleBtn = document.querySelector('.mobile-menu-toggle');

    menu.classList.toggle('active');
    toggleBtn.textContent = menu.classList.contains('active') ? '✕' : '☰';

    // Закрытие меню при клике вне его области
    if (menu.classList.contains('active')) {
        document.addEventListener('click', closeMenuOnClickOutside);
    } else {
        document.removeEventListener('click', closeMenuOnClickOutside);
    }
}

function closeMenuOnClickOutside(event) {
    const menu = document.getElementById('mobileMenu');
    const toggleBtn = document.querySelector('.mobile-menu-toggle');

    if (!menu.contains(event.target) && !toggleBtn.contains(event.target)) {
        menu.classList.remove('active');
        toggleBtn.textContent = '☰';
        document.removeEventListener('click', closeMenuOnClickOutside);
    }
}
