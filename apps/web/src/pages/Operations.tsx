import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { providerToken } from "@/lib/identity";

type Ticket = {reference:string; topic:string; message:string; contact:string; status:string; owner:string | null; created_at:string};
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
  const [error,setError] = useState("");
  async function load() { setStats(await staff("")); setTickets(await staff("/support")); }
  useEffect(() => {void load().catch(e => setError(e.message));}, []);
  async function action(reference:string, action:string) {
    try {await staff("/support/"+reference,"POST",{action}); await load();} catch(e) {setError((e as Error).message);}
  }
  return <main className="mx-auto max-w-4xl p-6 space-y-4">
    <h1 className="text-3xl font-semibold">Operations</h1><Link to="/identity#review">Sign in as staff</Link>
    <section className="rounded border p-4"><h2 className="font-semibold">Service overview</h2>
      <p>Agent activity (24 hours): {JSON.stringify(stats.agent_activity ?? {})}</p>
      <p>Service health: {JSON.stringify(stats.services ?? {})}</p>
      <p>Overdue reviews: {String(stats.overdue_reviews ?? "—")}</p>
      <p>Email delivery: {JSON.stringify(stats.delivery_counts ?? {})}</p>
      <p>Delivery failures: {JSON.stringify(stats.delivery_failures ?? [])}</p>
      <p>Pending reviews: {String(stats.pending_reviews ?? "—")}</p>
      <p>Open support requests: {String(stats.open_support ?? "—")}</p>
      <p>Document failures: {String(stats.document_failures ?? "—")}</p>
      <p>Applications: {JSON.stringify(stats.applications_by_status ?? {})}</p></section>
    <h2 className="font-semibold">Support requests</h2>
    {tickets.map(t => <article key={t.reference} className="border rounded p-4 space-y-2">
      <p>{t.reference} · {t.topic} · {t.owner || "Unassigned"} · {new Date(t.created_at).toLocaleString()}</p>
      <p>{t.message}</p><p>Contact: {t.contact}</p>
      <button onClick={() => void action(t.reference,"claim")}>Claim</button>{" · "}
      <button onClick={() => void action(t.reference,"close")}>Close</button></article>)}
    {error && <p role="alert">{error}</p>}
  </main>;
}
