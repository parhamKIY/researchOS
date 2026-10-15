"use client";

import { useEffect, useState } from "react";
import { api, ApiFailure } from "@/lib/api";
import type { PublicSystemSettings } from "@/lib/system-llm";

export function SystemModelNotice({ expired }: { expired: () => void }) {
  const [state, setState] = useState<PublicSystemSettings | null>(null);
  const [error, setError] = useState("");
  useEffect(() => {
    let alive = true;
    api<PublicSystemSettings>("/settings/system-model").then((value) => { if (alive) setState(value); }).catch((err) => {
      if (!alive) return;
      if (err instanceof ApiFailure && err.status === 401) expired();
      else setError((err as Error).message);
    });
    return () => { alive = false; };
  }, [expired]);
  return <section className="system-model-card" aria-label="System default text model"><p className="eyebrow">System default text model</p>
    {error ? <p role="alert">{error}</p> : !state ? <p role="status">Loading default model…</p> : state.active ? <p><strong>{state.active.model_name}</strong> · {state.active.execution_mode === "mock" ? "MOCK · local fixture" : "Connection verified"}</p> : <p>No system provider is active. An administrator can configure it.</p>}
    <p className="muted">Personal model routes take precedence. Open a paper to review its analysis plan and approve the exact destinations before sending text.</p>
  </section>;
}
