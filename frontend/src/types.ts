// Mirrors backend/app/services/report.py (FinalReport) and app/api/sessions.py (SessionSummary).

export interface TranscriptLine {
  speaker: "interviewer" | "candidate";
  text: string;
}

export interface QuestionReport {
  question_id: string;
  text: string;
  topic: string;
  transcript: TranscriptLine[];
  evaluated: boolean;
  scores: Record<string, number>;
  evidence: Record<string, string>;
  strengths: string[];
  improvements: string[];
  missed_key_points: string[];
  score: number | null;
  sample_answer: string | null;
}

export interface PracticeDay {
  day: number;
  focus: string;
  tasks: string[];
}

export interface FinalReport {
  session_id: string;
  role: string;
  interview_type: string;
  difficulty: string;
  generated_at: string;
  overall_score: number;
  hiring_signal: "Strong" | "Lean yes" | "Lean no" | "Not yet";
  questions_planned: number;
  questions_answered: number;
  questions_scored?: number; // 0 with answers > 0: scoring failed, so there is no score to show
  dimension_scores: Record<string, number>;
  summary: string;
  strengths: string[];
  improvements: string[];
  practice_plan: PracticeDay[];
  questions: QuestionReport[];
  speech: SpeechSummary | null;
  coach_generated: boolean;
}

export interface SessionSummary {
  id: string;
  role: string;
  interview_type: string;
  difficulty: string;
  status: "planning" | "in_progress" | "scoring" | "done" | "failed";
  created_at: string;
  overall_score: number | null;
  hiring_signal: string | null;
}

export interface SpeechSummary {
  avg_wpm: number | null;
  pace: "slow" | "good" | "fast" | null;
  total_words: number;
  fillers_per_100_words: number;
  filler_counts: Record<string, number>;
  hedges: number;
  long_pauses: number;
  answer_seconds: Record<string, number>;
  flags: string[];
}
