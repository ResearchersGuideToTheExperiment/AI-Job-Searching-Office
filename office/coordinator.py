from office.models import Analysis, FACT_FIELDS


def build_tasks(analysis: Analysis, warnings: list[str]) -> list[dict]:
    tasks = [{"text": "Review all extracted information and compare it with the original advertisement before preparing an application.",
              "source": "", "verification": True, "importance": "review"}]
    verbs = {"eligibility": "Check your eligibility", "essential": "Prepare evidence for this essential criterion",
             "desirable": "Consider evidence for this preference", "document": "Prepare this document",
             "question": "Draft an answer to this question", "application": "Complete this step manually"}
    for req in analysis.requirements:
        tasks.append({"text": f"{verbs[req.category]}: {req.text}", "source": req.source_quote,
                      "verification": req.importance == "unclear", "importance": req.importance})
    for name in FACT_FIELDS:
        if name=='salary' or (name=='application_email' and analysis.application_url.value):
            continue  # Optional omissions are not failed application requirements.
        if getattr(analysis, name).value is None:
            tasks.append({"text": f"Verify missing {name.replace('_', ' ')} with the official advertisement or institution (if applicable).",
                          "source": "", "verification": True, "importance": "review"})
    if warnings:
        tasks.append({"text": "Review the original for requirements omitted by evidence validation.",
                      "source": "", "verification": True, "importance": "review"})
    destination = analysis.application_url.value or analysis.application_email.value or analysis.submission_method.value
    fact = analysis.application_url if analysis.application_url.value else analysis.application_email if analysis.application_email.value else analysis.submission_method
    tasks.append({"text": f"After your final review, submit manually via: {destination}" if destination else "Verify the official submission route, then submit manually after your final review.",
                  "source": fact.source_quote or "", "verification": True, "importance": "review"})
    return tasks
