import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { providerToken } from "@/lib/identity";

type Ticket = {reference:string; topic:string; message:string; contact:string; status:string; owner:string | null; created_at:string};
type Shadow = {decision_id:string; application_id:string; status:string; policy_outcome:string; probability:number | null; age_shap_log_odds:number | null; baseline_log_odds:number | null; disagreement:boolean | null; reason_codes:string[]};
async function staff(path:string, method = "GET", body?:object) {
  const response = await fetch("/v1/operations" + path, {method, headers: {
    Authorization: "Bearer " + await providerToken(), ...(body ? {"Content-Type":"application/json"} : {})
  }, body:body ? JSON.stringify(body) : undefined});
  if (!response.ok) throw new Error((await response.json()).detail || "Request failed");
  return response.json();
}
export default function Operations() {
  const [stats,setStats] = useState<Record<string,unknown>>({});
  const [tickets,setTickets] = useState<Ticket[]>([]);
  const [shadow,setShadow] = useState<Shadow[]>([]);
  const [error,setError] = useState("");
  async function load() { setStats(await staff("")); setTickets(await staff("/support")); setShadow(await staff("/shadow")); }
  useEffect(() => {void load().catch(e => setError(e.message));}, []);
  async function action(reference:string, action:string) {
    try {await staff("/support/"+reference,"POST",{action}); await load();} catch(e) {setError((e as Error).message);}
  }
  return <main className="mx-auto max-w-4xl p-6 space-y-4">
    <h1 className="text-3xl font-semibold">Operations</h1><Link to="/identity#review">Sign in as staff</Link>
    <section className="rounded border p-4"><h2 className="font-semibold">Service overview</h2>
      <h3 className="font-semibold">Cloud SQL backups and recovery</h3>
      {Array.isArray(stats.backup_monitor) && stats.backup_monitor.length ? stats.backup_monitor.map((item: {target:string; status:string; issues:string[]; latest_successful_backup_at?:string; pitr_enabled?:boolean}) => (
        <div key={item.target} className="border rounded p-2">
          <p>{item.target} · {item.status}</p>
          <p>Last successful scheduled backup: {item.latest_successful_backup_at ? new Date(item.latest_successful_backup_at).toLocaleString() : "Unavailable"}</p>
          <p>Point-in-time recovery: {item.pitr_enabled === true ? "Enabled" : item.pitr_enabled === false ? "Disabled" : "Unknown"}</p>
          {item.issues.length > 0 && <p>Issues: {item.issues.join(", ").replace(/_/g, " ")}</p>}
        </div>
      )) : <p>Monitoring is not configured.</p>}
      <p>Agent activity (24 hours): {JSON.stringify(stats.agent_activity ?? {})}</p>
      <p>Service health: {JSON.stringify(stats.services ?? {})}</p>
      <p>Overdue reviews: {String(stats.overdue_reviews ?? "—")}</p>
      <p>Email delivery: {JSON.stringify(stats.delivery_counts ?? {})}</p>
      <p>Delivery failures: {JSON.stringify(stats.delivery_failures ?? [])}</p>
      <p>Pending reviews: {String(stats.pending_reviews ?? "—")}</p>
      <p>Open support requests: {String(stats.open_support ?? "—")}</p>
      <p>Document failures: {String(stats.document_failures ?? "—")}</p>
      <p>Applications: {JSON.stringify(stats.applications_by_status ?? {})}</p></section>
    <section className="rounded border p-4 space-y-2"><h2 className="font-semibold">Research shadow model</h2>
      <p>Age-only model trained on historical Taiwan credit-card data. Scores are for research and do not make lending decisions.</p>
      <p>Recent policy disagreements: {shadow.filter(s => s.disagreement === true).length} of {shadow.filter(s => s.disagreement !== null).length} comparable decisions.</p>
      {shadow.map(s => <div key={s.decision_id} className="border rounded p-2">
        <p>Application {s.application_id} · policy {s.policy_outcome} · {s.status}</p>
        {s.probability !== null && <p>Research score {(s.probability * 100).toFixed(1)}% · age SHAP {s.age_shap_log_odds?.toFixed(3)} log-odds · baseline {s.baseline_log_odds?.toFixed(3)} · {s.reason_codes.join(", ").replace(/_/g, " ")} · disagreement {s.disagreement === null ? "not comparable" : String(s.disagreement)}</p>}
      </div>)}
    </section>
    <h2 className="font-semibold">Support requests</h2>
    {tickets.map(t => <article key={t.reference} className="border rounded p-4 space-y-2">
      <p>{t.reference} · {t.topic} · {t.owner || "Unassigned"} · {new Date(t.created_at).toLocaleString()}</p>
      <p>{t.message}</p><p>Contact: {t.contact}</p>
      <button onClick={() => void action(t.reference,"claim")}>Claim</button>{" · "}
      <button onClick={() => void action(t.reference,"close")}>Close</button></article>)}
    {error && <p role="alert">{error}</p>}
  </main>;
}
