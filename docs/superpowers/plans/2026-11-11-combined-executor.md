# Combined executor implementation plan

Goal: Wire compact fixed-class output into the real AppServer purpose with bounded failure diagnostics.
Architecture: Preserve730c172 progress/provenance; reuse d0c2230 metadata/error/cleanup changes and ef2847f hash/anchor/AST decoder. Only scoped_patch switches schema/instructions. Production and originalUNKNOWN remain untouched.
Tech stack: Python, existing native JSONRPC fakechild, isolated Git/AST tests.

- [x] Fix exact base and explicit component-owner coordination.
- [x] Reproduce missing compact schema through fakechild outputSchema assertion.
- [x] Wire compact schema/instructions and verify33 focused tests.
- [x] Complete full offline suite, strict all validation, secret scan, context/diagram impact and publisher handoff.
