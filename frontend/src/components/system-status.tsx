"use client";

import { useEffect, useState } from "react";
import { readHealth, type HealthState } from "@/lib/health";

const labels: Record<HealthState, string> = {
  checking: "Checking…", ok: "Connected", unavailable: "Unavailable",
};

export function SystemStatus() {
  const [live, setLive] = useState<HealthState>("checking");
  const [ready, setReady] = useState<HealthState>("checking");
  const [checkedAt, setCheckedAt] = useState<string>();
  const [refresh, setRefresh] = useState(0);

  useEffect(() => {
    let disposed = false;
    let controller: AbortController | undefined;
    let timeout: ReturnType<typeof setTimeout> | undefined;
    async function check() {
      controller?.abort();
      if (timeout) clearTimeout(timeout);
      controller = new AbortController();
      timeout = setTimeout(() => controller?.abort(), 8000);
      const results = await Promise.all([
        readHealth("/api/v1/health/live", controller.signal),
        readHealth("/api/v1/health/ready", controller.signal),
      ]);
      if (timeout) clearTimeout(timeout);
      if (!disposed) {
        setLive(results[0]);
        setReady(results[1]);
        setCheckedAt(new Date().toLocaleTimeString());
      }
    }
    void check();
    const interval = setInterval(() => void check(), 15000);
    return () => {
      disposed = true;
      clearInterval(interval);
      if (timeout) clearTimeout(timeout);
      controller?.abort();
    };
  }, [refresh]);

  return (
    <section className="status-panel" aria-labelledby="status-title">
      <div className="section-heading">
        <div><p className="eyebrow">Live environment</p><h2 id="status-title">System readiness</h2></div>
        <button className="refresh-button" onClick={() => setRefresh((value) => value + 1)}>Refresh status</button>
      </div>
      <div aria-live="polite">
        {[
          { name: "Application server", detail: "Live connection to the research API.", state: live },
          { name: "Database & message broker", detail: "PostgreSQL schema and Redis connection.", state: ready },
        ].map(({ name, detail, state }) => (
          <div className="service-row" key={name}>
            <div><h3>{name}</h3><p>{detail}</p></div>
            <span className={`badge badge-${state}`}><span className="status-dot" />{labels[state]}</span>
          </div>
        ))}
        <p className="check-time">{checkedAt ? `Last checked ${checkedAt} · refreshes every 15 seconds` : "Connecting to your local environment…"}</p>
      </div>
    </section>
  );
}
