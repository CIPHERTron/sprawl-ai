export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-8 text-center">
      <div className="max-w-2xl space-y-6">
        <div className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/5 px-4 py-1.5 text-sm text-white/60">
          <span className="h-2 w-2 animate-pulse rounded-full bg-emerald-400" />
          Sprawl AI — M4 online
        </div>

        <h1 className="text-5xl font-bold tracking-tight text-white">
          Secret sprawl,{" "}
          <span className="bg-linear-to-r from-emerald-400 to-cyan-400 bg-clip-text text-transparent">
            eliminated.
          </span>
        </h1>

        <p className="text-lg text-white/60">
          Detect exposed credentials, visualize their blast radius, and rotate
          them safely — human-in-the-loop, verify-before-revoke, auto-rollback.
        </p>

        <div className="flex items-center justify-center gap-4">
          <a
            href="/demo"
            className="rounded-lg bg-emerald-500 px-6 py-3 text-sm font-semibold text-white shadow-lg transition hover:bg-emerald-400"
          >
            Try demo →
          </a>
          <a
            href="https://github.com/CIPHERTron/sprawl-ai"
            target="_blank"
            rel="noopener noreferrer"
            className="rounded-lg border border-white/10 px-6 py-3 text-sm font-semibold text-white/70 transition hover:border-white/30 hover:text-white"
          >
            View on GitHub
          </a>
        </div>
      </div>
    </main>
  );
}
