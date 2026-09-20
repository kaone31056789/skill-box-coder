// Railway (and any uptime probe) can hit this without loading the React app.
export const dynamic = "force-dynamic";

export function GET() {
  return Response.json({ status: "ok" });
}
