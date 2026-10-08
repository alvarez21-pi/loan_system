import { createFileRoute } from "@tanstack/react-router";
import { useEffect, useState } from "react";
import AppShell from "../components/AppShell";
import { Button, Card, DataTable, Field, Input, PageHeader, Select, StatCard, fmtNumber, money } from "../components/lms-ui";
import useResource from "../hooks/useResource.js";
import { borrowers, errorMessage, getUser, hasPermission, loanProducts, reports, users } from "../lib/api";
import { localDateString, localDateString as today } from "../lib/utils";
import { showToast } from "../lib/toast";

export const Route = createFileRoute("/reports")({
  head: () => ({
    meta: [
      { title: "Reports — Microfinance LMS" },
      { name: "description", content: "Filterable operational and financial reports, exportable as PDF or Excel." },
    ],
  }),
  component: () => (
    <AppShell>
      <ReportsPage />
    </AppShell>
  ),
});

type ReportDef = {
  label: string;
  path: string;
  financial?: boolean;
  filters?: ("dateRange" | "product" | "officer" | "period" | "borrower")[];
};

const REPORTS: Record<string, ReportDef> = {
  "portfolio-at-risk": { label: "Portfolio at Risk", path: "portfolio-at-risk", filters: ["product"] },
  collections: { label: "Collections", path: "collections", filters: ["dateRange", "period"] },
  disbursements: { label: "Disbursements", path: "disbursements", filters: ["dateRange", "product", "officer"] },
  "income-statement": { label: "Income Statement", path: "income-statement", financial: true, filters: ["dateRange"] },
  "portfolio-by-product": { label: "Portfolio by Product", path: "portfolio-by-product" },
  "borrower-statement": { label: "Borrower Statement", path: "borrower-statement", filters: ["borrower"] },
  "cash-flow": { label: "Cash Flow & Capital", path: "cash-flow", financial: true, filters: ["dateRange"] },
  "loan-officer-performance": { label: "Loan Officer Performance", path: "loan-officer-performance", filters: ["dateRange"] },
  "expenses-by-category": { label: "Expenses by Category", path: "expenses-by-category", financial: true, filters: ["dateRange"] },
  "payroll-summary": { label: "Payroll Summary", path: "payroll-summary", financial: true, filters: ["dateRange"] },
  "leave-summary": { label: "Leave Summary", path: "leave-summary", filters: ["dateRange"] },
};

/** Report cells: numbers get thousand separators; ids and calendar-ish keys stay as they are. */
const PLAIN_KEYS = /(^id$|_id$|^period$|^date$|^month$|^bucket$)/;
const formatCell = (key: string, value: unknown) =>
  typeof value === "number" && !PLAIN_KEYS.test(key) ? fmtNumber(value) : ((value as any) ?? "—");

function findTableRows(payload: any): any[] {
  if (!payload) return [];
  for (const value of Object.values(payload)) {
    if (Array.isArray(value) && value.length && typeof value[0] === "object") return value as any[];
  }
  for (const value of Object.values(payload)) {
    if (Array.isArray(value)) return value as any[];
  }
  return [];
}

function findKpis(payload: any): [string, string][] {
  if (!payload) return [];
  const kpis: [string, string][] = [];
  for (const [key, value] of Object.entries(payload)) {
    if (Array.isArray(value) || (value && typeof value === "object")) continue;
    if (typeof value === "number") {
      const looksLikeMoney = /amount|balance|value|total|income|expense|payroll|net|cash|worth/i.test(key);
      kpis.push([key.replace(/_/g, " "), looksLikeMoney ? money(value) : fmtNumber(value)]);
    } else if (typeof value === "string" && key !== "note") {
      kpis.push([key.replace(/_/g, " "), value]);
    }
  }
  return kpis;
}

function monthsAgo(n: number) {
  const d = new Date();
  d.setMonth(d.getMonth() - n);
  return localDateString(d);
}

function ReportsPage() {
  const user = getUser();
  const [selected, setSelected] = useState("portfolio-at-risk");
  const [payload, setPayload] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [startDate, setStartDate] = useState(monthsAgo(3));
  const [endDate, setEndDate] = useState(today());
  const [productId, setProductId] = useState("");
  const [officerId, setOfficerId] = useState("");
  const [period, setPeriod] = useState("monthly");
  const [borrowerId, setBorrowerId] = useState("");

  const productList = useResource(() => loanProducts.list(), []);
  const officerList = useResource(() => (hasPermission(user, "users:manage") ? users.list() : Promise.resolve({ data: [] })), []);
  const borrowerList = useResource(() => borrowers.list(), []);

  const availableReports = Object.entries(REPORTS).filter(
    ([, def]) => hasPermission(user, def.financial ? "reports:financial" : "reports:view"),
  );
  const report = REPORTS[selected];

  function params() {
    const p: Record<string, string> = {};
    if (report?.filters?.includes("dateRange")) {
      p.start_date = startDate;
      p.end_date = endDate;
    }
    if (report?.filters?.includes("product") && productId) p.product_id = productId;
    if (report?.filters?.includes("officer") && officerId) p.officer_id = officerId;
    if (report?.filters?.includes("period")) p.period = period;
    return p;
  }

  function path() {
    if (selected === "borrower-statement") return `borrower-statement/${borrowerId || 0}`;
    return report?.path || selected;
  }

  async function load() {
    if (selected === "borrower-statement" && !borrowerId) {
      showToast("Select a borrower first.", "danger");
      return;
    }
    setLoading(true);
    try {
      const result = await reports.get(path(), params());
      setPayload(result);
    } catch (error) {
      showToast(errorMessage(error), "danger");
      setPayload(null);
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    setPayload(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected]);

  async function download(format: "pdf" | "excel") {
    if (selected === "borrower-statement" && !borrowerId) {
      showToast("Select a borrower first.", "danger");
      return;
    }
    try {
      const blob = await reports.download(path(), format, params());
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `${selected}.${format === "pdf" ? "pdf" : "xlsx"}`;
      link.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      showToast(errorMessage(error), "danger");
    }
  }

  const rows = findTableRows(payload);
  const kpis = findKpis(payload);
  const collectionsChart = selected === "collections" && rows.length ? rows : null;

  return (
    <>
      <PageHeader title="Reports" description="Export as a branded PDF or Excel." />

      <Card className="mb-4">
        <div className="flex flex-wrap items-end gap-3">
          <Field label="Report">
            <Select value={selected} onChange={(e) => setSelected(e.target.value)}>
              {availableReports.map(([key, def]) => (
                <option key={key} value={key}>
                  {def.label}
                </option>
              ))}
            </Select>
          </Field>
          {report?.filters?.includes("dateRange") ? (
            <>
              <Field label="From">
                <Input type="date" value={startDate} onChange={(e: any) => setStartDate(e.target.value)} />
              </Field>
              <Field label="To">
                <Input type="date" value={endDate} onChange={(e: any) => setEndDate(e.target.value)} />
              </Field>
            </>
          ) : null}
          {report?.filters?.includes("period") ? (
            <Field label="Grouping">
              <Select value={period} onChange={(e) => setPeriod(e.target.value)}>
                <option value="daily">Daily</option>
                <option value="weekly">Weekly</option>
                <option value="monthly">Monthly</option>
              </Select>
            </Field>
          ) : null}
          {report?.filters?.includes("product") ? (
            <Field label="Product">
              <Select value={productId} onChange={(e) => setProductId(e.target.value)}>
                <option value="">All products</option>
                {(productList.data || []).map((p: any) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
          {report?.filters?.includes("officer") ? (
            <Field label="Officer">
              <Select value={officerId} onChange={(e) => setOfficerId(e.target.value)}>
                <option value="">All officers</option>
                {(officerList.data || []).filter((u: any) => u.role === "maker").map((u: any) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
          {report?.filters?.includes("borrower") ? (
            <Field label="Borrower">
              <Select value={borrowerId} onChange={(e) => setBorrowerId(e.target.value)}>
                <option value="">Select borrower</option>
                {(borrowerList.data || []).map((b: any) => (
                  <option key={b.id} value={b.id}>
                    {b.name}
                  </option>
                ))}
              </Select>
            </Field>
          ) : null}
          <Button onClick={load} disabled={loading}>
            {loading ? "Loading…" : "Run report"}
          </Button>
          <Button variant="outline" onClick={() => download("pdf")}>
            Download PDF
          </Button>
          <Button variant="outline" onClick={() => download("excel")}>
            Download Excel
          </Button>
        </div>
      </Card>

      {kpis.length ? (
        <div className="mb-4 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {kpis.map(([label, value]) => (
            <StatCard key={label} label={label} value={value} />
          ))}
        </div>
      ) : null}

      {collectionsChart ? (
        <Card title="Expected vs collected" className="mb-4">
          <div className="flex items-end gap-3" style={{ height: 140 }}>
            {(() => {
              const max = Math.max(1, ...collectionsChart.flatMap((r: any) => [r.expected_amount || 0, r.actual_collected || 0]));
              return collectionsChart.map((r: any) => (
                <div key={r.period} className="flex flex-1 flex-col items-center gap-1">
                  <div className="flex w-full items-end justify-center gap-1" style={{ height: 110 }}>
                    <div className="w-1/2 rounded-t-sm bg-muted-foreground/40" style={{ height: `${((r.expected_amount || 0) / max) * 100}%` }} title={`Expected ${money(r.expected_amount)}`} />
                    <div className="w-1/2 rounded-t-sm bg-primary" style={{ height: `${((r.actual_collected || 0) / max) * 100}%` }} title={`Collected ${money(r.actual_collected)}`} />
                  </div>
                  <span className="text-[10px] text-muted-foreground">{r.period}</span>
                </div>
              ));
            })()}
          </div>
          <p className="mt-2 text-xs text-muted-foreground">Grey = expected · Blue = collected</p>
        </Card>
      ) : null}

      <Card title={report?.label}>
        <DataTable
          rows={rows}
          empty={payload ? "No rows for this filter." : "Run the report to see results."}
          columns={
            rows.length
              ? Object.keys(rows[0]).map((key) => ({ key, label: key.replace(/_/g, " "), render: (row: any) => formatCell(key, row[key]) as any }))
              : [{ key: "empty", label: "Report data" }]
          }
        />
      </Card>
    </>
  );
}
