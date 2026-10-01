"""Semantic (meaning-based) product search, layered on the keyword search.

    embedders   text → vectors (hashing: no dependencies; sentence_transformers: a local open model)
    index       ProductEmbedding rows: build, refresh, status, cosine similarity
    expand      the customer's words (English, Hindi, Hinglish) → catalogue words
    backend     HybridSearchBackend: keyword + related words + semantic, over real products only

Nothing here creates product data: it only ranks rows that exist in the database.
"""
