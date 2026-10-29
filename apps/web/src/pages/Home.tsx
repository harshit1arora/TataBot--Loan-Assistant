import { Nav } from "@/components/landing/Nav";
import { Hero } from "@/components/landing/Hero";
import { HowItWorks } from "@/components/landing/HowItWorks";
import { Features } from "@/components/landing/Features";
import { Architecture } from "@/components/landing/Architecture";
import { Impact } from "@/components/landing/Impact";
import { EmiEstimator } from "@/components/landing/EmiEstimator";
import { Security } from "@/components/landing/Security";
import { CTA } from "@/components/landing/CTA";
import { Footer } from "@/components/landing/Footer";

export default function Home() {
  return (
    <div className="min-h-screen bg-white">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-[60] focus:rounded-lg focus:bg-white focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-blue-900"
      >
        Skip to content
      </a>
      <Nav />
      <main id="main">
        <Hero />
        <HowItWorks />
        <Features />
        <Architecture />
        <Impact />
        <EmiEstimator />
        <Security />
        <CTA />
      </main>
      <Footer />
    </div>
  );
}
