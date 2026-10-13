# ResearchOS

ResearchOS is a planned open-source research workspace for organizing scientific papers, producing evidence-grounded analyses, and building a reusable research knowledge base.

The project is currently in planning. No application, benchmark, or provider integration has been implemented or verified yet.

## Project documents

- [Implementation roadmap (Persian)](docs/ROADMAP.md)
- [Original project specification (English)](docs/PROJECT_SPEC.md)
- [Contributor and implementation instructions](AGENTS.md)

## Planned architecture

A modular monolith with a Python/FastAPI backend, a Next.js/TypeScript frontend, PostgreSQL, Redis, and Celery. Vector retrieval with pgvector comes after the initial paper-analysis workflow is usable.

AI providers, document parsers, storage, and retrieval strategies will have replaceable interfaces. Uploaded documents and generated claims will retain source references and processing versions.

## First usable release

Create a research project, upload a PDF, configure an AI provider and model, follow background processing, inspect a structured analysis alongside its source evidence, and revisit saved results.

The frontend will be developed alongside each feature. Testing will use clearly identified mocks without paid credentials; real-provider verification will be reported separately.

## Development workflow

Work on the local `master` branch and push completed, verified increments to the remote `master` branch. The configured Git remote is also named `master`.

Installation, deployment instructions, test outcomes, and screenshots will be added when the corresponding functionality exists.
