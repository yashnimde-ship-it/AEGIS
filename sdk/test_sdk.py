"""
Simulates a student's agent using @aegis.trace.
Runs against the local backend (make sure it's running on :8000).
Uses a fake LLM response so no real OpenAI key needed.
"""
import sys
import time
sys.path.insert(0, ".")

import aegis


# --- Fake OpenAI-style response ---
class FakeUsage:
    prompt_tokens     = 400
    completion_tokens = 150

class FakeResponse:
    model = "gpt-4o"
    usage = FakeUsage()

    def model_dump(self):
        return {"model": self.model, "usage": {"prompt_tokens": 400, "completion_tokens": 150}}


aegis.init(
    agent_name="demo-agent",
    api_url="https://aegis-wg8k.onrender.com",
    budget_per_run=0.004,  # call 1=$0.0025 (ok), call 2=$0.005 (crosses $0.004), call 3=blocked
)


@aegis.trace
def ask_llm(prompt: str):
    """Each call costs ~$0.0025 at 400 input + 150 output tokens on gpt-4o."""
    time.sleep(0.05)
    return FakeResponse()


# Outer traced function — all ask_llm calls inside share one run_id.
# This is the recommended pattern: trace the task, not individual LLM calls.
@aegis.trace
def run_agent_task(question: str):
    for i in range(1, 6):
        try:
            resp = ask_llm(f"{question} (step {i})")
            print(f"  Step {i}: OK  model={resp.model}")
        except aegis.AegisBudgetError as e:
            print(f"  Step {i}: BLOCKED — {e}")
            return


print("=== AEGIS SDK smoke test ===\n")
print("Running agent task (budget $0.004, each call ~$0.0025)...")
print("Expected: step 1 OK, step 2 OK, step 3 BLOCKED.\n")

run_agent_task("Explain recursion")

print("\nDone.")
print("Alerts:  http://127.0.0.1:8000/alerts")
print("Agents:  http://127.0.0.1:8000/agents")
