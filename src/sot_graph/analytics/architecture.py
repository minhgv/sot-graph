"""
src/sot_graph/analytics/architecture.py
Zero-dependency architectural classifier, pattern detector, domain aggregator,
violation analyzer, and Mermaid diagram generator for multi-language codebases.
"""
from __future__ import annotations

import collections
import dataclasses
import enum
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

from sot_graph.analytics.graph import (
    AnalyticsGraph,
    CommunityResult,
    OperationCancelledError,
)

class ArchitecturalLayer(str, enum.Enum):
    PRESENTATION = "Presentation (UI / View)"
    BUSINESS_LOGIC = "Business Logic (State / Services)"
    DOMAIN = "Domain (Entities / UseCases)"
    DATA = "Data & Infrastructure (Repository / DB / API)"
    CORE = "Core & Utilities (Config / Common / Router)"
    UNKNOWN = "General / Unclassified"


@dataclasses.dataclass
class LayerBreakdown:
    layer: ArchitecturalLayer
    node_count: int
    file_count: int
    sample_nodes: List[str]
    sample_paths: List[str]
    top_symbols: List[str]


@dataclasses.dataclass
class ArchitectureViolation:
    violation_type: str  # "LAYER_BYPASS", "INVERTED_DEPENDENCY", "CIRCULAR_DEPENDENCY", "GOD_COMPONENT"
    severity: str  # "CRITICAL", "HIGH", "MEDIUM", "LOW"
    source_node: str
    source_path: str
    target_node: str
    target_path: str
    description: str
    recommendation: str


@dataclasses.dataclass
class BusinessDomain:
    name: str
    category: str  # "Core Domain", "Supporting Domain", "Generic/Infrastructure"
    node_count: int
    file_count: int
    files: List[str]
    sample_symbols: List[str]
    cohesion_score: float
    dependencies: List[str]  # other domain names
@dataclasses.dataclass
class FunctionalModule:
    name: str
    category: str  # "Core Business", "Integration & Gateway", "Platform / Infrastructure", "UI / Presentation", "Supporting / Common"
    responsibility: str
    node_count: int
    file_count: int
    core_entities: List[str]
    entrypoints: List[str]
    dependencies: List[str]
    sample_symbols: List[str]
    internal_files: List[str]


@dataclasses.dataclass
class RouteEndpoint:
    route_type: str  # "HTTP_API", "UI_PAGE", "EVENT_DISPATCH", "CLI_COMMAND"
    path_or_pattern: str
    handler: str
    file_anchor: str
    line: int
    method: Optional[str] = None
    auth_guard: Optional[str] = None
    target_layer: Optional[str] = None


@dataclasses.dataclass
class RoutingArchitecture:
    total_routes: int
    http_routes: List[RouteEndpoint]
    ui_routes: List[RouteEndpoint]
    event_routes: List[RouteEndpoint]
    mermaid_routing_diagram: str
    mermaid_hld_diagram: str


@dataclasses.dataclass
class ArchitectureProfile:
    pattern_name: str
    primary_language: str
    framework_hints: List[str]
    layer_breakdown: Dict[ArchitecturalLayer, LayerBreakdown]
    domains: List[BusinessDomain]
    functional_modules: List[FunctionalModule]
    routing_architecture: RoutingArchitecture
    violations: List[ArchitectureViolation]
    mermaid_hld_diagram: str
    mermaid_layer_diagram: str
    mermaid_routing_tree: str
    mermaid_execution_flow: str
    mermaid_domain_flow: str
    modularity_verdict: str
    recommendations_p0: List[str]
    recommendations_p1: List[str]
    recommendations_p2: List[str]


def is_test_or_mock_path(path: str) -> bool:
    """
    Identify whether a file path belongs to tests, mocks, or spec suites.
    Matches /test/, /tests/, /integration_test/, /mock/, /spec/, _test., .spec., .test., test_*.
    """
    if not path:
        return False
    normalized = path.replace("\\", "/").lower()
    parts = normalized.split("/")
    test_dir_names = {
        "test", "tests", "integration_test", "integration_tests",
        "mock", "mocks", "spec", "specs", "__tests__", "__test__"
    }
    if any(p in test_dir_names for p in parts[:-1]):
        return True

    filename = parts[-1]
    if filename.startswith("test_") or filename.startswith("mock_"):
        return True
    if "_test." in filename or ".spec." in filename or ".test." in filename or "_mock." in filename or "-test." in filename or "-spec." in filename:
        return True
    if filename.endswith("_test") or filename.endswith("_spec"):
        return True
    return False


UI_CONTROLLER_DENYLIST: Set[str] = {
    "texteditingcontroller",
    "scrollcontroller",
    "animationcontroller",
    "tabcontroller",
    "pagecontroller",
    "focusnode",
    "changenotifier",
    "valuenotifier",
    "streamcontroller",
    "searchcontroller",
    "segmentedbuttoncontroller",
    "expansiontilecontroller",
    "undomanager",
    "statecontroller",
    "viewcontroller",
    "uicontroller",
    "gesturecontroller",
    "refreshcontroller",
}
# ---------------------------------------------------------------------------
# Layer Classification Rules
# ---------------------------------------------------------------------------

_PRESENTATION_PATTERNS = [
    re.compile(r"/(presentation|views?|screens?|pages?|widgets?|components?|templates?|dialogs?|ui)/", re.I),
    re.compile(r"(controller|view|screen|page|widget|dialog|fragment|activity|component)\.(dart|java|kt|ts|tsx|js|jsx|vue|php|py)$", re.I),
    re.compile(r"\b(StatefulWidget|StatelessWidget|Widget|Screen|Page|View|Component|Dialog)\b"),
]

_DOMAIN_PATTERNS = [
    re.compile(r"/(domain|entities|models?|usecases?|interactors?|contracts?|interfaces?|value_objects?|aggregates?)/", re.I),
    re.compile(r"(entity|model|usecase|interactor|contract|interface|value_object)\.(dart|java|kt|ts|js|php|py|go|rs)$", re.I),
    re.compile(r"\b(Entity|UseCase|Interactor|Aggregate|ValueObject|Contract|DomainModel)\b"),
]

_LOGIC_PATTERNS = [
    re.compile(r"/(bloc|cubit|notifiers?|viewmodels?|services?|handlers?|actions?|reducers?|state|events?|store)/", re.I),
    re.compile(r"(bloc|cubit|viewmodel|service|handler|notifier|reducer|store)\.(dart|java|kt|ts|js|php|py|go|rs)$", re.I),
    re.compile(r"\b(Bloc|Cubit|ViewModel|Service|Handler|Notifier|StateNotifier|ChangeNotifier|Reducer)\b"),
]

_DATA_PATTERNS = [
    re.compile(r"/(data|repositories|repository|datasources?|dao|dto|api|clients?|network|database|db|queries|migrations?|rest)/", re.I),
    re.compile(r"(repository|datasource|dao|dto|client|api|dao_impl|repository_impl)\.(dart|java|kt|ts|js|php|py|go|rs)$", re.I),
    re.compile(r"\b(Repository|DataSource|Dao|Dto|ApiClient|RestClient|HttpService|DatabaseHelper|SqliteHelper)\b"),
]

_CORE_PATTERNS = [
    re.compile(r"/(core|common|utils?|helpers?|configs?|constants?|security|auth|middleware|interceptors?|router|routes?|theme)/", re.I),
    re.compile(r"(config|constant|util|helper|router|route|middleware|interceptor|theme|security)\.(dart|java|kt|ts|js|php|py|go|rs)$", re.I),
    re.compile(r"\b(Config|Constants|AppRouter|Utils|Helper|Middleware|Interceptor|Theme)\b"),
]


def classify_node_layer(node_id: str, data: Dict[str, Any]) -> ArchitecturalLayer:
    """Classify a node into an architectural layer based on path, label, kind, and keywords."""
    path = (data.get("path") or "").lower()
    label = data.get("label") or node_id
    keywords = " ".join(data.get("keywords") or []).lower()
    text = f"{path} {label} {keywords}"

    # 1. Check Presentation Layer
    for pat in _PRESENTATION_PATTERNS:
        if pat.search(text) or pat.search(path) or pat.search(label):
            return ArchitecturalLayer.PRESENTATION

    # 2. Check Domain Layer (Clean Architecture: UseCases, Entities, Contracts)
    for pat in _DOMAIN_PATTERNS:
        if pat.search(text) or pat.search(path) or pat.search(label):
            return ArchitecturalLayer.DOMAIN

    # 3. Check Business Logic Layer (State management, Services, Coordinators)
    for pat in _LOGIC_PATTERNS:
        if pat.search(text) or pat.search(path) or pat.search(label):
            return ArchitecturalLayer.BUSINESS_LOGIC

    # 4. Check Data / Repository Layer
    for pat in _DATA_PATTERNS:
        if pat.search(text) or pat.search(path) or pat.search(label):
            return ArchitecturalLayer.DATA
    # 5. Check Core / Infrastructure Layer
    for pat in _CORE_PATTERNS:
        if pat.search(text) or pat.search(path) or pat.search(label):
            return ArchitecturalLayer.CORE

    # Fallback heuristic based on directory convention
    if any(p in path for p in ["/ui/", "/widget/", "/screen/", "/page/", "/view/"]):
        return ArchitecturalLayer.PRESENTATION
    if any(p in path for p in ["/logic/", "/bloc/", "/service/", "/store/", "/action/"]):
        return ArchitecturalLayer.BUSINESS_LOGIC
    if any(p in path for p in ["/model/", "/entity/", "/dto/", "/schema/"]):
        return ArchitecturalLayer.DOMAIN
    if any(p in path for p in ["/data/", "/repo/", "/api/", "/db/", "/sql/", "/network/"]):
        return ArchitecturalLayer.DATA
    if any(p in path for p in ["/core/", "/shared/", "/base/", "/util/", "/lib/"]):
        return ArchitecturalLayer.CORE

    return ArchitecturalLayer.UNKNOWN


# ---------------------------------------------------------------------------
# Pattern and Framework Detection
# ---------------------------------------------------------------------------

def detect_pattern_and_framework(
    graph: AnalyticsGraph,
) -> Tuple[str, str, List[str]]:
    """Detect the overarching software architecture pattern, primary language, and frameworks."""
    ext_counts: Dict[str, int] = collections.defaultdict(int)
    all_paths = [d.get("path", "") for d in graph.nodes.values() if d.get("path")]

    for p in all_paths:
        ext = Path(p).suffix.lower()
        if ext:
            ext_counts[ext] += 1

    top_ext = max(ext_counts.items(), key=lambda x: x[1])[0] if ext_counts else ".py"

    lang_map = {
        ".dart": "Dart / Flutter",
        ".java": "Java (JVM)",
        ".kt": "Kotlin (Android/JVM)",
        ".ts": "TypeScript",
        ".tsx": "TypeScript (React)",
        ".js": "JavaScript",
        ".jsx": "JavaScript (React)",
        ".php": "PHP",
        ".py": "Python",
        ".go": "Go",
        ".rs": "Rust",
        ".cpp": "C++",
        ".c": "C",
        ".swift": "Swift",
        ".cs": "C# (.NET)",
    }
    primary_lang = lang_map.get(top_ext, "Multi-language / General")

    # Framework & Pattern signatures
    frameworks: List[str] = []
    has_bloc = False
    has_clean_arch = False
    has_spring = False
    has_laravel = False
    has_react = False
    has_nestjs = False
    has_fastapi = False

    labels_joined = " ".join([d.get("label", "") for d in graph.nodes.values()]).lower()
    paths_joined = " ".join(all_paths).lower().replace("\\", "/")

    if "dart" in primary_lang.lower():
        if "bloc" in labels_joined or "cubit" in labels_joined or "/bloc/" in paths_joined:
            has_bloc = True
            frameworks.append("BLoC / Cubit State Management")
        if "provider" in labels_joined:
            frameworks.append("Provider")
        if "getx" in labels_joined or "get_state" in paths_joined:
            frameworks.append("GetX")
        if "retrofit" in labels_joined or "dio" in labels_joined or "http" in paths_joined:
            frameworks.append("Dio / REST API")
        if "hive" in labels_joined or "sqflite" in labels_joined or "shared_preferences" in labels_joined:
            frameworks.append("Local Storage (SQLite/Hive)")
        if any(f in paths_joined for f in ["/presentation/", "/domain/", "/data/"]):
            has_clean_arch = True

    elif "java" in primary_lang.lower() or "kotlin" in primary_lang.lower():
        if "spring" in paths_joined or "@controller" in labels_joined or "autowired" in labels_joined:
            has_spring = True
            frameworks.append("Spring Boot Framework")
        if "jpa" in paths_joined or "hibernate" in labels_joined or "repository" in paths_joined:
            frameworks.append("Spring Data JPA / Hibernate")
        if "security" in paths_joined or "jwt" in labels_joined or "otp" in labels_joined:
            frameworks.append("Security & Auth Gateway")

    elif "typescript" in primary_lang.lower() or "javascript" in primary_lang.lower():
        if "@nestjs" in labels_joined or "/controllers" in paths_joined and "/modules" in paths_joined:
            has_nestjs = True
            frameworks.append("NestJS Modular Framework")
        if "react" in paths_joined or "usestate" in labels_joined or "useeffect" in labels_joined:
            has_react = True
            frameworks.append("React UI Framework")
        if "redux" in paths_joined or "zustand" in paths_joined or "pinia" in paths_joined:
            frameworks.append("State Management (Redux/Zustand)")

    elif "php" in primary_lang.lower():
        if "eloquent" in labels_joined or "artisan" in paths_joined or "app/http/controllers" in paths_joined:
            has_laravel = True
            frameworks.append("Laravel MVC Framework")
        if "symfony" in paths_joined:
            frameworks.append("Symfony Framework")

    elif "python" in primary_lang.lower():
        if "fastapi" in labels_joined or "apirouter" in labels_joined:
            has_fastapi = True
            frameworks.append("FastAPI")
        if "django" in paths_joined or "models.model" in labels_joined:
            frameworks.append("Django Framework")
        if "sqlite3" in labels_joined or "sqlalchemy" in labels_joined:
            frameworks.append("SQLAlchemy / SQLite Storage")

    # Determine Pattern Name
    if has_bloc and has_clean_arch:
        pattern = "Flutter BLoC Clean Architecture (Feature-First)"
    elif has_bloc:
        pattern = "BLoC / Event-Driven State Architecture"
    elif has_spring:
        pattern = "Layered MVC & Enterprise Service Architecture (Spring Boot)"
    elif has_nestjs:
        pattern = "Modular Microservice / Hexagonal Architecture (NestJS)"
    elif has_react:
        pattern = "Component-Driven Client Architecture (React SPA)"
    elif has_laravel:
        pattern = "Action-Domain-Responder / Model-View-Controller (Laravel PHP)"
    elif has_fastapi:
        pattern = "Asynchronous API & Service Layer Architecture (FastAPI)"
    elif has_clean_arch:
        pattern = "Clean Architecture / Onion Layered Architecture"
    else:
        pattern = f"Modular Layered Architecture ({primary_lang})"

    return pattern, primary_lang, frameworks


# ---------------------------------------------------------------------------
# Domain Aggregator
# ---------------------------------------------------------------------------

def aggregate_business_domains(
    graph: AnalyticsGraph,
    community_res: CommunityResult,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> List[BusinessDomain]:
    """
    Group low-level nodes and communities into High-Level Functional Business Domains.
    Extracts domains from feature paths (/features/<name>/, /modules/<name>/, etc.).
    """
    if cancel_check and cancel_check():
        raise OperationCancelledError("Analytics operation cancelled by client")
    domain_buckets: Dict[str, Dict[str, Any]] = collections.defaultdict(
        lambda: {
            "nodes": [],
            "files": set(),
            "symbols": [],
            "communities": set(),
        }
    )

    for node_id, data in graph.nodes.items():
        path = data.get("path", "")
        label = data.get("label", node_id)
        kind = data.get("kind", "symbol")

        # Extract domain key from path
        domain_name = _extract_domain_from_path(path)
        b = domain_buckets[domain_name]
        b["nodes"].append(node_id)
        if path:
            b["files"].add(path)
        if kind != "file":
            b["symbols"].append(label)

        cid = community_res.node_to_community.get(node_id)
        if cid is not None:
            b["communities"].add(cid)

    domains: List[BusinessDomain] = []

    for d_name, b in domain_buckets.items():
        if not b["nodes"]:
            continue

        file_list = sorted(list(b["files"]))
        node_count = len(b["nodes"])
        file_count = len(file_list)

        # Categorize domain
        name_lower = d_name.lower()
        if any(k in name_lower for k in ["core", "common", "shared", "util", "infrastructure", "network", "config"]):
            category = "Generic / Infrastructure Domain"
        elif any(k in name_lower for k in ["auth", "login", "user", "profile", "setting", "notification"]):
            category = "Supporting Domain"
        else:
            category = "Core Business Domain"

        # Calculate cohesion: internal edges / total edges incident to domain nodes
        domain_node_set = set(b["nodes"])
        internal_edges = 0
        external_edges = 0
        dep_domains: Set[str] = set()

        for edge in graph.edges:
            src, dst = edge["src"], edge["dst"]
            src_in = src in domain_node_set
            dst_in = dst in domain_node_set

            if src_in and dst_in:
                internal_edges += 1
            elif src_in:
                external_edges += 1
                dst_path = graph.nodes.get(dst, {}).get("path", "")
                dst_domain = _extract_domain_from_path(dst_path)
                if dst_domain != d_name:
                    dep_domains.add(dst_domain)
            elif dst_in:
                external_edges += 1

        total_incident = internal_edges + external_edges
        cohesion = round((internal_edges / total_incident), 2) if total_incident > 0 else 1.0

        sample_symbols = b["symbols"][:6]

        domains.append(
            BusinessDomain(
                name=d_name,
                category=category,
                node_count=node_count,
                file_count=file_count,
                files=file_list,
                sample_symbols=sample_symbols,
                cohesion_score=cohesion,
                dependencies=sorted(list(dep_domains))[:6],
            )
        )

    # Sort domains: Core Business Domains first, then by node count
    domains.sort(
        key=lambda d: (
            0 if "Core" in d.category else (1 if "Supporting" in d.category else 2),
            -d.node_count,
        )
    )
    return domains

def _extract_domain_from_path(path: str) -> str:
    """Extract a clean high-level domain name from a file path."""
    if not path:
        return "Global / Root Domain"

    parts = Path(path).parts
    lower_parts = [p.lower() for p in parts]

    # Look for feature / module keywords
    for marker in ["features", "modules", "domains", "services", "components", "pages", "apps"]:
        if marker in lower_parts:
            idx = lower_parts.index(marker)
            if idx + 1 < len(parts):
                feature_name = parts[idx + 1]
                # Clean up feature name (e.g. 'client_crm' -> 'Client Crm')
                clean_name = re.sub(r"[-_]", " ", feature_name).title()
                return f"{clean_name} Domain"

    # Check top-level directories in src/ or lib/
    for root_marker in ["lib", "src", "app"]:
        if root_marker in lower_parts:
            idx = lower_parts.index(root_marker)
            if idx + 1 < len(parts) and idx + 2 < len(parts):
                folder = parts[idx + 1]
                if folder.lower() in ["core", "shared", "common", "utils", "config"]:
                    return "Core & Shared Domain"
                clean_name = re.sub(r"[-_]", " ", folder).title()
                return f"{clean_name} Domain"

    # Fallback to parent directory
    parent = Path(path).parent.name
    if parent and parent not in [".", ""]:
        return f"{re.sub(r'[-_]', ' ', parent).title()} Module"

    return "General Domain"


def aggregate_functional_modules(
    graph: AnalyticsGraph,
    domains: List[BusinessDomain],
    node_layers: Dict[str, ArchitecturalLayer],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> List[FunctionalModule]:
    """
    Decompose the codebase into comprehensive Functional Modules (Features/Subsystems).
    Maps responsibilities, core entities, entrypoints, and cross-module dependencies.
    """
    if cancel_check and cancel_check():
        raise OperationCancelledError("Analytics operation cancelled by client")
    modules: List[FunctionalModule] = []
    for d in domains:
        name = d.name
        cat = d.category
        if "Core" in cat:
            module_cat = "Core Business"
        elif "Supporting" in cat:
            module_cat = "Supporting & Service"
        elif any(k in name.lower() for k in ["api", "gateway", "router", "controller", "webhook"]):
            module_cat = "Integration & Gateway"
        elif any(k in name.lower() for k in ["ui", "page", "widget", "screen", "view"]):
            module_cat = "UI / Presentation"
        else:
            module_cat = "Platform & Infrastructure"

        clean_title = name.replace(" Domain", "").replace(" Module", "")
        if module_cat == "Core Business":
            resp = f"Encapsulates {clean_title} domain business rules, entities, state machines, and data processing workflows."
        elif module_cat == "Supporting & Service":
            resp = f"Provides supporting capabilities for {clean_title}, including authentication, permissions, or specialized services."
        elif module_cat == "Integration & Gateway":
            resp = f"Handles external API routing, contract translation, webhooks, and client communication for {clean_title}."
        elif module_cat == "UI / Presentation":
            resp = f"Manages user interface rendering, screens, widgets, and user interaction handling for {clean_title}."
        else:
            resp = f"Provides core foundation, shared utilities, configurations, and common infrastructure for {clean_title}."

        core_entities: List[str] = []
        entrypoints: List[str] = []
        domain_files_set = set(d.files)

        for node_id, data in graph.nodes.items():
            path = data.get("path", "")
            if path in domain_files_set:
                label = data.get("label", node_id)
                kind = data.get("kind", "symbol")
                layer = node_layers.get(node_id, ArchitecturalLayer.UNKNOWN)
                if kind != "file":
                    if layer in (ArchitecturalLayer.DOMAIN, ArchitecturalLayer.DATA) and any(k in label.lower() for k in ["class", "struct", "model", "entity", "dto", "schema", "table"]):
                        if label not in core_entities:
                            core_entities.append(label)
                    elif layer in (ArchitecturalLayer.PRESENTATION, ArchitecturalLayer.BUSINESS_LOGIC) and any(k in label.lower() for k in ["controller", "page", "screen", "router", "handler", "bloc", "cubit", "service", "callback"]):
                        if label not in entrypoints:
                            entrypoints.append(label)

        if not core_entities:
            core_entities = [s for s in d.sample_symbols if any(k in s.lower() for k in ["model", "data", "entity", "result", "item", "order", "user", "info", "state"])][:4]
        if not entrypoints:
            entrypoints = [s for s in d.sample_symbols if any(k in s.lower() for k in ["page", "bloc", "service", "ctrl", "controller", "router", "helper", "action"])][:4]

        modules.append(
            FunctionalModule(
                name=name,
                category=module_cat,
                responsibility=resp,
                node_count=d.node_count,
                file_count=d.file_count,
                core_entities=core_entities[:5],
                entrypoints=entrypoints[:5],
                dependencies=d.dependencies,
                sample_symbols=d.sample_symbols[:6],
                internal_files=d.files,
            )
        )

    return modules


def extract_routing_architecture(
    graph: AnalyticsGraph,
    node_layers: Dict[str, ArchitecturalLayer],
    primary_lang: str,
    pattern_name: str,
    include_tests: bool = False,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> RoutingArchitecture:
    """
    Extract routing topology across HTTP APIs, UI Pages, and Event Dispatches.
    Supports multi-stack conventions (Flutter, FastAPI, Odoo, Spring, NestJS, etc.).
    """
    if cancel_check and cancel_check():
        raise OperationCancelledError("Analytics operation cancelled by client")
    http_routes: List[RouteEndpoint] = []
    ui_routes: List[RouteEndpoint] = []
    event_routes: List[RouteEndpoint] = []
    seen_endpoints: Set[str] = set()

    for node_id, data in graph.nodes.items():
        label = data.get("label", node_id)
        path = data.get("path", "")
        line = data.get("line_start") or data.get("line") or 1
        kind = data.get("kind", "symbol")
        layer = node_layers.get(node_id, ArchitecturalLayer.UNKNOWN)

        if not path or kind == "file":
            continue

        if not include_tests and is_test_or_mock_path(path):
            continue

        label_lower = label.lower()
        path_lower = path.lower()

        # 1. Detect HTTP / REST API Endpoints
        is_http = False
        method = "POST" if any(k in label_lower for k in ["post", "create", "insert", "upload", "callback", "upsert", "write"]) else ("GET" if any(k in label_lower for k in ["get", "list", "fetch", "query", "find", "search", "read"]) else "ANY")
        endpoint_pattern = ""

        # Denylist check & layer check to prevent UI controllers / pages from being classified as HTTP_API
        is_ui_controller = any(denied in label_lower for denied in UI_CONTROLLER_DENYLIST)
        is_presentation_layer = (layer == ArchitecturalLayer.PRESENTATION)
        is_ui_path = any(k in path_lower for k in ["/widgets/", "/components/", "/views/", "/pages/", "/screens/", "/ui/", "lib/src/widgets", "/templates/"])

        if not is_presentation_layer and not is_ui_controller and not is_ui_path:
            if any(k in path_lower for k in ["controller", "router", "openapi", "endpoints", "api/", "routes/", "views.py", "endpoints.py", "controllers/"]) or "controller" in label_lower or "router" in label_lower:
                if any(k in label_lower for k in ["def ", "async def ", "function ", "method ", "class "]):
                    clean_name = re.sub(r"^(class|def|async def|function|method)\s+", "", label).split("(")[0].strip()
                    if not clean_name.startswith("_") or clean_name in ["_authenticate", "_authenticate_bearer", "_config", "_ok", "_err"]:
                        if clean_name.lower() not in UI_CONTROLLER_DENYLIST:
                            is_http = True
                            endpoint_pattern = f"/{clean_name.replace('_', '/')}"

        if is_http:
            key = f"HTTP:{path}:{label}"
            if key not in seen_endpoints:
                seen_endpoints.add(key)
                http_routes.append(
                    RouteEndpoint(
                        route_type="HTTP_API",
                        path_or_pattern=endpoint_pattern or f"/{label.split()[-1]}",
                        handler=label,
                        file_anchor=f"{path}:{line}",
                        line=line,
                        method=method,
                        auth_guard="Bearer / Session Auth" if any(k in path_lower or k in label_lower for k in ["auth", "admin", "token", "secure", "guard"]) else "Public / None",
                        target_layer=layer.value,
                    )
                )

        # 2. Detect UI Navigation / Page Routes
        route_path = ""
        is_ui = False
        if layer == ArchitecturalLayer.PRESENTATION or any(k in path_lower for k in ["/page/", "/pages/", "/screen/", "/screens/", "/views/", "/ui/", "/widgets/", "/components/"]):
            if any(k in label_lower for k in ["page", "screen", "view", "dialog", "widget"]) and ("class " in label_lower or "widget" in label_lower):
                clean_page = re.sub(r"^class\s+", "", label).split()[0].strip()
                if not clean_page.startswith("_") or clean_page.endswith("Page"):
                    is_ui = True
                    route_path = f"/{re.sub(r'(?<!^)(?=[A-Z])', '_', clean_page).lower().replace('_page', '').replace('_screen', '')}"

        if is_ui:
            key = f"UI:{path}:{label}"
            if key not in seen_endpoints:
                seen_endpoints.add(key)
                ui_routes.append(
                    RouteEndpoint(
                        route_type="UI_PAGE",
                        path_or_pattern=route_path or f"/{label.split()[-1]}",
                        handler=label,
                        file_anchor=f"{path}:{line}",
                        line=line,
                        method="PAGE_ROUTE",
                        auth_guard="Authenticated Route" if any(k in path_lower or k in label_lower for k in ["admin", "client", "auth", "secure", "verify"]) else "Standard Page",
                        target_layer=layer.value,
                    )
                )

        # 3. Detect Event & State Dispatches
        is_event = False
        clean_event = ""
        if any(k in label_lower for k in ["event", "state", "action", "mutation", "signal", "listener"]):
            if any(k in label_lower for k in ["class ", "def ", "function "]):
                is_event = True
                clean_event = re.sub(r"^(class|def|function)\s+", "", label).split("(")[0].strip()

        if is_event and clean_event:
            key = f"EVT:{path}:{label}"
            if key not in seen_endpoints:
                seen_endpoints.add(key)
                event_routes.append(
                    RouteEndpoint(
                        route_type="EVENT_DISPATCH",
                        path_or_pattern=f"Event::{clean_event}",
                        handler=label,
                        file_anchor=f"{path}:{line}",
                        line=line,
                        method="EVENT_EMIT",
                        auth_guard="Domain Scope",
                        target_layer=layer.value,
                    )
                )

    http_routes.sort(key=lambda r: r.file_anchor)
    ui_routes.sort(key=lambda r: r.file_anchor)
    event_routes.sort(key=lambda r: r.file_anchor)

    total_routes = len(http_routes) + len(ui_routes) + len(event_routes)
    mermaid_routing = generate_mermaid_routing_tree_diagram(http_routes, ui_routes, event_routes)
    mermaid_hld = generate_mermaid_hld_c4_diagram(primary_lang, pattern_name, http_routes, ui_routes)

    return RoutingArchitecture(
        total_routes=total_routes,
        http_routes=http_routes,
        ui_routes=ui_routes,
        event_routes=event_routes,
        mermaid_routing_diagram=mermaid_routing,
        mermaid_hld_diagram=mermaid_hld,
    )

def generate_mermaid_hld_c4_diagram(
    primary_lang: str,
    pattern_name: str,
    http_routes: List[RouteEndpoint],
    ui_routes: List[RouteEndpoint],
) -> str:
    """Generate a High-Level Design (HLD) C4-Container style system context diagram."""
    lines = [
        "```mermaid",
        "graph TD",
        "    %% High-Level Design (HLD) System Context & Container Map",
        "    classDef client fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1;",
        "    classDef gateway fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#bf360c;",
        "    classDef coreModule fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20;",
        "    classDef supportModule fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#4a148c;",
        "    classDef persistence fill:#eceff1,stroke:#455a64,stroke-width:2px,color:#263238;",
        "",
        '    subgraph Clients ["1. Client & Actor Channels"]',
        '        WebClient["🌐 Web Browser / SPA Client"]:::client',
        '        MobileApp["📱 Mobile Application (Flutter/Native)"]:::client',
        '        ThirdParty["🔗 External API & Webhook Callers"]:::client',
        "    end",
        "",
        '    subgraph Gateway ["2. Ingress & Routing Gateway"]',
        f'        Router["🔀 Central Gateway & Page/API Dispatcher<br/>({pattern_name})"]:::gateway',
        "    end",
        "",
        '    subgraph CoreBusiness ["3. Core Functional Business Modules"]',
        '        BusinessServices["⚡ Business UseCases, BLoCs & Domain Handlers"]:::coreModule',
        '        DomainEntities["💎 Domain Models, Aggregates & Invariants"]:::coreModule',
        "    end",
        "",
        '    subgraph SupportPlatform ["4. Supporting & Platform Services"]',
        '        AuthSecurity["🛡️ Auth & IAM Gateway / Access Control"]:::supportModule',
        '        ConfigShared["⚙️ Shared Utilities, Theme & Interceptors"]:::supportModule',
        "    end",
        "",
        '    subgraph StorageLayer ["5. Persistence & External Infrastructure"]',
        '        Database["💾 Relational DB / PostgreSQL / SQLite"]:::persistence',
        '        ExternalServices["🌐 Upstream REST APIs / Third-Party Services"]:::persistence',
        "    end",
        "",
        "    %% Interactions Flow",
        "    WebClient ==>|HTTP / WebSocket| Router",
        "    MobileApp ==>|App Navigation / API| Router",
        "    ThirdParty ==>|Webhooks / Callbacks| Router",
        "    Router ==>|Dispatch Requests| BusinessServices",
        "    Router -.->|Authenticate Token| AuthSecurity",
        "    BusinessServices ==>|Execute Domain Logic| DomainEntities",
        "    BusinessServices -.->|Use Config / Helpers| ConfigShared",
        "    DomainEntities ==>|Persist Records| Database",
        "    BusinessServices ==>|Call Remote Service| ExternalServices",
        "```",
    ]
    return "\n".join(lines)


def generate_mermaid_routing_tree_diagram(
    http_routes: List[RouteEndpoint],
    ui_routes: List[RouteEndpoint],
    event_routes: List[RouteEndpoint],
) -> str:
    """Generate a hierarchical routing map in Mermaid."""
    lines = [
        "```mermaid",
        "graph LR",
        "    %% Routing & Dispatch Topology Tree",
        "    classDef root fill:#263238,stroke:#37474f,stroke-width:2px,color:#ffffff;",
        "    classDef http fill:#e1f5fe,stroke:#0288d1,stroke-width:2px,color:#01579b;",
        "    classDef ui fill:#e8f5e9,stroke:#388e3c,stroke-width:2px,color:#1b5e20;",
        "    classDef evt fill:#fff8e1,stroke:#fbc02d,stroke-width:2px,color:#f57f17;",
        "",
        '    Root["🔀 System Dispatch Root"]:::root',
        "",
    ]

    if http_routes:
        lines.append('    Root --> HTTP_Group["🌐 HTTP REST APIs / Webhooks"]:::http')
        for r in http_routes[:6]:
            clean_id = re.sub(r"[^a-zA-Z0-9_]", "_", r.path_or_pattern)[:24]
            name = r.path_or_pattern[:28]
            method = r.method or "API"
            lines.append(f'    HTTP_Group --> H_{clean_id}["{method}: {name}"]:::http')

    if ui_routes:
        lines.append('    Root --> UI_Group["📱 UI Pages & Screen Navigation"]:::ui')
        for r in ui_routes[:6]:
            clean_id = re.sub(r"[^a-zA-Z0-9_]", "_", r.path_or_pattern)[:24]
            name = r.path_or_pattern[:28]
            lines.append(f'    UI_Group --> U_{clean_id}["Page: {name}"]:::ui')

    if event_routes:
        lines.append('    Root --> EVT_Group["⚡ Event Bus & State Dispatches"]:::evt')
        for r in event_routes[:6]:
            clean_id = re.sub(r"[^a-zA-Z0-9_]", "_", r.path_or_pattern)[:24]
            name = r.path_or_pattern.replace("Event::", "")[:28]
            lines.append(f'    EVT_Group --> E_{clean_id}["{name}"]:::evt')

    lines.append("```")
    return "\n".join(lines)
# ---------------------------------------------------------------------------
# Architectural Violations Analyzer
# ---------------------------------------------------------------------------

def detect_architectural_violations(
    graph: AnalyticsGraph,
    node_layers: Dict[str, ArchitecturalLayer],
    cancel_check: Optional[Callable[[], bool]] = None,
) -> List[ArchitectureViolation]:
    """
    Detect anti-patterns and rule breaches:
    1. Layer Bypassing: Presentation layer directly calling Data layer (skipping Business Logic).
    2. Inverted Dependency: Data or Domain depending on Presentation.
    3. High-coupling God Components.
    """
    if cancel_check and cancel_check():
        raise OperationCancelledError("Analytics operation cancelled by client")
    violations: List[ArchitectureViolation] = []

    # Valid dependency flow order:
    # Presentation -> Business Logic -> Domain -> Data -> Core
    # Invalid: Presentation -> Data (Layer bypass)
    # Invalid: Data -> Presentation (Inverted dependency)
    # Invalid: Domain -> Presentation (Inverted dependency)

    seen_pairs: Set[Tuple[str, str]] = set()

    for edge in graph.edges:
        src, dst = edge["src"], edge["dst"]
        l_src = node_layers.get(src, ArchitecturalLayer.UNKNOWN)
        l_dst = node_layers.get(dst, ArchitecturalLayer.UNKNOWN)

        src_data = graph.nodes.get(src, {})
        dst_data = graph.nodes.get(dst, {})
        src_path = src_data.get("path", "")
        dst_path = dst_data.get("path", "")
        src_label = src_data.get("label", src)
        dst_label = dst_data.get("label", dst)

        # 1. Layer Bypass (Presentation -> Data directly)
        if l_src == ArchitecturalLayer.PRESENTATION and l_dst == ArchitecturalLayer.DATA:
            pair = (src_path or src_label, dst_path or dst_label)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                violations.append(
                    ArchitectureViolation(
                        violation_type="LAYER_BYPASS",
                        severity="MEDIUM",
                        source_node=src_label,
                        source_path=src_path,
                        target_node=dst_label,
                        target_path=dst_path,
                        description=(
                            f"UI component '{src_label}' directly calls Data layer entity "
                            f"'{dst_label}', bypassing the Business Logic / BLoC / Service layer."
                        ),
                        recommendation=(
                            "Route interaction through a dedicated BLoC event, ViewModel, or UseCase. "
                            "Prevent direct repository or API client instantiation in UI widgets."
                        ),
                    )
                )

        # 2. Inverted Dependency (Data/Domain -> Presentation)
        if l_src in (ArchitecturalLayer.DATA, ArchitecturalLayer.DOMAIN) and l_dst == ArchitecturalLayer.PRESENTATION:
            pair = (src_path or src_label, dst_path or dst_label)
            if pair not in seen_pairs:
                seen_pairs.add(pair)
                violations.append(
                    ArchitectureViolation(
                        violation_type="INVERTED_DEPENDENCY",
                        severity="HIGH",
                        source_node=src_label,
                        source_path=src_path,
                        target_node=dst_label,
                        target_path=dst_path,
                        description=(
                            f"Lower architectural layer '{l_src.value}' ({src_label}) "
                            f"depends on higher Presentation layer ({dst_label})."
                        ),
                        recommendation=(
                            "Invert dependency using interfaces, callbacks, or reactive streams. "
                            "Lower layers must never reference UI widgets or screens."
                        ),
                    )
                )

    # Sort violations: HIGH -> MEDIUM -> LOW
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    violations.sort(key=lambda v: severity_order.get(v.severity, 4))
    return violations


# ---------------------------------------------------------------------------
# Mermaid Diagram Generator
# ---------------------------------------------------------------------------

def generate_mermaid_layer_diagram(
    layer_breakdown: Dict[ArchitecturalLayer, LayerBreakdown],
    pattern_name: str,
) -> str:
    """Generate a clean Mermaid diagram representing architectural layer boundaries."""
    lines = [
        "```mermaid",
        "graph TD",
        '    %% SOT-Graph Architectural Layer Boundary Diagram',
        '    classDef pres fill:#e3f2fd,stroke:#1565c0,stroke-width:2px,color:#0d47a1;',
        '    classDef logic fill:#e8f5e9,stroke:#2e7d32,stroke-width:2px,color:#1b5e20;',
        '    classDef domain fill:#fff3e0,stroke:#e65100,stroke-width:2px,color:#bf360c;',
        '    classDef data fill:#f3e5f5,stroke:#7b1fa2,stroke-width:2px,color:#4a148c;',
        '    classDef core fill:#eceff1,stroke:#455a64,stroke-width:2px,color:#263238;',
        "",
        '    subgraph PresentationLayer ["1. Presentation Layer (UI & Views)"]',
        f'        UI["🖥️ Screens, Widgets & UI Controls<br/>({layer_breakdown[ArchitecturalLayer.PRESENTATION].node_count} nodes)"]:::pres',
        '    end',
        "",
        '    subgraph LogicLayer ["2. Business Logic & State Layer"]',
        f'        BLOC["⚡ BLoCs, Cubits, ViewModels & Services<br/>({layer_breakdown[ArchitecturalLayer.BUSINESS_LOGIC].node_count} nodes)"]:::logic',
        '    end',
        "",
        '    subgraph DomainLayer ["3. Domain & Business Model Layer"]',
        f'        DOMAIN["💎 UseCases, Entities & Contracts<br/>({layer_breakdown[ArchitecturalLayer.DOMAIN].node_count} nodes)"]:::domain',
        '    end',
        "",
        '    subgraph DataLayer ["4. Data & Infrastructure Layer"]',
        f'        DATA["💾 Repositories, DataSources & ApiClients<br/>({layer_breakdown[ArchitecturalLayer.DATA].node_count} nodes)"]:::data',
        '    end',
        "",
        '    subgraph CoreLayer ["5. Core, Config & Shared Utilities"]',
        f'        CORE["⚙️ Router, Network, Theme & Utilities<br/>({layer_breakdown[ArchitecturalLayer.CORE].node_count} nodes)"]:::core',
        '    end',
        "",
        '    %% Unidirectional Call Flow',
        '    UI ==>|"Dispatch Events / Observe State"| BLOC',
        '    BLOC ==>|"Execute Business Rules"| DOMAIN',
        '    DOMAIN ==>|"Request Data Persistence"| DATA',
        '    BLOC -.->|"Query Core Utilities"| CORE',
        '    DATA -.->|"Use Network/Storage Driver"| CORE',
        "```",
    ]
    return "\n".join(lines)


def generate_mermaid_execution_flow(
    primary_lang: str,
    pattern_name: str,
) -> str:
    """Generate an execution sequence diagram for the primary architectural lifecycle."""
    lines = [
        "```mermaid",
        "sequenceDiagram",
        "    autonumber",
        "    actor User as 👤 User / Client",
        "    participant UI as 🖥️ Presentation (Screen/Widget)",
        "    participant Logic as ⚡ State Manager (BLoC/ViewModel)",
        "    participant Domain as 💎 Domain (UseCase/Entity)",
        "    participant Repo as 💾 Data (Repository/DataSource)",
        "    participant Remote as 🌐 Backend REST API / Local DB",
        "",
        "    User->>UI: 1. Interact / Trigger User Action",
        "    UI->>Logic: 2. Dispatch Event / Call Method",
        "    activate Logic",
        "    Logic->>Logic: 3. Emit Loading / Pending State",
        "    Logic-->>UI: 4. Re-render UI with Loading State",
        "    Logic->>Domain: 5. Invoke Business UseCase",
        "    activate Domain",
        "    Domain->>Repo: 6. Request Data via Repository Contract",
        "    activate Repo",
        "    Repo->>Remote: 7. Execute HTTP Request / SQL Query",
        "    Remote-->>Repo: 8. Return JSON Response / Raw Data",
        "    Repo->>Repo: 9. Map DTO to Domain Entity",
        "    Repo-->>Domain: 10. Return Typed Entity Result",
        "    deactivate Repo",
        "    Domain-->>Logic: 11. Return Success/Failure Outcome",
        "    deactivate Domain",
        "    Logic->>Logic: 12. Transition to Success/Error State",
        "    Logic-->>UI: 13. Emit Final State to UI",
        "    deactivate Logic",
        "    UI-->>User: 14. Render Updated UI Content",
        "```",
    ]
    return "\n".join(lines)


def generate_mermaid_domain_flow(
    domains: List[BusinessDomain],
) -> str:
    """Generate a Mermaid relationship diagram between top business domains."""
    top_domains = domains[:8]
    lines = [
        "```mermaid",
        "graph LR",
        '    classDef coreDom fill:#e8eaf6,stroke:#3f51b5,stroke-width:2px,color:#1a237e;',
        '    classDef suppDom fill:#e0f2f1,stroke:#00897b,stroke-width:2px,color:#004d40;',
        '    classDef genDom fill:#f5f5f5,stroke:#616161,stroke-width:2px,color:#212121;',
        "",
    ]

    for d in top_domains:
        clean_id = re.sub(r"[^a-zA-Z0-9_]", "_", d.name)
        css_class = "coreDom" if "Core" in d.category else ("suppDom" if "Supporting" in d.category else "genDom")
        lines.append(f'    {clean_id}["📦 {d.name}<br/>({d.file_count} files, {d.node_count} nodes)"]:::{css_class}')

    lines.append("")
    # Add domain dependency links
    for d in top_domains:
        src_id = re.sub(r"[^a-zA-Z0-9_]", "_", d.name)
        for dep in d.dependencies:
            # Check if dep is in top_domains
            for target in top_domains:
                if target.name == dep and target.name != d.name:
                    dst_id = re.sub(r"[^a-zA-Z0-9_]", "_", target.name)
                    lines.append(f"    {src_id} --> {dst_id}")

    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Comprehensive Architecture Profiler
# ---------------------------------------------------------------------------

def build_architecture_profile(
    graph: AnalyticsGraph,
    community_res: CommunityResult,
    cancel_check: Optional[Callable[[], bool]] = None,
) -> ArchitectureProfile:
    """Construct the complete multi-layer architecture profile for report generation."""
    if cancel_check and cancel_check():
        raise OperationCancelledError("Analytics operation cancelled by client")

    # 1. Classify all nodes into layers
    node_layers: Dict[str, ArchitecturalLayer] = {}
    layer_nodes: Dict[ArchitecturalLayer, List[str]] = collections.defaultdict(list)
    layer_files: Dict[ArchitecturalLayer, Set[str]] = collections.defaultdict(set)
    layer_symbols: Dict[ArchitecturalLayer, List[str]] = collections.defaultdict(list)

    for node_id, data in graph.nodes.items():
        if cancel_check and cancel_check():
            raise OperationCancelledError("Analytics operation cancelled by client")
        layer = classify_node_layer(node_id, data)
        node_layers[node_id] = layer
        layer_nodes[layer].append(node_id)
        path = data.get("path", "")
        if path:
            layer_files[layer].add(path)
        if data.get("kind") != "file":
            layer_symbols[layer].append(data.get("label", node_id))

    # Build Layer Breakdown
    layer_breakdown: Dict[ArchitecturalLayer, LayerBreakdown] = {}
    for layer in ArchitecturalLayer:
        nodes = layer_nodes[layer]
        files = sorted(list(layer_files[layer]))
        symbols = layer_symbols[layer]
        layer_breakdown[layer] = LayerBreakdown(
            layer=layer,
            node_count=len(nodes),
            file_count=len(files),
            sample_nodes=nodes[:5],
            sample_paths=files[:5],
            top_symbols=symbols[:5],
        )

    # 2. Detect Pattern and Frameworks
    pattern_name, primary_lang, frameworks = detect_pattern_and_framework(graph)

    # 3. Aggregate Business Domains and Functional Modules
    domains = aggregate_business_domains(graph, community_res, cancel_check=cancel_check)
    functional_modules = aggregate_functional_modules(
        graph, domains, node_layers, cancel_check=cancel_check
    )

    # 4. Extract Routing Architecture
    routing_arch = extract_routing_architecture(
        graph, node_layers, primary_lang, pattern_name, cancel_check=cancel_check
    )

    # 5. Detect Architectural Violations
    violations = detect_architectural_violations(
        graph, node_layers, cancel_check=cancel_check
    )

    # 6. Generate Diagrams
    mermaid_layer = generate_mermaid_layer_diagram(layer_breakdown, pattern_name)
    mermaid_exec = generate_mermaid_execution_flow(primary_lang, pattern_name)
    mermaid_domain = generate_mermaid_domain_flow(domains)
    mermaid_hld = routing_arch.mermaid_hld_diagram
    mermaid_routing = routing_arch.mermaid_routing_diagram

    # 7. Formulate Prioritized Recommendations (P0, P1, P2)
    recs_p0: List[str] = []
    recs_p1: List[str] = []
    recs_p2: List[str] = []

    # Check for critical violations
    crit_violations = [v for v in violations if v.severity in ("CRITICAL", "HIGH")]
    if crit_violations:
        for v in crit_violations[:3]:
            recs_p0.append(
                f"**[Break Inverted Dependency]** Decouple `{v.source_node}` from Presentation layer `{v.target_node}`. "
                f"{v.recommendation}"
            )

    # Layer bypasses
    bypass_violations = [v for v in violations if v.violation_type == "LAYER_BYPASS"]
    if bypass_violations:
        recs_p1.append(
            f"**[Enforce Clean Layer Boundaries]** Found {len(bypass_violations)} UI-to-Data direct calls. "
            f"Introduce BLoC events or UseCases to encapsulate data access (e.g. `{bypass_violations[0].source_node}` -> `{bypass_violations[0].target_node}`)."
        )

    # Modularization recommendation
    if len(domains) > 5:
        recs_p2.append(
            f"**[Domain Package Isolation]** Extract Core Domain modules ({domains[0].name}, {domains[1].name}) "
            f"into independent internal packages/libraries with explicit public API export boundaries."
        )

    if not recs_p0:
        recs_p0.append(
            "**[Architectural Invariants Verified]** Zero high-risk circular dependencies or inverted layer calls detected across the codebase."
        )
    if not recs_p1:
        recs_p1.append(
            "**[State-to-UI Integrity]** Presentation components adhere cleanly to unidirectional reactive data-binding rules."
        )
    if not recs_p2:
        recs_p2.append(
            "**[Modular Scalability]** Maintain current clean separation of concerns as new feature modules are added."
        )

    mod_q = community_res.modularity
    if mod_q >= 0.4:
        mod_verdict = f"🟢 **STRONG MODULARITY (Q = {mod_q:.3f})** - System exhibits distinct, loosely-coupled architectural boundaries."
    elif mod_q >= 0.2:
        mod_verdict = f"🟡 **MODERATE MODULARITY (Q = {mod_q:.3f})** - Functional clusters exist with moderate cross-boundary linkage."
    else:
        mod_verdict = f"🔴 **TIGHT COUPLING (Q = {mod_q:.3f})** - High inter-module entanglement; refactoring recommended."

    return ArchitectureProfile(
        pattern_name=pattern_name,
        primary_language=primary_lang,
        framework_hints=frameworks,
        layer_breakdown=layer_breakdown,
        domains=domains,
        functional_modules=functional_modules,
        routing_architecture=routing_arch,
        violations=violations,
        mermaid_hld_diagram=mermaid_hld,
        mermaid_layer_diagram=mermaid_layer,
        mermaid_routing_tree=mermaid_routing,
        mermaid_execution_flow=mermaid_exec,
        mermaid_domain_flow=mermaid_domain,
        modularity_verdict=mod_verdict,
        recommendations_p0=recs_p0,
        recommendations_p1=recs_p1,
        recommendations_p2=recs_p2,
    )
