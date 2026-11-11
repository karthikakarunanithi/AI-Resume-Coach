Create an interview plan for a {duration}-minute {interview_type} interview for the role "{role}" at {difficulty} difficulty.

Write exactly {num_questions} questions.
Mix: {mix}
Order questions from easier to harder.

Rules:
- Resume questions must reference the candidate's actual projects or experience by name and probe decisions, trade-offs, and results (e.g. "In your deepfake detection project, why did you choose an LSTM for the temporal part instead of a transformer?").
- JD questions must target skills the job description requires.
- Bank questions: pick from the RETRIEVED BANK QUESTIONS below; you may rephrase lightly to fit the candidate, and keep their key points.
- Every question must be answerable verbally in about 2 minutes. One question per item, no multi-part lists.
- source is "resume", "jd", or "bank". difficulty is 1-5. ideal_key_points: 3-5 concrete points a strong answer contains.
- Do not repeat a topic unless the plan would otherwise be too short.

CANDIDATE PROFILE:
{profile_json}

JOB DESCRIPTION ANALYSIS:
{jd_json}

RETRIEVED BANK QUESTIONS:
{bank_json}

Return JSON: {"questions": [{"text": ..., "topic": ..., "difficulty": ..., "source": ..., "ideal_key_points": [...]}]}
