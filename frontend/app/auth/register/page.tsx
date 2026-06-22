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
  privacy_policy_accepted: boolean;
  personal_data_policy_accepted: boolean;
};

export default function RegisterPage() {
  const router = useRouter();
  const [form,    setForm]    = useState<RegisterForm>({
    email: "",
    name: "",
    password: "",
    org_name: "",
    privacy_policy_accepted: false,
    personal_data_policy_accepted: false,
  });
  const [error,   setError]   = useState("");
  const [loading, setLoading] = useState(false);

  const canRegister = form.privacy_policy_accepted && form.personal_data_policy_accepted;

  const set = (k: "email" | "name" | "password" | "org_name") => (e: ChangeEvent<HTMLInputElement>) =>
    setForm(f => ({ ...f, [k]: e.target.value }));

  const setConsent = (k: "privacy_policy_accepted" | "personal_data_policy_accepted") =>
    (e: ChangeEvent<HTMLInputElement>) => setForm(f => ({ ...f, [k]: e.target.checked }));

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    if (!canRegister) {
      setError("Для регистрации необходимо принять оба согласия");
      return;
    }
    setError(""); setLoading(true);
    try {
      await auth.register(form);
      router.push("/projects");
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : "Ошибка регистрации");
    } finally {
      setLoading(false);
    }
  }

  const inp = (label: string, key: "email" | "name" | "password" | "org_name", type = "text", required = true) => (
    <div>
      <label style={{fontSize:11,color:"var(--muted)",display:"block",marginBottom:4,textTransform:"uppercase",letterSpacing:".06em"}}>{label}</label>
      <input type={type} required={required} value={form[key]} onChange={set(key)}
        style={{width:"100%",padding:"9px 12px",border:"1px solid var(--border2)",borderRadius:5,fontSize:14,outline:"none"}}/>
    </div>
  );

  const checkbox = (
    label: string,
    key: "privacy_policy_accepted" | "personal_data_policy_accepted",
  ) => (
    <label style={{display:"flex",alignItems:"flex-start",gap:9,fontSize:12,color:"var(--text)",lineHeight:1.4,cursor:"pointer"}}>
      <input
        type="checkbox"
        required
        checked={form[key]}
        onChange={setConsent(key)}
        style={{marginTop:2,width:15,height:15,accentColor:"var(--blue-dark)",flex:"0 0 auto"}}
      />
      <span>{label}</span>
    </label>
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

          <div style={{display:"flex",flexDirection:"column",gap:9}}>
            {checkbox("Согласен с политикой конфиденциальности", "privacy_policy_accepted")}
            {checkbox("Согласен с политикой обработки персональных данных", "personal_data_policy_accepted")}
          </div>

          {error && <div style={{fontSize:12,color:"var(--red)",padding:"8px 12px",background:"#fef2f2",borderRadius:4}}>{error}</div>}

          <button type="submit" disabled={loading || !canRegister}
            style={{padding:"10px",background:"var(--blue-dark)",color:"#fff",border:"none",borderRadius:5,fontSize:14,fontWeight:600,cursor:loading || !canRegister ? "not-allowed" : "pointer",opacity:loading || !canRegister ? .6 : 1}}>
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
