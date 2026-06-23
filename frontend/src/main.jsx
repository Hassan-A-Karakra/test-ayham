import React, { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import {
  BarChart3,
  ClipboardList,
  FileBadge,
  FileText,
  LayoutDashboard,
  LogOut,
  MapPinned,
  RefreshCw,
  ShieldCheck,
  UserPlus,
  Users,
} from "lucide-react";
import "./styles.css";

const initialUser = JSON.parse(localStorage.getItem("lrmis_user") || "null");
const API_BASE = "";

function App() {
  const [token, setToken] = useState(localStorage.getItem("lrmis_token") || "");
  const [user, setUser] = useState(initialUser);
  const [tab, setTab] = useState("dashboard");
  const [toast, setToast] = useState(null);

  const notify = (message, error = false) => {
    setToast({ message, error });
    window.clearTimeout(window.__lrmisToast);
    window.__lrmisToast = window.setTimeout(() => setToast(null), 4200);
  };

  const api = async (path, options = {}) => {
    const headers = { "Content-Type": "application/json", ...(options.headers || {}) };
    if (token) headers.Authorization = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
    const text = await res.text();
    const data = text ? JSON.parse(text) : null;
    if (!res.ok) throw new Error(data?.detail || res.statusText);
    return data;
  };

  const signIn = async (credentials) => {
    const data = await api("/auth/login", {
      method: "POST",
      body: JSON.stringify(credentials),
    });
    setToken(data.access_token);
    setUser(data.user);
    localStorage.setItem("lrmis_token", data.access_token);
    localStorage.setItem("lrmis_user", JSON.stringify(data.user));
  };

  const logout = () => {
    setToken("");
    setUser(null);
    localStorage.removeItem("lrmis_token");
    localStorage.removeItem("lrmis_user");
  };

  if (!token || !user) {
    return <LoginScreen onLogin={signIn} notify={notify} toast={toast} />;
  }

  return (
    <main className="app-shell">
      <aside className="sidebar">
        <div>
          <p className="eyebrow">LRMIS</p>
          <h2>{user.name}</h2>
          <p className="role">{user.role}</p>
        </div>
        <nav className="nav">
          <NavButton icon={<LayoutDashboard />} label="Dashboard" active={tab === "dashboard"} onClick={() => setTab("dashboard")} />
          <NavButton icon={<UserPlus />} label="Submit" active={tab === "submit"} onClick={() => setTab("submit")} />
          <NavButton icon={<ClipboardList />} label="Track" active={tab === "track"} onClick={() => setTab("track")} />
          <NavButton icon={<ShieldCheck />} label="Staff" active={tab === "staff"} onClick={() => setTab("staff")} />
          <NavButton icon={<Users />} label="Surveyor" active={tab === "surveyor"} onClick={() => setTab("surveyor")} />
          <NavButton icon={<MapPinned />} label="Map" active={tab === "map"} onClick={() => setTab("map")} />
          <NavButton icon={<FileBadge />} label="Certificate" active={tab === "certificate"} onClick={() => setTab("certificate")} />
        </nav>
        <button className="secondary logout" onClick={logout}>
          <LogOut size={18} /> Logout
        </button>
      </aside>

      <section className="workspace">
        <Topbar tab={tab} onRefresh={() => window.dispatchEvent(new CustomEvent("lrmis-refresh"))} />
        {tab === "dashboard" && <Dashboard api={api} notify={notify} />}
        {tab === "submit" && <SubmitPortal api={api} notify={notify} user={user} />}
        {tab === "track" && <TrackPortal api={api} notify={notify} user={user} />}
        {tab === "staff" && <StaffConsole api={api} notify={notify} user={user} />}
        {tab === "surveyor" && <SurveyorConsole api={api} notify={notify} user={user} />}
        {tab === "map" && <MapView api={api} notify={notify} />}
        {tab === "certificate" && <CertificateView api={api} notify={notify} />}
      </section>
      {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.message}</div>}
    </main>
  );
}

function LoginScreen({ onLogin, notify, toast }) {
  const [username, setUsername] = useState("staff");
  const [password, setPassword] = useState("staff123");
  const [loading, setLoading] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setLoading(true);
    try {
      await onLogin({ username, password });
    } catch (err) {
      notify(err.message, true);
    } finally {
      setLoading(false);
    }
  };

  return (
    <main className="login-shell">
      <section className="login-panel">
        <div>
          <p className="eyebrow">Land Registration Authority</p>
          <h1>LRMIS</h1>
          <p className="muted">Workflow-driven land registration, cadastral survey, certificates, maps, and analytics.</p>
        </div>
        <form className="form-grid" onSubmit={submit}>
          <label>Username<input value={username} onChange={(e) => setUsername(e.target.value)} autoComplete="username" required /></label>
          <label>Password<input value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="current-password" required /></label>
          <button disabled={loading}>{loading ? "Signing in..." : "Sign in"}</button>
          <p className="hint">Demo users: applicant/applicant123, staff/staff123, surveyor/surveyor123, manager/manager123</p>
        </form>
      </section>
      {toast && <div className={`toast ${toast.error ? "error" : ""}`}>{toast.message}</div>}
    </main>
  );
}

function NavButton({ icon, label, active, onClick }) {
  return <button className={active ? "active" : ""} onClick={onClick}>{React.cloneElement(icon, { size: 18 })}<span>{label}</span></button>;
}

function Topbar({ tab, onRefresh }) {
  const titles = {
    dashboard: "Analytics Dashboard",
    submit: "Applicant Portal",
    track: "Track Application",
    staff: "Registrar and Staff Console",
    surveyor: "Surveyor Interface",
    map: "Live Parcel Map",
    certificate: "Certificate View",
  };
  return (
    <header className="topbar">
      <div>
        <h1>{titles[tab]}</h1>
        <p className="muted">FastAPI, PyMongo, MongoDB, React, Leaflet, OpenStreetMap, GeoJSON</p>
      </div>
      <button className="secondary icon-btn" onClick={onRefresh}><RefreshCw size={18} /> Refresh</button>
    </header>
  );
}

function Dashboard({ api, notify }) {
  const [kpis, setKpis] = useState({});
  const [statusRows, setStatusRows] = useState([]);
  const [zoneRows, setZoneRows] = useState([]);
  const [apps, setApps] = useState([]);
  const [statusFilter, setStatusFilter] = useState("");

  const load = async () => {
    try {
      const [kpiData, byStatus, byZone, appData] = await Promise.all([
        api("/analytics/kpis"),
        api("/analytics/applications-by-status"),
        api("/analytics/applications-by-zone"),
        api(`/applications/?page_size=25${statusFilter ? `&status=${encodeURIComponent(statusFilter)}` : ""}`),
      ]);
      setKpis(kpiData);
      setStatusRows(byStatus);
      setZoneRows(byZone);
      setApps(appData.items || []);
    } catch (err) {
      notify(err.message, true);
    }
  };

  useEffect(() => {
    load();
    const refresh = () => load();
    window.addEventListener("lrmis-refresh", refresh);
    return () => window.removeEventListener("lrmis-refresh", refresh);
  }, [statusFilter]);

  return (
    <section className="tab-view">
      <div className="kpi-grid">
        <Kpi label="Total" value={kpis.total_applications} />
        <Kpi label="Pending" value={kpis.pending_applications} />
        <Kpi label="Approved" value={kpis.approved_applications} />
        <Kpi label="Rejected" value={kpis.rejected_applications} />
        <Kpi label="Objections" value={kpis.applications_under_objection} />
        <Kpi label="Certificates" value={kpis.certificates_issued} />
      </div>
      <div className="content-grid">
        <Panel title="Applications by Status"><Bars rows={statusRows} /></Panel>
        <Panel title="Pending by Zone"><Bars rows={zoneRows} /></Panel>
        <section className="panel wide">
          <div className="section-head">
            <h3>Application Management</h3>
            <input value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} placeholder="Filter by status" />
          </div>
          <ApplicationTable apps={apps} />
        </section>
      </div>
    </section>
  );
}

function Kpi({ label, value }) {
  return <div className="kpi"><span>{label}</span><strong>{value ?? 0}</strong></div>;
}

function Panel({ title, children }) {
  return <section className="panel"><div className="section-head"><h3>{title}</h3></div>{children}</section>;
}

function Bars({ rows }) {
  const max = Math.max(1, ...rows.map((row) => row.count || row.task_count || row.reviews || 0));
  if (!rows.length) return <p className="muted">No records yet.</p>;
  return (
    <div className="bar-list">
      {rows.map((row) => {
        const value = row.count || row.task_count || row.reviews || 0;
        return <div className="bar-row" key={row._id || row.staff_code || row.name}><span>{row._id || row.staff_code || "none"}</span><div className="bar-track"><div className="bar-fill" style={{ width: `${(value / max) * 100}%` }} /></div><strong>{value}</strong></div>;
      })}
    </div>
  );
}

function ApplicationTable({ apps }) {
  return (
    <div className="table-wrap">
      <table>
        <thead><tr><th>ID</th><th>Status</th><th>Type</th><th>Zone</th><th>Parcel</th><th>Submitted</th></tr></thead>
        <tbody>
          {apps.map((app) => (
            <tr key={app._id}>
              <td>{app.application_id}</td>
              <td>{app.status}</td>
              <td>{app.application_type}</td>
              <td>{app.parcel_ref?.zone_id}</td>
              <td>{app.parcel_ref?.parcel_number}</td>
              <td>{app.timestamps?.submitted_at}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function SubmitPortal({ api, notify }) {
  const [applicantId, setApplicantId] = useState("");
  const [createdApplication, setCreatedApplication] = useState("");
  const applicantIdValid = /^[a-fA-F0-9]{24}$/.test(applicantId.trim());

  const createApplicant = async (event) => {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const nationalId = String(f.get("national_id") || "").trim();
    if (nationalId.length < 4) {
      notify("National ID must be at least 4 characters.", true);
      return;
    }
    try {
      const applicant = await api("/applicants/", {
        method: "POST",
        body: JSON.stringify({
          full_name: f.get("full_name"),
          applicant_type: f.get("applicant_type"),
          identity: { national_id: nationalId, verified: false },
          contacts: { email: f.get("email") || null, phone: f.get("phone") || null },
          address: { city: f.get("city"), zone_id: f.get("zone_id") },
          verification_state: "unverified",
          preferred_language: "ar",
          notification_preferences: { on_status_change: true, on_missing_documents: true, on_certificate_ready: true },
          privacy_settings: { show_contact_to_staff: true },
        }),
      });
      setApplicantId(applicant._id);
      setCreatedApplication("");
      notify(`Applicant created: ${applicant._id}`);
    } catch (err) {
      notify(err.message, true);
    }
  };

  const submitApplication = async (event) => {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    const applicantObjectId = String(f.get("applicant_id") || "").trim();
    if (!/^[a-fA-F0-9]{24}$/.test(applicantObjectId)) {
      notify("Create Applicant first, then use the generated 24-character Applicant ObjectId.", true);
      return;
    }
    const lon = 35.2001 + Math.random() * 0.02;
    const lat = 31.9021 + Math.random() * 0.02;
    const size = 0.0012;
    try {
      const application = await api("/applications/", {
        method: "POST",
        headers: { "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({
          application_type: f.get("application_type"),
          priority: f.get("priority"),
          applicant_ref: { applicant_id: applicantObjectId, applicant_type: f.get("applicant_type"), submitted_by_representative: false },
          parcel: {
            parcel_number: f.get("parcel_number"),
            block_number: f.get("block_number"),
            basin_number: f.get("basin_number"),
            zone_id: f.get("zone_id"),
            area_sqm: Number(normalizeDigits(f.get("area_sqm"))) || null,
            land_use: f.get("land_use"),
            geometry: { type: "Polygon", coordinates: [[[lon, lat], [lon + size, lat], [lon + size, lat + size], [lon, lat + size], [lon, lat]]] },
          },
          description: f.get("description"),
          tags: [f.get("application_type")],
          required_documents: [
            { document_type: "ownership_deed", file_name: f.get("ownership_deed"), required: true, status: "uploaded" },
            { document_type: "id_copy", file_name: f.get("id_copy"), required: true, status: "uploaded" },
          ],
        }),
      });
      setCreatedApplication(application.application_id);
      notify(`Application submitted: ${application.application_id}`);
    } catch (err) {
      notify(err.message, true);
    }
  };

  return (
    <section className="tab-view">
      <form className="panel form-grid three" onSubmit={createApplicant}>
        <h3>Create Applicant Profile</h3>
        <label>Full name<input name="full_name" required /></label>
        <label>Type<select name="applicant_type"><option>citizen</option><option>lawyer</option><option>company</option><option>surveyor</option><option>authorized_representative</option></select></label>
        <label>National ID<input name="national_id" placeholder="At least 4 digits" required /></label>
        <label>Email<input name="email" type="email" /></label>
        <label>Phone<input name="phone" /></label>
        <label>City<input name="city" defaultValue="Ramallah" /></label>
        <label>Zone<input name="zone_id" defaultValue="ZONE-RM-01" /></label>
        <button>Create Applicant</button>
      </form>
      <form className="panel form-grid three" onSubmit={submitApplication}>
        <h3>Submit Land Application</h3>
        <label>Applicant ObjectId<input name="applicant_id" value={applicantId} onChange={(e) => setApplicantId(e.target.value)} placeholder="Click Create Applicant first" required /></label>
        <label>Applicant type<select name="applicant_type"><option>citizen</option><option>lawyer</option><option>company</option><option>surveyor</option><option>authorized_representative</option></select></label>
        <label>Application type<select name="application_type"><option>first_registration</option><option>ownership_transfer</option><option>parcel_subdivision</option><option>parcel_merge</option><option>boundary_correction</option><option>certificate_request</option></select></label>
        <label>Priority<select name="priority"><option>normal</option><option>high</option><option>urgent</option><option>low</option></select></label>
        <label>Parcel number<input name="parcel_number" defaultValue="145" required /></label>
        <label>Block number<input name="block_number" defaultValue="12" required /></label>
        <label>Basin number<input name="basin_number" defaultValue="3" required /></label>
        <label>Zone<input name="zone_id" defaultValue="ZONE-RM-01" required /></label>
        <label>Area sqm<input name="area_sqm" type="number" step="0.1" defaultValue="850.5" /></label>
        <label>Land use<input name="land_use" defaultValue="residential" /></label>
        <label className="span-3">Description<textarea name="description" defaultValue="Ownership transfer application." /></label>
        <label>Ownership deed<input name="ownership_deed" defaultValue="deed.pdf" /></label>
        <label>ID copy<input name="id_copy" defaultValue="id.pdf" /></label>
        <button disabled={!applicantIdValid} title={applicantIdValid ? "Submit application" : "Create Applicant first"}>Submit Application</button>
        {!applicantIdValid && <p className="form-warning span-3">Create Applicant first. This field must contain a generated MongoDB ObjectId, not a name or normal text.</p>}
      </form>
      {createdApplication && <div className="panel success"><strong>Application ID:</strong> {createdApplication}</div>}
    </section>
  );
}

function TrackPortal({ api, notify, user }) {
  const [applicationId, setApplicationId] = useState("");
  const [application, setApplication] = useState(null);
  const [documentType, setDocumentType] = useState("ownership_deed");
  const [fileName, setFileName] = useState("extra.pdf");
  const [comment, setComment] = useState("");
  const [objection, setObjection] = useState("");

  const load = async () => {
    if (!applicationId) return;
    try {
      setApplication(await api(`/applications/${encodeURIComponent(applicationId)}`));
    } catch (err) {
      notify(err.message, true);
    }
  };

  const addDocument = async () => {
    try {
      await api(`/applications/${applicationId}/documents`, { method: "POST", body: JSON.stringify({ document_type: documentType, file_name: fileName, required: true, status: "uploaded" }) });
      notify("Document added");
      load();
    } catch (err) {
      notify(err.message, true);
    }
  };

  const addComment = async () => {
    try {
      await api(`/applications/${applicationId}/comments`, { method: "POST", body: JSON.stringify({ author_type: user.role === "applicant" ? "applicant" : "staff", author_id: user.username, message: comment }) });
      notify("Comment added");
      load();
    } catch (err) {
      notify(err.message, true);
    }
  };

  const addObjection = async () => {
    try {
      await api(`/applications/${applicationId}/objections`, { method: "POST", body: JSON.stringify({ submitted_by: user.username, reason: objection, supporting_documents: [] }) });
      notify("Objection submitted");
      load();
    } catch (err) {
      notify(err.message, true);
    }
  };

  return (
    <section className="tab-view">
      <section className="panel">
        <div className="section-head">
          <h3>Application Status</h3>
          <div className="inline-controls"><input value={applicationId} onChange={(e) => setApplicationId(e.target.value)} placeholder="Application ID or ObjectId" /><button onClick={load}>Track</button></div>
        </div>
        {application && <ApplicationDetails application={application} />}
      </section>
      <section className="panel form-grid three">
        <h3>Applicant Actions</h3>
        <label>Document type<input value={documentType} onChange={(e) => setDocumentType(e.target.value)} /></label>
        <label>File name<input value={fileName} onChange={(e) => setFileName(e.target.value)} /></label>
        <button type="button" onClick={addDocument}>Add Document</button>
        <label className="span-3">Comment<textarea value={comment} onChange={(e) => setComment(e.target.value)} /></label>
        <button type="button" onClick={addComment}>Add Comment</button>
        <label className="span-3">Objection reason<textarea value={objection} onChange={(e) => setObjection(e.target.value)} /></label>
        <button type="button" onClick={addObjection}>Submit Objection</button>
      </section>
    </section>
  );
}

function ApplicationDetails({ application }) {
  const details = [
    ["ID", application.application_id],
    ["Status", application.status],
    ["Type", application.application_type],
    ["Zone", application.parcel_ref?.zone_id],
    ["Parcel", application.parcel_ref?.parcel_number],
    ["Certificate", application.certificate?.certificate_id || application.certificate_state || "not issued"],
    ["Surveyor", application.assignment?.assigned_surveyor_id || "not assigned"],
    ["Objection", application.objection?.has_objection ? "yes" : "no"],
  ];
  return (
    <>
      <div className="detail-grid">{details.map(([label, value]) => <div className="detail" key={label}><span>{label}</span>{value}</div>)}</div>
      <div className="timeline">{(application.timeline || []).map((item, index) => <div className="timeline-item" key={`${item.state}-${index}`}><strong>{item.state}</strong><p>{item.at}</p><p className="muted">{item.notes}</p></div>)}</div>
    </>
  );
}

function StaffConsole({ api, notify, user }) {
  const [applicationId, setApplicationId] = useState("");
  const [targetState, setTargetState] = useState("pre_checked");
  const [notes, setNotes] = useState("Reviewed by registrar");

  const createStaff = async (event) => {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    try {
      const staff = await api("/staff/", {
        method: "POST",
        body: JSON.stringify({
          staff_code: f.get("staff_code"),
          name: f.get("name"),
          role: f.get("role"),
          department: f.get("department"),
          skills: splitCsv(f.get("skills")),
          coverage: { zone_ids: splitCsv(f.get("zones")) },
          schedule: { timezone: "Asia/Hebron", shifts: [{ day: "Mon", start: "08:00", end: "16:00" }] },
          workload: { active_tasks: 0, max_tasks: 10 },
          contacts: { email: f.get("email") || null },
          active: true,
        }),
      });
      notify(`Staff created: ${staff.staff_code}`);
    } catch (err) {
      notify(err.message, true);
    }
  };

  const transition = async () => {
    try {
      await api(`/applications/${applicationId}/transition`, { method: "PATCH", body: JSON.stringify({ target_state: targetState, actor_type: "registrar", actor_id: user.username, notes, meta: { source: "react_staff_console" } }) });
      notify("Transition applied");
    } catch (err) {
      notify(err.message, true);
    }
  };

  const autoAssign = async () => action(api, notify, `/applications/${applicationId}/auto-assign-surveyor`, "POST", {}, "Surveyor assigned");
  const review = async () => action(api, notify, `/applications/${applicationId}/registrar-review`, "PATCH", { decision: "approved_for_certificate", registrar_id: user.username, notes: "Legal documents reviewed and accepted." }, "Registrar review saved");
  const issueCertificate = async () => action(api, notify, `/applications/${applicationId}/certificate`, "POST", {}, "Certificate issued");

  return (
    <section className="tab-view">
      <form className="panel form-grid three" onSubmit={createStaff}>
        <h3>Create Staff Member</h3>
        <label>Staff code<input name="staff_code" defaultValue="SURV-RM-01" /></label>
        <label>Name<input name="name" defaultValue="Survey Team A" /></label>
        <label>Role<select name="role"><option>surveyor</option><option>registrar</option><option>manager</option><option>clerk</option></select></label>
        <label>Department<input name="department" defaultValue="Cadastral Survey" /></label>
        <label>Zones<input name="zones" defaultValue="ZONE-RM-01,ZONE-RM-02" /></label>
        <label>Skills<input name="skills" defaultValue="boundary_survey,gps_mapping" /></label>
        <label>Email<input name="email" type="email" /></label>
        <button>Create Staff</button>
      </form>
      <section className="panel form-grid three">
        <h3>Registrar Workflow Actions</h3>
        <label>Application ID<input value={applicationId} onChange={(e) => setApplicationId(e.target.value)} /></label>
        <label>Next state<select value={targetState} onChange={(e) => setTargetState(e.target.value)}>{["pre_checked","survey_required","surveyed","legal_review","approved","certificate_issued","closed","missing_documents","on_hold","under_objection","rejected"].map((s) => <option key={s}>{s}</option>)}</select></label>
        <label>Notes<input value={notes} onChange={(e) => setNotes(e.target.value)} /></label>
        <button type="button" onClick={transition}>Apply Transition</button>
        <button type="button" onClick={autoAssign}>Auto Assign Surveyor</button>
        <button type="button" onClick={review}>Registrar Review</button>
        <button type="button" onClick={issueCertificate}>Issue Certificate</button>
      </section>
    </section>
  );
}

function SurveyorConsole({ api, notify, user }) {
  const [applicationId, setApplicationId] = useState("");
  const [milestone, setMilestone] = useState("visit_scheduled");
  const [surveyors, setSurveyors] = useState([]);

  const load = async () => {
    try {
      setSurveyors(await api("/analytics/surveyors"));
    } catch (err) {
      notify(err.message, true);
    }
  };

  useEffect(() => {
    load();
    const refresh = () => load();
    window.addEventListener("lrmis-refresh", refresh);
    return () => window.removeEventListener("lrmis-refresh", refresh);
  }, []);

  const saveMilestone = async () => action(api, notify, `/applications/${applicationId}/survey-milestone`, "PATCH", { milestone, by: user.username, meta: { ui: "react_surveyor" } }, "Milestone saved");
  const uploadReport = async (event) => {
    event.preventDefault();
    const f = new FormData(event.currentTarget);
    await action(api, notify, `/applications/${applicationId}/survey-report`, "POST", { report_number: f.get("report_number"), file_name: f.get("file_name"), summary: f.get("summary"), measurements: {}, evidence: [] }, "Survey report metadata uploaded");
  };

  return (
    <section className="tab-view">
      <section className="panel form-grid three">
        <h3>Survey Task Execution</h3>
        <label>Application ID<input value={applicationId} onChange={(e) => setApplicationId(e.target.value)} /></label>
        <label>Milestone<select value={milestone} onChange={(e) => setMilestone(e.target.value)}>{["visit_scheduled","arrived_on_site","survey_started","survey_completed","report_uploaded","registrar_reviewed"].map((s) => <option key={s}>{s}</option>)}</select></label>
        <button type="button" onClick={saveMilestone}>Save Milestone</button>
      </section>
      <form className="panel form-grid three" onSubmit={uploadReport}>
        <h3>Upload Survey Report Metadata</h3>
        <label>Report number<input name="report_number" defaultValue="REP-001" /></label>
        <label>File name<input name="file_name" defaultValue="survey-report.pdf" /></label>
        <label className="span-3">Summary<textarea name="summary" defaultValue="Survey completed and parcel boundaries match the submitted cadastral data." /></label>
        <button>Upload Report</button>
      </form>
      <Panel title="Surveyor Workload"><Bars rows={surveyors} /></Panel>
    </section>
  );
}

function MapView({ api, notify }) {
  const mapRef = useRef(null);
  const layerRef = useRef(null);
  const nodeRef = useRef(null);
  const [zone, setZone] = useState("");

  const load = async () => {
    try {
      const feed = await api(`/analytics/geofeeds/parcels${zone ? `?zone=${encodeURIComponent(zone)}` : ""}`);
      if (!mapRef.current) {
        mapRef.current = L.map(nodeRef.current).setView([31.91, 35.21], 13);
        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, attribution: "&copy; OpenStreetMap" }).addTo(mapRef.current);
      }
      if (layerRef.current) layerRef.current.remove();
      layerRef.current = L.geoJSON(feed, {
        style: (feature) => ({ color: feature.properties.dispute_state === "under_objection" ? "#b42318" : "#0f766e", weight: 2, fillOpacity: 0.25 }),
        onEachFeature: (feature, layer) => layer.bindPopup(`<strong>${feature.properties.parcel_code}</strong><br>${feature.properties.application_status || "no application"}<br>${feature.properties.zone_id}`),
      }).addTo(mapRef.current);
      if (layerRef.current.getBounds().isValid()) mapRef.current.fitBounds(layerRef.current.getBounds(), { padding: [20, 20] });
    } catch (err) {
      notify(err.message, true);
    }
  };

  useEffect(() => {
    load();
    const refresh = () => load();
    window.addEventListener("lrmis-refresh", refresh);
    return () => window.removeEventListener("lrmis-refresh", refresh);
  }, []);

  return (
    <section className="panel">
      <div className="section-head">
        <h3>Parcels, Pending Applications, and Disputes</h3>
        <div className="inline-controls"><input value={zone} onChange={(e) => setZone(e.target.value)} placeholder="Zone filter" /><button onClick={load}>Load Map</button></div>
      </div>
      <div id="map" ref={nodeRef} />
    </section>
  );
}

function CertificateView({ api, notify }) {
  const [applicationId, setApplicationId] = useState("");
  const [certificate, setCertificate] = useState(null);

  const load = async () => {
    try {
      const application = await api(`/applications/${applicationId}`);
      setCertificate(application.certificate);
    } catch (err) {
      notify(err.message, true);
    }
  };

  return (
    <section className="panel">
      <div className="section-head">
        <h3>Official Land Registration Certificate</h3>
        <div className="inline-controls"><input value={applicationId} onChange={(e) => setApplicationId(e.target.value)} placeholder="Application ID" /><button onClick={load}>Load</button></div>
      </div>
      <div className="certificate">
        {certificate ? (
          <>
            <p className="eyebrow">Official Certificate</p>
            <h1>{certificate.certificate_id}</h1>
            <p>Status: {certificate.status}</p>
            <p>Type: {certificate.certificate_type}</p>
            <p>Issued at: {certificate.issued_at}</p>
            <p>Issued by: {certificate.issued_by}</p>
            <p>Verification: {certificate.verification?.qr_code_url}</p>
          </>
        ) : <p className="muted">No certificate loaded.</p>}
      </div>
    </section>
  );
}

function splitCsv(value) {
  return String(value || "").split(",").map((item) => item.trim()).filter(Boolean);
}

function normalizeDigits(value) {
  const arabic = "٠١٢٣٤٥٦٧٨٩";
  const eastern = "۰۱۲۳۴۵۶۷۸۹";
  return String(value || "").replace(/[٠-٩۰-۹]/g, (digit) => {
    const arabicIndex = arabic.indexOf(digit);
    if (arabicIndex >= 0) return String(arabicIndex);
    return String(eastern.indexOf(digit));
  });
}

async function action(api, notify, path, method, body, success) {
  try {
    await api(path, { method, body: JSON.stringify(body) });
    notify(success);
  } catch (err) {
    notify(err.message, true);
  }
}

createRoot(document.getElementById("root")).render(<App />);
