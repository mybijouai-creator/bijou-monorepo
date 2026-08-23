import { useEffect, useState } from "react";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { CaseStudies } from "./components/CaseStudies";
import { Changelog } from "./components/Changelog";
import { ComparisonTable } from "./components/ComparisonTable";
import { DemoChat } from "./components/DemoChat";
import { FAQ } from "./components/FAQ";
import { Features } from "./components/Features";
import { FinalCTA } from "./components/FinalCTA";
import { Footer } from "./components/Footer";
import { Hero } from "./components/Hero";
import { HowItWorks } from "./components/HowItWorks";
import { Navbar } from "./components/Navbar";
import { OnboardingModal } from "./components/OnboardingModal";
import { OutreachQueue } from "./components/OutreachQueue";
import { PainSection } from "./components/PainSection";
import { Playbooks } from "./components/Playbooks";
import { Pricing } from "./components/Pricing";
import { PWAInstallPrompt } from "./components/PWAInstallPrompt";
import { RevenueCalculator } from "./components/RevenueCalculator";
import { SlideDeckModal } from "./components/SlideDeckModal";
// Fix 6: Viral hook components — Hook A + B after PainSection, Hook C after Pricing
import { Story2amProperty } from "./components/Story2amProperty";
import { StoryLunchRushClinic } from "./components/StoryLunchRushClinic";
import { VoiceComingSoon } from "./components/VoiceComingSoon";
import { ViralPillars } from "./components/ViralPillars";
import { WaitlistStrip } from "./components/WaitlistStrip";
import { WhatsAppCTA } from "./components/WhatsAppCTA";
import { track } from "./services/posthog";

export default function App() {
  const [isMenuOpen, setIsMenuOpen] = useState(false);
  const [slideDeckOpen, setSlideDeckOpen] = useState(false);
  // 2026-07-30: hash route for the agent-fleet review queue
  // e.g. https://mybijou.xyz/#/admin/outreach-queue
  const [route, setRoute] = useState<string>(() =>
    typeof window !== "undefined" ? window.location.hash : ""
  );
  const [modalState, setModalState] = useState<{
    isOpen: boolean;
    mode: "signup" | "waitlist" | "demo";
    source: string;
  }>({
    isOpen: false,
    mode: "signup",
    source: "navbar",
  });

  // Fix scroll position - always start from top
  useEffect(() => {
    window.scrollTo(0, 0);
    // Prevent scroll restoration
    if (
      typeof window !== "undefined" &&
      "scrollRestoration" in window.history
    ) {
      window.history.scrollRestoration = "manual";
    }
    // One-time landing pageview. posthog-js also fires its own $pageview via
    // capture_pageview=true; this gives us a typed event for the funnel.
    track("landing_pageview", {
      utm_source: new URLSearchParams(window.location.search).get("utm_source") || undefined,
      utm_medium: new URLSearchParams(window.location.search).get("utm_medium") || undefined,
      utm_campaign: new URLSearchParams(window.location.search).get("utm_campaign") || undefined,
      referrer: document.referrer || undefined,
    });
    // Hash-route listener (for /admin/outreach-queue)
    const onHash = () => setRoute(window.location.hash);
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);

  const openModal = (mode: "signup" | "waitlist" | "demo", source: string) => {
    setModalState({ isOpen: true, mode, source });
    if (mode === "signup") track("signup_modal_opened", { source });
    if (mode === "demo") track("demo_modal_opened", { source });
    if (mode === "waitlist") track("waitlist_modal_opened", { source });
  };

  const closeModal = () => {
    setModalState((prev) => ({ ...prev, isOpen: false }));
  };

  // 2026-07-30: if hash route matches, render the agent-fleet review queue
  // instead of the landing page. Same shell (ErrorBoundary + bg), no nav
  // distractions — the queue is for the founder only.
  const isQueue = route === "#/admin/outreach-queue";

  return (
    <ErrorBoundary>
    <div
      className="min-h-screen text-white selection:bg-emerald-500/30 selection:text-emerald-200 overflow-x-hidden"
      style={{ backgroundColor: "#030810" }}
    >
      {/* Clean background - minimal effects like OpenClaw */}
      <div className="fixed inset-0 pointer-events-none z-0">
        <div className="absolute top-[-5%] left-[-5%] w-[25%] h-[25%] bg-emerald-900/8 rounded-full blur-[100px]" />
        <div className="absolute bottom-[-5%] right-[-5%] w-[25%] h-[25%] bg-emerald-900/6 rounded-full blur-[100px]" />
      </div>

      <div className="relative z-10">
        {isQueue ? (
          <OutreachQueue />
        ) : (
          <>
        <Navbar
          isMenuOpen={isMenuOpen}
          setIsMenuOpen={setIsMenuOpen}
          onOpenModal={() => openModal("signup", "navbar")}
        />
        <main>
          <Hero onOpenModal={() => openModal("signup", "hero")} />
          <PainSection />
          {/* Fix 6 Hook A: 2am Property story — after PainSection, before Pricing */}
          <Story2amProperty />
          {/* Fix 6 Hook B: Lunch Rush Clinic story — after Hook A */}
          <StoryLunchRushClinic />
          <Features />
          <ComparisonTable />
          <ViralPillars
            onOpenModal={() => openModal("signup", "viral_pillars")}
          />
          <RevenueCalculator
            onOpenModal={() => openModal("signup", "revenue_calculator")}
          />
          <Pricing onOpenModal={() => openModal("signup", "pricing")} />
          {/* Fix 6 Hook C: Voice coming soon — after Pricing */}
          <VoiceComingSoon />
          <HowItWorks onOpenModal={() => openModal("signup", "how_it_works")} />
          <Playbooks onOpenModal={() => openModal("signup", "playbooks")} />
          <CaseStudies
            onOpenModal={() => openModal("signup", "case_studies")}
          />
          <DemoChat onOpenModal={() => openModal("demo", "demo_chat")} />
          <FAQ />
          {/* 2026-08-23: Public changelog — recent shipped changes. Anchored
              at #changelog for shareable links. */}
          <Changelog />
          <FinalCTA
            onOpenModal={() => openModal("signup", "final_cta")}
            onOpenSlideDeck={() => setSlideDeckOpen(true)}
          />
        </main>
        <Footer />

        {/* Fixed CTAs */}
        <WhatsAppCTA phoneNumber="60174106981" />
        <WaitlistStrip
          onOpenModal={() => openModal("waitlist", "waitlist_strip")}
        />
        <PWAInstallPrompt />

        {/* Onboarding Modal */}
        <OnboardingModal
          isOpen={modalState.isOpen}
          onClose={closeModal}
          mode={modalState.mode}
          source={modalState.source}
        />

        {/* Slide Deck / Resources Modal */}
        <SlideDeckModal
          isOpen={slideDeckOpen}
          onClose={() => setSlideDeckOpen(false)}
        />
          </>
        )}
      </div>
    </div>
    </ErrorBoundary>
  );
}
