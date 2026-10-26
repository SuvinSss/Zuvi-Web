import { useState, type FormEvent } from "react";
import { Navigate } from "react-router-dom";
import { Alert, Button, Field } from "../components/ui";
import { messageOf } from "../lib/api";
import type { Portal } from "../lib/types";
import { useSession } from "../state/session";

const TITLES: Record<Portal, string> = {
  customer: "Customer sign in",
  store: "Store sign in",
  delivery: "Delivery partner sign in",
  admin: "Admin sign in",
};

export function Login({ portal }: { portal: Portal }) {
  const { session, login } = useSession();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (session?.authenticated && session.portal === portal) return <Navigate to="/" replace />;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(portal, username, password);
    } catch (err) {
      setError(messageOf(err));
    } finally {
      setBusy(false);
    }
  }

  return (
    <form className="card" style={{ maxWidth: 420 }} onSubmit={(e) => void submit(e)}>
      <h1>{TITLES[portal]}</h1>
      {error && <Alert>{error}</Alert>}
      <Field label="Username">
        {({ id }) => (
          <input id={id} autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        )}
      </Field>
      <Field label="Password">
        {({ id }) => (
          <input id={id} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        )}
      </Field>
      <Button type="submit" disabled={busy || !username || !password}>
        {busy ? "Signing in…" : "Sign in"}
      </Button>
    </form>
  );
}
