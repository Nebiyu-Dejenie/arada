# ARADA Charter

These are the owner's governing directives for the ARADA project, stored verbatim (whitespace normalised) so that every future design and implementation decision can be checked against the source text.

| Document | Issued | Role |
|---|---|---|
| [PERMANENT_COMMAND.md](PERMANENT_COMMAND.md) | 2026-09-26 | **Governs.** Permanent operating command: engineering principles, question policy, phase order, definition of done, and the report format. |
| [MASTER_DIRECTIVE.md](MASTER_DIRECTIVE.md) | 2026-09-26 | Business model and platform scope: the three-level model, the 18 verticals, the Business Factory, finance, Telegram, security and infrastructure requirements. |

## Precedence

1. The owner's most recent explicit instruction.
2. `PERMANENT_COMMAND.md`
3. `MASTER_DIRECTIVE.md`
4. Accepted ADRs (`docs/adr/`)

When two sources conflict, the higher one wins, and the resolution is recorded here.

## Resolved conflicts

| Topic | Master Directive said | Permanent Command says | Resolution |
|---|---|---|---|
| Root domain | "The existing root domain… registrar at Hostinger" | `ROOT_DOMAIN = TBD`. **Do not use `arada.fun` or `arada.click`**; they belong to unrelated projects. Ask only at the domain phase. | Domain is a configuration value (`ROOT_DOMAIN`), currently TBD. See ADR-026. |
| Hostname convention | Evaluate and document a decision before implementation | Do not finalise the naming convention until the domain/tenant-routing phase | The evaluation is kept as input (`05`). The decision is deferred (ADR-008). |
| Phase order | Phases 0–15 (§91) | Phases 0–9 (§55), with a reference vertical *before* the Merchant Factory | §55 governs (`15_ROADMAP.md`, ADR-027). |
| Infrastructure sizing | Every service must declare explicit CPU/RAM/storage | Never invent CPU/RAM/storage values; base the topology on actual machine resources | Every service declares requirements, but the values stay TBD until they are measured or supplied (`11`, `14`). |
| Trade-off priority | Correctness, tenant isolation, financial integrity, security, reliability, observability, maintainability, automation, cost, scalability, UX | Correctness → security → maintainability → extensibility → reliability → cost efficiency → scale | The Permanent Command's order governs. Tenant isolation and financial integrity are treated as parts of correctness and security, so they still outrank everything else. |
| Questions | Ask the 14 listed questions before implementation | Ask only questions that block the *next* phase; record the rest as KNOWN / ASSUMED / UNKNOWN / BLOCKING | The question register in `20_DECISIONS.md` uses the Permanent Command's policy. |
