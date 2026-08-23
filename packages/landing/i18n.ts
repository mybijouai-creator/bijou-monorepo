import i18n from "i18next";
import LanguageDetector from "i18next-browser-languagedetector";
import { initReactI18next } from "react-i18next";

// Translation resources
const resources = {
  en: {
    translation: {
      // Navbar

      // Hero Section
      "hero.badge": "🚀 RM0 to start — no credit card, no WABA needed",
      "hero.title.part1": "Your WhatsApp goes",
      "hero.title.savingsAmount": "offline at 10pm.",
      "hero.title.part2": "Your competitors'",
      "hero.title.priceAmount": "doesn't.",
      "hero.subtitle.part1":
        "Bijou is a Malaysian AI for WhatsApp & Telegram. Replies instantly in Manglish, books Cal.com appointments, qualifies leads automatically —",
      "hero.subtitle.roi": "while you sleep.",
      "hero.subtitle.part2": "",
      "hero.cta.trial": "Start Free — RM0",
      "hero.cta.demo": "Book Demo",
      "hero.trustFooter":
        "✅ 30-day money-back · ✅ No WABA needed · ✅ Cancel anytime",
      "hero.trust.pdpa": "PDPA Compliant",
      "hero.chatDemo.assistant": "Bijou Assistant",
      "hero.chatDemo.status": "Active • 02:45 AM",
      "hero.chatDemo.msg1":
        "Boss, can check property viewing? 2am liao but I excited.",
      "hero.chatDemo.msg2":
        "No prob boss! I still awake. Which area you looking? KLCC or Mont Kiara? 🏙️",
      "hero.chatDemo.msg3": "MK. Got balcony one.",
      "hero.chatDemo.msg4":
        "Got! Residensi 22, High Floor. I send you video brochure now. 📹",
      "hero.roiCard.title": "Monthly Savings",
      "hero.roiCard.amount": "RM2,700+",
      "hero.roiCard.comparison": "vs part-time WhatsApp staff (PayScale)",
      "hero.roiCard.roi": "~900% ROI",

      // Pricing Section — Single PRO Tier (RM 299/month, updated 2026-07-30 per pricing-drift-2026-07-30.md)
      "pricing.badge": "💎 Honest, Simple Pricing",
      "pricing.title": "One Plan. Everything That's Live.",
      "pricing.subtitle.part1": "Backed by a",
      "pricing.subtitle.trial": "30-day money-back guarantee",
      "pricing.subtitle.part2": ". No contract. Cancel anytime.",

      // PRO Plan — Single Tier
      "pricing.pro.name": "PRO",
      "pricing.pro.price": "299",
      "pricing.pro.yearlyPrice": "2,990",
      "pricing.pro.yearlySaving": "Save RM598 — 2 months free",
      "pricing.pro.description": "Everything you need to never miss a lead",
      "pricing.pro.badge": "THE ONLY PLAN",
      "pricing.pro.features.0": "WhatsApp AI Agent — no WABA, no Meta fees",
      "pricing.pro.features.1": "Telegram AI Agent — same brain, same Manglish",
      "pricing.pro.features.2": "3,000 Conversations/month (~100/day)",
      "pricing.pro.features.3": "Full TRACE AI — 4-agent empathy pipeline",
      "pricing.pro.features.4": "Manglish + EN / BM / Mandarin / Tamil",
      "pricing.pro.features.5":
        "Cal.com Booking — create, check, cancel appointments",
      "pricing.pro.features.6": "Auto email confirmations to customers",
      "pricing.pro.features.7":
        "Lead Qualification — Hot / Warm / Cold auto-detection",
      "pricing.pro.features.8":
        "Escalation alerts — email you when AI can't handle it",
      "pricing.pro.features.9": "Knowledge Base — 200 documents (FAQs included)",
      "pricing.pro.earlyAccessNote":
        "Pro customers get early access FREE when new features ship — multi-user seats, extra channels, SMS reminders & more.",

      // 2026-08-23: Competitor comparison (English copy on all 4 locales
      // for speed; localize the brand-sensitive parts in a follow-up).
      "pricing.compare.badge": "Bijou vs the alternatives",
      "pricing.compare.title": "How Bijou stacks up",
      "pricing.compare.subtitle":
        "Same job, different trade-offs. Verified 2026-08 against each competitor's public pricing page.",

      // Add-ons Roadmap
      "pricing.addons.title": "Coming Q2–Q4 2026 (Paid Add-ons)",
      "pricing.addons.subtitle":
        "Every feature that ships = a revenue event. Pro customers get early access free.",

      // CTA + Enterprise footnote
      "pricing.cta.trial": "Start 30-Day Trial",
      "pricing.cta.enterprise": "Contact us →",
      "pricing.cta.enterprisePrompt":
        "Need multi-team, multi-number, or a custom setup?",

      // Guarantee
      "pricing.guarantee.title": "30-Day Money-Back Guarantee",
      "pricing.guarantee.subtitle":
        "If Bijou doesn't deliver in 30 days, get 100% refunded — no questions asked",

      // LEGACY KEYS — kept for rollback reference, no longer rendered

      // Case Studies Section
      "cases.title": "Pilot Examples",
      "cases.subtitle": "Sample outcomes we're targeting with early pilots. Real case studies ship after our first 10 customers.",

      // Real Estate Case Study
      "cases.realEstate.company": "Property Agency (Pilot Example)",
      "cases.realEstate.industry": "Real Estate Agency",
      "cases.realEstate.stat1.value": "0%",
      "cases.realEstate.stat1.label": "Missed Calls",
      "cases.realEstate.stat2.value": "+40%",
      "cases.realEstate.stat2.label": "Leads Qualified",
      "cases.realEstate.quote":
        "Before Bijou, we lost leads every time we were in a viewing. Now, Bijou answers instantly, sends the brochure, and books the next viewing. It's like having a super-agent.",
      "cases.realEstate.cta": "Read Full Case Study",

      // Healthcare Case Study
      "cases.healthcare.company": "Dental Clinic (Pilot Example)",
      "cases.healthcare.industry": "Dental Specialist",
      "cases.healthcare.stat1.value": "-75%",
      "cases.healthcare.stat1.label": "No-Show Rate",
      "cases.healthcare.stat2.value": "24/7",
      "cases.healthcare.stat2.label": "Booking Availability",
      "cases.healthcare.quote":
        "Our nurses used to spend hours calling patients to confirm slots. Bijou does it automatically on WhatsApp. Patients love it, and our chairs are always full.",
      "cases.healthcare.cta": "Read Full Case Study",

      // Contact Forms
      "contact.enterprise.title": "Enterprise Inquiries",
      "contact.enterprise.subtitle":
        "Let's discuss how Bijou AI can transform your business",
      "contact.partnership.title": "Partnership Opportunities",
      "contact.partnership.subtitle":
        "Collaborate with us to bring AI to more businesses",
      "contact.integration.title": "Integration Requests",
      "contact.integration.subtitle": "Tell us what integrations you need",

      "form.name": "Full Name",
      "form.email": "Email Address",
      "form.company": "Company Name",
      "form.phone": "Phone Number",
      "form.message": "Message",
      "form.submit": "Submit",
      "form.sending": "Sending...",
      "form.success": "Thank you! We'll be in touch within 24 hours.",
      "form.error": "Something went wrong. Please email us directly at",

      // Footer

      // Features Section
      "features.badge": "What You Actually Get",
      "features.title.part1": "Every Feature,",
      "features.title.highlight": "Clearly Explained",
      "features.subtitle":
        "No buzzwords. No vague icons. Click any feature below to see exactly what it does and how it works.",
      "features.live": "All features are live and working today",
      "features.noBeta": "No beta. No waitlist. No asterisk.",
      "features.stats.features": "Live Features",
      "features.stats.features.sub": "all working today",
      "features.stats.setup": "Setup Time",
      "features.stats.setup.sub": "self-serve, no dev",
      "features.stats.convos": "Conversations/mo",
      "features.stats.convos.sub": "~100 per day",
      "features.stats.langs": "Languages Supported",
      "features.stats.langs.sub": "EN · BM · 中文 · தமிழ்",
      "features.badge.live": "Live Now",
      "features.badge.unique": "Unique to Bijou",
      "features.badge.enterprise": "Enterprise-Grade",
      "features.wa.title": "WhatsApp AI Agent",
      "features.wa.subtitle": "No WABA. No Meta fees. No markups.",
      "features.wa.desc":
        "Connect your existing WhatsApp number in minutes via QR scan. No Facebook Business Manager, no WABA application, no RM0.05/message Meta fees. Bijou handles inbound queries flat at RM299/mo.",
      "features.wa.b1": "Scan QR → live in 15 min",
      "features.wa.b2": "No per-conversation charges",
      "features.wa.b3": "No Meta markup ever",
      "features.tg.title": "Telegram AI Agent",
      "features.tg.subtitle": "Same brain. Second channel. Included free.",
      "features.tg.desc":
        "The same AI, knowledge base and Manglish personality runs simultaneously on Telegram at no extra cost. Reach customers on whichever app they prefer.",
      "features.tg.b1": "Included in Pro — no extra fee",
      "features.tg.b2": "Same TRACE engine and knowledge base",
      "features.tg.b3": "Independent channel, unified setup",
      "features.trace.badge": "Production · v300 · Live on bijou-production.fly.dev",
      "features.trace.title": "Gemini 2.5 Flash with smart context. Plus automatic handover when AI hits its limit.",
      "features.trace.subtitle": "Fast LLM. Smart escalation. No fake pipeline.",
      "features.trace.desc":
        "Every message goes through Gemini 2.5 Flash with per-tenant context, your knowledge base, and Manglish tone. If the conversation gets too complex or emotionally charged, the handover system flags it and a human takes over. No fake pipeline — just a fast LLM and a smart escalation layer that actually works.",
      "features.trace.b1": "Detects frustration before it escalates",
      "features.trace.b2": "Understands context, not just keywords",
      "features.trace.b3": "Answers only from your data — no hallucination",
      "features.manglish.title": "Manglish Engine",
      "features.manglish.subtitle": "Can lah. Got or not? Sorted.",
      "features.manglish.desc":
        "20+ regex patterns handle Malaysian code-switching natively — BM, English, Mandarin, Tamil and Manglish blended naturally. Adjust tone from full corporate to full pasar malam.",
      "features.manglish.b1": "English, Malay, Mandarin, Tamil",
      "features.manglish.b2": "Tone slider: formal to full Manglish",
      "features.manglish.b3": "No robotic 'Certainly, I can assist you'",
      "features.cal.title": "Cal.com Booking",
      "features.cal.subtitle": "Book, check, cancel — all via WhatsApp chat.",
      "features.cal.desc":
        "Full two-way calendar integration via Cal.com. Customers book appointments, check availability and cancel — entirely through a WhatsApp or Telegram conversation. No links, no forms.",
      "features.cal.b1": "Book, check & cancel via chat",
      "features.cal.b2": "Automated email confirmation sent to customer",
      "features.cal.b3": "Zero dev work needed",
      "features.escalation.title": "Smart Escalation Alerts",
      "features.escalation.subtitle":
        "You are emailed before the customer rage-quits.",
      "features.escalation.desc":
        "Bijou detects frustration signals, 3+ unanswered questions and explicit human requests — then instantly emails you the full conversation thread. Never miss a hot lead or angry customer.",
      "features.escalation.b1": "Frustration detection built-in",
      "features.escalation.b2": "Full conversation context in alert email",
      "features.escalation.b3": "Custom domain email (Growth plan)",
      "features.kb.title": "Knowledge Base",
      "features.kb.subtitle": "Your FAQs. Your voice. Zero hallucination.",
      "features.kb.desc":
        "Upload up to 200 documents. Bijou answers only from what you have taught it — no making things up. Update an FAQ and the AI knows instantly, no retraining required.",
      "features.kb.b1": "200 documents (Pro)",
      "features.kb.b2": "Instant updates — no retraining",
      "features.kb.b3": "AI stays in-lane, never guesses",
      "features.leads.title": "Lead Qualification",
      "features.leads.subtitle": "Hot, warm, cold — tagged automatically.",
      "features.leads.desc":
        "Bijou probes for budget, timeline and intent naturally in conversation. Every lead is tagged automatically so you know exactly who to call back first.",
      "features.leads.b1": "Budget + timeline detection",
      "features.leads.b2": "Hot / warm / cold tagging",
      "features.leads.b3": "Included in escalation alert summary",
      "features.security.title": "PDPA-Ready Security",
      "features.security.subtitle": "Your data. Fully isolated. Always.",
      "features.security.desc":
        "Row-Level Security means your customer data is 100% isolated from every other Bijou tenant. AES-256 encryption at rest. PDPA and GDPR compliant. Hosted on Fly.io Singapore region.",
      "features.security.b1": "Row-level multi-tenant data isolation",
      "features.security.b2": "AES-256 + PDPA + GDPR ready",
      "features.security.b3": "99.9% uptime — Singapore region",

      // Comparison Table
      "comparison.badge": "Honest Comparison",
      "comparison.title.part1": "How We Stack Up",
      "comparison.title.highlight": "Against Everyone Else",
      "comparison.subtitle":
        "No cherry-picked metrics. Every row is verifiable. We included the ones where competitors beat us too.",
      "comparison.disclaimer":
        "* ChatDaddy advertises RM75/mo but requires a WABA account (+RM150–400/mo in Meta fees). Real total: RM280–500+/mo.",
      "comparison.filter.all": "All",
      "comparison.cat.pricing": "Pricing",
      "comparison.cat.channels": "Channels",
      "comparison.cat.ai": "AI & Language",
      "comparison.cat.automation": "Automation",
      "comparison.cat.setup": "Setup & Support",
      "comparison.best": "★ Best Value",
      "comparison.cta.title": "You have seen the numbers. Judge for yourself.",
      "comparison.cta.body":
        "RM299/mo. No WABA. No hidden Meta fees. No annual trap. WhatsApp direct to the founder if you have any questions.",
      "comparison.cta.wa": "Ask Jewel on WhatsApp",
      "comparison.cta.email": "jewel@mybijou.xyz",

      // Waitlist Strip
      "waitlist.headline": "Only 7 Early Adopter Spots Left — RM299/mo Forever",
      "waitlist.pill1": "Done for you",
      "waitlist.pill2": "Live in 15 min",
      "waitlist.pill3": "Zero setup hassle",
      "waitlist.social": "Built in KL. Made for Malaysian SMEs.",
      "waitlist.mobileSub":
        "✅ Done for you · ⚡ Live in 15 min · 🚫 Zero hassle",
      "waitlist.cta": "Claim My Spot",

      // Early Adopter block (Pricing)
      "pricing.ea.label": "Early Adopter Price Lock",
      "pricing.ea.badge": "🔥 Closing Soon",
      "pricing.ea.claimed": "of {{total}} founding spots claimed",
      "pricing.ea.left": "left",
      "pricing.ea.b1": "RM299 rate locked forever",
      "pricing.ea.b2": "New customers pay RM399+",
      "pricing.ea.b3": "Cancel anytime, no trap",
      "pricing.ea.b4": "Free add-ons when they ship",
    },
  },
  ms: {
    translation: {
      // Navbar
      // Hero Section
      "hero.badge":
        "🚀 RM0 untuk mulakan — tiada kad kredit, tiada WABA diperlukan",
      "hero.title.part1": "WhatsApp anda",
      "hero.title.savingsAmount": "offline pada 10 malam.",
      "hero.title.part2": "Pesaing anda",
      "hero.title.priceAmount": "tidak.",
      "hero.subtitle.part1":
        "Bijou ialah AI Malaysia untuk WhatsApp & Telegram. Balas segera dalam Manglish, tempah temujanji Cal.com, kelayakan leads automatik —",
      "hero.subtitle.roi": "semasa anda tidur.",
      "hero.subtitle.part2": "",
      "hero.cta.trial": "Mulakan Percuma — RM0",
      "hero.cta.demo": "Tempah Demo",
      "hero.trustFooter":
        "✅ Wang dikembalikan dalam 30 hari · ✅ Tiada WABA diperlukan · ✅ Batal bila-bila masa",
      "hero.trust.pdpa": "Mematuhi PDPA",
      "hero.chatDemo.assistant": "Pembantu Bijou",
      "hero.chatDemo.status": "Aktif • 02:45 AM",
      "hero.chatDemo.msg1":
        "Boss, boleh check property viewing? 2am dah tapi excited nak tengok.",
      "hero.chatDemo.msg2":
        "Tak masalah boss! Saya masih jaga. Area mana nak cari? KLCC atau Mont Kiara? 🏙️",
      "hero.chatDemo.msg3": "MK. Yang ada balcony.",
      "hero.chatDemo.msg4":
        "Ada! Residensi 22, Tingkat Tinggi. Saya hantar video brochure sekarang. 📹",
      "hero.roiCard.title": "Penjimatan Bulanan",
      "hero.roiCard.amount": "RM2,700+",
      "hero.roiCard.comparison": "berbanding pekerja WhatsApp separuh masa",
      "hero.roiCard.roi": "ROI ~900%",

      // Pricing Section — Satu Peringkat PRO (RM 299/bulan, dikemaskini Ogos 2026)
      "pricing.badge": "💎 Harga Jujur, Mudah",
      "pricing.title": "Satu Pelan. Semua Yang Sedia Ada.",
      "pricing.subtitle.part1": "Dijamin oleh",
      "pricing.subtitle.trial": "jaminan wang dikembalikan 30 hari",
      "pricing.subtitle.part2": ". Tiada kontrak. Batalkan bila-bila masa.",

      // Pelan PRO — Satu Peringkat
      "pricing.pro.name": "PRO",
      "pricing.pro.price": "299",
      "pricing.pro.yearlyPrice": "2,990",
      "pricing.pro.yearlySaving": "Jimat RM598 — 2 bulan percuma",
      "pricing.pro.description":
        "Semua yang anda perlukan supaya tiada petunjuk terlepas",
      "pricing.pro.badge": "SATU-SATUNYA PELAN",
      "pricing.pro.features.0":
        "Ejen AI WhatsApp — tanpa WABA, tanpa bayaran Meta",
      "pricing.pro.features.1": "Ejen AI Telegram — otak sama, Manglish sama",
      "pricing.pro.features.2": "3,000 Perbualan/bulan (~100/hari)",
      "pricing.pro.features.3": "AI TRACE Penuh — 4 ejen empati",
      "pricing.pro.features.4": "Manglish + EN / BM / Mandarin / Tamil",
      "pricing.pro.features.5":
        "Tempahan Cal.com — cipta, semak, batal temujanji",
      "pricing.pro.features.6": "E-mel pengesahan automatik kepada pelanggan",
      "pricing.pro.features.7":
        "Kelayakan Petunjuk — Pengesan Hot / Warm / Cold automatik",
      "pricing.pro.features.8":
        "Amaran eskalasi — e-mel anda apabila AI tidak dapat handle",
      "pricing.pro.features.9": "Pangkalan Pengetahuan — 200 dokumen (termasuk FAQ)",
      "pricing.pro.earlyAccessNote":
        "Pelanggan Pro mendapat akses awal PERCUMA apabila ciri baharu dilancarkan — tempat berbilang pengguna, saluran tambahan & lebih.",

      // Bahagian Tambahan
      "pricing.addons.title": "Akan Datang Q2–Q4 2026 (Tambahan Berbayar)",
      "pricing.addons.subtitle":
        "Setiap ciri baharu = peluang hasil. Pelanggan Pro dapat akses awal percuma.",

      "pricing.cta.trial": "Mulakan Percubaan 30 Hari",
      "pricing.cta.enterprise": "Hubungi kami →",
      "pricing.cta.enterprisePrompt":
        "Perlukan berbilang pengguna, nombor, atau setup tersuai?",

      "pricing.guarantee.title": "Jaminan Wang Dikembalikan 30 Hari",
      "pricing.guarantee.subtitle":
        "Jika Bijou tidak memberikan hasil dalam 30 hari, kami pulangkan 100% — tanpa soal",

      // KUNCI LAMA — untuk rujukan rollback, tidak dipaparkan lagi
      // Case Studies Section
      "cases.title": "Contoh Pilot",
      "cases.subtitle":
        "Contoh hasil yang kami sasarkan dengan pilot awal. Kajian kes sebenar akan keluar selepas 10 pelanggan pertama kami.",

      // Real Estate Case Study
      "cases.realEstate.company": "Agensi Hartanah (Contoh Pilot)",
      "cases.realEstate.industry": "Agensi Hartanah",
      "cases.realEstate.stat1.value": "0%",
      "cases.realEstate.stat1.label": "Panggilan Terlepas",
      "cases.realEstate.stat2.value": "+40%",
      "cases.realEstate.stat2.label": "Petunjuk Layak",
      "cases.realEstate.quote":
        "Sebelum Bijou, kami kehilangan petunjuk setiap kali di viewing. Sekarang, Bijou jawab serta-merta, hantar brosur, dan book viewing seterusnya. Macam ada super-ejen.",
      "cases.realEstate.cta": "Baca Kajian Kes Penuh",

      // Healthcare Case Study
      "cases.healthcare.company": "Klinik Pergigian (Contoh Pilot)",
      "cases.healthcare.industry": "Pakar Pergigian",
      "cases.healthcare.stat1.value": "-75%",
      "cases.healthcare.stat1.label": "Kadar Tak Hadir",
      "cases.healthcare.stat2.value": "24/7",
      "cases.healthcare.stat2.label": "Ketersediaan Tempahan",
      "cases.healthcare.quote":
        "Jururawat kami dulu habis jam panggil pesakit untuk confirm slot. Bijou buat automatik di WhatsApp. Pesakit suka, dan kerusi kami sentiasa penuh.",
      "cases.healthcare.cta": "Baca Kajian Kes Penuh",

      // Contact Forms
      "contact.enterprise.title": "Pertanyaan Perusahaan",
      "contact.enterprise.subtitle":
        "Mari berbincang bagaimana Bijou AI boleh transformasi perniagaan anda",
      "contact.partnership.title": "Peluang Kerjasama",
      "contact.partnership.subtitle":
        "Bekerjasama dengan kami untuk bawa AI ke lebih banyak perniagaan",
      "contact.integration.title": "Permintaan Integrasi",
      "contact.integration.subtitle":
        "Beritahu kami integrasi apa yang anda perlukan",

      "form.name": "Nama Penuh",
      "form.email": "Alamat E-mel",
      "form.company": "Nama Syarikat",
      "form.phone": "Nombor Telefon",
      "form.message": "Mesej",
      "form.submit": "Hantar",
      "form.sending": "Menghantar...",
      "form.success": "Terima kasih! Kami akan hubungi dalam 24 jam.",
      "form.error": "Ada masalah. Sila e-mel kami terus di",

      // Footer
      // Bahagian Ciri-ciri
      "features.badge": "Apa Yang Anda Dapat",
      "features.title.part1": "Setiap Ciri,",
      "features.title.highlight": "Dijelaskan Dengan Jelas",
      "features.subtitle":
        "Tiada buzzword. Tiada ikon yang samar. Klik mana-mana ciri untuk lihat cara kerjanya.",
      "features.live": "Semua ciri aktif dan berfungsi hari ini",
      "features.noBeta": "Tiada beta. Tiada senarai tunggu. Tiada asterisk.",
      "features.stats.features": "Ciri Aktif",
      "features.stats.features.sub": "semua berfungsi hari ini",
      "features.stats.setup": "Masa Persediaan",
      "features.stats.setup.sub": "layan diri, tiada pembangun",
      "features.stats.convos": "Perbualan/bulan",
      "features.stats.convos.sub": "~100 sehari",
      "features.stats.langs": "Bahasa Disokong",
      "features.stats.langs.sub": "EN · BM · 中文 · தமிழ்",
      "features.badge.live": "Aktif Sekarang",
      "features.badge.unique": "Unik kepada Bijou",
      "features.badge.enterprise": "Gred Perusahaan",
      "features.wa.title": "Ejen AI WhatsApp",
      "features.wa.subtitle": "Tiada WABA. Tiada bayaran Meta. Tiada markup.",
      "features.wa.desc":
        "Sambungkan nombor WhatsApp sedia ada anda dalam beberapa minit melalui imbasan QR. Tiada Facebook Business Manager, tiada permohonan WABA, tiada bayaran Meta RM0.05/mesej. Bijou mengendalikan pertanyaan masuk pada kadar rata RM299/bulan.",
      "features.wa.b1": "Imbas QR → aktif dalam 15 minit",
      "features.wa.b2": "Tiada caj setiap perbualan",
      "features.wa.b3": "Tiada markup Meta selamanya",
      "features.tg.title": "Ejen AI Telegram",
      "features.tg.subtitle": "Otak sama. Saluran kedua. Percuma.",
      "features.tg.desc":
        "AI, pangkalan pengetahuan dan personaliti Manglish yang sama berjalan serentak di Telegram tanpa kos tambahan.",
      "features.tg.b1": "Termasuk dalam Pro — tiada bayaran tambahan",
      "features.tg.b2": "Enjin TRACE dan pangkalan pengetahuan yang sama",
      "features.tg.b3": "Saluran bebas, persediaan bersatu",
      "features.trace.badge": "Production · v300 · Live di bijou-production.fly.dev",
      "features.trace.title": "Gemini 2.5 Flash dengan konteks pintar. Plus auto-handover bila AI sampai had.",
      "features.trace.subtitle": "LLM laju. Eskalasi pintar. Tiada pipeline tipu.",
      "features.trace.desc":
        "Setiap mesej lalu Gemini 2.5 Flash dengan konteks per-tenant, knowledge base anda, dan tone Manglish. Kalau perbualan jadi terlalu kompleks atau emosi tinggi, sistem handover akan flag dan staff anda ambil alih. Tiada pipeline tipu — cuma LLM laju dan layer eskalasi pintar yang betul-betul jalan.",
      "features.trace.b1": "Mengesan kekecewaan sebelum ia meningkat",
      "features.trace.b2": "Faham konteks, bukan sekadar kata kunci",
      "features.trace.b3": "Jawab hanya dari data anda — tiada halusinasi",
      "features.manglish.title": "Enjin Manglish",
      "features.manglish.subtitle": "Boleh lah. Ada atau tidak? Selesai.",
      "features.manglish.desc":
        "Lebih 20 corak regex mengendalikan pertukaran kod Malaysia secara asli — BM, Inggeris, Mandarin, Tamil dan Manglish dicampur secara semula jadi.",
      "features.manglish.b1": "Inggeris, Melayu, Mandarin, Tamil",
      "features.manglish.b2": "Slider nada: formal hingga Manglish penuh",
      "features.manglish.b3":
        "Tiada respons robot 'Certainly, I can assist you'",
      "features.cal.title": "Tempahan Cal.com",
      "features.cal.subtitle": "Tempah, semak, batal — semua melalui WhatsApp.",
      "features.cal.desc":
        "Integrasi kalendar dua hala penuh melalui Cal.com. Pelanggan tempah temujanji, semak ketersediaan dan batal — semuanya melalui WhatsApp atau Telegram.",
      "features.cal.b1": "Tempah, semak & batal melalui sembang",
      "features.cal.b2": "E-mel pengesahan automatik dihantar kepada pelanggan",
      "features.cal.b3": "Tiada kerja pembangun diperlukan",
      "features.escalation.title": "Amaran Eskalasi Pintar",
      "features.escalation.subtitle":
        "Anda diemelkan sebelum pelanggan mengamuk.",
      "features.escalation.desc":
        "Bijou mengesan isyarat kekecewaan, 3+ soalan tidak dijawab dan permintaan manusia eksplisit — kemudian segera menghantar e-mel utas perbualan penuh kepada anda.",
      "features.escalation.b1": "Pengesanan kekecewaan terbina dalam",
      "features.escalation.b2": "Konteks perbualan penuh dalam e-mel amaran",
      "features.escalation.b3": "E-mel domain tersuai (Pelan Growth)",
      "features.kb.title": "Pangkalan Pengetahuan",
      "features.kb.subtitle": "FAQ anda. Suara anda. Tiada halusinasi.",
      "features.kb.desc":
        "Muat naik sehingga 200 dokumen. Bijou hanya menjawab dari apa yang anda ajar — tiada rekaan. Kemaskini FAQ dan AI tahu serta-merta.",
      "features.kb.b1": "200 dokumen (Pro)",
      "features.kb.b2": "Kemaskini serta-merta — tiada latihan semula",
      "features.kb.b3": "AI kekal dalam laluan, tidak pernah meneka",
      "features.leads.title": "Kelayakan Petunjuk",
      "features.leads.subtitle":
        "Panas, suam, sejuk — ditanda secara automatik.",
      "features.leads.desc":
        "Bijou menyiasat bajet, garis masa dan niat secara semula jadi dalam perbualan. Setiap petunjuk ditanda secara automatik.",
      "features.leads.b1": "Pengesanan bajet + garis masa",
      "features.leads.b2": "Penandaan Hot / Warm / Cold",
      "features.leads.b3": "Disertakan dalam ringkasan amaran eskalasi",
      "features.security.title": "Keselamatan Sedia PDPA",
      "features.security.subtitle":
        "Data anda. Diasingkan sepenuhnya. Sentiasa.",
      "features.security.desc":
        "Keselamatan Peringkat Baris bermakna data pelanggan anda diasingkan 100% daripada setiap penyewa Bijou yang lain. Penyulitan AES-256. Patuh PDPA dan GDPR.",
      "features.security.b1":
        "Pengasingan data berbilang penyewa peringkat baris",
      "features.security.b2": "AES-256 + PDPA + GDPR sedia",
      "features.security.b3": "99.9% uptime — rantau Singapura",

      // Jadual Perbandingan
      "comparison.badge": "Perbandingan Jujur",
      "comparison.title.part1": "Bagaimana Kami Berbanding",
      "comparison.title.highlight": "Dengan Yang Lain",
      "comparison.subtitle":
        "Tiada metrik terpilih. Setiap baris boleh disahkan. Kami sertakan yang pesaing mengatasi kami juga.",
      "comparison.disclaimer":
        "* ChatDaddy mengiklankan RM75/bulan tetapi memerlukan akaun WABA (+RM150–400/bulan dalam bayaran Meta). Jumlah sebenar: RM280–500+/bulan.",
      "comparison.filter.all": "Semua",
      "comparison.cat.pricing": "Harga",
      "comparison.cat.channels": "Saluran",
      "comparison.cat.ai": "AI & Bahasa",
      "comparison.cat.automation": "Automasi",
      "comparison.cat.setup": "Persediaan & Sokongan",
      "comparison.best": "★ Nilai Terbaik",
      "comparison.cta.title": "Anda sudah lihat angkanya. Nilai sendiri.",
      "comparison.cta.body":
        "RM299/bulan. Tiada WABA. Tiada bayaran Meta tersembunyi. Tiada perangkap tahunan. WhatsApp terus kepada pengasas jika ada soalan.",
      "comparison.cta.wa": "Tanya Jewel di WhatsApp",
      "comparison.cta.email": "jewel@mybijou.xyz",

      // Jalur Senarai Tunggu
      "waitlist.headline":
        "Hanya 7 Spot Pengamal Awal Tinggal — RM299/bulan Selamanya",
      "waitlist.pill1": "Dibuat untuk anda",
      "waitlist.pill2": "Aktif dalam 15 minit",
      "waitlist.pill3": "Tiada kerumitan persediaan",
      "waitlist.social": "Dibina di KL. Dicipta untuk PKS Malaysia.",
      "waitlist.mobileSub":
        "✅ Dibuat untuk anda · ⚡ Aktif 15 minit · 🚫 Tiada kerumitan",
      "waitlist.cta": "Tuntut Tempat Saya",

      // Blok Pengamal Awal
      "pricing.ea.label": "Kunci Harga Pengamal Awal",
      "pricing.ea.badge": "🔥 Hampir Penuh",
      "pricing.ea.claimed": "daripada {{total}} spot pengasas dituntut",
      "pricing.ea.left": "tinggal",
      "pricing.ea.b1": "Kadar RM299 dikunci selamanya",
      "pricing.ea.b2": "Pelanggan baharu bayar RM399+",
      "pricing.ea.b3": "Batal bila-bila masa, tiada perangkap",
      "pricing.ea.b4": "Tambahan percuma apabila dihantar",
    },
  },
  zh: {
    translation: {
      // Navbar
      // Hero Section
      "hero.badge": "🚀 RM0起步 — 无需信用卡，无需WABA",
      "hero.title.part1": "您的WhatsApp",
      "hero.title.savingsAmount": "晚上10点就下线。",
      "hero.title.part2": "竞争对手的",
      "hero.title.priceAmount": "不会。",
      "hero.subtitle.part1":
        "Bijou是针对WhatsApp和Telegram的马来西AI。用Manglish即时回复，预约Cal.com资讯，自动筛选潜在客户 —",
      "hero.subtitle.roi": "当您熟睡时。",
      "hero.subtitle.part2": "",
      "hero.cta.trial": "免费开始 — RM0",
      "hero.cta.demo": "预约演示",
      "hero.trustFooter": "✅ 30天退款保证 · ✅ 无需WABA · ✅ 随时取消",
      "hero.trust.pdpa": "符合PDPA规范",
      "hero.chatDemo.assistant": "Bijou助手",
      "hero.chatDemo.status": "活跃 • 02:45 AM",
      "hero.chatDemo.msg1":
        "老板，可以check property viewing吗？2am了但我很excited。",
      "hero.chatDemo.msg2":
        "没问题老板！我还醒着。你要找哪个区？KLCC还是Mont Kiara？🏙️",
      "hero.chatDemo.msg3": "MK。有balcony的。",
      "hero.chatDemo.msg4":
        "有！Residensi 22，高楼层。我现在发给你视频手册。📹",
      "hero.roiCard.title": "每月节省",
      "hero.roiCard.amount": "RM2,700+",
      "hero.roiCard.comparison": "相比兼职WhatsApp员工（PayScale数据）",
      "hero.roiCard.roi": "~900% 投资回报率",

      // 定价部分 — 单一PRO套餐（RM 299/月，2026年8月更新）
      "pricing.badge": "💎 诚实透明定价",
      "pricing.title": "一个套餐。所有已上线功能。",
      "pricing.subtitle.part1": "享有",
      "pricing.subtitle.trial": "30天退款保证",
      "pricing.subtitle.part2": "。无合同。随时取消。",

      // PRO套餐 — 单一定价
      "pricing.pro.name": "PRO",
      "pricing.pro.price": "299",
      "pricing.pro.yearlyPrice": "2,990",
      "pricing.pro.yearlySaving": "节省RM598 — 免费使用2个月",
      "pricing.pro.description": "您需要的一切，永不错过任何线索",
      "pricing.pro.badge": "唯一方案",
      "pricing.pro.features.0": "WhatsApp AI代理 — 无需WABA，无Meta费用",
      "pricing.pro.features.1": "Telegram AI代理 — 相同大脑，相同马来式英语",
      "pricing.pro.features.2": "每月3,000次对话（约100次/天）",
      "pricing.pro.features.3": "完整TRACE AI — 4智能体共情管道",
      "pricing.pro.features.4": "Manglish + 英语/马来语/普通话/泰米尔语",
      "pricing.pro.features.5": "Cal.com预约 — 创建、查询、取消预约",
      "pricing.pro.features.6": "自动向客户发送预约确认邮件",
      "pricing.pro.features.7": "线索资格认定 — 自动热/温/冷检测",
      "pricing.pro.features.8": "升级警报 — AI无法处理时邮件给您",
      "pricing.pro.features.9": "知识库 — 200份文件 (包含FAQ)",
      "pricing.pro.earlyAccessNote":
        "Pro客户可在新功能上线时免费获得早期访问权限 — 多用户席位、额外渠道等。",

      // 插件路线图
      "pricing.addons.title": "2026年Q2–Q4即将推出（付费插件）",
      "pricing.addons.subtitle":
        "每项新功能 = 一次收入机会。Pro客户优先免费体验。",

      "pricing.cta.trial": "开始30天试用",
      "pricing.cta.enterprise": "联系我们 →",
      "pricing.cta.enterprisePrompt": "需要多用户、多号码或自定义方案？",

      "pricing.guarantee.title": "30天退款保证",
      "pricing.guarantee.subtitle":
        "如果Bijou在30天内未能达到预期，100%退款，无需解释",

      // 旧版密钥 — 保留供回滚参考，不再渲染
      // Case Studies Section
      "cases.title": "试点案例",
      "cases.subtitle": "我们早期试点期望达致的成果示例。真实案例将在首批10位客户后发布。",

      // Real Estate Case Study
      "cases.realEstate.company": "房地产代理（试点示例）",
      "cases.realEstate.industry": "房地产代理",
      "cases.realEstate.stat1.value": "0%",
      "cases.realEstate.stat1.label": "漏接电话",
      "cases.realEstate.stat2.value": "+40%",
      "cases.realEstate.stat2.label": "潜在客户筛选",
      "cases.realEstate.quote":
        "在使用Bijou之前，每次看房时我们都会失去潜在客户。现在，Bijou立即回复、发送手册并预约下次看房。就像有一个超级代理。",
      "cases.realEstate.cta": "阅读完整案例研究",

      // Healthcare Case Study
      "cases.healthcare.company": "牙科诊所（试点示例）",
      "cases.healthcare.industry": "牙科专家",
      "cases.healthcare.stat1.value": "-75%",
      "cases.healthcare.stat1.label": "爽约率",
      "cases.healthcare.stat2.value": "24/7",
      "cases.healthcare.stat2.label": "预约可用性",
      "cases.healthcare.quote":
        "我们的护士过去要花数小时打电话确认时段。Bijou在WhatsApp上自动完成。患者喜欢，我们的座位总是满的。",
      "cases.healthcare.cta": "阅读完整案例研究",

      // Contact Forms
      "contact.enterprise.title": "企业咨询",
      "contact.enterprise.subtitle": "让我们讨论Bijou AI如何改变您的业务",
      "contact.partnership.title": "合作机会",
      "contact.partnership.subtitle": "与我们合作，将AI带给更多企业",
      "contact.integration.title": "集成请求",
      "contact.integration.subtitle": "告诉我们您需要哪些集成",

      "form.name": "全名",
      "form.email": "电子邮件地址",
      "form.company": "公司名称",
      "form.phone": "电话号码",
      "form.message": "留言",
      "form.submit": "提交",
      "form.sending": "发送中...",
      "form.success": "谢谢！我们会在24小时内联系您。",
      "form.error": "出了点问题。请直接发送电子邮件至",

      // Footer
      // 功能部分
      "features.badge": "您真正获得的",
      "features.title.part1": "每项功能，",
      "features.title.highlight": "清晰说明",
      "features.subtitle":
        "没有术语。没有模糊图标。点击任意功能查看其工作原理。",
      "features.live": "所有功能今天都已上线运行",
      "features.noBeta": "无测试版。无等待列表。无星号。",
      "features.stats.features": "上线功能",
      "features.stats.features.sub": "今天全部可用",
      "features.stats.setup": "设置时间",
      "features.stats.setup.sub": "自助服务，无需开发",
      "features.stats.convos": "对话/月",
      "features.stats.convos.sub": "~100次/天",
      "features.stats.langs": "支持语言",
      "features.stats.langs.sub": "EN · BM · 中文 · தமிழ்",
      "features.badge.live": "立即可用",
      "features.badge.unique": "Bijou独有",
      "features.badge.enterprise": "企业级",
      "features.wa.title": "WhatsApp AI代理",
      "features.wa.subtitle": "无需WABA。无Meta费用。无加价。",
      "features.wa.desc":
        "通过QR扫描在几分钟内连接您现有的WhatsApp号码。无需Facebook Business Manager，无需WABA申请，无RM0.05/消息Meta费用。Bijou以RM299/月的固定费率处理入站查询。",
      "features.wa.b1": "扫描QR → 15分钟内上线",
      "features.wa.b2": "无每次对话费用",
      "features.wa.b3": "永不加价Meta费用",
      "features.tg.title": "Telegram AI代理",
      "features.tg.subtitle": "同一大脑。第二频道。免费附带。",
      "features.tg.desc":
        "相同的AI、知识库和Manglish个性同时在Telegram上运行，无额外费用。",
      "features.tg.b1": "包含在Pro中 — 无额外费用",
      "features.tg.b2": "相同TRACE引擎和知识库",
      "features.tg.b3": "独立频道，统一设置",
      // TODO(translate-zh): Honest copy translated below — verify with native speaker before publishing.
      "features.trace.badge": "Production · v300 · Live on bijou-production.fly.dev",
      "features.trace.title": "Gemini 2.5 Flash with smart context. Plus automatic handover when AI hits its limit.",
      "features.trace.subtitle": "Fast LLM. Smart escalation. No fake pipeline.",
      "features.trace.desc":
        "Every message goes through Gemini 2.5 Flash with per-tenant context, your knowledge base, and Manglish tone. If the conversation gets too complex or emotionally charged, the handover system flags it and a human takes over. No fake pipeline — just a fast LLM and a smart escalation layer that actually works.",
      "features.trace.b1": "在升级前检测挫败感",
      "features.trace.b2": "理解上下文，不只是关键词",
      "features.trace.b3": "只从您的数据回答 — 无幻觉",
      "features.manglish.title": "Manglish引擎",
      "features.manglish.subtitle": "Can lah。Got or not？搞定。",
      "features.manglish.desc":
        "20+个正则表达式模式原生处理马来西亚代码切换 — BM、英语、普通话、泰米尔语和Manglish自然混合。",
      "features.manglish.b1": "英语、马来语、普通话、泰米尔语",
      "features.manglish.b2": "语气滑块：正式到完整Manglish",
      "features.manglish.b3": "无机器人式'Certainly, I can assist you'",
      "features.cal.title": "Cal.com预约",
      "features.cal.subtitle": "预约、查询、取消 — 全通过WhatsApp。",
      "features.cal.desc":
        "通过Cal.com进行全双向日历集成。客户预约、查询可用性并取消 — 完全通过WhatsApp或Telegram对话。",
      "features.cal.b1": "通过聊天预约、查询和取消",
      "features.cal.b2": "自动向客户发送确认邮件",
      "features.cal.b3": "无需任何开发工作",
      "features.escalation.title": "智能升级警报",
      "features.escalation.subtitle": "在客户发怒前就会收到邮件。",
      "features.escalation.desc":
        "Bijou检测挫败信号、3+个未回答问题和明确的人工请求 — 然后立即向您发送完整对话线程。",
      "features.escalation.b1": "内置挫败感检测",
      "features.escalation.b2": "警报邮件中包含完整对话上下文",
      "features.escalation.b3": "自定义域名邮件（Growth计划）",
      "features.kb.title": "知识库",
      "features.kb.subtitle": "您的FAQ。您的声音。零幻觉。",
      "features.kb.desc":
        "上传最多200份文件。Bijou只从您教的内容回答 — 不编造。更新FAQ后AI立即知晓，无需重新训练。",
      "features.kb.b1": "200份文件（Pro）",
      "features.kb.b2": "即时更新 — 无需重新训练",
      "features.kb.b3": "AI保持在轨道上，从不猜测",
      "features.leads.title": "线索资格认定",
      "features.leads.subtitle": "热、温、冷 — 自动标记。",
      "features.leads.desc":
        "Bijou在对话中自然探询预算、时间线和意图。每个线索自动标记，让您知道先回访谁。",
      "features.leads.b1": "预算+时间线检测",
      "features.leads.b2": "热/温/冷标记",
      "features.leads.b3": "包含在升级警报摘要中",
      "features.security.title": "符合PDPA的安全性",
      "features.security.subtitle": "您的数据。完全隔离。始终如此。",
      "features.security.desc":
        "行级安全意味着您的客户数据与其他所有Bijou租户100%隔离。AES-256加密。符合PDPA和GDPR。",
      "features.security.b1": "行级多租户数据隔离",
      "features.security.b2": "AES-256 + PDPA + GDPR就绪",
      "features.security.b3": "99.9%正常运行时间 — 新加坡地区",

      // 比较表
      "comparison.badge": "诚实比较",
      "comparison.title.part1": "与竞争对手相比",
      "comparison.title.highlight": "我们的表现",
      "comparison.subtitle":
        "没有精心挑选的指标。每行都可验证。我们也包括了竞争对手胜过我们的地方。",
      "comparison.disclaimer":
        "* ChatDaddy宣传RM75/月，但需要WABA账户（+RM150-400/月Meta费用）。实际总计：RM280-500+/月。",
      "comparison.filter.all": "全部",
      "comparison.cat.pricing": "定价",
      "comparison.cat.channels": "频道",
      "comparison.cat.ai": "AI与语言",
      "comparison.cat.automation": "自动化",
      "comparison.cat.setup": "设置与支持",
      "comparison.best": "★ 最佳价值",
      "comparison.cta.title": "您已看到数字。自己判断。",
      "comparison.cta.body":
        "RM299/月。无WABA。无隐藏Meta费用。无年度陷阱。有任何问题直接WhatsApp创始人。",
      "comparison.cta.wa": "在WhatsApp上问Jewel",
      "comparison.cta.email": "jewel@mybijou.xyz",

      // 等待列表条
      "waitlist.headline": "仅剩7个早期用户名额 — RM299/月永久有效",
      "waitlist.pill1": "为您完成",
      "waitlist.pill2": "15分钟上线",
      "waitlist.pill3": "零设置麻烦",
      "waitlist.social": "在吉隆坡打造。专为马来西亚中小企业。",
      "waitlist.mobileSub": "✅ 为您完成 · ⚡ 15分钟上线 · 🚫 零麻烦",
      "waitlist.cta": "抢占我的名额",

      // 早期用户区块
      "pricing.ea.label": "早期用户价格锁定",
      "pricing.ea.badge": "🔥 即将结束",
      "pricing.ea.claimed": "共{{total}}个创始名额已被认领",
      "pricing.ea.left": "剩余",
      "pricing.ea.b1": "RM299费率永久锁定",
      "pricing.ea.b2": "新客户支付RM399+",
      "pricing.ea.b3": "随时取消，无陷阱",
      "pricing.ea.b4": "新功能上线时免费获得",
    },
  },
  ta: {
    translation: {
      // Navbar
      // Hero Section
      "hero.badge":
        "🚀 RM0-இல் தொடங்கவும் — கிரெடிட் கார்டு தேவையில்லை, WABA தேவையில்லை",
      "hero.title.part1": "உங்கள் WhatsApp",
      "hero.title.savingsAmount": "இரவு 10 மணிக்கு offline.",
      "hero.title.part2": "உங்கள் போட்டி வியாபாரிதர்களுக்கு",
      "hero.title.priceAmount": "இல்லை.",
      "hero.subtitle.part1":
        "Bijou மலேசிய WhatsApp & Telegram-க்கான AI. Manglish-இல் தக்ஷணமாக பதில், Cal.com சந்திப்புகளை பதிவு செய்கிறது, leads தானாக தெரிவு செய்கிறது —",
      "hero.subtitle.roi": "நீங்கள் தூங்கும்போது.",
      "hero.subtitle.part2": "",
      "hero.cta.trial": "இலவசமாக தொடங்குங்கள் — RM0",
      "hero.cta.demo": "டெமோ பதிவு செய்யவும்",
      "hero.trustFooter":
        "✅ 30 நாள் பண திரும்பி உத்தரவாதம் · ✅ WABA தேவையில்லை · ✅ எப்போதும் ரத்து செய்யலாம்",
      "hero.trust.pdpa": "PDPA இணங்குதல்",
      "hero.chatDemo.assistant": "Bijou உதவியாளர்",
      "hero.chatDemo.status": "செயலில் • 02:45 AM",
      "hero.chatDemo.msg1":
        "Boss, property viewing check பண்ண முடியுமா? 2am ஆகிவிட்டது ஆனால் excited ஆக இருக்கிறேன்.",
      "hero.chatDemo.msg2":
        "பிரச்சனை இல்லை boss! நான் இன்னும் விழித்திருக்கிறேன். எந்த பகுதியை தேடுகிறீர்கள்? KLCC அல்லது Mont Kiara? 🏙️",
      "hero.chatDemo.msg3": "MK. Balcony உள்ளது.",
      "hero.chatDemo.msg4":
        "உள்ளது! Residensi 22, உயர் தளம். இப்போது வீடியோ brochure அனுப்புகிறேன். 📹",
      "hero.roiCard.title": "மாதாந்திர சேமிப்பு",
      "hero.roiCard.amount": "RM2,700+",
      "hero.roiCard.comparison":
        "பகுதி நேர WhatsApp ஊழியருடன் ஒப்பிடும்போது",
      "hero.roiCard.roi": "~900% ROI",

      // விலை பிரிவு — ஒற்றை PRO திட்டம் (RM 299/மாதம், ஆகஸ்ட் 2026 புதுப்பிக்கப்பட்டது)
      "pricing.badge": "💎 நேர்மையான, எளிய விலை",
      "pricing.title": "ஒரே ஒரு திட்டம். இப்போது உள்ள அனைத்தும்.",
      "pricing.subtitle.part1": "உத்தரவாதம்:",
      "pricing.subtitle.trial": "30 நாள் பணத்திரும்ப உத்தரவாதம்",
      "pricing.subtitle.part2":
        ". ஒப்பந்தம் இல்லை. எப்போது வேண்டுமானாலும் ரத்து செய்யலாம்.",

      // PRO திட்டம் — ஒற்றை நிலை
      "pricing.pro.name": "PRO",
      "pricing.pro.price": "299",
      "pricing.pro.yearlyPrice": "2,990",
      "pricing.pro.yearlySaving": "RM598 சேமிக்கவும் — 2 மாதங்கள் இலவசம்",
      "pricing.pro.description":
        "எந்த வாய்ப்பும் தவற விடாமல் இருக்க தேவையான அனைத்தும்",
      "pricing.pro.badge": "ஒரே ஒரு திட்டம்",
      "pricing.pro.features.0":
        "WhatsApp AI — WABA இல்லாமல், Meta கட்டணம் இல்லாமல்",
      "pricing.pro.features.1": "Telegram AI — ஒரே மூளை, ஒரே Manglish",
      "pricing.pro.features.2": "மாதத்திற்கு 3,000 உரையாடல்கள் (~100/நாள்)",
      "pricing.pro.features.3": "முழு TRACE AI — 4-முகவர் பச்சாதாப குழாய்",
      "pricing.pro.features.4": "Manglish + EN / BM / மண்டரின் / தமிழ்",
      "pricing.pro.features.5":
        "Cal.com தேர்வு — பதிவு, சரிபார்க்கல், ரத்து செய்யலாம்",
      "pricing.pro.features.6":
        "பதிவு உறுதிப்படுத்தல் மின்னஞ்சல் தானாக அனுப்பப்படும்",
      "pricing.pro.features.7":
        "லீட் தகுதி — Hot / Warm / Cold தானியக்க கண்டறிதல்",
      "pricing.pro.features.8":
        "எஸ்கலேஷன் எமைல் — AI தடுமாறும்போது மின்னஞ்சல் வரும்",
      "pricing.pro.features.9": "அறிவுத் தளம் — 200 ஆவணங்கள் (FAQ உள்ளடங்கும்)",
      "pricing.pro.earlyAccessNote":
        "Pro வாடிக்கையாளர்கள் புதிய அம்சங்கள் வெளியிடப்படும்போது இலவச ஆரம்ப அணுகல் பெறுவார்கள்.",

      // சேர்க்கை வரைபடம்
      "pricing.addons.title": "Q2–Q4 2026-இல் வரவிருக்கும் (கட்டண சேர்க்கைகள்)",
      "pricing.addons.subtitle":
        "ஒவ்வொரு புதிய அம்சமும் = வருவாய் நிகழ்வு. Pro வாடிக்கையாளர்கள் முதலில் இலவசமாக பெறுவார்கள்.",

      "pricing.cta.trial": "30 நாள் சோதனை தொடங்கவும்",
      "pricing.cta.enterprise": "எங்களை தொடர்பு கொள்ளுங்கள் →",
      "pricing.cta.enterprisePrompt":
        "பல பயனர்கள், பல எண்கள், அல்லது தனிப்பயன் அமைப்பு தேவையா?",

      "pricing.guarantee.title": "30 நாள் பணத்திரும்ப உத்தரவாதம்",
      "pricing.guarantee.subtitle":
        "30 நாட்களில் Bijou பலன் தரவில்லை என்றால், கேள்வியின்றி 100% திரும்பப் பெறுவோம்",

      // பழைய விசைகள் — rollback குறிப்புக்காக வைக்கப்பட்டுள்ளன, இனி பயன்படுத்தப்படவில்லை
      // Case Studies Section
      "cases.title": "பைலட் எடுத்துக்காட்டுகள்",
      "cases.subtitle":
        "ஆரம்ப பைலட்களில் நாம் இலக்கு வைக்கும் முடிவுகளின் எடுத்துக்காட்டுகள். உண்மையான வழக்கு ஆய்வுகள் எங்கள் முதல் 10 வாடிக்கையாளர்களுக்குப் பிறகு வெளியிடப்படும்.",

      // Real Estate Case Study
      "cases.realEstate.company": "ரியல் எஸ்டேட் ஏஜென்சி (பைலட் எடுத்துக்காட்டு)",
      "cases.realEstate.industry": "ரியல் எஸ்டேட் ஏஜென்சி",
      "cases.realEstate.stat1.value": "0%",
      "cases.realEstate.stat1.label": "தவறிய அழைப்புகள்",
      "cases.realEstate.stat2.value": "+40%",
      "cases.realEstate.stat2.label": "தகுதிபெற்ற லீட்ஸ்",
      "cases.realEstate.quote":
        "Bijou க்கு முன், நாங்கள் பார்வையில் இருக்கும் போதெல்லாம் லீட்ஸை இழந்தோம். இப்போது, Bijou உடனடியாக பதிலளிக்கிறது, தகவல் புத்தகத்தை அனுப்புகிறது, அடுத்த பார்வையை பதிவு செய்கிறது. சூப்பர் ஏஜென்ட் இருப்பது போல்.",
      "cases.realEstate.cta": "முழு வழக்கு ஆய்வைப் படிக்கவும்",

      // Healthcare Case Study
      "cases.healthcare.company": "பல் மருத்துவ நிலையம் (பைலட் எடுத்துக்காட்டு)",
      "cases.healthcare.industry": "பல் மருத்துவ நிபுணர்",
      "cases.healthcare.stat1.value": "-75%",
      "cases.healthcare.stat1.label": "வராத விகிதம்",
      "cases.healthcare.stat2.value": "24/7",
      "cases.healthcare.stat2.label": "பதிவு கிடைக்கும் தன்மை",
      "cases.healthcare.quote":
        "எங்கள் செவிலியர்கள் முன்பு நோயாளிகளை அழைத்து ஸ்லாட்களை உறுதிப்படுத்த மணிநேரங்களை செலவிட்டனர். Bijou WhatsApp இல் தானாகவே செய்கிறது. நோயாளிகள் விரும்புகிறார்கள், மற்றும் எங்கள் நாற்காலிகள் எப்போதும் நிரம்பியுள்ளன.",
      "cases.healthcare.cta": "முழு வழக்கு ஆய்வைப் படிக்கவும்",

      // Contact Forms
      "contact.enterprise.title": "நிறுவன விசாரணைகள்",
      "contact.enterprise.subtitle":
        "Bijou AI உங்கள் வணிகத்தை எவ்வாறு மாற்றும் என்பதை விவாதிப்போம்",
      "contact.partnership.title": "கூட்டாண்மை வாய்ப்புகள்",
      "contact.partnership.subtitle":
        "அதிக வணிகங்களுக்கு AI ஐக் கொண்டு வர எங்களுடன் ஒத்துழைக்கவும்",
      "contact.integration.title": "ஒருங்கிணைப்பு கோரிக்கைகள்",
      "contact.integration.subtitle":
        "உங்களுக்கு என்ன ஒருங்கிணைப்புகள் தேவை என்று சொல்லுங்கள்",

      "form.name": "முழு பெயர்",
      "form.email": "மின்னஞ்சல் முகவரி",
      "form.company": "நிறுவனத்தின் பெயர்",
      "form.phone": "தொலைபேசி எண்",
      "form.message": "செய்தி",
      "form.submit": "சமர்ப்பிக்கவும்",
      "form.sending": "அனுப்புகிறது...",
      "form.success": "நன்றி! நாங்கள் 24 மணி நேரத்திற்குள் தொடர்பு கொள்வோம்.",
      "form.error":
        "ஏதோ தவறு நடந்தது. தயவுசெய்து எங்களுக்கு நேரடியாக மின்னஞ்சல் அனுப்பவும்",

      // Footer
      // அம்சங்கள் பிரிவு
      "features.badge": "நீங்கள் உண்மையில் என்ன பெறுகிறீர்கள்",
      "features.title.part1": "ஒவ்வொரு அம்சமும்,",
      "features.title.highlight": "தெளிவாக விவரிக்கப்பட்டுள்ளது",
      "features.subtitle":
        "வீண் வார்த்தைகள் இல்லை. தெளிவற்ற ஐகான்கள் இல்லை. எந்த அம்சத்தையும் கிளிக் செய்து அது எப்படி வேலை செய்கிறது என்று பாருங்கள்.",
      "features.live": "அனைத்து அம்சங்களும் இன்று செயல்படுகின்றன",
      "features.noBeta":
        "பீட்டா இல்லை. காத்திருப்பு பட்டியல் இல்லை. விதிவிலக்கு இல்லை.",
      "features.stats.features": "செயலில் உள்ள அம்சங்கள்",
      "features.stats.features.sub": "இன்று அனைத்தும் வேலை செய்கின்றன",
      "features.stats.setup": "அமைப்பு நேரம்",
      "features.stats.setup.sub": "சுயசேவை, டெவலப்பர் தேவையில்லை",
      "features.stats.convos": "உரையாடல்கள்/மாதம்",
      "features.stats.convos.sub": "~100 நாளுக்கு",
      "features.stats.langs": "ஆதரிக்கப்படும் மொழிகள்",
      "features.stats.langs.sub": "EN · BM · 中文 · தமிழ்",
      "features.badge.live": "இப்போது செயல்படுகிறது",
      "features.badge.unique": "Bijou மட்டுமே",
      "features.badge.enterprise": "நிறுவன-தரம்",
      "features.wa.title": "WhatsApp AI முகவர்",
      "features.wa.subtitle":
        "WABA தேவையில்லை. Meta கட்டணம் இல்லை. மார்க்அப் இல்லை.",
      "features.wa.desc":
        "QR ஸ்கேன் மூலம் சில நிமிடங்களில் உங்கள் WhatsApp எண்ணை இணைக்கவும். Facebook Business Manager தேவையில்லை, WABA விண்ணப்பம் தேவையில்லை, RM0.05/செய்தி Meta கட்டணம் இல்லை.",
      "features.wa.b1": "QR ஸ்கேன் → 15 நிமிடத்தில் செயல்படுகிறது",
      "features.wa.b2": "ஒவ்வொரு உரையாடலுக்கும் கட்டணம் இல்லை",
      "features.wa.b3": "Meta மார்க்அப் ஒருபோதும் இல்லை",
      "features.tg.title": "Telegram AI முகவர்",
      "features.tg.subtitle":
        "ஒரே மூளை. இரண்டாவது சேனல். இலவசமாக சேர்க்கப்பட்டது.",
      "features.tg.desc":
        "அதே AI, அறிவுத் தளம் மற்றும் Manglish ஆளுமை Telegram-இல் ஒரே நேரத்தில் இயங்குகிறது, எந்த கூடுதல் செலவும் இல்லாமல்.",
      "features.tg.b1": "Pro-இல் சேர்க்கப்பட்டது — கூடுதல் கட்டணம் இல்லை",
      "features.tg.b2": "அதே TRACE என்ஜின் மற்றும் அறிவுத் தளம்",
      "features.tg.b3": "சுதந்திர சேனல், ஒருங்கிணைந்த அமைப்பு",
      // TODO(translate-ta): Honest copy translated below — verify with native speaker before publishing.
      "features.trace.badge": "Production · v300 · Live on bijou-production.fly.dev",
      "features.trace.title": "Gemini 2.5 Flash with smart context. Plus automatic handover when AI hits its limit.",
      "features.trace.subtitle": "Fast LLM. Smart escalation. No fake pipeline.",
      "features.trace.desc":
        "Every message goes through Gemini 2.5 Flash with per-tenant context, your knowledge base, and Manglish tone. If the conversation gets too complex or emotionally charged, the handover system flags it and a human takes over. No fake pipeline — just a fast LLM and a smart escalation layer that actually works.",
      "features.trace.b1": "அதிகரிக்கும் முன் விரக்தியை கண்டறிகிறது",
      "features.trace.b2": "சூழலை புரிகிறது, வெறும் சொற்களை மட்டுமல்ல",
      "features.trace.b3": "உங்கள் தரவிலிருந்து மட்டுமே பதில் — மாயை இல்லை",
      "features.manglish.title": "Manglish என்ஜின்",
      "features.manglish.subtitle": "Can lah. Got or not? தீர்ந்தது.",
      "features.manglish.desc":
        "20+ regex வடிவங்கள் மலேசிய குறியீடு-மாற்றத்தை இயல்பாகவே கையாளுகின்றன — BM, ஆங்கிலம், மண்டரின், தமிழ் மற்றும் Manglish இயல்பாக கலக்கப்பட்டது.",
      "features.manglish.b1": "ஆங்கிலம், மலாய், மண்டரின், தமிழ்",
      "features.manglish.b2": "தொனி ஸ்லைடர்: முறையான முதல் முழு Manglish வரை",
      "features.manglish.b3": "ரோபோட்டிக் 'Certainly, I can assist you' இல்லை",
      "features.cal.title": "Cal.com பதிவு",
      "features.cal.subtitle":
        "பதிவு, சரிபார், ரத்து — அனைத்தும் WhatsApp வழியாக.",
      "features.cal.desc":
        "Cal.com வழியாக முழு இரு-திசை காலண்டர் ஒருங்கிணைப்பு. வாடிக்கையாளர்கள் WhatsApp அல்லது Telegram உரையாடல் வழியாக முழுமையாக பதிவு செய்கிறார்கள்.",
      "features.cal.b1": "அரட்டை வழியாக பதிவு, சரிபார் மற்றும் ரத்து",
      "features.cal.b2": "வாடிக்கையாளருக்கு தானாக உறுதிப்படுத்தல் மின்னஞ்சல்",
      "features.cal.b3": "டெவலப்பர் வேலை தேவையில்லை",
      "features.escalation.title": "ஸ்மார்ட் எஸ்கலேஷன் எச்சரிக்கைகள்",
      "features.escalation.subtitle":
        "வாடிக்கையாளர் கோபமாவதற்கு முன்பே உங்களுக்கு மின்னஞ்சல் வரும்.",
      "features.escalation.desc":
        "Bijou விரக்தி சமிக்ஞைகள், 3+ பதிலளிக்கப்படாத கேள்விகள் மற்றும் வெளிப்படையான மனித கோரிக்கைகளை கண்டறிகிறது — பின்னர் உடனடியாக முழு உரையாடல் நூலை மின்னஞ்சல் செய்கிறது.",
      "features.escalation.b1": "விரக்தி கண்டறிதல் உள்ளமைக்கப்பட்டது",
      "features.escalation.b2": "எச்சரிக்கை மின்னஞ்சலில் முழு உரையாடல் சூழல்",
      "features.escalation.b3": "தனிப்பயன் டொமைன் மின்னஞ்சல் (Growth திட்டம்)",
      "features.kb.title": "அறிவுத் தளம்",
      "features.kb.subtitle": "உங்கள் FAQ. உங்கள் குரல். சூன்ய மாயை.",
      "features.kb.desc":
        "200 ஆவணங்களை பதிவேற்றவும். Bijou நீங்கள் கற்பித்ததிலிருந்து மட்டுமே பதில் கூறுகிறது — கற்பனை செய்வதில்லை. FAQ புதுப்பிக்கவும் AI உடனடியாக தெரிந்துகொள்ளும்.",
      "features.kb.b1": "200 ஆவணங்கள் (Pro)",
      "features.kb.b2": "உடனடி புதுப்பிப்புகள் — மறுபயிற்சி தேவையில்லை",
      "features.kb.b3": "AI பாதையில் இருக்கும், ஒருபோதும் யூகிக்காது",
      "features.leads.title": "லீட் தகுதிப்பெறுதல்",
      "features.leads.subtitle":
        "சூடான, வெதுவெதுப்பான, குளிர் — தானாக குறிக்கப்படும்.",
      "features.leads.desc":
        "Bijou உரையாடலில் இயல்பாக பட்ஜெட், கால அட்டவணை மற்றும் நோக்கத்தை ஆராய்கிறது. ஒவ்வொரு லீட்டும் தானாக குறிக்கப்படும்.",
      "features.leads.b1": "பட்ஜெட் + கால அட்டவணை கண்டறிதல்",
      "features.leads.b2": "சூடான / வெதுவெதுப்பான / குளிர் குறிக்கல்",
      "features.leads.b3": "எஸ்கலேஷன் எச்சரிக்கை சுருக்கத்தில் சேர்க்கப்பட்டது",
      "features.security.title": "PDPA-தயார் பாதுகாப்பு",
      "features.security.subtitle":
        "உங்கள் தரவு. முழுமையாக தனிமைப்படுத்தப்பட்டது. எப்பொழுதும்.",
      "features.security.desc":
        "வரிசை-நிலை பாதுகாப்பு என்பது உங்கள் வாடிக்கையாளர் தரவு மற்ற அனைத்து Bijou வாடகையாளர்களிடமிருந்தும் 100% தனிமைப்படுத்தப்பட்டுள்ளது என்று அர்த்தம். AES-256 குறியாக்கம். PDPA மற்றும் GDPR இணங்குதல்.",
      "features.security.b1": "வரிசை-நிலை பல-வாடகையாளர் தரவு தனிமைப்படுத்தல்",
      "features.security.b2": "AES-256 + PDPA + GDPR தயார்",
      "features.security.b3": "99.9% அப்டைம் — சிங்கப்பூர் பிராந்தியம்",

      // ஒப்பீட்டு அட்டவணை
      "comparison.badge": "நேர்மையான ஒப்பீடு",
      "comparison.title.part1": "நாங்கள் எவ்வாறு ஒப்பிடுகிறோம்",
      "comparison.title.highlight": "மற்றவர்களுடன்",
      "comparison.subtitle":
        "தேர்ந்தெடுக்கப்பட்ட அளவீடுகள் இல்லை. ஒவ்வொரு வரியும் சரிபார்க்கக்கூடியது. போட்டியாளர்கள் நம்மை மிஞ்சும் இடங்களும் சேர்க்கப்பட்டுள்ளன.",
      "comparison.disclaimer":
        "* ChatDaddy RM75/மாதம் விளம்பரப்படுத்துகிறது ஆனால் WABA கணக்கு தேவை (+RM150-400/மாதம் Meta கட்டணங்கள்). உண்மையான மொத்தம்: RM280-500+/மாதம்.",
      "comparison.filter.all": "அனைத்தும்",
      "comparison.cat.pricing": "விலை",
      "comparison.cat.channels": "சேனல்கள்",
      "comparison.cat.ai": "AI மற்றும் மொழி",
      "comparison.cat.automation": "தானியங்கு",
      "comparison.cat.setup": "அமைப்பு மற்றும் ஆதரவு",
      "comparison.best": "★ சிறந்த மதிப்பு",
      "comparison.cta.title":
        "நீங்கள் எண்களை பார்த்தீர்கள். நீங்களே தீர்மானிக்கவும்.",
      "comparison.cta.body":
        "RM299/மாதம். WABA இல்லை. மறைக்கப்பட்ட Meta கட்டணங்கள் இல்லை. வருடாந்திர பொறி இல்லை. கேள்விகள் இருந்தால் நிறுவகருக்கு நேரடியாக WhatsApp செய்யவும்.",
      "comparison.cta.wa": "WhatsApp-இல் Jewel-ஐ கேளுங்கள்",
      "comparison.cta.email": "jewel@mybijou.xyz",

      // காத்திருப்பு பட்டை
      "waitlist.headline":
        "வெறும் 7 ஆரம்ப பயனர் இடங்கள் மட்டுமே உள்ளன — RM299/மாதம் எப்பொழுதும்",
      "waitlist.pill1": "உங்களுக்காக செய்யப்பட்டது",
      "waitlist.pill2": "15 நிமிடத்தில் செயல்படுகிறது",
      "waitlist.pill3": "அமைப்பு சிரமம் சூன்யம்",
      "waitlist.social": "KL-ல் கட்டமைக்கப்பட்டது. மலேசிய SME-களுக்காக.",
      "waitlist.mobileSub":
        "✅ உங்களுக்காக செய்யப்பட்டது · ⚡ 15 நிமிடத்தில் · 🚫 சிரமம் இல்லை",
      "waitlist.cta": "என் இடத்தை கோரவும்",

      // ஆரம்ப பயனர் தொகுதி
      "pricing.ea.label": "ஆரம்ப பயனர் விலை பூட்டு",
      "pricing.ea.badge": "🔥 விரைவில் நிறைகிறது",
      "pricing.ea.claimed": "{{total}} நிறுவன இடங்களில் கோரப்பட்டவை",
      "pricing.ea.left": "மீதி",
      "pricing.ea.b1": "RM299 விலை என்றும் பூட்டப்பட்டது",
      "pricing.ea.b2": "புதிய வாடிக்கையாளர்கள் RM399+ செலுத்துவார்கள்",
      "pricing.ea.b3": "எப்போது வேண்டுமானாலும் ரத்து செய்யலாம், பொறி இல்லை",
      "pricing.ea.b4": "புதிய அம்சங்கள் வரும்போது இலவச சேர்க்கைகள்",
    },
  },
};

i18n
  .use(LanguageDetector) // Detect user language
  .use(initReactI18next) // Pass i18n to react-i18next
  .init({
    resources,
    fallbackLng: "en", // Fallback to English if language not found
    supportedLngs: ["en", "ms", "zh", "ta"],
    detection: {
    },
    interpolation: {
    },
  });

export default i18n;
