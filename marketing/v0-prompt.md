# v0 Prompt — Vibe Your Videos Pre-Launch Landing Page

## Prompt

Create a single-page pre-launch marketing website for "Vibe Your Videos" — an open-source AI video generator that turns a text prompt into a fully produced narrated video with AI visuals, voiceover, and typewriter-style captions. No editing. No timeline. Just type and get a video.

The site is at vibeyourvideos.com. The goal is to maximize email signups for the upcoming Pro launch. Use a dark theme (background #0f0f13, cards #1a1a24, accent purple #7c3aed / #a78bfa, text #e0e0e6, muted #6b6b80). Font: Inter or system sans-serif. The vibe is modern, minimal, creator-focused.

---

### Page Structure (top to bottom)

**1. Sticky Nav**
- Left: "Vibe Your Videos" wordmark in purple (#a78bfa)
- Right: "GitHub" link (https://github.com/mayurjobanputra/VibeYourVideos), "Get Early Access" CTA button (purple #7c3aed, scrolls to signup form)

**2. Hero Section**
- Large headline: "Turn Any Idea Into a Narrated Video"
- Subheadline: "Type a prompt. Get a fully produced video with AI visuals, voiceover, and captions. No editing. No timeline. Just vibes."
- Primary CTA button: "Get Early Access to Pro" (purple, scrolls to signup)
- Secondary link: "It's open source — try it free on GitHub →"
- Below the CTA: a subtle social proof line like "Open source · MIT licensed · 100% local"
- Background: subtle animated gradient or grain texture, nothing heavy

**3. "How It Works" — 4-Step Visual Flow**
- Horizontal row on desktop, vertical stack on mobile
- Each step is a numbered card with an icon and short description:
  1. "Type your idea" — Describe any video concept in plain text
  2. "AI writes the script" — An LLM breaks your idea into scenes with narration and visual cues
  3. "Visuals + voice generated" — AI creates an image for each scene and narrates the script
  4. "Get your video" — FFmpeg assembles everything into a polished MP4 with crossfade transitions
- Use simple line icons or emoji-style icons, keep it clean

**4. Feature Grid — "What You Get (Free)"**
- 2x3 or 3x2 grid of feature cards, each with an icon, title, and one-liner:
  - "Up to 90s videos" — Short-form content, ready to post
  - "Vertical + Horizontal" — 9:16 for Reels/TikTok, 16:9 for YouTube
  - "Typewriter Captions" — Words appear as they're spoken, bold high-contrast text
  - "AI Script Writing" — Scene-by-scene scripts from a single prompt
  - "AI Image Generation" — Unique visuals for every scene
  - "Runs 100% Locally" — Your content, your data, your machine

**5. Caption Demo Section**
- Headline: "Captions That Keep Viewers Locked In"
- Short description: "Words roll onto screen as they're spoken — bold, high-contrast typewriter text. Choose captions on, off, or generate both versions in one job."
- Visual: a mockup or stylized illustration showing the typewriter caption effect on a dark video frame. Use a code-style or terminal-style visual if a real screenshot isn't available.

**6. Pro Teaser — "Coming Soon: Vibe Your Videos Pro"**
- This is the conversion section. Make it feel exclusive and exciting.
- Headline: "Go Beyond 90 Seconds"
- Subheadline: "Pro is for creators and teams who want full control."
- Feature list (use check icons, two columns on desktop):
  - Longer videos beyond 90 seconds
  - Content Design Studio — fine-tune scripts, visuals, and pacing before rendering
  - Advanced caption styling and positioning
  - Animated content instead of static images
  - Brand Kit — logos, fonts, color palettes for consistent branding
  - Video reference — use existing footage as a style guide
  - Scheduler — queue and schedule video generation
  - Automation Engine — trigger video creation from external events
  - Direct upload to social platforms
- Below the list: "Be first in line when Pro launches."

**7. Email Signup Form (the main conversion point)**
- id="signup" so the nav CTA scrolls here
- Headline: "Get Early Access"
- Subheadline: "Drop your email. We'll let you know when Pro is ready — plus early-bird pricing."
- Single email input + "Join the Waitlist" submit button (purple)
- Below the form: "No spam. Unsubscribe anytime." in muted text
- The form should POST to a placeholder endpoint `/api/waitlist` with JSON `{ "email": "..." }`
- Show a success state after submit: "You're on the list 🎬" with a confetti or checkmark animation

**8. Open Source CTA Banner**
- Full-width dark card with purple border accent
- "Vibe Your Videos is free and open source."
- "Star us on GitHub" button linking to https://github.com/mayurjobanputra/VibeYourVideos
- "MIT Licensed" badge

**9. Footer**
- Left: "© 2026 Vibe Your Videos"
- Right: GitHub link, "Back to top" link
- Keep it minimal

---

### SEO Requirements
- `<title>`: "Vibe Your Videos — AI Video Generator | Turn Text Into Narrated Videos"
- `<meta name="description">`: "Turn any idea into a narrated video with AI-generated visuals, voiceover, and typewriter captions. Open source, runs locally. Try free or join the Pro waitlist."
- `<meta name="keywords">`: "AI video generator, text to video, AI narration, AI visuals, open source video tool, typewriter captions, video from prompt, vibe your videos"
- Open Graph tags for social sharing:
  - `og:title`: "Vibe Your Videos — Turn Any Idea Into a Narrated Video"
  - `og:description`: "AI-generated visuals, voiceover, and typewriter captions. Open source and free. Pro coming soon."
  - `og:type`: "website"
  - `og:url`: "https://vibeyourvideos.com"
  - `og:image`: "https://vibeyourvideos.com/og-image.png" (placeholder)
- Twitter card meta tags (summary_large_image)
- Canonical URL: `https://vibeyourvideos.com`
- Use semantic HTML: `<header>`, `<main>`, `<section>`, `<footer>`, `<nav>`
- All images should have alt text
- Use `<h1>` for the hero headline only, `<h2>` for section headings, `<h3>` for card titles
- Add JSON-LD structured data for SoftwareApplication schema

**10. Technical Notes**
- Single HTML page with Tailwind CSS (via CDN) and inline styles where needed
- Fully responsive: mobile-first, looks great on all breakpoints
- Smooth scroll behavior for anchor links
- Subtle entrance animations on scroll (fade-in-up) using CSS or minimal JS
- The email form should have client-side validation (valid email format)
- Accessible: proper ARIA labels, focus states, keyboard navigation, color contrast
- Lightweight — no heavy frameworks, no unnecessary JS libraries
- Add a favicon link (placeholder `/favicon.ico`)
