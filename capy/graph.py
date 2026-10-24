"""FalkorDB access for Capy: the GraphRAG knowledge layer plus Capy's own structured layer.

Knowledge layer (GraphRAG SDK): Document -> Chunk <- MENTIONED_IN - Entity, entities linked by
RELATES {rel_type, fact, source_chunk_ids}. Capy's layer adds Talk nodes, PRESENTS edges, speaker
profile properties, and memory (MET / WANTS_TO_MEET / INTRO edges) — all in the same graph.
"""
from functools import lru_cache

from falkordb import FalkorDB
from graphrag_sdk import ConnectionConfig, Entity, GraphRAG, LiteLLM, LiteLLMEmbedder, Ontology, Relation
from graphrag_sdk.ingestion.extraction_strategies.entity_extractors import compute_entity_id

from capy.config import settings

EMBED_DIM = 256
ME = compute_entity_id("Maya Chen", "Person")  # the demo persona

ONTOLOGY = Ontology(
    entities=[
        Entity(label="Person", description="A human being: a conference speaker, author or attendee."),
        Entity(label="Organization", description="A company, team, community or open source project."),
        Entity(label="Problem", description="A concrete engineering pain point or challenge a team faces, "
               "e.g. 'code review can't keep up with AI-generated pull requests', 'securing AI agents', "
               "'proving the ROI of AI coding tools'. Phrase it as the problem, not the fix."),
        Entity(label="Practice", description="A technique, workflow, pattern or approach used to address a "
               "problem, e.g. 'agentic code review', 'policy-as-code guardrails', 'DORA metrics'."),
        Entity(label="Tool", description="A software product, framework, library or service, e.g. "
               "'GitHub Copilot coding agent', 'GitHub Actions', 'MCP'."),
    ],
    relations=[
        Relation(label="WORKS_AT", description="The person is employed by or leads the organization.",
                 patterns=[("Person", "Organization")]),
        Relation(label="FACES", description="Currently struggling with this problem.",
                 patterns=[("Person", "Problem"), ("Organization", "Problem")]),
        Relation(label="SOLVED", description="Has solved, fixed, reduced or shipped a solution to this problem, "
                 "or teaches how to solve it.", patterns=[("Person", "Problem"), ("Organization", "Problem"),
                                                       ("Person", "Practice"), ("Organization", "Practice")]),
        Relation(label="PRACTICES", description="Uses, advocates or teaches this practice.",
                 patterns=[("Person", "Practice"), ("Organization", "Practice")]),
        Relation(label="BUILT", description="Created, maintains or ships this tool.",
                 patterns=[("Person", "Tool"), ("Organization", "Tool")]),
        Relation(label="USES", description="Uses this tool.", patterns=[("Person", "Tool"), ("Organization", "Tool")]),
        Relation(label="ADDRESSES", description="This practice or tool helps solve the problem.",
                 patterns=[("Practice", "Problem"), ("Tool", "Problem"), ("Practice", "Practice"), ("Tool", "Practice")]),
    ],
)


def person_id(name: str) -> str:
    return compute_entity_id(name, "Person")


@lru_cache
def db() -> FalkorDB:
    return FalkorDB(host=settings.falkordb_host, port=settings.falkordb_port,
                    username=settings.falkordb_username, password=settings.falkordb_password,
                    ssl=settings.falkordb_tls)


def graph():
    return db().select_graph(settings.graph_name)


def q(cypher: str, **params) -> list[list]:
    return graph().query(cypher, params).result_set


def ro(cypher: str, **params) -> list[list]:
    return graph().ro_query(cypher, params).result_set


def rag() -> GraphRAG:
    return GraphRAG(
        connection=ConnectionConfig(host=settings.falkordb_host, port=settings.falkordb_port,
                                    username=settings.falkordb_username, password=settings.falkordb_password,
                                    ssl=settings.falkordb_tls, graph_name=settings.graph_name,
                                    query_timeout_ms=60000),
        # gpt-6-luna only takes temperature=0 with reasoning off — which also makes extraction fast and cheap
        llm=LiteLLM(model=f"openai/{settings.openai_model}", api_key=settings.openai_api_key,
                    temperature=0.0, reasoning_effort="none"),
        embedder=LiteLLMEmbedder(model=f"openai/{settings.embedding_model}", api_key=settings.openai_api_key,
                                 dimensions=EMBED_DIM),
        ontology=ONTOLOGY,
        embedding_dimension=EMBED_DIM,
    )


PERSONA = """Profile: Maya Chen, Staff Platform Engineer at Fernway, a 400-person fintech. She is attending
GitHub Universe 2026 to find people who have already solved the problems her team faces.

Maya's team rolled out the GitHub Copilot coding agent to 120 developers. Maya faces three problems:
1. Code review cannot keep up with AI-generated pull requests: agent PRs pile up and senior engineers
   are the bottleneck. She faces this problem most urgently.
2. Securing AI agents and MCP servers: her security team wants guardrails and governance before agents
   can touch production repositories.
3. Proving the ROI of AI coding tools: leadership asks her to measure developer productivity and show
   impact with real metrics.
Maya uses GitHub Actions and GitHub Copilot. Maya works at Fernway."""
