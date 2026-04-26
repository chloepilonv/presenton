import { NextRequest, NextResponse } from "next/server";

const SKIP_PREFIXES = ["/api/health", "/api/_next"];

export function middleware(req: NextRequest) {
  const token = process.env.PRESENTON_API_TOKEN;
  if (!token) return NextResponse.next();

  const path = req.nextUrl.pathname;
  if (SKIP_PREFIXES.some((p) => path.startsWith(p))) {
    return NextResponse.next();
  }

  const header = req.headers.get("authorization") ?? "";
  const [scheme, value] = header.split(" ");
  if (scheme?.toLowerCase() !== "bearer" || value !== token) {
    return NextResponse.json({ error: "Unauthorized" }, { status: 401 });
  }
  return NextResponse.next();
}

export const config = {
  matcher: ["/api/:path*"],
};
