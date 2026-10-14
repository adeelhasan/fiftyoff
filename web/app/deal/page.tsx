import type { Metadata } from "next";
import DealPage from "@/components/pages/DealPage";

// One exported page; FastAPI serves it for every /deal/{slug}/ and writes the link preview into its head (api_v1).
export const metadata: Metadata = { title: "Deal" };

export default function Page() {
  return <DealPage />;
}
