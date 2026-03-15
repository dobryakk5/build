"use client";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/api";

export default function LoginPage() {
  const router = useRouter();
  const [email,    setEmail]    = useState("");
  const [password, setPassword] = useState("");
  const [error,    setError]    = useState("");
  const [loading,  setLoading]  = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      const data = await auth.login(email, password);
      localStorage.setItem("access_token",  data.access_token);
      localStorage.setItem("refresh_token", data.refresh_token);
      localStorage.setItem("user",          JSON.stringify(data.user));
      router.push("/projects");
    } catch (err: any) {
      setError(err.message ?? "Ошибка входа");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div style={{minHeight:"100vh",display:"flex",alignItems:"center",justifyContent:"center",background:"var(--bg)"}}>
      <div style={{background:"var(--surface)",borderRadius:8,border:"1px solid var(--border)",padding:"40px 36px",width:360}}>
        <div style={{fontWeight:700,fontSize:20,marginBottom:24,color:"var(--text)"}}>
          🏗 СтройКонтроль
        </div>

        <form onSubmit={handleSubmit} style={{display:"flex",flexDirection:"column",gap:14}}>
          <div>
            <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:4,textTransform:"uppercase",letterSpacing:".06em"}}>Email</label>
            <input
              type="email" required value={email} onChange={e=>setEmail(e.target.value)}
              style={{width:"100%",padding:"9px 12px",border:"1px solid var(--border2)",borderRadius:5,fontSize:14,outline:"none"}}
            />
          </div>
          <div>
            <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:4,textTransform:"uppercase",letterSpacing:".06em"}}>Пароль</label>
            <input
              type="password" required value={password} onChange={e=>setPassword(e.target.value)}
              style={{width:"100%",padding:"9px 12px",border:"1px solid var(--border2)",borderRadius:5,fontSize:14,outline:"none"}}
            />
          </div>

          {error && <div style={{fontSize:12,color:"var(--red)",padding:"8px 12px",background:"#fef2f2",borderRadius:4}}>{error}</div>}

          <button
            type="submit" disabled={loading}
            style={{padding:"10px",background:"var(--blue-dark)",color:"#fff",border:"none",borderRadius:5,fontSize:14,fontWeight:600,cursor:"pointer",opacity:loading?.6:1}}
          >
            {loading ? "Входим..." : "Войти"}
          </button>
        </form>
      </div>
    </div>
  );
}
