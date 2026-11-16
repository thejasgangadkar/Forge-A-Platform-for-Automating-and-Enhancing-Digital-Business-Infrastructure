def plan_infrastructure(business_data):

    business_type = business_data.get("business_type", "")

    plan = {
        "website": True,
        "ai_agents": [],
        "automation_workflows": []
    }

    if "restaurant" in business_type.lower():
        plan["ai_agents"].append("customer_support_bot")
        plan["automation_workflows"].append("online_reservations")

    elif "clinic" in business_type.lower():
        plan["ai_agents"].append("patient_support_bot")
        plan["automation_workflows"].append("appointment_booking")

    else:
        plan["ai_agents"].append("customer_support_bot")

    return plan