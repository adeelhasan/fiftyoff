import Today from "@/components/pages/Today";

export default function Page() {
  return (
    <>
      {/* Start the one home-page request with the HTML instead of after hydration (LCP is the Just in photo). */}
      {process.env.NEXT_PUBLIC_API !== "fixtures" && <link rel="preload" href="/api/v1/today" as="fetch" crossOrigin="anonymous" />}
      <Today />
    </>
  );
}
