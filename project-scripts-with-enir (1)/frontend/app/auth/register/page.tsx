"use client";
import { useState } from "react";
import type { ChangeEvent, FormEvent } from "react";
import { useRouter } from "next/navigation";
import { auth } from "@/lib/api";

type RegisterForm = {
  email: string;
  name: string;
  password: string;
  org_name: string;
};

export default function RegisterPage() {
  const router = useRouter();
  const [form,    setForm]    = useState<RegisterForm>({ email: "", name: "", password: "", org_name: "" });
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(false);

  const set = (k: keyof RegisterForm) => (e: ChangeEvent<HTMLInputElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }));

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(""); setLoading(true);
    try {
      const data = await auth.register(form);
      localStorage.setItem("access_token",  data.access_token);
      localStorage.setItem("refresh_token", data.refresh_token);
      localStorage.setItem("user",          JSON.stringify(data.user));
      router.push("/projects");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ошибка регистрации");
    } finally {
      setLoading(false);
    }
  }

  const inp = (label: string, key: keyof RegisterForm, type = "text", required = true) => (
    <div>
      <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:4,textTransform:"uppercase",letterSpacing:".06em"}}>{label}</label>
      <input type={type} required={required} value={form[key]} onChange={set(key)}
        style={{width:"100%",padding:"9px 12px",border:"1px solid var(--border2)",borderRadius:5,fontSize:14,outline:"none"}}/>
    </div>
  );

  return (
    <div style={{minHeight:"100vh",display:"flex",alignItems:"center",justifyContent:"center",background:"var(--bg)"}}>
      <div style={{background:"var(--surface)",borderRadius:8,border:"1px solid var(--border)",padding:"40px 36px",width:380}}>
        <div style={{fontWeight:700,fontSize:20,marginBottom:6}}>🏗 СтройКонтроль</div>
        <div style={{fontSize:13,color:"var(--muted)",marginBottom:24}}>Создайте аккаунт</div>

        <form onSubmit={handleSubmit} style={{display:"flex",flexDirection:"column",gap:14}}>
          {inp("Ваше имя",      "name")}
          {inp("Email",         "email",    "email")}
          {inp("Пароль",        "password", "password")}
          {inp("Название компании (необязательно)", "org_name", "text", false)}

          {error && <div style={{fontSize:12,color:"var(--red)",padding:"8px 12px",background:"#fef2f2",borderRadius:4}}>{error}</div>}

          <button type="submit" disabled={loading}
            style={{padding:"10px",background:"var(--blue-dark)",color:"#fff",border:"none",borderRadius:5,fontSize:14,fontWeight:600,cursor:"pointer",opacity:loading?.6:1}}>
            {loading ? "Регистрируем..." : "Зарегистрироваться"}
          </button>
        </form>

        <div style={{marginTop:16,fontSize:13,color:"var(--muted)",textAlign:"center"}}>
          Уже есть аккаунт?{" "}
          <span onClick={()=>router.push("/auth/login")} style={{color:"var(--blue-dark)",cursor:"pointer",fontWeight:500}}>Войти</span>
        </div>
      </div>
    </div>
  );
}
