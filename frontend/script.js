const API = "https://online-complaint-management.onrender.com";

/* ================= HELPER ================= */

function getValue(id) {
    const el = document.getElementById(id);
    return el ? el.value.trim() : "";
}

function showError(msg) {
    alert(msg);
}

/* ================= STUDENT ================= */

/* ================= SUBMIT COMPLAINT ================= */

async function submitComplaint() {

    const name = getValue("name");
    const complaint = getValue("complaint");

    if (!name || !complaint) {
        showError("Fill all fields");
        return;
    }

    try {
        const res = await fetch(`${API}/submit`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name, complaint })
        });

        const data = await res.json();

        if (!res.ok) {
            showError(data.error || "Submission failed");
            return;
        }

        // 🔥 Professional Display Instead of Alert
        document.getElementById("resultBox").innerHTML = `
            <div class="card">
                <h3 style="color:#27ae60;">Complaint Submitted Successfully</h3>
                <p>Your Complaint ID:</p>
                <h2 style="color:#3b6fd8;">${data.id}</h2>
                <p>Please save this ID to track your complaint status.</p>
            </div>
        `;

        document.getElementById("name").value = "";
        document.getElementById("complaint").value = "";

    } catch (err) {
        showError("Server not running");
    }
}


/* ================= CHECK STATUS ================= */

async function checkStatus() {

    const id = getValue("complaintId");

    if (!id) {
        showError("Enter Complaint ID");
        return;
    }

    try {
        const res = await fetch(`${API}/status/${id}`);
        const data = await res.json();

        const box = document.getElementById("statusBox");

        if (!res.ok) {
            box.innerHTML = `<p style="color:red;">${data.error}</p>`;
            return;
        }

        box.innerHTML = `
            <div class="card">
                <h3>Complaint #${data.id}</h3>

                <p><strong>Complaint:</strong></p>
                <p>${data.complaint}</p>

                <hr>

                <p><strong>Status:</strong> ${data.status}</p>
                <p><strong>Assigned To:</strong> ${data.assigned_to}</p>

                <p><strong>Reply:</strong></p>
                <p>${data.reply || "Not Replied Yet"}</p>

                <p class="meta">
                    Created: ${data.created_at}<br>
                    Updated: ${data.updated_at}
                </p>
            </div>
        `;

    } catch (err) {
        showError("Server error");
    }
}

/* ================= LOGIN ================= */

async function login() {
    const username = getValue("username");
    const password = getValue("password");

    const res = await fetch(`${API}/login`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ username, password })
    });

    const data = await res.json();

    if (!res.ok) {
        showError(data.error);
        return;
    }

    if (data.role === "admin") {
        window.location.href = "admin.html";
    } else {
        window.location.href = "staff.html";
    }
}

async function logout() {
    await fetch(`${API}/logout`, { credentials: "include" });
    window.location.href = "login.html";
}

/* ================= ADMIN ================= */

async function loadAdmin() {

    const container = document.getElementById("complaintsList");
    if (!container) return;

    const res = await fetch(`${API}/admin/complaints`, {
        credentials: "include"
    });

    if (!res.ok) {
        window.location.href = "login.html";
        return;
    }

    const data = await res.json();
    container.innerHTML = "";

    data.forEach(c => {

        // 🟢 RESOLVED → LOCK VIEW
        if (c.status === "Resolved") {

            container.innerHTML += `
            <div class="card">
                <h3>#${c.id} - ${c.name}</h3>
                <p>${c.complaint}</p>
                <p><strong>Status:</strong> ${c.status}</p>
                <p><strong>Assigned:</strong> ${c.assigned_to}</p>
                <p><strong>Reply:</strong> ${c.reply}</p>
                <p><small>${c.updated_at}</small></p>
            </div>
            `;

        } else {

            // 🟡 PENDING / IN PROGRESS → EDITABLE
            container.innerHTML += `
            <div class="card">
                <h3>#${c.id} - ${c.name}</h3>
                <p>${c.complaint}</p>

                <span class="badge ${c.status === "Resolved" ? "resolved" : c.status === "In Progress" ? "progress" : "pending"}">
${c.status}
</span>
                <p><strong>Assigned:</strong> ${c.assigned_to}</p>

                <select id="status-${c.id}">
                    <option value="Pending" ${c.status==="Pending"?"selected":""}>Pending</option>
                    <option value="In Progress" ${c.status==="In Progress"?"selected":""}>In Progress</option>
                </select>

                <input id="assign-${c.id}" 
                       value="${c.assigned_to === 'Not Assigned' ? '' : c.assigned_to}" 
                       placeholder="Assign staff1 / staff2">

                <button onclick="adminUpdate(${c.id})">
                    Update
                </button>

                <button onclick="deleteComplaint(${c.id})">
                    Delete
                </button>
            </div>
            `;
        }

    });
}

async function adminUpdate(id) {
    const status = getValue(`status-${id}`);
    const assigned_to = getValue(`assign-${id}`);

    await fetch(`${API}/update/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status, assigned_to })
    });

    loadAdmin();
}

/* ================= STAFF ================= */

async function loadStaff() {

    const container = document.getElementById("complaintsList");
    if (!container) return;

    const res = await fetch(`${API}/staff/complaints`, {
        credentials: "include"
    });

    if (!res.ok) {
        window.location.href = "login.html";
        return;
    }

    const data = await res.json();
    container.innerHTML = "";

    if (data.length === 0) {
        container.innerHTML = "<p>No complaints assigned.</p>";
        return;
    }

    data.forEach(c => {

        if (c.status === "Resolved") {

            // 🔒 Already completed
            container.innerHTML += `
            <div class="card">
                <h3>#${c.id} - ${c.name}</h3>
                <p>${c.complaint}</p>
                <span class="badge ${c.status === "Resolved" ? "resolved" : c.status === "In Progress" ? "progress" : "pending"}">
${c.status}
</span>
                <p><strong>Your Reply:</strong> ${c.reply}</p>
                <p><small>${c.updated_at}</small></p>
            </div>
            `;

        } else {

            // ✏ Still active
            container.innerHTML += `
            <div class="card">
                <h3>#${c.id} - ${c.name}</h3>
                <p>${c.complaint}</p>

                <textarea id="reply-${c.id}" 
                          placeholder="Write reply...">${c.reply || ""}</textarea>

                <select id="status-${c.id}">
                    <option value="In Progress">In Progress</option>
                    <option value="Resolved">Resolved</option>
                </select>

                <button onclick="staffUpdate(${c.id})">
                    Update
                </button>
            </div>
            `;
        }

    });
}

async function staffUpdate(id) {
    const status = getValue(`status-${id}`);
    const reply = getValue(`reply-${id}`);

    await fetch(`${API}/update/${id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ status, reply })
    });

    loadStaff();
}

async function deleteComplaint(id) {
    await fetch(`${API}/delete/${id}`, {
        method: "DELETE",
        credentials: "include"
    });

    loadAdmin();
}

/* ================= AUTO LOAD ================= */

document.addEventListener("DOMContentLoaded", () => {
    const path = window.location.pathname;

    if (path.includes("admin.html")) {
        loadAdmin();
    }

    if (path.includes("staff.html")) {
        loadStaff();
    }
});