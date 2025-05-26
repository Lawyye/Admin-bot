// === GLOBALS === let filterSearch = ""; let filterStatus = "";

function escapeHtml(str) { return str.replace(/[&<>"']/g, m => ({ '&': '&', '<': '<', '>': '>', '"': '"', "'": ''' })[m]); }

function notify(msg) { const el = document.createElement('div'); el.className = 'toast'; el.innerText = msg; document.body.appendChild(el); setTimeout(() => el.remove(), 3000); }

function fetchRequests() { fetch(`/admin/api/requests?search=${encodeURIComponent(filterSearch)}&status_f=${encodeURIComponent(filterStatus)}`) .then(res => res.json()) .then(data => renderRequests(data.requests)); }

function renderRequests(requests) { const tbody = document.getElementById('requests-table'); tbody.innerHTML = ''; for (let req of requests) { const row = document.createElement('tr'); row.innerHTML = <td>${req.id}</td> <td>${req.created_at}</td> <td>${escapeHtml(req.name)}</td> <td>${escapeHtml(req.phone)}</td> <td>${escapeHtml(req.message)}</td> <td> <form onsubmit="return updateStatus(event, ${req.id})"> <select name="status"> <option value="new" ${req.status === 'new' ? 'selected' : ''}>new</option> <option value="inwork" ${req.status === 'inwork' ? 'selected' : ''}>inwork</option> <option value="done" ${req.status === 'done' ? 'selected' : ''}>done</option> </select> <input type="hidden" name="id" value="${req.id}"> <button type="submit">OK</button> </form> </td> <td> ${(req.documents || []).map(doc =><a href="/admin/download/${doc.file_id}" class="doc-btn" download>${escapeHtml(doc.file_name)}</a>).join("<br>")} </td> <td> <button onclick="showReplyModal(${req.user_id})">Ответить</button> </td>; tbody.appendChild(row); } }

function updateStatus(event, reqId) { event.preventDefault(); const form = event.target; const data = new FormData(form); fetch('/admin/status', { method: 'POST', body: data }).then(() => { notify("Статус обновлён!"); fetchRequests(); }); return false; }

function showReplyModal(userId) { document.getElementById('reply-user-id').value = userId; document.getElementById('reply-modal').style.display = 'block'; }

function closeReplyModal() { document.getElementById('reply-modal').style.display = 'none'; document.getElementById('reply-form').reset(); }

document.getElementById('reply-form').onsubmit = function(e) { e.preventDefault(); const form = e.target; const data = new FormData(form); fetch('/admin/reply', { method: 'POST', body: data }).then(() => { closeReplyModal(); notify("Ответ отправлен!"); }); };

document.getElementById('search').addEventListener('input', function () { filterSearch = this.value; fetchRequests(); });

document.getElementById('status-filter').addEventListener('change', function () { filterStatus = this.value; fetchRequests(); });

document.getElementById('mobile-search').addEventListener('input', function () { filterSearch = this.value; fetchRequests(); });

document.getElementById('mobile-status-filter').addEventListener('change', function () { filterStatus = this.value; fetchRequests(); });

setInterval(fetchRequests, 5000); window.addEventListener("load", fetchRequests);

// === WORKING MOBILE MENU === function toggleMobileMenu() { const menu = document.getElementById("mobileMenu"); const toggleBtn = document.querySelector(".mobile-menu-toggle"); if (!menu || !toggleBtn) return; const isActive = menu.classList.toggle("active"); toggleBtn.textContent = isActive ? '✖' : '☰'; console.log("Меню:", isActive ? 'Открыто' : 'Закрыто'); }

document.addEventListener("DOMContentLoaded", () => { console.log("JS загружен — DOM готов"); const toggleBtn = document.querySelector(".mobile-menu-toggle"); if (toggleBtn) { toggleBtn.addEventListener("click", toggleMobileMenu); console.log("Слушатель на гамбургер добавлен"); } else { console.warn("Кнопка меню не найдена"); } });

