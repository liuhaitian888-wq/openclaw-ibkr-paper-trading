# News body and bounded historical replay implementation plan

Goal: Deliver actual retained broker article text to secretary evidence tools and an executable bounded historical replay using existing strategy interfaces, with a reproducible real-data run.
Architecture: Reuse tested5f/67 news producer/body/reader changes on00cfe81 without new collection workers. Add a bounded local manifest/CSV replay using strategies.base plus existing DualMA/mean-reversion; execute next-event market-price assumption with explicit costs and cash settlement; chronological development/held-out reports. No broker/service/productionDB access by replay.
Tech stack: Python standard library, existing strategy classes, isolated unittest suite.

- [x] Confirm real human scope; preserve independent source/publication ownership and production gates.
- [x] Check saved local/cloud datasets: rehearsal quotes simulated, quote-state tables empty, historical observer only persists bar endpoints; selected raw-callback searches empty. Do not use these as real OHLCV.
- [ ] Complete news revision/time/hash/TTL/text readers and evidence-based deterministic research summary, tests.
- [ ] Implement manifest validation, bounded chronological runner, explicit costs/cash/settlement and reproducible result artifacts; tests expose lookahead/cost/settlement failures.
- [ ] Obtain a small public publisher historical sample locally if no saved eligible dataset; record exact source bytes/hash, transforms, timestamps, period/security identity and limitations. No cloud public-DEFERRED bypass or large downloads.
- [ ] Execute actual real-history replay locally, preserve source/result fingerprints, do not claim a synthetic run or pre-registered OOS.
- [ ] Sync existing OpenSpec/specs/tasks and affected diagram dependencies, full linked suite, secrets and fixed commit handoff to sole publisher.
