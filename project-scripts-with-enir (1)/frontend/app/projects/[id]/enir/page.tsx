"use client";
import { useState } from "react";
import { useParams } from "next/navigation";
import EnirBrowser  from "./EnirBrowser";
import EnirMapping  from "./EnirMapping";

export default function EnirPage() {
  const [tab, setTab] = useState<"browser" | "mapping">("browser");
  const { id } = useParams<{ id: string }>();

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", overflow: "hidden" }}>
      {/* sub-tabs */}
      <div style={{
        display: "flex", gap: 0,
        borderBottom: "1px solid var(--border)",
        background: "var(--hdr2)", flexShrink: 0,
      }}>
        {([
          { key: "browser", label: "📖 Справочник ЕНИР" },
          { key: "mapping", label: "🔗 Маппинг сметы" },
        ] as const).map(t => (
          <button key={t.key} onClick={() => setTab(t.key)} style={{
            padding: "8px 16px", border: "none", cursor: "pointer",
            fontSize: 12, fontWeight: 500, background: "transparent",
            color:        tab === t.key ? "#e2e8f0" : "#64748b",
            borderBottom: tab === t.key ? "2px solid var(--blue)" : "2px solid transparent",
          }}>{t.label}</button>
        ))}
      </div>

      <div style={{ flex: 1, overflow: "hidden" }}>
        {tab === "browser" ? <EnirBrowser /> : <EnirMapping projectId={id} />}
      </div>
    </div>
  );
}
