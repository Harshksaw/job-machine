import os
import sys
import httpx

SAMPLE_JDS = [
    ("Acme Cloud", "Backend Engineer",
     "We're looking for a backend engineer with experience in distributed "
     "systems, message queues, Go or Python, and cloud infrastructure (AWS "
     "or GCP). You'll own service reliability and CI/CD."),
    ("Vectra AI", "AI/ML Engineer",
     "Seeking an engineer to build RAG pipelines, work with vector "
     "databases, and integrate LLM providers with failover. Python and "
     "LangChain experience required."),
    ("Ridewell", "Mobile Engineer",
     "Build and maintain our React Native rider app serving thousands of "
     "users, including native module work and CI/CD for app store "
     "releases."),
]


def main() -> int:
    base_url = os.environ.get("RESUME_TAILOR_URL", "http://localhost:8420")

    failures = []
    for company, role, jd_text in SAMPLE_JDS:
        resp = httpx.post(
            f"{base_url}/tailor",
            json={"jd_text": jd_text, "company": company, "role": role},
            timeout=60,
        )
        if resp.status_code != 200:
            failures.append(f"{company}/{role}: HTTP {resp.status_code} {resp.text}")
            continue
        body = resp.json()
        if body["pages"] != 1:
            failures.append(f"{company}/{role}: expected 1 page, got {body['pages']}")
            continue
        print(f"OK  {company}/{role} -> {body['pdf_path']} ({body['pages']} page)")

    if failures:
        print("\nFAILURES:")
        for f in failures:
            print(f"  - {f}")
        return 1

    print(f"\nAll {len(SAMPLE_JDS)} sample job descriptions produced valid one-page resumes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
