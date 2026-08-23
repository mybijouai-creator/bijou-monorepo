import { AnimatePresence } from "framer-motion";
import { Github, Instagram, Linkedin, Mail, Twitter } from "lucide-react";
import React, { useState } from "react";
import { BijouLogo } from "./BijouLogo";
import { EnterpriseContactForm } from "./EnterpriseContactForm";
import { InfoModal } from "./InfoModal";
import { IntegrationForm } from "./IntegrationForm";
import { PartnershipForm } from "./PartnershipForm";

export const Footer: React.FC = () => {
  const [activeModal, setActiveModal] = useState<
    | "about"
    | "careers"
    | "privacy"
    | "terms"
    | "enterprise"
    | "partnership"
    | "integration"
    | null
  >(null);

  return (
    <>
      <footer className="bg-black border-t border-deep-green-500/20 pt-16 pb-8">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="grid md:grid-cols-4 gap-12 mb-12">
            <div className="col-span-1 md:col-span-2">
              <div className="flex items-center gap-3 mb-4">
                <BijouLogo size={32} tone="gold" />
                <span className="font-bold text-xl">
                  <span className="text-transparent bg-clip-text bg-gradient-to-r from-gold-400 to-gold-200">
                    Bijou
                  </span>
                  <span className="text-white font-extrabold">AI</span>
                </span>
              </div>
              <p className="text-gray-400 max-w-sm mb-6">
                The Digital Employee that understands your local customers. No
                apps, no friction, just results.
              </p>

              {/* Contact Information */}
              <div className="mb-6 space-y-2 text-sm text-gray-400">
                <p className="flex items-center gap-2">
                  <Mail className="w-4 h-4 text-gold-400" />
                  <a
                    href="mailto:hello@mybijou.xyz"
                    className="hover:text-gold-400 transition-colors"
                  >
                    hello@mybijou.xyz
                  </a>
                </p>
                {/* WhatsApp direct */}
                <p className="flex items-center gap-2">
                  <svg
                    className="w-4 h-4 text-emerald-400 flex-shrink-0"
                    fill="currentColor"
                    viewBox="0 0 24 24"
                  >
                    <path d="M17.472 14.382c-.297-.149-1.758-.867-2.03-.967-.273-.099-.471-.148-.67.15-.197.297-.767.966-.94 1.164-.173.199-.347.223-.644.075-.297-.15-1.255-.463-2.39-1.475-.883-.788-1.48-1.761-1.653-2.059-.173-.297-.018-.458.13-.606.134-.133.298-.347.446-.52.149-.174.198-.298.298-.497.099-.198.05-.371-.025-.52-.075-.149-.669-1.612-.916-2.207-.242-.579-.487-.5-.669-.51-.173-.008-.371-.01-.57-.01-.198 0-.52.074-.792.372-.272.297-1.04 1.016-1.04 2.479 0 1.462 1.065 2.875 1.213 3.074.149.198 2.096 3.2 5.077 4.487.709.306 1.262.489 1.694.625.712.227 1.36.195 1.871.118.571-.085 1.758-.719 2.006-1.413.248-.694.248-1.289.173-1.413-.074-.124-.272-.198-.57-.347m-5.421 7.403h-.004a9.87 9.87 0 01-5.031-1.378l-.361-.214-3.741.982.998-3.648-.235-.374a9.86 9.86 0 01-1.51-5.26c.001-5.45 4.436-9.884 9.888-9.884 2.64 0 5.122 1.03 6.988 2.898a9.825 9.825 0 012.893 6.994c-.003 5.45-4.437 9.884-9.885 9.884m8.413-18.297A11.815 11.815 0 0012.05 0C5.495 0 .16 5.335.157 11.892c0 2.096.547 4.142 1.588 5.945L.057 24l6.305-1.654a11.882 11.882 0 005.683 1.448h.005c6.554 0 11.89-5.335 11.893-11.893a11.821 11.821 0 00-3.48-8.413z" />
                  </svg>
                  <a
                    href="https://api.whatsapp.com/send/?phone=60174106981"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-emerald-400 transition-colors"
                  >
                    +60 17-410 6981
                  </a>
                </p>
                <div className="text-xs text-gray-500 space-y-1">
                  <p>
                    Sales:{" "}
                    <a
                      href="mailto:mrj@mybijou.xyz"
                      className="hover:text-gold-400 transition-colors"
                    >
                      mrj@mybijou.xyz
                    </a>
                  </p>
                  <p>
                    Support:{" "}
                    <a
                      href="mailto:support@mybijou.xyz"
                      className="hover:text-gold-400 transition-colors"
                    >
                      support@mybijou.xyz
                    </a>
                  </p>
                  <p>
                    Founder:{" "}
                    <a
                      href="mailto:jewel@mybijou.xyz"
                      className="hover:text-gold-400 transition-colors"
                    >
                      jewel@mybijou.xyz
                    </a>
                  </p>
                </div>
              </div>

              {/* Social Media Links */}
              <div className="flex gap-4 mb-6">
                <a
                  href="https://www.x.com/meetbijou"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-gray-400 hover:text-gold-400 transition-colors"
                  aria-label="Twitter/X"
                >
                  <Twitter className="w-5 h-5" />
                </a>
                <a
                  href="https://www.linkedin.com/company/mybijou/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-gray-400 hover:text-gold-400 transition-colors"
                  aria-label="LinkedIn"
                >
                  <Linkedin className="w-5 h-5" />
                </a>
                <a
                  href="https://www.instagram.com/mybijouai/"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-gray-400 hover:text-gold-400 transition-colors"
                  aria-label="Instagram"
                >
                  <Instagram className="w-5 h-5" />
                </a>
                <a
                  href="https://github.com/w3jdev"
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-gray-400 hover:text-gold-400 transition-colors"
                  aria-label="GitHub"
                >
                  <Github className="w-5 h-5" />
                </a>
              </div>

              {/* W3J LLC Attribution */}
              <div className="flex items-center gap-3 pt-4 border-t border-white/5">
                <img
                  src="https://www.w3jdev.com/w3j-logo-gold.png"
                  alt="W3J LLC"
                  className="h-6 w-auto"
                />
                <div className="text-xs text-gray-500">
                  <p>
                    A production of{" "}
                    <a
                      href="https://www.w3jdev.com"
                      target="_blank"
                      rel="noopener noreferrer"
                      className="text-gold-400 hover:text-gold-300 transition-colors font-semibold"
                    >
                      W3J LLC
                    </a>
                  </p>
                  <p className="text-gray-600">
                    Wyoming, USA • Operations: Kuala Lumpur, Malaysia
                  </p>
                </div>
              </div>
            </div>

            <div>
              <h4 className="font-bold text-white mb-4">Product</h4>
              <ul className="space-y-2 text-sm text-gray-400">
                <li>
                  <a
                    href="#features"
                    className="hover:text-gold-400 transition-colors"
                  >
                    Features
                  </a>
                </li>
                <li>
                  <a
                    href="#pricing"
                    className="hover:text-gold-400 transition-colors"
                  >
                    Pricing
                  </a>
                </li>
                <li>
                  <button
                    onClick={() => setActiveModal("integration")}
                    className="hover:text-gold-400 transition-colors"
                  >
                    Integrations
                  </button>
                </li>
                <li>
                  <a
                    href="#case-studies"
                    className="hover:text-gold-400 transition-colors"
                  >
                    Case Studies
                  </a>
                </li>
              </ul>
            </div>

            <div>
              <h4 className="font-bold text-white mb-4">Company</h4>
              <ul className="space-y-2 text-sm text-gray-400">
                <li>
                  <button
                    onClick={() => setActiveModal("about")}
                    className="hover:text-gold-400 transition-colors"
                  >
                    About Us
                  </button>
                </li>
                <li>
                  <button
                    onClick={() => setActiveModal("careers")}
                    className="hover:text-gold-400 transition-colors"
                  >
                    Careers
                  </button>
                </li>
                <li>
                  <button
                    onClick={() => setActiveModal("privacy")}
                    className="hover:text-gold-400 transition-colors"
                  >
                    Privacy Policy
                  </button>
                </li>
                <li>
                  <button
                    onClick={() => setActiveModal("terms")}
                    className="hover:text-gold-400 transition-colors"
                  >
                    Terms of Service
                  </button>
                </li>
                {/* 2026-08-23: PDPA/GDPR self-serve data-request page. End users
                    can exercise access / download / delete rights without
                    logging in. Issue #26. */}
                <li>
                  <a
                    href="https://app.mybijou.xyz/data-request"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="hover:text-gold-400 transition-colors"
                  >
                    Your Data Rights
                  </a>
                </li>
              </ul>
              <h4 className="font-bold text-white mb-4 mt-6">Contact</h4>
              <ul className="space-y-2 text-sm text-gray-400">
                <li>
                  <button
                    onClick={() => setActiveModal("enterprise")}
                    className="hover:text-gold-400 transition-colors"
                  >
                    Enterprise Inquiries
                  </button>
                </li>
                <li>
                  <button
                    onClick={() => setActiveModal("partnership")}
                    className="hover:text-gold-400 transition-colors"
                  >
                    Partnerships
                  </button>
                </li>
              </ul>
            </div>
          </div>

          <div className="border-t border-white/5 pt-8 text-center space-y-2">
            <p className="text-sm text-gray-600">
              &copy; {new Date().getFullYear()} Bijou AI. All rights reserved.
            </p>
            <p className="text-xs text-gray-700">
              Made with 🤍 by{" "}
              <a
                href="https://www.w3jdev.com"
                target="_blank"
                rel="noopener noreferrer"
                className="text-gold-400/60 hover:text-gold-400 transition-colors"
              >
                W3J LLC
              </a>{" "}
              •
              <a
                href="https://github.com/w3jdev"
                target="_blank"
                rel="noopener noreferrer"
                className="text-gold-400/60 hover:text-gold-400 transition-colors ml-1"
              >
                GitHub
              </a>
            </p>
          </div>
        </div>
      </footer>

      {/* Modals */}
      <AnimatePresence>
        {activeModal === "about" && (
          <InfoModal type="about" onClose={() => setActiveModal(null)} />
        )}
        {activeModal === "careers" && (
          <InfoModal type="careers" onClose={() => setActiveModal(null)} />
        )}
        {activeModal === "privacy" && (
          <InfoModal type="privacy" onClose={() => setActiveModal(null)} />
        )}
        {activeModal === "terms" && (
          <InfoModal type="terms" onClose={() => setActiveModal(null)} />
        )}
        {activeModal === "enterprise" && (
          <EnterpriseContactForm onClose={() => setActiveModal(null)} />
        )}
        {activeModal === "partnership" && (
          <PartnershipForm onClose={() => setActiveModal(null)} />
        )}
        {activeModal === "integration" && (
          <IntegrationForm onClose={() => setActiveModal(null)} />
        )}
      </AnimatePresence>
    </>
  );
};
