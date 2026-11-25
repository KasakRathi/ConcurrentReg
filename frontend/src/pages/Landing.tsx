import { ControlSection } from "@/components/landing/ControlSection";
import { ExperienceSection } from "@/components/landing/ExperienceSection";
import { FactsSection } from "@/components/landing/FactsSection";
import { FooterSection } from "@/components/landing/FooterSection";
import { GuaranteesSection } from "@/components/landing/GuaranteesSection";
import { SiteNav } from "@/components/nav/SiteNav";
import { Hero } from "@/components/landing/Hero";
import { QuoteSection } from "@/components/landing/QuoteSection";
import { ReproduceSection } from "@/components/landing/ReproduceSection";
import { ResultsSection } from "@/components/landing/ResultsSection";
import { RunSection } from "@/components/landing/RunSection";
import { WorkloadsSection } from "@/components/landing/WorkloadsSection";

export default function Landing() {
  return (
    <div className="lp min-h-screen overflow-x-clip">
      <a href="#run" className="sr-only focus:not-sr-only focus:fixed focus:left-3 focus:top-3 focus:z-[100] focus:rounded-md focus:bg-white focus:px-3 focus:py-2 focus:text-black">Skip to content</a>
      <SiteNav />
      <main>
        <Hero />
        <RunSection />
        <ExperienceSection />
        <WorkloadsSection />
        <ResultsSection />
        <ReproduceSection />
        <GuaranteesSection />
        <QuoteSection />
        <ControlSection />
        <FactsSection />
      </main>
      <FooterSection />
    </div>
  );
}
