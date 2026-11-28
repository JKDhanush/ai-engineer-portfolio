"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { setToken } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function submit(ev: React.FormEvent) {
    ev.preventDefault();
    setError(null);
    const res = await fetch("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, password }) });
    if (!res.ok) { setError("Wrong email or password"); return; }
    setToken((await res.json()).access_token);
    router.push("/");
  }

  return (
    <main className="mx-auto max-w-sm px-4 py-16">
      <h1 className="text-xl font-semibold text-ink">Sign in</h1>
      <p className="mt-1 text-sm text-slate-600">Accounts are created by an administrator (<code>make user</code>).</p>
      <form onSubmit={submit} className="mt-6 space-y-3">
        <input type="email" required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="Email"
          autoComplete="username" className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm" />
        <input type="password" required value={password} onChange={(e) => setPassword(e.target.value)}
          placeholder="Password" autoComplete="current-password"
          className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm" />
        {error && <p className="text-sm text-red-700">{error}</p>}
        <button className="w-full rounded-md bg-accent py-2 text-sm text-white">Sign in</button>
      </form>
    </main>
  );
}
