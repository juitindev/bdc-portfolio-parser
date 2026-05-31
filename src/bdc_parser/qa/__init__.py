"""Hybrid SQL+RAG question-answering layer (v0).

Only the RAG retrieval + grounded-answer slice is implemented today
(FDUS only). The router (sql|rag|hybrid) and the SQL/DuckDB branch are
NOT built yet — see the TODO in cli.py and the Architecture section of
CLAUDE.md.

Public surface:
    qa.retrieve.retrieve(query, ticker, k=10) -> list[RetrievedChunk]
    qa.answer.answer(question, ticker, ...)    -> Answer
"""
