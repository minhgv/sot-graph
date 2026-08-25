# SOT-Graph Known Limitations & Tradeoffs

## 1. Dynamic Metaprogramming & Reflection
- **Python / Ruby / JS `eval` / `getattr` / `send`**: Highly dynamic symbol invocations cannot be statically resolved via AST or SCIP indexers. SOT-Graph flags dynamic calls with `call_kind: "DYNAMIC"` rather than guessing edges.
- **Dependency Injection Frameworks**: Runtime DI containers (e.g. Spring in Java, NestJS in TypeScript) where interface implementations are bound via external XML/annotations are resolved to interface definitions.

## 2. Multi-Language Monorepo Cross-Language Boundaries
- Cross-language RPC boundaries (e.g., Python client calling Go gRPC server) are linked via API routing / solution trace heuristic tables (`api_cross_bindings`), not raw intra-language compiler references.

## 3. SCIP Index Freshness Dependency
- SCIP evidence requires generating SCIP index files (`scip-python`, `scip-typescript`, `scip-java`) through compiler toolchains. When source files drift past their recorded snapshot hashes without a re-index, SOT-Graph automatically marks SCIP provider evidence as `STALE` and falls back to live AST reconciliation.
