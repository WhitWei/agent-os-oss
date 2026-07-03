---
name: agentos
description: The safety and governance skill for LLM Agents executing tasks. Trigger whenever planning to execute dangerous commands, write data to databases (Neo4j), or modify project code logic.
---

# 🛡️ Agent OS Governance Skill

**CRITICAL RULE**: As an AI Agent, you are operating within a strictly governed runtime (Agent OS). You MUST NOT bypass the security measures. All physical data writes and high-risk executions must be funneled through the `agentos` CLI tool.

## 🚀 Routing Logic

When deciding how to fulfill the user's request, apply the following routing logic:

### 1. Complex Reasoning / Code Generation / Script Execution
If the task requires code generation, script validation, or iterative complex problem-solving, you MUST delegate it to the **Global-Loop-Engine (GLE)** via the `agentos loop run` plugin command.

- **Command**:
  ```bash
  agentos loop run --task "<detailed prompt and success criteria>"
  ```
- **Why**: GLE has an internal reasoning loop that safely experiments and generates reliable output within the sandbox.

### 2. Physical Data Writes / Database Commits (Neo4j)
If the task requires committing entities, relationships, or ontologies to the physical Neo4j graph database, you MUST NOT execute raw Cypher queries. Instead, follow the two-step **Governance Moat** process using `agentos validate` and `agentos write`.

#### Step 2.1: Validate (Generate Nonce)
First, validate your RDF/TTL payload against the SHACL rules for the domain.
- **Command**:
  ```bash
  agentos validate <domain> <path-to-data.ttl>
  ```
- **Result**: If the validation passes, the CLI will output a cryptographically signed **Nonce** (e.g., `Validation passed. Nonce: 1718029393:a1b2c3d4...`). You must capture this Nonce!

#### Step 2.2: Governed Write (Commit)
Second, use the exact Nonce obtained from Step 2.1 to perform the write. The WriteGate will verify the signature and execute the Neo4j `MERGE` automatically.
- **Command**:
  ```bash
  agentos write <domain> <nonce> <path-to-data.ttl>
  ```
- **Result**: The data is safely persisted to Neo4j.

## 🛑 Forbidden Actions

- ❌ **Do NOT run `docker exec`** or `cypher-shell` directly to write into the Neo4j container. That bypasses the WriteGate and violates the governance policy.
- ❌ **Do NOT execute untrusted code blindly**. If unsure, delegate to `agentos loop run`.

## 🛠️ Typical Workflow Example

```bash
# 1. You prepare data in a .ttl file for the "it-asset-mgmt" domain
echo "<http://agent-os.local/data/employee/emp-001> <http://agent-os.local/ontology/it-asset-mgmt#employeeName> \"Alice\" ." > new_emp.ttl

# 2. You request a validation Nonce
NONCE=$(agentos validate it-asset-mgmt new_emp.ttl | grep "Nonce:" | awk '{print $3}')

# 3. You commit the data using the obtained Nonce
agentos write it-asset-mgmt $NONCE new_emp.ttl
```

By following these rules, you guarantee compliance with the semantic firewall, budget constraints, and database safety policies defined by Agent OS.
