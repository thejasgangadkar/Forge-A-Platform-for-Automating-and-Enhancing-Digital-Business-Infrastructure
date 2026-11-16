def generate_support_agent_config(business_context: str):
    """
    Generates a configuration for a customer support agent based on the business context.
    This will define the agent's persona, knowledge base scope, and permitted actions.
    """
    # Stub: This will integrate with LLM service to dynamically generate prompt templates
    return {
        "role": "Customer Support Agent",
        "description": "An AI agent designed to handle customer inquiries, FAQs, and support tickets.",
        "knowledge_base_requirements": ["Product Information", "Return Policy", "Contact Details"],
        "tone": "Professional and helpful"
    }
