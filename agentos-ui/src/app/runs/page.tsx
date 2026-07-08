"use client";

import { useEffect, useState } from "react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";

interface RunRecord {
  run_id: string;
  sop_id: string;
  state: string;
  updated_at: string;
}

export default function Workflows() {
  const [runs, setRuns] = useState<RunRecord[]>([]);

  useEffect(() => {
    fetch("/api/v1/workflows/runs")
      .then(res => res.json())
      .then(data => setRuns(data.runs || []))
      .catch(console.error);
  }, []);

  return (
    <div className="space-y-6">
      <h1 className="text-3xl font-bold tracking-tight text-white">Workflow Traces</h1>
      <div className="rounded-md border border-zinc-800">
        <Table>
          <TableHeader>
            <TableRow className="hover:bg-transparent border-zinc-800">
              <TableHead className="text-zinc-400">Run ID</TableHead>
              <TableHead className="text-zinc-400">SOP ID</TableHead>
              <TableHead className="text-zinc-400">State</TableHead>
              <TableHead className="text-zinc-400">Updated At</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {runs.length === 0 ? (
              <TableRow className="hover:bg-transparent border-zinc-800">
                <TableCell colSpan={4} className="text-center text-zinc-500">No runs found.</TableCell>
              </TableRow>
            ) : (
              runs.map((r, i) => (
                <TableRow key={i} className="hover:bg-zinc-900 border-zinc-800">
                  <TableCell className="font-mono text-zinc-300">{r.run_id}</TableCell>
                  <TableCell className="text-zinc-300">{r.sop_id}</TableCell>
                  <TableCell>
                    <Badge variant={r.state === "COMPLETED" ? "default" : "secondary"} className={r.state === "COMPLETED" ? "bg-emerald-500/10 text-emerald-500" : ""}>
                      {r.state}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-zinc-400">{r.updated_at}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
