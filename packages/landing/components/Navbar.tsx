import {
    AnimatePresence,
    motion,
    useMotionValueEvent,
    useScroll,
} from "framer-motion";
import { Menu, X } from "lucide-react";
import React, { useState } from "react";
import { BijouLogo } from "./BijouLogo";
import { LanguageSwitcher } from "./LanguageSwitcher";
import { track as trackPostHog } from "../services/posthog";

interface NavbarProps {
  isMenuOpen: boolean;
  setIsMenuOpen: (isOpen: boolean) => void;
  onOpenModal: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  isMenuOpen,
  setIsMenuOpen,
  onOpenModal,
}) => {
  const [isScrolled, setIsScrolled] = useState(false);
  const { scrollY } = useScroll();

  useMotionValueEvent(scrollY, "change", (latest) => {
    if (latest > 50) {
      setIsScrolled(true);
    } else {
      setIsScrolled(false);
    }
    // Close mobile menu on scroll
    if (latest > 100 && isMenuOpen) {
      setIsMenuOpen(false);
    }
  });

  return (
    <motion.nav
      className={`fixed top-0 left-0 right-0 z-50 border-b transition-all duration-300 ${
        isScrolled
          ? "bg-black/80 backdrop-blur-xl border-white/10 shadow-lg"
          : "bg-transparent border-transparent"
      }`}
    >
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex justify-between items-center h-20">
          {/* Signal Gem mark + wordmark */}
          <a
            href="#top"
            className="flex items-center gap-3 cursor-pointer"
            aria-label="Bijou AI — home"
          >
            <BijouLogo size={40} tone="gold" />
            <span className="font-bold text-xl tracking-tight">
              Bijou<span className="text-gradient-gold">AI</span>
            </span>
          </a>

          {/* Desktop Menu */}
          <div className="hidden md:flex items-center gap-8">
            <a
              href="#features"
              className="text-sm font-medium text-gray-300 hover:text-gold-400 transition-colors"
            >
              Features
            </a>
            <a
              href="#roadmap"
              className="text-sm font-medium text-gray-300 hover:text-gold-400 transition-colors"
            >
              Roadmap
            </a>
            <a
              href="#demo"
              className="text-sm font-medium text-gray-300 hover:text-gold-400 transition-colors"
            >
              Live Demo
            </a>
            <a
              href="#changelog"
              className="text-sm font-medium text-gray-300 hover:text-gold-400 transition-colors flex items-center gap-1.5"
            >
              What's new
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
            </a>
            <LanguageSwitcher />
            <button
              onClick={() => { trackPostHog("nav_signup_clicked", { cta: "navbar_early_access" }); onOpenModal?.(); }}
              className="bg-gradient-to-r from-gold-500 to-gold-300 hover:from-gold-400 hover:to-gold-300 text-black font-bold py-2 px-6 rounded-lg transition-all shadow-[0_0_20px_rgba(212,175,55,0.4)] hover:shadow-[0_0_30px_rgba(212,175,55,0.6)]"
            >
              Get Early Access
            </button>
          </div>

          {/* Mobile Menu Button */}
          <div className="md:hidden">
            <button
              onClick={() => setIsMenuOpen(!isMenuOpen)}
              className="touch-target text-gray-300 hover:text-white focus:outline-none p-2 -mr-2 rounded-lg hover:bg-white/10 transition-colors"
              aria-label={isMenuOpen ? "Close menu" : "Open menu"}
              aria-expanded={isMenuOpen}
            >
              {isMenuOpen ? (
                <X className="w-6 h-6" />
              ) : (
                <Menu className="w-6 h-6" />
              )}
            </button>
          </div>
        </div>
      </div>

      {/* Mobile Menu Dropdown */}
      <AnimatePresence>
        {isMenuOpen && (
          <motion.div
            initial={{ opacity: 0, height: 0 }}
            animate={{ opacity: 1, height: "auto" }}
            exit={{ opacity: 0, height: 0 }}
            transition={{ duration: 0.2, ease: "easeInOut" }}
            className="md:hidden glass-panel border-t border-gold-400/10 bg-dark-900 overflow-hidden"
          >
            <div className="px-4 pt-2 pb-6 space-y-1">
              <a
                href="#features"
                className="block text-base font-medium text-gray-300 hover:text-gold-400 py-3 border-b border-white/5"
                onClick={() => setIsMenuOpen(false)}
              >
                Features
              </a>
              <a
                href="#roadmap"
                className="block text-base font-medium text-gray-300 hover:text-gold-400 py-3 border-b border-white/5"
                onClick={() => setIsMenuOpen(false)}
              >
                Roadmap
              </a>
              <a
                href="#demo"
                className="block text-base font-medium text-gray-300 hover:text-gold-400 py-3 border-b border-white/5"
                onClick={() => setIsMenuOpen(false)}
              >
                Live Demo
              </a>
              <div className="pt-3 pb-2">
                <LanguageSwitcher />
              </div>
              <button
                onClick={() => {
                  setIsMenuOpen(false);
                  onOpenModal();
                }}
                className="w-full mt-2 bg-gradient-to-r from-gold-500 to-gold-300 hover:from-gold-400 hover:to-gold-300 text-black font-bold py-3.5 px-6 rounded-lg"
              >
                Get Early Access
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.nav>
  );
};
