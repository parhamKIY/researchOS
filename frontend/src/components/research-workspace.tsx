"use client";

import { useCallback, useEffect, useState, type FormEvent } from "react";
import { api, ApiFailure, type Session } from "@/lib/api";
import { SystemStatus } from "@/components/system-status";
import { ProjectLibrary } from "@/components/project-library";
import { PaperLibrary } from "@/components/paper-library";

export function ResearchWorkspace() {
  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [project, setProject] = useState("");
  const expired = useCallback(() => { setSession(null); setProject(""); setError("Your session expired. Please sign in again."); }, []);

  async function restore() {
    try { setSession(await api<Session>("/auth/session")); setError(""); }
    catch (err) {
      if (!(err instanceof ApiFailure && err.status === 401)) setError((err as Error).message);
    } finally { setLoading(false); }
  }
  useEffect(() => {
    let alive = true;
    api<Session>("/auth/session").then((value) => { if (alive) setSession(value); })
      .catch((err) => {
        if (alive && !(err instanceof ApiFailure && err.status === 401)) setError(err.message);
      }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true); setError("");
    try {
      setSession(await api<Session>("/auth/login", {
        method: "POST", body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      }));
    } catch (err) { setError((err as Error).message); }
    finally { setBusy(false); }
  }

  async function logout() {
    if (!session) return;
    setBusy(true); setError("");
    try {
      await api("/auth/logout", { method: "POST" }, session.csrf_token);
      setSession(null);
      setProject("");
    } catch (err) {
      if (err instanceof ApiFailure && err.status === 401) setSession(null);
      else setError((err as Error).message);
    } finally { setBusy(false); }
  }

  return (
    <div className="workspace">
      <aside className="sidebar">
        <a href="/" className="brand"><span className="brand-mark">R</span>ResearchOS<span className="brand-dot">.</span></a>
        <p className="sidebar-label">Your workspace</p>
        <div className="active-nav"><span>◈</span> Overview</div>
        <div className="sidebar-foot"><span className="mini-dot" />Private research workspace</div>
      </aside>
      <main>
        <header className="topbar"><span>Workspace / Overview</span>
          {session ? <div className="account"><span>{session.user.email}</span><button onClick={logout} disabled={busy}>Sign out</button></div> : <span className="local-label">PRIVATE · LOCAL</span>}
        </header>
        <div className="main-content">
          <p className="eyebrow">A place for lasting knowledge</p>
          <h1>Your research,<br /><span>connected to its evidence.</span></h1>
          {error && <p role="alert" className="error-message">{error}</p>}
          {loading ? <p role="status" className="intro">Opening your workspace…</p> : !session ? (
            <section className="form-panel">
              <h2>Sign in to your workspace</h2>
              <p>Your papers and projects belong to your account.</p>
              <form onSubmit={login}>
                <label>Email<input name="email" type="email" autoComplete="username" required maxLength={320} /></label>
                <label>Password<input name="password" type="password" autoComplete="current-password" required maxLength={256} /></label>
                <button className="primary-button" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
              </form>
              <p className="muted">Accounts are created through local setup. Public registration is unavailable.</p>
              {error && <button className="refresh-button" onClick={restore} disabled={busy}>Retry connection</button>}
            </section>
          ) : <><p className="intro">Your private workspace is ready.</p>
            <ProjectLibrary key={session.user.id} session={session} expired={expired} selected={project} select={setProject} />
            <PaperLibrary key={session.user.id} session={session} expired={expired} project={project} />
            <details className="infrastructure-details"><summary>Infrastructure status</summary><SystemStatus /></details></>}
          <footer>ResearchOS <span>Traceable sources. Reproducible analysis.</span></footer>
        </div>
      </main>
    </div>
  );
}
