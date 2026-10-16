import type { Metadata } from "next";
import Sizes from "@/components/pages/Sizes";

export const metadata: Metadata = { title: "Clothes & Shoes" };

export default function Page() {
  return <Sizes />;
}
