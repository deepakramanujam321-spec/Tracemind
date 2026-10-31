import { useCallback, useEffect, useState } from "react";

interface Notification {
  id: number;
  notification_id: string;
  user_id: string;
  title: string;
  body: string;
  status: string;
  created_at: string;
}

const USER_ID = "u-1";

export default function App() {
  const [rows, setRows] = useState<Notification[]>([]);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [injectFault, setInjectFault] = useState(false);
  const [message, setMessage] = useState("");

  const refresh = useCallback(async () => {
    const res = await fetch(`/api/notifications?user_id=${USER_ID}`);
    if (res.ok) setRows(await res.json());
  }, []);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 2000);
    return () => clearInterval(t);
  }, [refresh]);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    const res = await fetch("/api/notifications", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: USER_ID, title, body, fault: injectFault ? "ack_failure" : null }),
    });
    setMessage(res.ok ? `Queued ${(await res.json()).notification_id}` : `Error ${res.status}`);
    setTitle("");
    setBody("");
  }

  return (
    <main style={{ fontFamily: "sans-serif", maxWidth: 720, margin: "2rem auto", padding: "0 16px" }}>
      <h1>Notification Inbox ({USER_ID})</h1>
      <form onSubmit={submit} style={{ display: "grid", gap: 8, marginBottom: 24 }}>
        <h2>Create notification</h2>
        <input placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} required />
        <textarea placeholder="Body" value={body} onChange={(e) => setBody(e.target.value)} required />
        <label>
          <input type="checkbox" checked={injectFault} onChange={(e) => setInjectFault(e.target.checked)} />{" "}
          Inject ack-failure
        </label>
        <button type="submit">Send</button>
        {message && <small>{message}</small>}
      </form>
      <h2>Inbox ({rows.length})</h2>
      <ul style={{ listStyle: "none", padding: 0 }}>
        {rows.map((r) => (
          <li key={r.id} style={{ border: "1px solid #ccc", borderRadius: 6, padding: 8, marginBottom: 8 }}>
            <strong>{r.title}</strong> <em>[{r.status}]</em>
            <div>{r.body}</div>
            <small>{r.notification_id} · {r.created_at}</small>
          </li>
        ))}
      </ul>
    </main>
  );
}
