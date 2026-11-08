# WAKER BLIND EVALUATION SPECIFICATION (KAGGLE MODE)
**Feature:** Hidden Test Vault & Blind Evaluation  
**Author:** Tuankhoa (Founder / Lead Architect) & Antigravity  
**Target Version:** `waker-ai v1.1.0+`

## 1. Core Problem
When the coding agent (Coder) writes both code and tests, it suffers from self-grading bias, tautological assertions, and test leakage. The tests become ineffective at catching genuine bugs.

## 2. Kaggle-Style Blind Architecture
- **Architect (Chatbox):** Defines public API contracts in `tasks.yaml` and authors hidden test suites into `.waker/vault/`.
- **Waker Supervisor:** Locks `.waker/vault/` away from worker read permissions.
- **Worker (Coder):** Only sees public specs, interfaces, and sample tests. Implements the solution blind to edge-case tests.
- **Evaluation Gate:** Waker dynamically injects hidden test suites during verify phase. If tests fail, returns high-level diagnostic without leaking test source code.
