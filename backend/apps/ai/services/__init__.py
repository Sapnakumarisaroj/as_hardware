"""The AI hardware assistant (Phase 12).

    HardwareAssistantService   one customer message in → one grounded answer out
     ├── IntentService          what is asked: intent, language, search words, budget, sizes
     ├── CatalogRetrievalService  the real products for those words (Phase 4 keyword search)
     ├── RecommendationService  message, reasons, budget fit, knowledge and safety notes
     └── AIConversationService  the conversation records (AIConversation / AIMessage)

A language model (integrations.llm) is optional. It only helps to understand the question and
to phrase the answer; everything a customer could act on (products, prices, stock, delivery)
is read from the database and checked again before it is shown.
"""
