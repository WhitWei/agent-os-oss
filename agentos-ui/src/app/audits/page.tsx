"use client";

import { useEffect, useState } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

interface AuditRecord {
  trace_id: string;
  decision: string;
  reviewer: string;
  reason?: string;
  timestamp: string;
}

export default function Audits() {
  const [audits, setAudits] = useState<AuditRecord[]>([]);

  useEffect(() => {
    fetch("/api/v1/governance/audits")
      .then(res => res.json())
      .then(data => setAudits(data.audits || []))
      .catch(console.error);
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold tracking-tight text-white">Governance Audits</h1>
      <div className="rounded-md border border-zinc-800">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent border-zinc-800">
              <TableHead className="text-zinc-400">Trace ID</TableHead>
              <TableHead className="text-zinc-400">Decision</TableHead>
              <TableHead className="text-zinc-400">Reviewer</TableHead>
              <TableHead className="text-zinc-400">Reason</TableHead>
              <TableHead className="text-zinc-400">Timestamp</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {audits.length === 0 ? (
              <TableRow className="hover:bg-transparent border-zinc-800">
                <TableCell colSpan={5} className="text-center text-zinc-500">No audits found.</TableCell>
              </TableRow>
            ) : (
              audits.map((a, i) => (
                <TableRow key={i} className="hover:bg-zinc-900 border-zinc-800">
                  <TableCell className="font-mono text-zinc-300">{a.trace_id}</TableCell>
                  <TableCell>
                    <Badge variant="outline" className={a.decision === "REJECTED" ? "border-rose-500 text-rose-500" : "border-emerald-500 text-emerald-500"}>
                      {a.decision}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-zinc-300">{a.reviewer}</TableCell>
                  <TableCell className="text-zinc-400 max-w-xs truncate" title={a.reason}>{a.reason || "-"}</TableCell>
                  <TableCell className="text-zinc-400">{a.timestamp}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
