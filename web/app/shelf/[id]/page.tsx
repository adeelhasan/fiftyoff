import type { Metadata } from "next";
import ShelfPage from "@/components/pages/ShelfPage";

// Exported once, as /shelf/_/. FastAPI serves that file for every /shelf/{id}/ (fiftyoff/api_v1.py), so shelves
// need no listing at build time; the page reads its id from location.pathname.
export const dynamicParams = false;
export function generateStaticParams() {
  return [{ id: "_" }];
}

export const metadata: Metadata = { title: "Shelf" };

export default function Page() {
  return <ShelfPage />;
}
