import { AnimatePresence, motion } from "framer-motion";
import {
    AlertCircle,
    ArrowRight,
    Building2,
    Calendar,
    Crown,
    ExternalLink,
    Mail,
    MessageSquare,
    Phone,
    RefreshCw,
    Shield,
    Sparkles,
    Users,
    X,
} from "lucide-react";
import React, { useEffect, useState } from "react";
import { track as trackPostHog, identifyUser } from "../services/posthog";

interface OnboardingModalProps {
  isOpen: boolean;
  onClose: () => void;
  mode: "signup" | "waitlist" | "demo";
  source?: string;
}

interface ErrorState {
  type: "validation" | "duplicate" | "server" | "network";
  title: string;
  message: string;
  solution: string;
  actionLabel: string;
  actionHandler: () => void;
  showSupport?: boolean;
}

export const OnboardingModal: React.FC<OnboardingModalProps> = ({
  isOpen,
  onClose,
  mode = "signup",
  source = "modal",
}) => {
  const [formData, setFormData] = useState({
    business_name: "",
    email: "",
    phone: "",
    industry: "",
    demo_time: "",
  });

  const [status, setStatus] = useState<
    "idle" | "loading" | "success" | "error"
  >("idle");
  const [errorState, setErrorState] = useState<ErrorState | null>(null);
  const [loadingProgress, setLoadingProgress] = useState(0);

  // Sophisticated loading progress animation
  useEffect(() => {
    if (status === "loading") {
      setLoadingProgress(0);
      const interval = setInterval(() => {
        setLoadingProgress((prev) => {
          if (prev >= 90) return prev; // Stay at 90% until actual completion
          return prev + Math.random() * 15;
        });
      }, 200);
      return () => clearInterval(interval);
    }
    return; // explicit void when not loading, so useEffect return type is consistent
  }, [status]);

  const validatePhone = (phone: string): string => {
    if (!phone) return "";

    // Strip all non-digits
    let cleaned = phone.replace(/\D/g, "");

    // If starts with 0, replace with 60 (Malaysian format)
    if (cleaned.startsWith("0")) {
      cleaned = "60" + cleaned.substring(1);
    }

    return cleaned;
  };

  const createErrorState = (apiError: any): ErrorState => {
    // 2026-08-22 FIX: api/leads.js and api/demo.js return {error, message,
    // code}, never {detail, message: "...already registered..."} — so
    // errorMessage below was always "Unknown error" or a generic sentence,
    // and EVERY branch past this point (duplicate/validation/server/network)
    // was unreachable dead code; every real failure fell through to the
    // generic "Something Unexpected Happened" fallback regardless of cause.
    // `code` is exact and always present — check it first.
    const errorMessage: string =
      apiError.detail || apiError.error || apiError.message || "Unknown error";
    const code: string | undefined = apiError.code;

    // Handle duplicate email scenario
    if (
      code === "DUPLICATE_EMAIL" ||
      errorMessage.includes("already registered") ||
      errorMessage.includes("duplicate")
    ) {
      const email = formData.email;
      return {
        type: "duplicate",
        title: "Already Part of the Family! 🎉",
        message: `Great news! ${email} is already registered with Bijou AI.`,
        solution: "You can access your account or request a password reset.",
        actionLabel: "Access My Account",
        actionHandler: () => {
          window.open(
            `https://wa.me/60174106981?text=Hi! I need help accessing my Bijou AI account for ${email}`,
            "_blank",
          );
        },
        showSupport: true,
      };
    }

    // Handle validation errors
    if (
      code === "MISSING_EMAIL" ||
      code === "INVALID_EMAIL" ||
      code === "MISSING_NAME" ||
      code === "MISSING_DEMO_TIME" ||
      errorMessage.includes("invalid") ||
      errorMessage.includes("required")
    ) {
      return {
        type: "validation",
        title: "Form Incomplete",
        message: "Please check your information and try again.",
        solution: errorMessage,
        actionLabel: "Fix & Retry",
        actionHandler: () => {
          setStatus("idle");
          setErrorState(null);
        },
      };
    }

    // Handle server errors
    if (
      code === "INTERNAL_ERROR" ||
      code === "RATE_LIMITED" ||
      errorMessage.includes("server") ||
      errorMessage.includes("500")
    ) {
      return {
        type: "server",
        title: "Server Hiccup",
        message:
          "Our servers are experiencing high demand (good problem to have!).",
        solution:
          "Please try again in a moment, or WhatsApp us for immediate assistance.",
        actionLabel: "Try Again",
        actionHandler: () => {
          setStatus("idle");
          setErrorState(null);
        },
        showSupport: true,
      };
    }

    // Handle network errors
    if (
      !navigator.onLine ||
      errorMessage.includes("network") ||
      errorMessage.includes("fetch")
    ) {
      return {
        type: "network",
        title: "Connection Issue",
        message: "Looks like your internet connection is unstable.",
        solution:
          "Check your connection and try again, or save our WhatsApp for later.",
        actionLabel: "Retry",
        actionHandler: () => {
          setStatus("idle");
          setErrorState(null);
        },
        showSupport: true,
      };
    }

    // Generic error fallback
    return {
      type: "server",
      title: "Something Unexpected Happened",
      message:
        "Don't worry, this happens sometimes with high-traffic websites.",
      solution: "Our team has been notified. Try again or contact us directly.",
      actionLabel: "Try Again",
      actionHandler: () => {
        setStatus("idle");
        setErrorState(null);
      },
      showSupport: true,
    };
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setStatus("loading");
    setErrorState(null);
    setLoadingProgress(0);

    // Client-side validation with better UX
    if (
      !formData.business_name.trim() ||
      formData.business_name.trim().length < 2
    ) {
      setErrorState({
        type: "validation",
        title: "Business Name Required",
        message: "We need to know what to call your business!",
        solution: "Enter your business name (minimum 2 characters)",
        actionLabel: "Got It",
        actionHandler: () => {
          setStatus("idle");
          setErrorState(null);
          // Focus the business name field
          setTimeout(() => {
            document
              .querySelector<HTMLInputElement>(
                'input[placeholder*="Business name"]',
              )
              ?.focus();
          }, 100);
        },
      });
      setStatus("error");
      return;
    }

    if (
      !formData.email.trim() ||
      !formData.email.includes("@") ||
      !formData.email.includes(".")
    ) {
      setErrorState({
        type: "validation",
        title: "Valid Email Required",
        message:
          "We need your email to send you important updates and access details.",
        solution: "Enter a valid email address (e.g., you@company.com)",
        actionLabel: "Fix Email",
        actionHandler: () => {
          setStatus("idle");
          setErrorState(null);
          setTimeout(() => {
            document
              .querySelector<HTMLInputElement>('input[type="email"]')
              ?.focus();
          }, 100);
        },
      });
      setStatus("error");
      return;
    }

    if (formData.phone && formData.phone.trim()) {
      const cleanedPhone = validatePhone(formData.phone);
      if (cleanedPhone.length < 10) {
        setErrorState({
          type: "validation",
          title: "WhatsApp Number Format",
          message:
            "We need a valid Malaysian WhatsApp number to send you updates.",
          solution:
            "Enter your WhatsApp number (e.g., 0123456789 or 60123456789)",
          actionLabel: "Fix Number",
          actionHandler: () => {
            setStatus("idle");
            setErrorState(null);
            setTimeout(() => {
              document
                .querySelector<HTMLInputElement>('input[type="tel"]')
                ?.focus();
            }, 100);
          },
        });
        setStatus("error");
        return;
      }
      formData.phone = cleanedPhone;
    }

    try {
      if (mode === "demo") {
        // Demo booking flow
        if (!formData.demo_time.trim()) {
          setErrorState({
            type: "validation",
            title: "Demo Time Required",
            message: "When would you like your personalized demo?",
            solution:
              'Enter your preferred time (e.g., "Monday 3pm" or "This Friday morning")',
            actionLabel: "Add Time",
            actionHandler: () => {
              setStatus("idle");
              setErrorState(null);
              setTimeout(() => {
                document
                  .querySelector<HTMLInputElement>(
                    'input[placeholder*="demo time"]',
                  )
                  ?.focus();
              }, 100);
            },
          });
          setStatus("error");
          return;
        }

        const demoPayload = {
          business_name: formData.business_name.trim(),
          email: formData.email.toLowerCase().trim(),
          phone: formData.phone || "",
          industry: formData.industry || "",
        };

        // Simulate progress for better UX
        setTimeout(() => setLoadingProgress(60), 500);

        // First register in onboarding system
        const response = await fetch("/api/leads", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            ...demoPayload,
            name: demoPayload.business_name,
            // 2026-08-22 FIX: was hardcoded "website", so every demo booking
            // (App.tsx opens this modal with source="demo_chat") was
            // misattributed to "website" in Supabase/PostHog, breaking
            // funnel analytics for that CTA. Mirror the signup/waitlist
            // branch below, which already does this correctly.
            source: source || "website",
          }),
        });

        const result = await response.json();
        setLoadingProgress(80);

        if (!response.ok) {
          trackPostHog("lead_capture_form_failed", { source, mode, status: response.status });
          const errorState = createErrorState(result);
          setErrorState(errorState);
          setStatus("error");
          return;
        }

        // 2026-08-22 FIX: response.ok is true even for a duplicate email
        // (api/leads.js still saves nothing new but returns 200) — check the
        // isNewLead signal so a returning prospect sees the dedicated
        // "Already Part of the Family" UI instead of the generic success
        // screen implying a fresh signup just happened.
        if (result.isNewLead === false) {
          trackPostHog("lead_capture_duplicate", { source, mode });
          setErrorState(createErrorState(result));
          setStatus("error");
          return;
        }

        // SECURITY (2026-07-20): Demo flow used to call the public /api/send
        // (open proxy) for WhatsApp notification. Now we pass demo_time
        // through a single new /api/demo endpoint that handles both the
        // lead save AND the owner notify server-to-server. The lead saved
        // above doesn't include demo_time; /api/demo will record it.
        try {
          await fetch("/api/demo", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              lead_id: result.leadId,
              business_name: formData.business_name,
              email: formData.email,
              phone: formData.phone,
              industry: formData.industry,
              demo_time: formData.demo_time,
              source,
            }),
          });
        } catch (notifError) {
          console.warn("Demo notification failed:", notifError);
          // Don't fail the flow if notification fails
        }

        // PostHog: identify the user + mark demo completed
        identifyUser(formData.email.toLowerCase().trim(), {
          email: formData.email.toLowerCase().trim(),
          name: formData.business_name,
          industry: formData.industry || undefined,
          source,
          created_at: new Date().toISOString(),
        });
        trackPostHog("signup_modal_completed", { source, mode, industry: formData.industry || undefined });

        setLoadingProgress(100);
        setStatus("success");
      } else {
        // Regular signup/waitlist flow
        const signupPayload = {
          business_name: formData.business_name.trim(),
          email: formData.email.toLowerCase().trim(),
          phone: formData.phone || "",
          industry: formData.industry || "",
        };

        setTimeout(() => setLoadingProgress(60), 500);

        const response = await fetch("/api/leads", {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
          },
          body: JSON.stringify({
            ...signupPayload,
            name: signupPayload.business_name,
            source: source || "website",
          }),
        });

        const result = await response.json();
        setLoadingProgress(80);

        if (!response.ok) {
          trackPostHog("lead_capture_form_failed", { source, mode, status: response.status });
          const errorState = createErrorState(result);
          setErrorState(errorState);
          setStatus("error");
          return;
        }

        // 2026-08-22 FIX: see identical duplicate-check comment in the demo
        // branch above — same signal, same reason.
        if (result.isNewLead === false) {
          trackPostHog("lead_capture_duplicate", { source, mode });
          setErrorState(createErrorState(result));
          setStatus("error");
          return;
        }

        // PostHog: identify the user + mark signup completed
        identifyUser(formData.email.toLowerCase().trim(), {
          email: formData.email.toLowerCase().trim(),
          name: formData.business_name,
          industry: formData.industry || undefined,
          source,
          created_at: new Date().toISOString(),
        });
        trackPostHog("signup_modal_completed", { source, mode, industry: formData.industry || undefined });

        setLoadingProgress(100);
        // Always show success — onboarding link is sent by email
        setStatus("success");
      }

      // Reset form after delay (except for signup which redirects)
      setTimeout(
        () => {
          if (mode === "waitlist" || mode === "demo") {
            setFormData({
              business_name: "",
              email: "",
              phone: "",
              industry: "",
              demo_time: "",
            });
            setStatus("idle");
            setLoadingProgress(0);
          }
        },
        mode === "waitlist" ? 4000 : 6000,
      );
    } catch (error: any) {
      console.error("Form submission error:", error);
      const errorState = createErrorState(error);
      setErrorState(errorState);
      setStatus("error");
    }
  };

  const handleInputChange = (field: string, value: string) => {
    setFormData((prev) => ({ ...prev, [field]: value }));
    if (status === "error") {
      setStatus("idle");
      setErrorState(null);
    }
  };

  const getModalTitle = () => {
    switch (mode) {
      case "waitlist":
        return "Join the VIP List";
      case "demo":
        return "Book Your Personal Demo";
      default:
        return "Start Your Free Trial";
    }
  };

  const getModalSubtitle = () => {
    switch (mode) {
      case "waitlist":
        return "Be first to access exclusive Malaysian SME features + insider tips";
      case "demo":
        return "15-minute personalized demo + free business automation analysis";
      default:
        return "30-day money-back • No credit card • Cancel anytime • Set up in 5 minutes";
    }
  };

  const getSuccessContent = () => {
    switch (mode) {
      case "waitlist":
        return {
          icon: "🎉",
          title: "You're on the VIP list!",
          message:
            "We'll WhatsApp you first when new features drop, plus exclusive Malaysian SME automation tips.",
          subMessage: "Expect your first insider tip within 24 hours!",
        };
      case "demo":
        return {
          icon: "✅",
          title: "Demo booked successfully!",
          message:
            "We'll WhatsApp you within 2 hours to confirm your preferred time slot.",
          subMessage:
            "Get ready to see how Bijou handles real customer inquiries in Manglish!",
        };
      default:
        return {
          icon: "🚀",
          title: "We got your details, boss!",
          message:
            "Check your email — we've sent a confirmation with your onboarding link to get started.",
          subMessage: "Ready to jump in now? Go to app.mybijou.xyz/signup",
        };
    }
  };

  if (!isOpen) return null;

  return (
    <AnimatePresence>
      <motion.div
        initial={{ opacity: 0 }}
        animate={{ opacity: 1 }}
        exit={{ opacity: 0 }}
        className="fixed inset-0 bg-black/80 backdrop-blur-sm z-50 flex items-center justify-center p-4"
        onClick={onClose}
      >
        <motion.div
          initial={{ opacity: 0, scale: 0.9, y: 20 }}
          animate={{ opacity: 1, scale: 1, y: 0 }}
          exit={{ opacity: 0, scale: 0.9, y: 20 }}
          transition={{ type: "spring", stiffness: 300, damping: 25 }}
          className="glass-panel-3d bg-dark-900/95 border border-white/10 rounded-3xl overflow-hidden shadow-[0_0_50px_rgba(0,0,0,0.5)] relative max-w-md w-full max-h-[90vh] overflow-y-auto"
          onClick={(e) => e.stopPropagation()}
        >
          {/* Close button */}
          <button
            onClick={onClose}
            className="absolute top-6 right-6 w-10 h-10 rounded-full glass-panel flex items-center justify-center hover:bg-white/10 transition-colors z-10"
          >
            <X className="w-5 h-5 text-gray-400" />
          </button>

          <div className="p-8">
            <div className="text-center mb-8">
              <motion.div
                initial={{ scale: 0 }}
                animate={{ scale: 1 }}
                transition={{ delay: 0.2, type: "spring" }}
                className="w-16 h-16 mx-auto mb-4 rounded-full bg-gradient-to-r from-emerald-500 to-emerald-400 flex items-center justify-center"
              >
                {mode === "demo" ? (
                  <Calendar className="w-8 h-8 text-dark-900" />
                ) : mode === "waitlist" ? (
                  <Crown className="w-8 h-8 text-dark-900" />
                ) : (
                  <Sparkles className="w-8 h-8 text-dark-900" />
                )}
              </motion.div>
              <h3 className="text-2xl font-display font-bold mb-2">
                {getModalTitle()}
              </h3>
              <p className="text-gray-300 text-sm leading-relaxed">
                {getModalSubtitle()}
              </p>
            </div>

            <AnimatePresence mode="wait">
              {status === "loading" && (
                <motion.div
                  key="loading"
                  initial={{ opacity: 0, y: -10 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -10 }}
                  className="flex flex-col items-center gap-4 p-6 rounded-xl glass-panel-3d border-emerald-500/30 bg-emerald-500/10 mb-6"
                >
                  <div className="relative w-12 h-12">
                    <div className="absolute inset-0 border-4 border-emerald-500/20 rounded-full"></div>
                    <div className="absolute inset-0 border-4 border-emerald-500 rounded-full border-t-transparent animate-spin"></div>
                  </div>
                  <div className="text-center">
                    <p className="text-emerald-400 font-semibold">
                      Setting up your account...
                    </p>
                    <div className="w-48 h-2 bg-gray-700 rounded-full mt-3 overflow-hidden">
                      <motion.div
                        className="h-full bg-gradient-to-r from-emerald-500 to-emerald-400 rounded-full"
                        initial={{ width: 0 }}
                        animate={{ width: `${loadingProgress}%` }}
                        transition={{ duration: 0.3 }}
                      />
                    </div>
                    <p className="text-emerald-300 text-xs mt-2">
                      Almost there... {Math.round(loadingProgress)}%
                    </p>
                  </div>
                </motion.div>
              )}

              {status === "success" && (
                <motion.div
                  key="success"
                  initial={{ opacity: 0, scale: 0.9 }}
                  animate={{ opacity: 1, scale: 1 }}
                  exit={{ opacity: 0, scale: 0.9 }}
                  className="flex flex-col items-center gap-4 p-6 rounded-xl glass-panel-3d border-emerald-500/30 bg-emerald-500/10 mb-6"
                >
                  <motion.div
                    initial={{ scale: 0 }}
                    animate={{ scale: 1 }}
                    transition={{ delay: 0.2, type: "spring", stiffness: 200 }}
                    className="text-6xl"
                  >
                    {getSuccessContent().icon}
                  </motion.div>
                  <div className="text-center">
                    <p className="text-emerald-400 font-semibold text-lg">
                      {getSuccessContent().title}
                    </p>
                    <p className="text-emerald-300 text-sm mt-2 leading-relaxed">
                      {getSuccessContent().message}
                    </p>
                    {getSuccessContent().subMessage && (
                      <p className="text-emerald-200 text-xs mt-3 italic">
                        {getSuccessContent().subMessage}
                      </p>
                    )}
                    {mode === "signup" && (
                      <a
                        // 2026-08-22 FIX: this used to be a bare link, so the
                        // business name/email/phone/industry the prospect
                        // just typed here were thrown away and they had to
                        // retype them on the next form — the modal promises
                        // "Set up in 5 minutes" but delivered a second,
                        // unrelated form. Pass them through as query params;
                        // signup.html reads and prefills the matching fields.
                        href={`https://app.mybijou.xyz/signup?${new URLSearchParams(
                          {
                            business_name: formData.business_name,
                            email: formData.email,
                            ...(formData.phone ? { phone: formData.phone } : {}),
                            ...(formData.industry
                              ? { industry: formData.industry }
                              : {}),
                          },
                        ).toString()}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="mt-4 inline-flex items-center gap-2 px-5 py-2.5 bg-emerald-500 hover:bg-emerald-400 text-dark-900 font-bold text-sm rounded-xl transition-all"
                      >
                        Create Account Now
                        <ExternalLink className="w-4 h-4" />
                      </a>
                    )}
                  </div>
                </motion.div>
              )}

              {status === "error" && errorState && (
                <motion.div
                  key="error"
                  initial={{ opacity: 0, x: -20 }}
                  animate={{ opacity: 1, x: 0 }}
                  exit={{ opacity: 0, x: -20 }}
                  className="p-6 rounded-xl glass-panel-3d border-red-500/30 bg-red-500/10 mb-6"
                >
                  <div className="flex items-start gap-4">
                    <div className="w-12 h-12 bg-red-500/20 rounded-full flex items-center justify-center flex-shrink-0">
                      <AlertCircle className="w-6 h-6 text-red-400" />
                    </div>
                    <div className="flex-1">
                      <h4 className="text-red-400 font-semibold text-lg mb-1">
                        {errorState.title}
                      </h4>
                      <p className="text-red-300 text-sm mb-2">
                        {errorState.message}
                      </p>
                      <p className="text-red-200 text-xs mb-4 italic">
                        {errorState.solution}
                      </p>

                      <div className="flex flex-col gap-2">
                        <button
                          onClick={errorState.actionHandler}
                          className="flex items-center gap-2 px-4 py-2 bg-red-500 text-white rounded-lg hover:bg-red-400 transition-colors text-sm font-medium"
                        >
                          <RefreshCw className="w-4 h-4" />
                          {errorState.actionLabel}
                        </button>

                        {errorState.showSupport && (
                          <a
                            href="https://wa.me/60174106981?text=Hi! I need help with my Bijou AI signup. I'm getting an error."
                            target="_blank"
                            rel="noopener noreferrer"
                            className="flex items-center gap-2 px-4 py-2 bg-gray-700 text-gray-300 rounded-lg hover:bg-gray-600 transition-colors text-sm"
                          >
                            <MessageSquare className="w-4 h-4" />
                            WhatsApp Support
                            <ExternalLink className="w-3 h-3" />
                          </a>
                        )}
                      </div>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>

            {status !== "success" && status !== "loading" && (
              <motion.form
                onSubmit={handleSubmit}
                className="space-y-4"
                initial={{ opacity: 0.7 }}
                animate={{ opacity: status === "error" ? 0.7 : 1 }}
                transition={{ duration: 0.2 }}
              >
                <div className="relative">
                  <Building2 className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type="text"
                    placeholder="Business name *"
                    value={formData.business_name}
                    onChange={(e) =>
                      handleInputChange("business_name", e.target.value)
                    }
                    className="w-full pl-12 pr-4 py-4 rounded-xl glass-panel-3d border border-white/10 focus:border-emerald-500/50 focus:outline-none text-white placeholder-gray-400 transition-all"
                    required
                  />
                </div>

                <div className="relative">
                  <Mail className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type="email"
                    placeholder="Email address *"
                    value={formData.email}
                    onChange={(e) => handleInputChange("email", e.target.value)}
                    className="w-full pl-12 pr-4 py-4 rounded-xl glass-panel-3d border border-white/10 focus:border-emerald-500/50 focus:outline-none text-white placeholder-gray-400 transition-all"
                    required
                  />
                </div>

                <div className="relative">
                  <Phone className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                  <input
                    type="tel"
                    placeholder="WhatsApp number (optional)"
                    value={formData.phone}
                    onChange={(e) => handleInputChange("phone", e.target.value)}
                    className="w-full pl-12 pr-4 py-4 rounded-xl glass-panel-3d border border-white/10 focus:border-emerald-500/50 focus:outline-none text-white placeholder-gray-400 transition-all"
                  />
                </div>

                <select
                  value={formData.industry}
                  onChange={(e) =>
                    handleInputChange("industry", e.target.value)
                  }
                  className="w-full px-4 py-4 rounded-xl glass-panel-3d border border-white/10 focus:border-emerald-500/50 focus:outline-none text-white bg-transparent transition-all appearance-none cursor-pointer"
                >
                  <option value="" disabled className="bg-gray-900">
                    Industry (optional)
                  </option>
                  <option value="real_estate" className="bg-gray-900">
                    Real Estate / Property
                  </option>
                  <option value="healthcare" className="bg-gray-900">
                    Healthcare / Dental / Clinic
                  </option>
                  <option value="fnb" className="bg-gray-900">
                    F&amp;B / Restaurant / Cafe
                  </option>
                  <option value="retail" className="bg-gray-900">
                    Retail / E-commerce
                  </option>
                  <option value="education" className="bg-gray-900">
                    Education / Tuition
                  </option>
                  <option value="beauty" className="bg-gray-900">
                    Beauty / Wellness / Spa
                  </option>
                  <option value="automotive" className="bg-gray-900">
                    Automotive
                  </option>
                  <option value="professional_services" className="bg-gray-900">
                    Professional Services / Legal / Accounting
                  </option>
                  <option value="logistics" className="bg-gray-900">
                    Logistics / Courier
                  </option>
                  <option value="other" className="bg-gray-900">
                    Other
                  </option>
                </select>

                {mode === "demo" && (
                  <div className="relative">
                    <Calendar className="absolute left-3 top-1/2 transform -translate-y-1/2 w-5 h-5 text-gray-400" />
                    <input
                      type="text"
                      placeholder="Preferred demo time * (e.g. Monday 3pm)"
                      value={formData.demo_time}
                      onChange={(e) =>
                        handleInputChange("demo_time", e.target.value)
                      }
                      className="w-full pl-12 pr-4 py-4 rounded-xl glass-panel-3d border border-white/10 focus:border-emerald-500/50 focus:outline-none text-white placeholder-gray-400 transition-all"
                      required
                    />
                  </div>
                )}

                {/* Submit button. Note: form is only rendered when status is
                    "error" | "idle" (see parent guard at line 652), so the
                    "loading" branch below is unreachable — collapsed to the
                    non-loading className + label. */}
                <motion.button
                  type="submit"
                  disabled={false}
                  whileHover={{ scale: 1.02 }}
                  whileTap={{ scale: 0.98 }}
                  className="w-full flex items-center justify-center gap-3 py-4 px-8 rounded-xl font-bold transition-all bg-gradient-to-r from-emerald-500 to-emerald-400 text-dark-900 shadow-[0_0_30px_rgba(16,185,129,0.4)] hover:shadow-[0_0_50px_rgba(16,185,129,0.6)]"
                >
                  {mode === "demo"
                    ? "Book My Demo"
                    : mode === "waitlist"
                      ? "Join VIP List"
                      : "Start Free Trial"}
                  <ArrowRight className="w-5 h-5" />
                </motion.button>

                {/* Trust signals */}
                <div className="flex items-center justify-center gap-4 pt-2 text-xs text-gray-400">
                  <div className="flex items-center gap-1">
                    <Shield className="w-3 h-3" />
                    <span>PDPA Compliant</span>
                  </div>
                  <div className="flex items-center gap-1">
                    <Users className="w-3 h-3" />
                    <span>500+ Malaysian SMEs</span>
                  </div>
                </div>

                <div className="mt-6 pt-4 border-t border-white/10 text-center">
                  <p className="text-sm text-gray-400 mb-3">
                    Questions? Our Malaysian team is standing by
                  </p>
                  <a
                    href="https://wa.me/60174106981?text=Hi! I'm interested in Bijou AI. Can we chat about how it can help my business?"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-2 text-emerald-400 hover:text-emerald-300 transition-colors font-medium"
                  >
                    <MessageSquare className="w-4 h-4" />
                    WhatsApp us instantly
                  </a>
                </div>
              </motion.form>
            )}
          </div>
        </motion.div>
      </motion.div>
    </AnimatePresence>
  );
};
