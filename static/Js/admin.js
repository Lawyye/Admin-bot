// === GLOBAL VARIABLES === let filterSearch = ""; let filterStatus = "";

// === HELPERS === function escapeHtml(str) { return str.replace(/[&<>"']/g, m => ({ '&': '&', '<': '<', '>': '>', '"': '"', "'": ''' })[m]); }

function notify(msg) { const el = document.createElement('div'); el.className = 'toast'; el.innerText = msg; document.body.appendChild(el); setTimeout(() => el.remove(), 3000); }

// === FETCH AND RENDER === function fetchRequests() { fetch(/admin/api/requests?search=${encodeURIComponent(filterSearch)}&status_f=${encodeURIComponent(filterStatus)}) .then(res => res.json()) .then(data => { renderRequests(data.requests); }); }

function renderRequests(requests) { let tbody = document.getElementById('requests-table'); tbody.innerHTML = ''; for (let req of requests) { let row = document.createElement('tr'); row.innerHTML = <td>${req.id}</td> <td>${req.created_at}</td> <td>${escapeHtml(req.name)}</td> <td>${escapeHtml(req.phone)}</td> <td>${escapeHtml(req.message)}</td> <td> <form onsubmit="return updateStatus(event, ${req.id})"> <select name="status"> <option value="new" ${req.status === 'new' ? 'selected' : ''}>new</option> <option value="inwork" ${req.status === 'inwork' ? 'selected' : ''}>inwork</option> <option value="done" ${req.status === 'done' ? 'selected' : ''}>done</option> </select> <input type="hidden" name="id" value="${req.id}"> <button type="submit">OK</button> </form> </td> <td> ${(req.documents || []).map(doc =><a href="/admin/download/${doc.file_id}" class="doc-btn" download>${escapeHtml(doc.file_name)}</a>).join("<br>")} </td> <td> <button onclick="showReplyModal(${req.user_id})">Ответить</button> </td>; tbody.appendChild(row); } }

// === STATUS UPDATE === function updateStatus(event, reqId) { event.preventDefault(); var form = event.target; var data = new FormData(form); fetch('/admin/status', { method: 'POST', body: data }).then(() => { notify("Статус обновлён!"); fetchRequests(); }); return false; }

// === REPLY MODAL === function showReplyModal(userId) { document.getElementById('reply-user-id').value = userId; document.getElementById('reply-modal').style.display = 'block'; }

function closeReplyModal() { document.getElementById('reply-modal').style.display = 'none'; document.getElementById('reply-form').reset(); }

document.getElementById('reply-form').onsubmit = function(e) { e.preventDefault(); var form = e.target; var data = new FormData(form); fetch('/admin/reply', { method: 'POST', body: data }).then(() => { closeReplyModal(); notify("Ответ отправлен!"); }); };

// === EVENT BINDINGS === document.getElementById('search').addEventListener('input', function() { filterSearch = this.value; fetchRequests(); });

document.getElementById('status-filter').addEventListener('change', function() { filterStatus = this.value; fetchRequests(); });

document.getElementById('mobile-search').addEventListener('input', function () { filterSearch = this.value; fetchRequests(); });

document.getElementById('mobile-status-filter').addEventListener('change', function () { filterStatus = this.value; fetchRequests(); });

// === MOBILE MENU TOGGLE === document.addEventListener("DOMContentLoaded", () => { const toggleBtn = document.getElementById("mobile-toggle-btn"); if (toggleBtn) { toggleBtn.addEventListener("click", () => { const menu = document.getElementById("mobileMenu"); menu.classList.toggle("active"); }); } });

setInterval(fetchRequests, 5000); window.onload = fetchRequests; 
function toggleMobileMenu() {
    const menu = document.getElementById("mobileMenu");
    menu.classList.toggle("active");
}
window.toggleMobileMenu = toggleMobileMenu;
