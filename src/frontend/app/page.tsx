import { readFile } from "node:fs/promises";
import { join } from "node:path";
import { StationDashboard } from "@/components/StationDashboard";
import type { DemoData } from "@/types/station";

export const dynamic = "force-dynamic";

export default async function Home() {
  let json: string;
  try {
    json = await readFile(join(process.cwd(), "data", "snapshots.json"), "utf8");
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;

    return (
      <main className="page-shell">
        <header className="page-heading">
          <div>
            <h1>Bergamo</h1>
            <p>Run the snapshot exporter from the CityFlow project root.</p>
          </div>
        </header>
        <code>uv run python -m city_flow.export_snapshots --city-dir data/bergamo</code>
      </main>
    );
  }

  const data: DemoData = JSON.parse(json);
  return <StationDashboard data={data} />;
}
