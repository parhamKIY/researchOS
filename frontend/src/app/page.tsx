import Link from "next/link";

export default function Home() {
  return (
    <div className="workspace">
      <aside className="sidebar">
        <Link href="/" className="brand"><span className="brand-mark">R</span>ResearchOS<span className="brand-dot">.</span></Link>
        <p className="sidebar-label">Your workspace</p>
        <div className="active-nav" aria-current="page"><span>◈</span> Overview</div>
        <div className="sidebar-foot"><span className="mini-dot" />Local development<br /><small>Foundation · v0.1</small></div>
      </aside>
      <main>
        <header className="topbar"><span>Workspace / Overview</span><span className="local-label">PRIVATE · LOCAL</span></header>
        <div className="main-content">
          <p className="eyebrow">A foundation for better research</p>
          <h1>Your research,<br /><span>connected to its evidence.</span></h1>
          <p className="intro">A place to understand scientific papers and build lasting knowledge.<br />Your workspace starts with a reliable foundation.</p>
          <section className="milestone-panel">
            <div><p className="eyebrow">Current milestone · 01</p><h2>Building the foundation</h2><p>The application shell and infrastructure checks are available.<br />Paper uploads and AI analysis arrive in the next milestones.</p></div>
            <a className="docs-link" href="/api/docs">Explore the API <span aria-hidden="true">↗</span></a>
          </section>
          <footer>ResearchOS <span>Traceable sources. Reproducible analysis.</span></footer>
        </div>
      </main>
    </div>
  );
}
