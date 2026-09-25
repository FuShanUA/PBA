"""Shared URL filtering and taxonomy rules for palantir.com pages."""

import re
from urllib.parse import urlparse


EXCLUDE_PREFIXES = (
    "/blog",
    "/docs",
    "/sitemap",
    "/cookie",
    "/terms",
    "/privacy-and-security",
    "/human-rights",
    "/modern-slavery",
    "/store",
    "/contact",
    "/.well-known",
    "/assets",
    "/jp",
    "/uk",
    "/us-public-policy",
    "/responsible-business",
    "/news-details",
)

NON_ENGLISH_LOCALES = {"de", "fr", "es", "ja", "zh", "ko", "pt", "it"}

# Section landing pages are navigation pages, not archive articles.
NAVIGATION_PATHS = {
    "/about/",
    "/careers/",
    "/careers/getting-hired/",
    "/careers/open-positions/",
    "/careers/students/",
    "/customer-success-services/",
    "/foundation/",
    "/foundation/about/",
    "/foundation/conference/",
    "/foundation/home/",
    "/foundation/journal/",
    "/foundation/news-and-resources/",
    "/impact/",
    "/information-security/",
    "/insights/",
    "/newsroom/",
    "/newsroom/press-releases/",
    "/newsroom/letters/",
    "/newsroom/media/",
    "/newsroom/thought-leadership/",
    "/offerings/",
    "/offerings/defense/news/",
    "/offerings/federal-health/publications/",
    "/offerings/palantir-for-builders/news/",
    "/offerings/palantir-for-builders/service-providers/",
    "/palantir-explained/",
    "/partnerships/",
    "/partnerships/preferred-partners/",
    "/pcl/",
    "/pcl/thought-leadership/",
    "/platforms/",
    "/platforms/apollo/content-hub/",
}

# Pages whose primary purpose is form submission, registration, gated download,
# or a thank-you state. They are not content pages.
CONVERSION_PATHS = {
    "/2025-ai-ds-ml-market-study/",
    "/2025-market-studies/",
    "/2025-modelops-market-study/",
    "/2025-wisdom-of-crowds-agentic-ai-market-study/",
    "/ai-sovereignty-is-your-alpha/",
    "/devcon-submit/",
    "/explore-usg-channel-fy23-partner-program-kickoff-registration/",
    "/foundry-explained-get-demo/",
    "/insights-moving-beyond-customer-analytics-whitepaper/",
    "/offerings-defense-secure-collaboration-contact/",
    "/platforms-apollo-get-started/",
    "/thank-you-or-moving-beyond-customer-analytics-whitepaper/",
}

CONVERSION_SEGMENTS = {
    "contact",
    "get-demo",
    "get-started",
    "register",
    "registration",
    "submit",
    "thank-you",
    "download",
}

BAD_PATHS = {
    "/500/",
    "/explore-telecommunications/",
    "/explore/telecommunications/",
    "/japan/",
    "/new-homepage/",
    "/pagenotfound/",
    "/404/",
    "/search/",
    "/security-advisories/log4j-vulnerability/",
}

SHAREHOLDER_SELECTOR_RE = re.compile(r"^/q[1-4]-\d{4}-letter/?$")


def path_parts(path):
    if not path:
        return []
    return [part for part in path.strip("/").split("/") if part]


def normalized_path(path):
    if not path:
        return "/"
    if not path.startswith("/"):
        path = "/" + path
    if not path.endswith("/"):
        path += "/"
    return path


def is_non_english_url(path):
    """Skip localized variants; this archive translates the English source."""
    return any(part.lower() in NON_ENGLISH_LOCALES for part in path_parts(path))


def is_non_content_path(path):
    path = normalized_path(path)
    if path == "/":
        return True
    if any(path.startswith(prefix) for prefix in EXCLUDE_PREFIXES):
        return True
    if is_non_english_url(path):
        return True
    if path in NAVIGATION_PATHS:
        return True
    if path in CONVERSION_PATHS or path in BAD_PATHS:
        return True
    if any(part.lower() == "404" for part in path_parts(path)):
        return True
    if SHAREHOLDER_SELECTOR_RE.match(path):
        return True
    if any(part.lower() in CONVERSION_SEGMENTS for part in path_parts(path)):
        return True
    if path.startswith("/explore/download/"):
        return True
    return False


def should_exclude(path):
    """Compatibility name used by the website scraper."""
    return is_non_content_path(path)


def _newsroom_subcategory(parts):
    if len(parts) >= 2:
        mapping = {
            "press-releases": "press-releases",
            "letters": "letters",
            "media": "media",
            "thought-leadership": "thought-leadership",
        }
        return mapping.get(parts[1], "announcements")
    return "announcements"


def _offerings_subcategory(parts, slug):
    if parts[0] == "defense":
        return "defense"
    if parts[0] in {"army-intelligence-data-platform", "army-vantage"}:
        return "defense"
    if parts[0].startswith("aip-for-") or parts[0].startswith("aip-sensor-"):
        return "ai-solutions"
    if parts[0] in {"palantir-fraud-detection", "unlock", "vertex-for-energy"}:
        return "industrial"

    if len(parts) >= 2:
        second = parts[1]
        mapping = {
            "aml-b": "financial-services",
            "anti-money-laundering": "financial-services",
            "automotive-mobility": "industrial",
            "construction": "industrial",
            "consumer-goods": "commerce",
            "crypto": "financial-services",
            "data-mesh": "ai-solutions",
            "data-protection": "ai-solutions",
            "defense": "defense",
            "edge-ai": "ai-solutions",
            "energy": "energy",
            "federal-health": "healthcare",
            "fedstart": "government",
            "financial-services": "financial-services",
            "food-and-beverage": "commerce",
            "government-web-services": "government",
            "gxp-solutions": "healthcare",
            "health": "healthcare",
            "hyperauto": "industrial",
            "insurance": "insurance",
            "intelligence": "intelligence",
            "iot": "industrial",
            "iot-A": "industrial",
            "life-sciences": "life-sciences",
            "metaconstellation": "defense",
            "mixed-reality": "ai-solutions",
            "palantir-for-builders": "builders",
            "procurement": "government",
            "readiness": "defense",
            "retail": "commerce",
            "semiconductors": "industrial",
            "supply-chain": "supply-chain",
            "supply-chain-risk-management": "supply-chain",
            "telecommunications": "telecommunications",
            "utilities": "utilities",
        }
        return mapping.get(second, "industry")
    return "industry"


def _platforms_subcategory(parts):
    if parts[0] == "aip":
        return "aip"
    if parts[0].startswith("attributes"):
        return "platform-capabilities"
    if parts[0] in {
        "developers",
        "foundry-entity-resolution",
        "rubix",
        "rubix-specs",
        "sovereignaios",
        "sovereignaios-modelengine",
        "titanium",
        "protect-your-sovereignty",
    }:
        if parts[0] in {"sovereignaios", "sovereignaios-modelengine", "protect-your-sovereignty"}:
            return "sovereign"
        if parts[0] == "foundry-entity-resolution":
            return "foundry"
        if parts[0] == "developers":
            return "developer"
        return "platform-capabilities"

    if len(parts) >= 2:
        mapping = {
            "aip": "aip",
            "apollo": "apollo",
            "foundry": "foundry",
            "gotham": "gotham",
            "ontology": "ontology",
        }
        return mapping.get(parts[1], "platform-capabilities")
    return "platform-capabilities"


def _careers_subcategory(parts, slug):
    if len(parts) >= 2:
        mapping = {
            "getting-hired": "hiring",
            "infrastructure": "engineering",
            "life-at-palantir": "culture",
            "meritocracy-fellowship": "fellowships",
            "open-positions": "opportunities",
            "students": "students",
        }
        return mapping.get(parts[1], "opportunities")
    if slug in {"american-tech-fellowship", "shipos-atf"}:
        return "fellowships"
    if slug in {"usg-recruitment", "veterans"}:
        return "opportunities"
    return "opportunities"


def _about_subcategory(parts, slug):
    if parts[0] == "climate-pledge":
        return "responsibility"
    if parts[0] == "foundation" or slug.startswith("foundation-"):
        return "foundation"
    return "company"


def categorize_url(path):
    """Return (primary category, stable secondary category) for a URL path."""
    parts = path_parts(path)
    if not parts:
        return "About", "company"
    top = parts[0]
    slug = "-".join(parts)

    if top == "newsroom":
        return "Newsroom", _newsroom_subcategory(parts)
    if re.match(r"^q[1-4]-\d{4}-letter$", top):
        return "Newsroom", "letters"
    if re.match(r"^\d{4}-.*market-stud", top):
        return "Insights", "market-research"
    if top in {
        "end-of-year-message-from-alex-karp",
        "first-breakfast",
        "in-defense-of-europe",
        "palantir-mourns-the-loss-of-sergio-marchionne",
    }:
        return "Newsroom", "announcements"

    if top in {"insights", "explore"}:
        return "Insights", "industry-insights"

    if top in {
        "aipcon",
        "devcon",
        "devcon-archive",
        "devcon-on-your-mark",
        "devcon3",
        "devcon4",
        "devcon5",
        "hannover",
        "master-classes",
    }:
        return "Events", "developer-events"

    if top in {
        "aip-for-asset-maintenance-scheduling",
        "aip-for-ehs-risk-management",
        "aip-for-maintenance-assistance",
        "aip-for-program-knowledge-management",
        "aip-for-public-consultation-analysis",
        "aip-for-sustainable-solutions",
        "aip-for-wastewater-system-optimization",
        "aip-for-work-breakdown-structure-creator",
        "aip-sensor-integration-for-wastewater-management",
        "army-intelligence-data-platform",
        "army-vantage",
        "defense",
        "palantir-fraud-detection",
        "unlock",
        "vertex-for-energy",
    } or top.startswith("offerings-") or top == "offerings":
        return "Offerings", _offerings_subcategory(parts, slug)

    if top in {
        "aip",
        "attributes",
        "developers",
        "foundry-entity-resolution",
        "protect-your-sovereignty",
        "rubix",
        "rubix-specs",
        "sovereignaios",
        "sovereignaios-modelengine",
        "titanium",
    } or top.startswith("attributes-") or top.startswith("platforms-") or top == "platforms":
        return "Platforms", _platforms_subcategory(parts)

    if top == "impact" or top.startswith("impact-") or top == "ncmec":
        return "Impact Studies", "customer-stories"

    if top in {"partners", "partnerships"} or top.startswith("partners-") or top.startswith("partnership-"):
        return "Partnerships", "partners"

    if top == "careers" or slug in {
        "american-tech-fellowship",
        "shipos-atf",
        "usg-recruitment",
        "veterans",
    }:
        return "Careers", _careers_subcategory(parts, slug)

    if top in {"about", "climate-pledge", "foundation"} or slug.startswith("foundation-"):
        return "About", _about_subcategory(parts, slug)

    if top == "pcl" or top.startswith("pcl-") or top == "aip-now-statement":
        return "Privacy & Civil Liberties", "privacy-and-governance"

    if top in {"information-security", "responsible-disclosure", "security-forge"} or top.startswith("security-advisories"):
        return "Information Security", "security"

    if top == "customer-success-services":
        return "Customer Success", "services"

    if top in {
        "alpha",
        "chain-reaction",
        "migration",
        "mission-manager",
        "interoperability",
        "shipos",
        "titan",
        "warpspeed",
    }:
        return "Special Products", "products"

    if top in {
        "beyond-anonymization",
        "designing-for-deletion",
        "palantir-is-not-a-data-company",
        "palantir-is-still-not-a-data-company",
        "privacy-and-civil-liberties-engineering",
        "purpose-based-access-controls",
        "trust-in-data",
    }:
        return "Palantir Explained", "series"

    return "About", "company"


def categorize_article(article):
    path = urlparse(article.get("u", "")).path
    return categorize_url(path)
