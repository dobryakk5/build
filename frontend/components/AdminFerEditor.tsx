"use client";

import { useCallback, useEffect, useState } from "react";
import type { ReactNode } from "react";

import AdminFerKnowledgePanel from "@/components/AdminFerKnowledgePanel";
import { admin as adminApi, fer as ferApi } from "@/lib/api";
import type { FerBrowseItem, FerCollectionSummary } from "@/lib/types";

type FerNodeKind = "collection" | "section" | "subsection" | "table";

type FerNode = {
  key: string;
  kind: FerNodeKind;
  id: number;
  title: string;
  meta: string;
  ignored: boolean;
  effective_ignored: boolean;
  collectionId: number;
  sectionId?: number;
  subsectionId?: number;
  expandable: boolean;
};

function nodeKey(kind: FerNodeKind, id: number) {
  return `${kind}:${id}`;
}

function collectionMeta(collection: FerCollectionSummary) {
  return `${collection.sections_count} разделов • ${collection.subsections_count} подразделов • ${collection.total_tables_count} таблиц`;
}

function itemMeta(item: FerBrowseItem) {
  if (item.kind === "section") {
    return `${item.subsection_count ?? 0} подразделов • ${item.table_count ?? 0} таблиц`;
  }
  if (item.kind === "subsection") {
    return `${item.table_count ?? 0} таблиц`;
  }
  return `${item.row_count ?? 0} строк`;
}

function collectionToNode(collection: FerCollectionSummary): FerNode {
  return {
    key: nodeKey("collection", collection.id),
    kind: "collection",
    id: collection.id,
    title: `Сборник ${collection.num}. ${collection.name}`,
    meta: collectionMeta(collection),
    ignored: collection.ignored,
    effective_ignored: collection.effective_ignored,
    collectionId: collection.id,
    expandable: true,
  };
}

function itemToNode(item: FerBrowseItem, parent: FerNode): FerNode {
  return {
    key: nodeKey(item.kind, item.id),
    kind: item.kind,
    id: item.id,
    title: item.title,
    meta: itemMeta(item),
    ignored: item.ignored,
    effective_ignored: item.effective_ignored,
    collectionId: parent.collectionId,
    sectionId:
      item.kind === "section"
        ? item.id
        : parent.kind === "collection"
          ? undefined
          : parent.kind === "section"
            ? parent.id
            : parent.sectionId,
    subsectionId:
      item.kind === "subsection"
        ? item.id
        : parent.kind === "subsection"
          ? parent.id
          : undefined,
    expandable: item.kind !== "table",
  };
}

async function fetchChildren(node: FerNode) {
  if (!node.expandable) {
    return [];
  }

  const response = await ferApi.browse({
    collectionId: node.collectionId,
    sectionId: node.kind === "section" ? node.id : node.sectionId,
    subsectionId: node.kind === "subsection" ? node.id : undefined,
  });

  return response.items.map((item) => itemToNode(item, node));
}

export default function AdminFerEditor() {
  const [rootNodes, setRootNodes] = useState<FerNode[]>([]);
  const [childrenByKey, setChildrenByKey] = useState<Record<string, FerNode[]>>({});
  const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [savingKey, setSavingKey] = useState<string | null>(null);

  const refreshTree = useCallback(async (expandedSnapshot?: Set<string>) => {
    const nextExpanded = expandedSnapshot ?? new Set<string>();
    const collections = await ferApi.collections();
    const nextRoots = collections.map(collectionToNode);
    const nextChildren: Record<string, FerNode[]> = {};

    const hydrate = async (nodes: FerNode[]) => {
      for (const node of nodes) {
        if (!node.expandable || !nextExpanded.has(node.key)) {
          continue;
        }
        const children = await fetchChildren(node);
        nextChildren[node.key] = children;
        await hydrate(children);
      }
    };

    await hydrate(nextRoots);
    setRootNodes(nextRoots);
    setChildrenByKey(nextChildren);
  }, []);

  useEffect(() => {
    setLoading(true);
    setError(null);
    refreshTree()
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : "Не удалось загрузить каталог ФЕР");
      })
      .finally(() => setLoading(false));
  }, [refreshTree]);

  const toggleExpand = useCallback(async (node: FerNode) => {
    if (!node.expandable) {
      return;
    }

    if (expandedKeys.has(node.key)) {
      setExpandedKeys((current) => {
        const next = new Set(current);
        next.delete(node.key);
        return next;
      });
      return;
    }

    if (!childrenByKey[node.key]) {
      const children = await fetchChildren(node);
      setChildrenByKey((current) => ({ ...current, [node.key]: children }));
    }

    setExpandedKeys((current) => {
      const next = new Set(current);
      next.add(node.key);
      return next;
    });
  }, [childrenByKey, expandedKeys]);

  const toggleIgnored = useCallback(async (node: FerNode, ignored: boolean) => {
    const snapshot = new Set(expandedKeys);
    setSavingKey(node.key);
    try {
      await adminApi.updateFerIgnored(node.kind, node.id, ignored);
      await refreshTree(snapshot);
      setExpandedKeys(snapshot);
    } finally {
      setSavingKey(null);
    }
  }, [expandedKeys, refreshTree]);

  const renderNodes = (nodes: FerNode[], depth = 0): ReactNode =>
    nodes.map((node) => {
      const isExpanded = expandedKeys.has(node.key);
      const children = childrenByKey[node.key] ?? [];
      const inheritedIgnore = node.effective_ignored && !node.ignored;

      return (
        <div key={node.key}>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr auto",
              gap: 12,
              alignItems: "center",
              padding: "10px 16px",
              borderBottom: "1px solid var(--border)",
              background: depth === 0 ? "#f8fafc" : "transparent",
              opacity: node.effective_ignored ? 0.5 : 1,
            }}
          >
            <div style={{ display: "flex", alignItems: "flex-start", gap: 10, paddingLeft: depth * 18 }}>
              <button
                type="button"
                onClick={() => toggleExpand(node)}
                disabled={!node.expandable}
                style={{
                  marginTop: 1,
                  width: 18,
                  height: 18,
                  border: "none",
                  background: "transparent",
                  color: node.expandable ? "var(--muted)" : "transparent",
                  cursor: node.expandable ? "pointer" : "default",
                  padding: 0,
                  fontSize: 11,
                }}
              >
                {node.expandable ? (isExpanded ? "▾" : "▸") : "•"}
              </button>
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: "var(--text)" }}>{node.title}</span>
                  <span
                    style={{
                      fontSize: 10,
                      color: "var(--muted)",
                      border: "1px solid var(--border)",
                      borderRadius: 999,
                      padding: "2px 7px",
                      background: "var(--bg)",
                      fontFamily: "var(--mono)",
                    }}
                  >
                    {node.kind === "collection" ? "Сборник" : node.kind === "section" ? "Раздел" : node.kind === "subsection" ? "Подраздел" : "Таблица"}
                  </span>
                  {inheritedIgnore && (
                    <span style={{ fontSize: 10, color: "#b45309", background: "#f59e0b16", border: "1px solid #f59e0b35", borderRadius: 999, padding: "2px 7px" }}>
                      по родителю
                    </span>
                  )}
                </div>
                <div style={{ marginTop: 4, fontSize: 11, color: "var(--muted)" }}>{node.meta}</div>
              </div>
            </div>

            <label style={{ display: "inline-flex", alignItems: "center", gap: 8, fontSize: 12, color: "var(--text)", whiteSpace: "nowrap" }}>
              <input
                type="checkbox"
                checked={node.ignored}
                disabled={savingKey === node.key}
                onChange={(event) => toggleIgnored(node, event.target.checked)}
              />
              Игнор
            </label>
          </div>

          {isExpanded && children.length > 0 && renderNodes(children, depth + 1)}
        </div>
      );
    });

  if (loading) {
    return <div style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>Загрузка каталога ФЕР...</div>;
  }

  if (error) {
    return <div style={{ padding: 32, textAlign: "center", color: "var(--red)" }}>{error}</div>;
  }

  return (
    <div>
      <AdminFerKnowledgePanel />
      <div style={{ padding: "14px 16px", borderBottom: "1px solid var(--border)", background: "#f8fafc", fontSize: 12, color: "var(--muted)", lineHeight: 1.5 }}>
        Игнор работает на уровне всей системы. Серые строки видны и в админской консоли, и в клиентском каталоге ФЕР. Наследование идёт сверху вниз: если игнорируется родитель, дочерние строки тоже становятся серыми.
      </div>
      {rootNodes.length === 0 ? (
        <div style={{ padding: 32, textAlign: "center", color: "var(--muted)" }}>Каталог ФЕР пуст.</div>
      ) : (
        <div>{renderNodes(rootNodes)}</div>
      )}
    </div>
  );
}
