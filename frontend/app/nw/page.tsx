"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";

import { nw as nwApi } from "@/lib/api";
import { useUser } from "@/lib/UserContext";
import type {
  NwDictEntry,
  NwDictionaries,
  NwFerMapping,
  NwItem,
  NwItemDetail,
  NwWorkType,
} from "@/lib/types";

const COLORS = {
  border: "#e2e8f0",
  borderHard: "#cbd5e1",
  bg: "#f8fafc",
  text: "#0f172a",
  muted: "#64748b",
  primary: "#0284c7",
  primaryBg: "#0284c715",
  hi: "#22c55e",
  hiBg: "#22c55e18",
  med: "#eab308",
  medBg: "#eab30818",
  lo: "#94a3b8",
  loBg: "#94a3b818",
  primaryChip: "#7c3aed",
  primaryChipBg: "#7c3aed15",
};

const MAPPING_TYPE_LABEL: Record<string, string> = {
  direct: "прямой",
  partial: "частичный",
  composite_part: "сопутств.",
  out_of_scope_subscope: "вне скоупа",
};

const MAPPING_TYPE_COLOR: Record<string, { fg: string; bg: string }> = {
  direct: { fg: COLORS.hi, bg: COLORS.hiBg },
  partial: { fg: COLORS.med, bg: COLORS.medBg },
  composite_part: { fg: COLORS.primary, bg: COLORS.primaryBg },
  out_of_scope_subscope: { fg: "#ef4444", bg: "#ef444418" },
};

const CONFIDENCE_COLOR: Record<string, { fg: string; bg: string }> = {
  high: { fg: COLORS.hi, bg: COLORS.hiBg },
  medium: { fg: COLORS.med, bg: COLORS.medBg },
  low: { fg: COLORS.lo, bg: COLORS.loBg },
};

function Chip({
  label,
  color = COLORS.muted,
  bg = COLORS.bg,
  title,
}: { label: string; color?: string; bg?: string; title?: string }) {
  return (
    <span
      title={title}
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "2px 8px",
        borderRadius: 12,
        fontSize: 11,
        fontWeight: 600,
        background: bg,
        color,
        border: `1px solid ${color}30`,
        whiteSpace: "nowrap",
      }}
    >
      {label}
    </span>
  );
}

function dictMap(entries: NwDictEntry[] | undefined): Record<string, string> {
  if (!entries) return {};
  const out: Record<string, string> = {};
  for (const e of entries) out[e.code] = e.name ?? e.description ?? e.code;
  return out;
}

export default function NwDictionaryPage() {
  const router = useRouter();
  const { user, loading: userLoading } = useUser();

  const [workTypes, setWorkTypes] = useState<NwWorkType[]>([]);
  const [dicts, setDicts] = useState<NwDictionaries | null>(null);
  const [items, setItems] = useState<NwItem[]>([]);
  const [loadingItems, setLoadingItems] = useState(false);

  const [selectedWt, setSelectedWt] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [filterStage, setFilterStage] = useState("");
  const [filterScope, setFilterScope] = useState("");
  const [filterRepair, setFilterRepair] = useState("");

  const [openItem, setOpenItem] = useState<NwItemDetail | null>(null);

  // ── auth gate ──
  useEffect(() => {
    if (userLoading) return;
    if (!user) router.push("/auth/login");
  }, [user, userLoading, router]);

  // ── initial load ──
  useEffect(() => {
    Promise.all([nwApi.workTypes(), nwApi.dictionaries()])
      .then(([wts, ds]) => {
        setWorkTypes(wts);
        setDicts(ds);
      })
      .catch((err) => console.error("NW initial load failed", err));
  }, []);

  // ── items reload on filter change ──
  const reloadItems = useCallback(() => {
    setLoadingItems(true);
    nwApi
      .items({
        work_type: selectedWt ?? undefined,
        q: search.trim() || undefined,
        stage: filterStage || undefined,
        location_scope: filterScope || undefined,
        repair_class: filterRepair || undefined,
      })
      .then(setItems)
      .catch((err) => console.error("NW items load failed", err))
      .finally(() => setLoadingItems(false));
  }, [selectedWt, search, filterStage, filterScope, filterRepair]);

  useEffect(() => {
    const t = setTimeout(reloadItems, 200);
    return () => clearTimeout(t);
  }, [reloadItems]);

  const otMap = useMemo(() => dictMap(dicts?.object_types), [dicts]);
  const btMap = useMemo(() => dictMap(dicts?.building_technologies), [dicts]);
  const lsMap = useMemo(() => dictMap(dicts?.location_scopes), [dicts]);
  const stMap = useMemo(() => dictMap(dicts?.stages), [dicts]);
  const rcMap = useMemo(() => dictMap(dicts?.repair_classes), [dicts]);

  const openItemDetail = useCallback((code: string) => {
    nwApi.item(code).then(setOpenItem).catch((err) => console.error("NW item load", err));
  }, []);

  if (userLoading || !user) {
    return (
      <div style={{ padding: 40, color: COLORS.muted, fontFamily: "system-ui, sans-serif" }}>
        Загрузка…
      </div>
    );
  }

  return (
    <div style={{ minHeight: "100vh", background: COLORS.bg, color: COLORS.text, fontFamily: "system-ui, sans-serif" }}>
      {/* Header */}
      <div
        style={{
          padding: "16px 24px",
          background: "white",
          borderBottom: `1px solid ${COLORS.border}`,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: 16,
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
          <button
            onClick={() => router.push("/projects")}
            style={{ background: "none", border: "none", color: COLORS.muted, fontSize: 12, cursor: "pointer" }}
          >
            ← Проекты
          </button>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>
            Нормализованные виды работ
          </h1>
          <span style={{ fontSize: 12, color: COLORS.muted }}>
            {workTypes.length} типов · {workTypes.reduce((s, w) => s + w.items_count, 0)} видов
          </span>
        </div>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "260px 1fr", minHeight: "calc(100vh - 50px)" }}>
        {/* Left: WT list */}
        <aside style={{ borderRight: `1px solid ${COLORS.border}`, background: "white", padding: "12px 8px" }}>
          <button
            onClick={() => setSelectedWt(null)}
            style={{
              width: "100%",
              textAlign: "left",
              padding: "8px 12px",
              background: selectedWt === null ? COLORS.primaryBg : "transparent",
              color: selectedWt === null ? COLORS.primary : COLORS.text,
              border: "none",
              borderRadius: 6,
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
              marginBottom: 4,
            }}
          >
            Все типы
            <span style={{ float: "right", fontSize: 11, color: COLORS.muted, fontWeight: 500 }}>
              {workTypes.reduce((s, w) => s + w.items_count, 0)}
            </span>
          </button>
          {workTypes.map((wt) => (
            <button
              key={wt.code}
              onClick={() => setSelectedWt(wt.code)}
              title={wt.description ?? ""}
              style={{
                width: "100%",
                textAlign: "left",
                padding: "8px 12px",
                background: selectedWt === wt.code ? COLORS.primaryBg : "transparent",
                color: selectedWt === wt.code ? COLORS.primary : COLORS.text,
                border: "none",
                borderRadius: 6,
                fontSize: 13,
                cursor: "pointer",
                marginBottom: 2,
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                gap: 8,
              }}
            >
              <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                <span style={{ color: COLORS.muted, fontSize: 11, fontFamily: "var(--mono, monospace)", marginRight: 6 }}>
                  {wt.code}
                </span>
                {wt.name}
              </span>
              <span style={{ fontSize: 11, color: COLORS.muted, fontWeight: 500, flexShrink: 0 }}>
                {wt.items_count}
              </span>
            </button>
          ))}
        </aside>

        {/* Right: items + filters */}
        <main style={{ padding: 16, overflow: "auto" }}>
          {/* Filters */}
          <div style={{ display: "flex", gap: 8, marginBottom: 12, flexWrap: "wrap" }}>
            <input
              type="search"
              placeholder="Поиск по названию, подвиду, заметке…"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              style={{
                flex: "1 1 280px",
                minWidth: 200,
                padding: "8px 12px",
                fontSize: 13,
                border: `1px solid ${COLORS.borderHard}`,
                borderRadius: 6,
                background: "white",
                color: COLORS.text,
              }}
            />
            <FilterDropdown
              value={filterStage}
              onChange={setFilterStage}
              placeholder="Этап"
              options={dicts?.stages ?? []}
            />
            <FilterDropdown
              value={filterScope}
              onChange={setFilterScope}
              placeholder="Зона"
              options={dicts?.location_scopes ?? []}
            />
            <FilterDropdown
              value={filterRepair}
              onChange={setFilterRepair}
              placeholder="Класс ремонта"
              options={dicts?.repair_classes ?? []}
              labelField="description"
            />
          </div>

          <div style={{ fontSize: 12, color: COLORS.muted, marginBottom: 8 }}>
            {loadingItems ? "Загрузка…" : `${items.length} записей`}
          </div>

          {/* Items table */}
          <div
            style={{
              background: "white",
              border: `1px solid ${COLORS.border}`,
              borderRadius: 8,
              overflow: "hidden",
            }}
          >
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
              <thead>
                <tr style={{ background: COLORS.bg, borderBottom: `1px solid ${COLORS.border}` }}>
                  <Th width={70}>Код</Th>
                  <Th>Уникальная формулировка</Th>
                  <Th width={140}>Подвид</Th>
                  <Th width={80}>Тип</Th>
                  <Th width={90}>Этапы</Th>
                  <Th width={130}>ФЕР (сб-разд)</Th>
                  <Th width={70}>Флаги</Th>
                </tr>
              </thead>
              <tbody>
                {items.map((it) => (
                  <tr
                    key={it.code}
                    onClick={() => openItemDetail(it.code)}
                    style={{
                      borderBottom: `1px solid ${COLORS.border}`,
                      cursor: "pointer",
                    }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = COLORS.bg)}
                    onMouseLeave={(e) => (e.currentTarget.style.background = "white")}
                  >
                    <Td>
                      <code style={{ fontSize: 11, color: COLORS.muted }}>{it.code}</code>
                    </Td>
                    <Td>{it.unique_label}</Td>
                    <Td style={{ color: COLORS.muted, fontSize: 12 }}>{it.subtype ?? ""}</Td>
                    <Td>
                      <Chip label={it.work_type_code} color={COLORS.primary} bg={COLORS.primaryBg} title={it.work_type_name} />
                    </Td>
                    <Td>
                      <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                        {it.stage_codes.map((sc) => (
                          <Chip key={sc} label={sc} title={stMap[sc]} />
                        ))}
                      </div>
                    </Td>
                    <Td>
                      <div style={{ display: "flex", gap: 3, flexWrap: "wrap", fontFamily: "var(--mono, monospace)", fontSize: 11 }}>
                        {(it.primary_fer_refs ?? []).length === 0 ? (
                          <span style={{ color: COLORS.muted, fontStyle: "italic" }}>—</span>
                        ) : (
                          (it.primary_fer_refs ?? []).map((r) => (
                            <Chip key={r} label={r} color={COLORS.primary} bg={COLORS.primaryBg} title={`Сборник ${parseInt(r.split("-")[0], 10)}, Раздел ${parseInt(r.split("-")[1], 10)}`} />
                          ))
                        )}
                      </div>
                    </Td>
                    <Td>
                      <div style={{ display: "flex", gap: 3, flexWrap: "wrap" }}>
                        {it.requires_permit_review && (
                          <Chip
                            label="разрешение"
                            color={COLORS.med}
                            bg={COLORS.medBg}
                            title="Перед заключением договора нужна проверка разрешительной/проектной документации (несущие конструкции, газ, реконструкция и т.п.)"
                          />
                        )}
                        {it.is_capital_repair === true && (
                          <Chip label="кап." color={COLORS.primary} bg={COLORS.primaryBg} title="Капитальный ремонт" />
                        )}
                        {it.is_capital_repair === null && it.repair_class_codes.length > 1 && (
                          <Chip
                            label="?"
                            color={COLORS.muted}
                            bg={COLORS.bg}
                            title="Класс ремонта (текущий vs капитальный) автоматически не определён — требуется уточнение от сметчика при классификации"
                          />
                        )}
                      </div>
                    </Td>
                  </tr>
                ))}
                {items.length === 0 && !loadingItems && (
                  <tr>
                    <td colSpan={7} style={{ padding: 32, textAlign: "center", color: COLORS.muted }}>
                      Нет записей под фильтр
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </main>
      </div>

      {/* Detail panel */}
      {openItem && dicts && (
        <DetailPanel
          item={openItem}
          dicts={dicts}
          maps={{ otMap, btMap, lsMap, stMap, rcMap }}
          onClose={() => setOpenItem(null)}
        />
      )}
    </div>
  );
}

function Th({ children, width }: { children: React.ReactNode; width?: number }) {
  return (
    <th
      style={{
        textAlign: "left",
        padding: "8px 12px",
        fontSize: 11,
        fontWeight: 700,
        color: COLORS.muted,
        textTransform: "uppercase",
        letterSpacing: ".04em",
        width,
      }}
    >
      {children}
    </th>
  );
}

function Td({ children, style }: { children: React.ReactNode; style?: React.CSSProperties }) {
  return <td style={{ padding: "8px 12px", verticalAlign: "top", ...style }}>{children}</td>;
}

function FilterDropdown({
  value,
  onChange,
  placeholder,
  options,
  labelField = "name",
}: {
  value: string;
  onChange: (v: string) => void;
  placeholder: string;
  options: NwDictEntry[];
  labelField?: "name" | "description";
}) {
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      style={{
        padding: "8px 12px",
        fontSize: 13,
        border: `1px solid ${COLORS.borderHard}`,
        borderRadius: 6,
        background: "white",
        color: value ? COLORS.text : COLORS.muted,
        minWidth: 140,
      }}
    >
      <option value="">{placeholder}</option>
      {options.map((o) => (
        <option key={o.code} value={o.code}>
          {o.code} — {(o[labelField] as string) ?? o.code}
        </option>
      ))}
    </select>
  );
}

function DetailPanel({
  item,
  dicts,
  maps,
  onClose,
}: {
  item: NwItemDetail;
  dicts: NwDictionaries;
  maps: {
    otMap: Record<string, string>;
    btMap: Record<string, string>;
    lsMap: Record<string, string>;
    stMap: Record<string, string>;
    rcMap: Record<string, string>;
  };
  onClose: () => void;
}) {
  const { otMap, btMap, lsMap, stMap, rcMap } = maps;
  const fer = item.fer_mappings ?? [];
  const primaryFer = fer.filter((m) => m.is_primary);
  const otherFer = fer.filter((m) => !m.is_primary);

  return (
    <div
      onClick={onClose}
      style={{
        position: "fixed",
        inset: 0,
        background: "#0f172a40",
        zIndex: 100,
        display: "flex",
        justifyContent: "flex-end",
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          width: 540,
          maxWidth: "90vw",
          background: "white",
          padding: 24,
          overflow: "auto",
          boxShadow: "-4px 0 24px #0001",
        }}
      >
        {/* Header */}
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 12 }}>
          <code style={{ fontSize: 12, color: COLORS.muted }}>{item.code}</code>
          <button
            onClick={onClose}
            style={{ background: "none", border: "none", cursor: "pointer", color: COLORS.muted, fontSize: 18 }}
          >
            ×
          </button>
        </div>
        <h2 style={{ margin: "0 0 4px 0", fontSize: 18, fontWeight: 700 }}>{item.unique_label}</h2>
        <div style={{ fontSize: 13, color: COLORS.muted, marginBottom: 16 }}>
          <Chip label={item.work_type_code} color={COLORS.primary} bg={COLORS.primaryBg} /> {item.work_type_name}
          {item.subtype && <span> · {item.subtype}</span>}
        </div>

        {/* Notes */}
        {item.notes && (
          <div
            style={{
              padding: 12,
              background: COLORS.bg,
              borderLeft: `3px solid ${COLORS.borderHard}`,
              fontSize: 12,
              color: COLORS.text,
              marginBottom: 16,
              borderRadius: 4,
            }}
          >
            {item.notes}
          </div>
        )}

        {/* Attribute groups */}
        <AttrGroup label="Тип объекта" codes={item.object_type_codes} map={otMap} />
        <AttrGroup label="Технология здания" codes={item.building_technology_codes} map={btMap} />
        <AttrGroup label="Зона выполнения" codes={item.location_scope_codes} map={lsMap} />
        <AttrGroup label="Этапы (для КТП и плана)" codes={item.stage_codes} map={stMap} />
        <AttrGroup label="Класс ремонта" codes={item.repair_class_codes} map={rcMap} />

        <div style={{ display: "flex", gap: 8, marginTop: 8, flexWrap: "wrap" }}>
          {item.requires_permit_review && (
            <Chip
              label="требует проверки разрешений"
              color={COLORS.med}
              bg={COLORS.medBg}
              title="Перед заключением договора нужна проверка разрешительной/проектной документации (для работ с несущими конструкциями, газом, реконструкцией и т.п.)"
            />
          )}
          {item.is_capital_repair === true && (
            <Chip label="капитальный ремонт" color={COLORS.primary} bg={COLORS.primaryBg} title="Работа квалифицирована как капитальный ремонт" />
          )}
          {item.is_capital_repair === false && (
            <Chip label="не капремонт" color={COLORS.muted} bg={COLORS.bg} title="Работа однозначно не относится к капитальному ремонту" />
          )}
          {item.is_capital_repair === null && (
            <Chip
              label="класс уточняется"
              color={COLORS.muted}
              bg={COLORS.bg}
              title="Класс ремонта (текущий или капитальный) автоматически не определяется — требуется уточнение от сметчика при классификации"
            />
          )}
        </div>

        {/* Расшифровка значений тегов выше */}
        {(item.requires_permit_review || item.is_capital_repair === null) && (
          <div style={{ marginTop: 10, fontSize: 11, color: COLORS.muted, lineHeight: 1.5 }}>
            {item.requires_permit_review && (
              <div>
                <strong>требует проверки разрешений</strong> — перед договором нужна проверка проектной/разрешительной документации.
              </div>
            )}
            {item.is_capital_repair === null && (
              <div>
                <strong>класс уточняется</strong> — текущий это ремонт или капитальный, автоматически не определяется. Уточняется при классификации сметы.
              </div>
            )}
          </div>
        )}

        {/* FER mapping */}
        <h3 style={{ margin: "24px 0 8px 0", fontSize: 14, fontWeight: 700, color: COLORS.text }}>
          ФЕР маппинг ({fer.length})
        </h3>
        {fer.length === 0 && (
          <div style={{ fontSize: 12, color: COLORS.muted, padding: 12, background: COLORS.bg, borderRadius: 4 }}>
            Этот NW не покрывается ФЕРн (агрегат / ФЕРм / коммерческие нормы).
          </div>
        )}
        {primaryFer.length > 0 && (
          <FerMappingList title="Основные" mappings={primaryFer} />
        )}
        {otherFer.length > 0 && (
          <FerMappingList title="Дополнительные" mappings={otherFer} />
        )}
      </div>
    </div>
  );
}

function AttrGroup({ label, codes, map }: { label: string; codes: string[]; map: Record<string, string> }) {
  if (codes.length === 0) return null;
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 600, marginBottom: 4, textTransform: "uppercase", letterSpacing: ".04em" }}>
        {label}
      </div>
      <div style={{ display: "flex", gap: 4, flexWrap: "wrap" }}>
        {codes.map((c) => (
          <Chip key={c} label={`${c} ${map[c] ?? ""}`} />
        ))}
      </div>
    </div>
  );
}

function FerMappingList({ title, mappings }: { title: string; mappings: NwFerMapping[] }) {
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: 11, color: COLORS.muted, fontWeight: 600, marginBottom: 6, textTransform: "uppercase", letterSpacing: ".04em" }}>
        {title}
      </div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {mappings.map((m, idx) => {
          const mt = MAPPING_TYPE_COLOR[m.mapping_type] ?? { fg: COLORS.muted, bg: COLORS.bg };
          const cf = CONFIDENCE_COLOR[m.confidence] ?? { fg: COLORS.muted, bg: COLORS.bg };
          const ferRef = `${String(m.fer_collection_num).padStart(2, "0")}-${String(m.fer_section_num).padStart(2, "0")}`;
          return (
            <div
              key={idx}
              style={{
                padding: 10,
                border: `1px solid ${COLORS.border}`,
                borderRadius: 6,
                fontSize: 12,
              }}
            >
              {/* Путь: ФЕР → Сборник N. Название → Раздел M. Полный заголовок */}
              <div style={{ marginBottom: 6 }}>
                <div style={{ fontSize: 10, color: COLORS.muted, textTransform: "uppercase", letterSpacing: ".04em", marginBottom: 2 }}>
                  ФЕР · код {ferRef}
                </div>
                <div style={{ fontSize: 12, fontWeight: 600, color: COLORS.text }}>
                  Сборник {m.fer_collection_num}
                  {m.collection_name && <span style={{ fontWeight: 500 }}> — {m.collection_name}</span>}
                </div>
                <div style={{ fontSize: 12, color: COLORS.text, marginTop: 2 }}>
                  {m.section_title
                    ? m.section_title
                    : <span style={{ color: COLORS.muted }}>Раздел {m.fer_section_num}</span>}
                </div>
              </div>

              <div style={{ display: "flex", gap: 6, alignItems: "center", marginBottom: m.notes ? 4 : 0, flexWrap: "wrap" }}>
                <Chip label={MAPPING_TYPE_LABEL[m.mapping_type] ?? m.mapping_type} color={mt.fg} bg={mt.bg} />
                <Chip label={m.confidence} color={cf.fg} bg={cf.bg} title={`Уверенность маппинга: ${m.confidence}`} />
                {m.is_primary && (
                  <Chip label="primary" color={COLORS.primaryChip} bg={COLORS.primaryChipBg} title="Основной NW для этого раздела ФЕР" />
                )}
              </div>
              {m.notes && <div style={{ color: COLORS.muted, fontSize: 11 }}>{m.notes}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}
