# 🔒 Security Policy

We take the security of Agent OS and the applications built on top of it very seriously. As a runtime environment that orchestrates agent permissions and sandboxing, robust security is at the core of our project.

## Reporting a Vulnerability

**Please do not report security vulnerabilities via public GitHub Issues.**

If you discover a security vulnerability (such as a sandbox bypass, firewall evasion, privilege escalation, or resource quota exhaustion exploit), please report it responsibly by following these steps:

1.  **Email Us**: Send an email describing the vulnerability to our security team. (For the PoC stage, please contact the repository owner at `security-alert@yourdomain.com`).
2.  **Describe the Details**: Please include as much detail as possible, including:
    *   Steps to reproduce the vulnerability (including payloads or sample codes).
    *   The potential impact of the exploit.
    *   Any suggested remediation or patches if available.
3.  **Vulnerability Triage**: We will acknowledge receipt of your report within 48 hours and work with you to analyze and resolve the issue.

## Sandbox & Firewall Boundaries

For security researcher audits, please note that the following are considered critical security boundaries:
-   **WasmSandbox**: The execution boundary of untrusted WASM bytes. Any execution escaping from Wasmtime memory/fuel limits is treated as a Critical vulnerability.
-   **AutonomyPolicy (Filesystem & Commands)**: The restriction of host file read/writes to `allowed_paths` and shell executions to the command whitelist. Any execution of unwhitelisted commands or access to denied paths (e.g. `/etc/passwd` or host envs) is treated as a Critical vulnerability.
-   **WriteGate (SHACL & Nonce)**: The strict 3-stage validation process. A write action bypass without verifying a signed cryptographic nonce is treated as a High vulnerability.

Thank you for helping keep Agent OS safe!
