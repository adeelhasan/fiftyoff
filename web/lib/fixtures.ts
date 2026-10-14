// Fixture mode for `next dev` (NEXT_PUBLIC_API=fixtures): web/fixtures/ is a copy of tests/fixtures/api_v1/.
import { ApiError } from "./api";

export async function fixture(path: string): Promise<unknown> {
  // Dynamic imports, so the fixtures are only fetched in fixture mode.
  const [route, query = ""] = path.split("?");
  const p = route.replace(/^\/api\/v1\//, "");
  await new Promise((r) => setTimeout(r, 300)); // let the loading state show
  if (p === "today") return (await import("@/fixtures/today.json")).default;
  if (p === "deals") return (await (query.includes("aisle=") ? import("@/fixtures/deals_filtered.json") : import("@/fixtures/deals.json"))).default;
  if (p === "shelves") return (await import("@/fixtures/shelves.json")).default;
  if (p.startsWith("shelves/")) return (await import("@/fixtures/shelf.json")).default;
  if (p === "sizes") return (await import("@/fixtures/sizes.json")).default;
  if (p === "sized") return (await import("@/fixtures/sized.json")).default;
  if (p === "gone") return (await import("@/fixtures/gone.json")).default;
  if (p.startsWith("product/")) return (await (p.includes("GONE") ? import("@/fixtures/product_gone.json") : import("@/fixtures/product.json"))).default;
  throw new ApiError(404, `no fixture for ${path}`);
}
