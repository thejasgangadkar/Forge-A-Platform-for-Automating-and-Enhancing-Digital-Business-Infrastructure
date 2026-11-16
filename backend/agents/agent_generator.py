def generate_support_agent(business_data):

    agent = {
        "agent_name": "Customer Support Assistant",
        "role": "Answer customer questions about the business",
        "knowledge_source": "website data",
        "supported_tasks": [
            "answer service questions",
            "provide business information",
            "assist customers"
        ]
    }

    return agent