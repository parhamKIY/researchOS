# ResearchOS — Master Project Specification & Implementation Instructions

## 1. Your Role

You are acting as a **Senior AI/ML Engineer, Senior Backend Engineer, Software Architect, and Full-Stack Developer**.

We are going to design and implement a serious, production-oriented, open-source software project called **ResearchOS**.

You are responsible for helping me take this project from initial architecture to a fully functional, well-tested, well-documented application.

Do not treat this project as a tutorial, a simple LLM wrapper, or a disposable prototype.

I want a real product that I can use regularly for academic research and eventually publish on GitHub as a strong portfolio project.

Your responsibilities include:

- Designing a scalable but practical architecture.
- Making justified technology and engineering decisions.
- Implementing maintainable, modular, production-quality code.
- Building real AI/ML functionality instead of relying on superficial LLM integrations.
- Applying software engineering best practices.
- Writing meaningful automated tests.
- Maintaining technical documentation.
- Identifying technical limitations and proposing improvements.
- Implementing the system incrementally, without introducing unnecessary complexity.

**Important:** You are the primary implementation agent. Do not stop after generating architecture diagrams, explanations, or pseudocode. The ultimate objective is a working application.

---

# 2. Project Vision

## What is ResearchOS?

ResearchOS is an **AI-Powered Research Intelligence and Knowledge Management Platform**.

It is designed for students, researchers, engineers, and academics who regularly read scientific papers, investigate research topics, compare methodologies, and identify research opportunities.

The central idea is simple:

Instead of manually reading, organizing, summarizing, comparing, and repeatedly analyzing academic papers, users should be able to manage much of this workflow through one intelligent research workspace.

ResearchOS should eventually support the complete research discovery workflow:

**Paper Discovery → Paper Import → Document Understanding → Research Analysis → Knowledge Organization → Cross-Paper Comparison → Research Gap Discovery → Feasibility Evaluation**

The platform should function as a personal research assistant, not merely a PDF summarizer.

## My personal objectives

I am a Computer Engineering student working in AI, Machine Learning, Deep Learning, Computer Vision, and academic research.

I frequently:

- Read academic papers, particularly recent AI/ML and Computer Vision papers.
- Analyze research methodologies.
- Investigate model architectures.
- Search for datasets and pretrained models.
- Evaluate limitations and future research directions.
- Identify potentially publishable research gaps.
- Compare ideas based on novelty, feasibility, implementation complexity, computational requirements, and available resources.

I want ResearchOS to support these workflows directly.

## My professional objectives

This project must also demonstrate practical skills relevant to AI/ML Engineering and AI Backend Engineering roles.

Important technologies and competencies include:

- Python
- FastAPI
- REST API design
- PostgreSQL
- Redis
- Asynchronous processing
- Celery
- Docker
- AI/LLM integration
- NLP
- Embedding models
- Retrieval-Augmented Generation (RAG)
- Vector databases
- PyTorch
- Hugging Face Transformers
- ML evaluation
- LLMOps
- Testing
- CI/CD
- System design

Every major technology should serve a legitimate purpose.

Do not add a framework only to increase the number of technologies listed in the README.

---

# 3. Core Product Modules

ResearchOS will contain several interconnected modules.

These represent the long-term product scope. They must be implemented in manageable development phases.

## Module A — Research Workspace & Paper Library

Create a research management system where users can organize papers and research activities.

Features:

1. Create, edit, archive, and delete research projects.
2. Upload academic PDFs.
3. Import papers using DOI or supported paper URLs.
4. Extract paper metadata:
   - Title
   - Authors
   - Publication year
   - Venue or journal
   - DOI
   - Abstract
   - Keywords, when available
   - Source URL
5. Organize papers by project, tags, and research topic.
6. Search and filter saved papers.
7. Detect duplicate papers using DOI, normalized metadata, and/or content hashes.
8. Display a paper's analysis history.
9. Store original documents and extracted content.
10. Support re-analysis with different models or configurations.
11. Maintain the provenance and version of each analysis.

The user should have a central dashboard showing their research projects, papers, recent analyses, and processing status.

## Module B — Intelligent Paper Analysis

This is one of the most important modules.

After uploading a scientific paper, ResearchOS should analyze it and generate a structured, evidence-based research report.

The report should contain:

### B1. General Paper Overview

- Title and publication information
- Research domain
- Research problem
- Main objective
- Motivation
- Main contributions
- Short summary
- Detailed summary
- Beginner-friendly explanation

### B2. Methodology Analysis

Explain:

- The overall proposed approach
- The model or system architecture
- Important components
- Input and output data
- Training procedure, if applicable
- Loss functions, where applicable
- Important algorithms
- Experimental setup
- Evaluation metrics
- Baselines
- How the proposed approach differs from previous methods

Explanations should be readable and technically accurate.

### B3. Results & Experiments

Extract:

- Main quantitative results
- Important experimental comparisons
- Ablation studies
- Reported improvements
- Performance trade-offs
- Important implementation details

Preserve the relationship between each result, its metric, dataset, and experimental setting.

### B4. Limitations

Identify:

- Limitations explicitly acknowledged by the authors.
- Limitations supported by the paper's experiments.
- Additional potential limitations inferred by the AI.

These categories must remain clearly separated.

Never present an AI-generated hypothesis as a claim explicitly made by the authors.

### B5. Future Work

Extract future directions explicitly mentioned in the paper.

Optionally propose additional future directions, but label them as AI-generated suggestions.

### B6. Research Gaps

Identify potentially valuable research opportunities.

For each candidate gap, record:

- Research gap title
- Description
- Motivation
- Supporting evidence
- Related limitations
- Proposed improvement
- Possible implementation strategy
- Required datasets
- Required models or architectures
- Possible evaluation metrics
- Estimated implementation difficulty
- Computational requirements
- Potential research contribution
- Uncertainty and unresolved questions

Do not claim an idea is novel merely because an LLM suggested it.

### B7. Research Resources

Extract relevant resources mentioned in the paper:

- Dataset names
- Dataset URLs
- GitHub repositories
- Model repositories
- Pretrained checkpoints
- Project websites
- Supplementary materials
- External tools

Separate resources explicitly found in the document from externally discovered resources.

Validate links when possible. Do not invent URLs.

## Module C — Figure, Table & Visual Understanding

Academic papers contain essential information in figures, architecture diagrams, tables, and charts.

The platform must eventually support:

1. Extracting embedded figures and tables from PDFs.
2. Preserving page references.
3. Extracting figure captions.
4. Associating figures with nearby relevant text.
5. Displaying figures inside the analysis interface.
6. Explaining important diagrams using supported multimodal models.
7. Summarizing important tables.
8. Explaining model architecture diagrams.
9. Connecting extracted visual information to methodology explanations.

The original figures should be preserved rather than recreated inaccurately.

When a document parser cannot reliably extract an element, indicate the limitation.

Multimodal AI analysis must be capability-aware: a text-only model should never silently be treated as a vision-capable model.

## Module D — Chat With Research Papers

Users should be able to ask natural-language questions about their research documents.

Supported scopes:

- One paper
- Multiple selected papers
- One research project
- The entire user's paper library

Example questions:

- "Explain the methodology of this paper in simple terms."
- "Which papers address generalization problems?"
- "Compare the evaluation datasets used by these papers."
- "Which methods rely on CLIP?"
- "Which papers mention compressed AI-generated images?"
- "What are the differences between the proposed architectures?"

Use Retrieval-Augmented Generation where appropriate.

Requirements:

- Evidence-grounded answers
- Document-level citations
- Page or section references
- Source-aware retrieval
- Conversation history
- Project/document filtering
- Clear handling of insufficient evidence
- Protection against cross-user document access

Prefer a retrieval pipeline that can be evaluated and improved rather than a black-box chain.

## Module E — Research Gap & Novelty Intelligence

This is a major long-term differentiator.

The platform should help researchers determine whether an idea is worth pursuing.

### E1. Research Gap Discovery

Analyze extracted limitations, future work, experimental weaknesses, and relationships between papers.

Generate candidate research directions with traceable supporting evidence.

### E2. Related Work Discovery

Integrate external academic discovery services where feasible, such as:

- OpenAlex
- Semantic Scholar
- Crossref

Potential functionality:

- Search related papers
- Retrieve bibliographic metadata
- Discover cited and citing papers
- Identify recent related studies
- Compare methods and contributions

Handle API quotas, restrictions, failures, and missing metadata.

### E3. Novelty Assessment

Given an idea, search for relevant prior work.

Compare:

- Research problems
- Methods
- Datasets
- Evaluation scenarios
- Claimed contributions

Produce an evidence-based novelty assessment with links to related papers.

Do not imply exhaustive literature coverage or guaranteed originality.

### E4. Feasibility Assessment

For each proposed research direction, evaluate:

- Availability of public datasets
- Availability of pretrained models
- Availability of source code
- Computational requirements
- Implementation difficulty
- Estimated project scope
- Reproducibility
- Potential experimental design
- Suitability for an undergraduate research project
- Potential for subsequent academic publication

Provide configurable scoring criteria and explain the rationale behind scores.

Distinguish verified facts, estimates, and AI-generated judgments.

## Module F — Knowledge Management & Cross-Paper Analysis

Allow users to build a cumulative research knowledge base.

Features:

- Compare two or more papers.
- Compare methodology and architecture.
- Compare datasets and metrics.
- Find common limitations.
- Identify conflicting conclusions.
- Compare reported results only when experimental settings are sufficiently comparable.
- Maintain personal annotations.
- Save important findings.
- Organize research ideas.
- Generate structured comparative reports.
- Export selected results to Markdown and eventually DOCX/PDF.

A long-term goal is to allow research projects to maintain a continuously growing knowledge base.

---

# 4. Dynamic AI Provider & Model Management

This is a mandatory architectural component, not an afterthought.

ResearchOS must NOT depend permanently on a single AI provider.

Design an extensible **AI Gateway / Provider Management Layer**.

## 4.1 Bring Your Own Key (BYOK)

Users should be able to configure their own API credentials through the application's settings interface.

Potential providers include:

- OpenAI
- Google Gemini
- Anthropic
- OpenAI-compatible providers
- Other supported providers
- Local model endpoints, in later versions

Provider availability and model capabilities must be configurable rather than blindly hardcoded.

## 4.2 Secure Credential Management

Requirements:

- Provider credentials are managed server-side.
- API keys must never be exposed in frontend bundles.
- Do not store plaintext credentials in the database.
- Use authenticated encryption and securely managed application secrets.
- Mask saved credentials in the UI.
- Allow credentials to be replaced or deleted.
- Prevent credentials from appearing in logs or error messages.
- Scope credentials to the appropriate user.
- Implement authorization checks for all settings endpoints.
- Never commit secrets to Git.
- Provide a `.env.example` without real credentials.

ResearchOS API authentication and external AI provider credentials are distinct concepts and must be designed separately.

## 4.3 Runtime Model Configuration

Users should be able to:

- Add providers.
- Configure API keys.
- Test connections.
- Discover or manually configure models.
- Select default models.
- Change models without restarting the backend.
- Assign specific models to different tasks.
- Configure generation parameters where supported.

Example routing:

| Task | Model Role |
|---|---|
| Paper summarization | General text LLM |
| Detailed methodology | Strong reasoning/text model |
| Figure analysis | Vision-capable model |
| Research gap analysis | Reasoning-capable model |
| Embeddings | Embedding model |
| Paper chat | Conversational text model |

The system must validate model capabilities before routing tasks.

## 4.4 Intelligent Routing & Fallback

Support:

- Configurable primary model
- Optional fallback model
- Timeouts
- Retries with backoff
- Rate-limit handling
- Provider error normalization
- Task-specific routing

Fallback must not silently bypass user privacy settings, cost budgets, or explicit provider preferences.

Do not automatically send sensitive documents to another provider without appropriate configuration.

## 4.5 Cost & Usage Tracking

Track:

- Provider
- Model
- Task
- Tokens consumed, when available
- Estimated or provider-reported cost
- Processing latency
- Number of requests
- Failures
- Retries

Users should eventually see a dashboard displaying AI usage and approximate costs.

Support configurable spending limits.

Handle cases where cost or token usage data is unavailable.

## 4.6 Implementation Strategy

Evaluate **LiteLLM** as a unified provider integration layer.

Use it if it meaningfully reduces integration complexity.

Do not build a huge custom proxy or separate microservice unless the actual system requirements justify it.

The provider abstraction should remain testable and replaceable.

Provide a mock AI provider for development and automated tests without requiring paid API credentials.

---

# 5. AI/ML Engineering Requirements

The AI component must go beyond basic prompt engineering.

ResearchOS should demonstrate practical experience in several AI/ML areas.

## 5.1 Document AI

Implement a structured document ingestion pipeline.

Evaluate suitable tools such as:

- Docling
- PyMuPDF
- GROBID, where useful

Required concepts:

- PDF parsing
- Layout-aware extraction
- Section detection
- Table extraction
- Figure extraction
- Metadata extraction
- Page-level provenance

Preserve as much document structure as reasonably possible.

Avoid reducing an academic paper to one giant unstructured text string.

## 5.2 NLP and Structured Information Extraction

Build pipelines for extracting scientific information.

Use:

- Pydantic schemas
- Structured LLM outputs
- Schema validation
- Section-aware processing
- Normalization
- Error handling

Distinguish missing information from failed extraction.

Support partial results if a specific analysis stage fails.

## 5.3 Embeddings & Semantic Search

Implement an embedding abstraction supporting suitable hosted or local embedding models.

Research:

- Sentence Transformers
- Hugging Face models
- Provider-hosted embeddings

Store vectors using PostgreSQL with pgvector unless a better choice is clearly justified.

Implement:

- Chunk generation
- Embedding generation
- Vector indexing
- Similarity search
- Document filtering
- Model/version tracking

When embedding configurations change, handle index compatibility and re-embedding correctly.

## 5.4 Retrieval-Augmented Generation

Build an explicit RAG pipeline.

Components should include:

1. Query processing
2. Document filtering
3. Candidate retrieval
4. Optional reranking
5. Context construction
6. LLM generation
7. Citation verification
8. Response generation

Support experimenting with:

- Fixed-size chunking
- Section-aware chunking
- Semantic chunking
- Dense retrieval
- Lexical/BM25 retrieval
- Hybrid retrieval
- Reranking

Implement an initial baseline first, then improve it based on evaluation results.

## 5.5 Multimodal AI

Support analysis of extracted figures and diagrams through vision-capable models.

This should be modular and optional if the configured provider does not support vision.

## 5.6 ML Experiments & Evaluation

A major objective is demonstrating actual ML engineering competency.

Create an evaluation framework for comparing retrieval strategies.

Potential metrics:

- Recall@K
- Precision@K
- MRR
- nDCG
- Citation accuracy
- Answer faithfulness
- Extraction accuracy
- End-to-end latency
- Cost per analysis

Build a small reproducible evaluation dataset with documented ground-truth annotations.

Include at least one measurable baseline and an experimental improvement in the mature project.

## 5.7 Optional Fine-Tuning

Fine-tuning is not mandatory for the initial MVP.

However, the architecture should allow future ML experimentation.

A suitable later project could be a scientific-section classifier trained to distinguish:

- Abstract
- Introduction
- Related Work
- Methodology
- Experiments
- Results
- Limitations
- Future Work
- Conclusion

This would create an opportunity to demonstrate PyTorch, Transformers, training, validation, and model evaluation.

Only introduce fine-tuning when there is a clear dataset, baseline, and measurable benefit.

---

# 6. Evidence, Citations & Scientific Reliability

ResearchOS must prioritize scientific reliability.

This is a fundamental product requirement.

For extracted research claims, preserve:

- Source paper
- Source page
- Source section, if available
- Supporting text or evidence reference
- Extraction method
- Model and analysis version

Important rules:

1. Do not fabricate research findings.
2. Do not fabricate URLs, datasets, repositories, or metrics.
3. Do not assume all information is present in every paper.
4. Clearly distinguish explicit author statements from AI-generated interpretations.
5. Do not present research gap suggestions as verified novelty.
6. Indicate uncertainty when evidence is insufficient.
7. Do not combine incompatible experimental results into misleading comparisons.
8. Treat PDF content and external documents as untrusted input, not executable instructions.

The UI should allow users to inspect supporting evidence and navigate to relevant document pages whenever possible.

Source grounding should be a first-class data modeling concern.

---

# 7. Backend Architecture

## Preferred Technology Stack

| Layer | Preferred Technology |
|---|---|
| Primary Backend | Python + FastAPI |
| API Validation | Pydantic |
| Relational Database | PostgreSQL |
| Vector Storage | pgvector |
| ORM / Migrations | SQLAlchemy + Alembic |
| Cache / Message Broker | Redis |
| Background Processing | Celery |
| AI Provider Integration | LiteLLM or equivalent abstraction |
| Document Parsing | Docling, with suitable fallbacks |
| ML/NLP | PyTorch + Hugging Face |
| Frontend | Next.js + TypeScript + Tailwind CSS |
| File Storage | Local abstraction initially, S3-compatible later |
| Deployment | Docker Compose |
| Backend Testing | Pytest |
| Frontend Testing | Appropriate TypeScript testing tools |
| CI/CD | GitHub Actions |

These are preferred choices, not a license to add unnecessary dependencies.

Document all significant deviations.

## Architecture Principles

Use a well-structured **modular monolith** initially.

Avoid premature microservices.

Suggested backend layers:

- API routers
- Request/response schemas
- Application services
- Domain models
- Data repositories
- AI provider adapters
- Document processing components
- Retrieval components
- Background tasks
- Infrastructure
- Security/configuration

Separate business logic from HTTP handlers.

Avoid oversized route handlers and tightly coupled AI integrations.

Use dependency injection where appropriate.

Keep implementation understandable and maintainable.

## FastAPI vs Django

FastAPI should be the primary backend.

Do not introduce Django REST Framework solely for portfolio purposes.

Django/DRF may be considered in a future phase only if there is a legitimate architectural reason.

---

# 8. API Design Requirements

Provide a properly designed, documented REST API.

Expected resource groups include:

- Authentication
- Users
- Research projects
- Papers
- Document uploads
- Analysis jobs
- Analysis results
- Figures and tables
- Conversations
- Research findings
- Providers
- Model configurations
- Usage analytics

Example endpoints:

```http
POST   /api/v1/projects
GET    /api/v1/projects

POST   /api/v1/papers/upload
GET    /api/v1/papers
GET    /api/v1/papers/{paper_id}
DELETE /api/v1/papers/{paper_id}

POST   /api/v1/papers/{paper_id}/analyze
GET    /api/v1/jobs/{job_id}
GET    /api/v1/papers/{paper_id}/analyses

POST   /api/v1/chat/query
POST   /api/v1/papers/compare

GET    /api/v1/providers
POST   /api/v1/providers
POST   /api/v1/providers/{provider_id}/test

GET    /api/v1/settings/model-routing
PUT    /api/v1/settings/model-routing

GET    /api/v1/analytics/usage
```

Treat these endpoints as initial design suggestions.

Follow best practices for:

- Resource naming
- HTTP status codes
- Pagination
- Filtering
- Sorting
- API versioning
- Authentication
- Authorization
- Input validation
- Consistent error responses
- Rate limiting
- Idempotency where appropriate
- OpenAPI/Swagger documentation

Long-running document analysis must use asynchronous jobs rather than blocking HTTP requests.

---

# 9. Database Design

Design a normalized relational schema that accommodates the complete research workflow.

Potential entities:

- User
- ResearchProject
- Paper
- PaperFile
- PaperSection
- PaperFigure
- PaperTable
- DocumentChunk
- AnalysisJob
- AnalysisReport
- ResearchFinding
- SupportingEvidence
- ResearchIdea
- Conversation
- ChatMessage
- ProviderCredential
- ModelConfiguration
- ModelRoutingRule
- AIUsageRecord

Refine these entities during architecture design.

Requirements:

- Proper relationships and foreign keys
- Indexes
- Database migrations
- Timestamps
- Clear ownership boundaries
- Paper and analysis versioning
- Stable source references
- Referential integrity
- Transaction management

Large binary files should not be stored directly in relational database columns unless there is a compelling reason.

Use a suitable file storage abstraction.

---

# 10. Asynchronous Processing

Scientific document analysis may be expensive or time-consuming.

Use Redis and Celery where appropriate.

A document analysis job should support states such as:

- Queued
- Parsing
- Extracting metadata
- Extracting figures
- Preparing context
- Running AI analysis
- Validating output
- Completed
- Partially completed
- Failed

Expose job status and meaningful progress to the frontend.

Implement:

- Safe retries
- Timeouts
- Error reporting
- Idempotent processing where possible
- Cleanup of failed temporary resources
- Prevention of accidental duplicate expensive jobs

Avoid uncontrolled concurrent LLM requests.

---

# 11. Frontend & User Experience

Build a clean, modern, professional research workspace.

The interface should be functional, readable, and optimized for long-term daily use.

Primary screens:

1. Dashboard
2. Research Projects
3. Paper Library
4. Paper Detail
5. PDF Viewer
6. AI Analysis Report
7. Figure & Table Viewer
8. Chat With Papers
9. Research Gap Explorer
10. Cross-Paper Comparison
11. AI Provider Settings
12. Usage & Cost Dashboard

Not all screens must be available in the first release.

## Paper Detail Experience

Prefer a layout where users can inspect the original document alongside AI-generated analysis.

For example:

- Left panel: original PDF
- Right panel: structured AI analysis
- Clickable evidence references that navigate to relevant pages

## Language Support

The platform should support English scientific papers.

Analysis outputs should be configurable between English and Persian.

Preserve technical terminology where necessary.

Design the UI for future internationalization and proper RTL layout.

## UX Expectations

- Responsive layouts
- Useful loading indicators
- Processing progress
- Clear errors
- Reusable UI components
- Accessible interaction patterns
- No fake functionality or decorative controls that do nothing

---

# 12. Security, Privacy & Reliability

Apply reasonable security practices from the beginning.

Important concerns:

- Secure credential storage
- Authentication and authorization
- Per-user resource ownership
- File validation
- Upload size limits
- Secure file paths
- Safe handling of malformed PDFs
- Input validation
- Protection against SQL injection
- Protection against prompt injection in documents
- SSRF protection for imported URLs and custom provider endpoints
- API rate limiting
- Logging without leaking sensitive information
- Restricting CORS appropriately
- Dependency security

Uploaded scientific papers may be private or unpublished.

Provide a clear indication of which external provider receives document content.

Do not assume cloud processing is acceptable for every document.

Before any public multi-user deployment, authentication and tenant isolation must be properly implemented and tested.

---

# 13. Testing & Quality Assurance

Testing must be part of the development process.

Include:

### Unit Tests

For:

- Business logic
- Parsers
- Data normalization
- Provider adapters
- Configuration validation
- Research extraction schemas

### Integration Tests

For:

- API endpoints
- PostgreSQL operations
- File uploads
- Background jobs
- Provider routing
- Retrieval operations

### End-to-End Tests

Cover essential user journeys:

1. Create a research project.
2. Upload a paper.
3. Process the document.
4. Generate a structured analysis.
5. Display results.
6. Inspect supporting evidence.
7. Save and revisit the analysis.

### AI Evaluation

Where applicable, measure:

- Extraction completeness
- Unsupported claims
- Citation correctness
- Retrieval performance
- Cost
- Latency

Use mocks and fixtures so CI tests do not depend on paid API credentials.

Maintain separate optional tests for real provider connectivity.

---

# 14. Development Roadmap

Do not implement everything at once.

Organize development into clearly scoped milestones.

## Phase 0 — Project Foundation

Deliver:

- Architecture document
- Project structure
- Development environment
- FastAPI application skeleton
- Next.js frontend skeleton
- PostgreSQL integration
- Database migrations
- Docker Compose
- Configuration management
- Basic tests
- Initial documentation
- GitHub Actions CI

## Phase 1 — Functional MVP

The first genuinely useful release.

Deliver:

- Research projects
- PDF uploads
- Persistent document library
- Document parsing
- Basic metadata extraction
- Basic figure extraction
- Structured paper analysis
- Summary
- Methodology
- Results
- Limitations
- Future work
- Initial research gap suggestions
- Supporting source references
- Persistent analysis history
- Secure provider configuration
- Dynamic model selection
- Asynchronous processing
- Functional frontend

The result must work end-to-end with a configured provider.

Provide mocked functionality for testing without credentials.

**The MVP must be a real usable application, not merely a collection of endpoint stubs.**

## Phase 2 — RAG & Research Assistant

Deliver:

- Document chunking
- Embeddings
- pgvector integration
- Semantic search
- Paper conversations
- Project-scoped conversations
- Citation-aware answers
- Retrieval evaluation
- Cross-paper comparison
- Improved figure understanding

## Phase 3 — Research Intelligence

Deliver:

- Academic search integrations
- Related paper discovery
- Evidence-supported gap discovery
- Research idea management
- Novelty assessment
- Dataset and model discovery
- Feasibility scoring
- Research reports
- Advanced comparison workflows

## Phase 4 — Advanced AI/ML & Production Engineering

Potential deliverables:

- Retrieval experiments and optimization
- Hybrid search
- Reranking
- Local model support
- Optional task-specific fine-tuning
- Advanced LLM observability
- Usage dashboards
- Provider cost optimization
- Improved security
- Multi-user capabilities
- Production deployment
- Performance and load testing

Treat this roadmap as adjustable based on implementation findings.

However, always maintain a functional vertical slice before expanding scope.

---

# 15. Documentation & GitHub Portfolio Quality

This project will be published on GitHub.

Its repository must demonstrate professional engineering practices.

Provide:

- A comprehensive English README
- Product overview
- Feature list
- Architecture explanation
- Tech stack
- Installation instructions
- Local development instructions
- Configuration guide
- API documentation
- Screenshots of real functionality
- Testing instructions
- Known limitations
- Development roadmap
- Security guidance
- Example workflows
- AI/ML evaluation results when available

Do not fabricate benchmark numbers, screenshots, or performance claims.

Use meaningful commits, maintainable naming conventions, and sensible repository organization.

Code comments should explain non-obvious decisions rather than repeat what the code already says.

---

# 16. Non-Functional Requirements

ResearchOS should be:

**Modular:** Components can be maintained and replaced independently.

**Extensible:** New AI providers, parsers, and analysis tasks can be added without major rewrites.

**Reliable:** Failures should be handled gracefully with useful diagnostics.

**Observable:** Developers can investigate processing failures and performance problems.

**Secure:** User data and provider credentials are protected.

**Cost-aware:** Expensive AI operations are tracked and controlled.

**Reproducible:** Analysis configurations, model versions, and relevant processing metadata are stored.

**Testable:** Components can be tested without connecting to paid services.

**Maintainable:** Avoid unnecessary abstraction, code duplication, and premature complexity.

**Portfolio-worthy:** Demonstrate real AI and backend engineering skills through functioning features and measurable results.

---

# 17. Critical Engineering Instructions

Follow these rules throughout development:

1. **Build for functionality, not appearances.** A working pipeline is more important than a large collection of unfinished UI screens.

2. **Avoid overengineering.** Start with a modular monolith and add complexity only when justified.

3. **Do not fake AI capabilities.** Any feature presented as functional must actually work or be clearly marked as incomplete.

4. **Do not fabricate scientific evidence.** Source grounding is essential.

5. **Do not hardcode API keys or rely on a single model provider.**

6. **Do not require expensive infrastructure unnecessarily.** Local development should be realistic for an individual developer.

7. **Use existing mature libraries where appropriate**, but understand and document their role.

8. **Make components replaceable.** Especially AI providers, document parsers, embeddings, and retrieval strategies.

9. **Separate MVP requirements from future enhancements.**

10. **Do not use Django and FastAPI together without a strong architectural justification.**

11. **Implement meaningful tests alongside code.**

12. **Make reasonable engineering decisions autonomously.** Ask questions only when an essential decision cannot safely be made without my input.

13. **Do not assume research ideas proposed by AI are scientifically novel.**

14. **Keep the project easy to run, inspect, and demonstrate.**

15. **At each development milestone, maintain a working application and update documentation.**

---

# 18. How You Should Start

We are now beginning the implementation process.

First, inspect the current repository and determine whether any project structure or code already exists.

If the repository is empty, initialize it using an appropriate, maintainable structure.

Before substantial implementation:

1. Summarize your understanding of ResearchOS.
2. Propose a practical overall architecture.
3. Define the Phase 1 MVP boundaries.
4. Identify major architectural decisions and their trade-offs.
5. Design the initial database schema.
6. Design the initial API contracts.
7. Define the initial repository structure.
8. Describe the paper processing and AI analysis pipeline.
9. Explain the provider management architecture.
10. Establish a milestone-based implementation plan.

Save the technical decisions in appropriate repository documentation so future development sessions can use them.

Then begin implementing **Phase 0**, followed by the smallest useful end-to-end slice of Phase 1.

Do not wait for repeated approvals for routine implementation details.

If a choice requires my personal API key, paid service access, or another external prerequisite, provide a safe configuration path and continue working on everything that can be implemented without it.

At the end of each milestone:

- Summarize completed functionality.
- List important files and architectural changes.
- Report executed tests and their outcomes.
- Explain how to run the application.
- Identify known limitations.
- State the next recommended implementation milestone.

Do not claim tests have passed unless they have actually been executed.

---

# 19. Definition of Success

The project will be successful when I can:

1. Open ResearchOS locally.
2. Create a research project.
3. Configure an AI provider and model through the interface.
4. Upload a scientific PDF.
5. See meaningful processing progress.
6. Receive a structured scientific analysis.
7. Read understandable explanations of the paper's methodology.
8. Inspect extracted figures and important tables.
9. Examine limitations and future work.
10. Review potential research opportunities.
11. Verify the evidence supporting important claims.
12. Save the results and revisit them later.
13. Analyze additional papers.
14. Eventually compare multiple papers and ask questions across my research library.

At the engineering level, I should also be able to demonstrate:

- A properly designed FastAPI backend.
- A relational PostgreSQL data model.
- Practical Redis and asynchronous job processing.
- Secure and dynamic AI provider integration.
- A structured document processing pipeline.
- NLP and LLM engineering.
- RAG and vector search.
- Automated tests.
- Containerized deployment.
- Reproducible AI/ML evaluation.

**Final direction:**

Build ResearchOS as a real, evolving AI research platform that I can personally use for years and confidently present as a professional AI/ML Engineering portfolio project.

Prioritize correctness, reliability, maintainability, demonstrable technical depth, and practical usefulness.

**Begin by inspecting the repository, establishing the technical foundation, and implementing the first working milestone.**
