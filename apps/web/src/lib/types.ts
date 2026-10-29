// Contracts mirrored from the services' Pydantic models.
// Money is always integer paise; the UI formats it. No floats in transit.

export type Scope = "customer" | "service";

export interface TokenResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  scope: Scope;
}

export interface CustomerProfile {
  customer_id: string;
  name: string;
  city: string;
  pre_approved_limit_paise: number;
  /** offered = a real pre-approved offer; indicative = derived from declared income. */
  limit_source: "offered" | "indicative";
  credit_score_band: "excellent" | "good" | "fair";
  /** self_declared in this build; a real deployment gets this from a bureau. */
  score_source: "demo_seed" | "self_declared" | "bureau";
  phone_verified: boolean;
  address_verified: boolean;
}

export interface RegisterCustomerRequest {
  name: string;
  phone: string;
  email: string;
  age: number;
  city: string;
  declared_monthly_income_rupees: number;
  declared_credit_score: number;
}

export interface RegisterCustomerResponse {
  customer_id: string;
  profile: CustomerProfile;
  next_step: string;
}

export type SupportTopic = "general" | "application" | "document" | "repayment" | "grievance";

export interface SupportMessageCreated {
  reference: string;
  status: string;
  expected_response: string;
}

export interface SupportMessageView {
  reference: string;
  topic: string;
  status: string;
  created_at: string;
}

export type DecisionOutcome = "approve" | "reject" | "require_document";

export interface DecisionView {
  outcome: DecisionOutcome;
  reason_codes: string[];
  emi_paise: number | null;
  tenure_months: number;
  interest_rate_percent: number;
  policy_version: string;
}

export interface ApplicationView {
  application_id: string;
  customer_id: string;
  requested_amount_paise: number;
  tenure_months: number;
  status: string;
  decision: DecisionView | null;
  sanction_document_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface DocumentView {
  document_id: string;
  doc_type: string;
  status: string;
  content_type: string;
  size_bytes: number;
  extraction_confidence: number | null;
  requires_review: boolean;
  verified_income_paise: number | null;
}

export interface SignedUrlResponse {
  url: string;
  expires_in: number;
}

export interface ChatResponse {
  session_id: string;
  state: string;
  reply: string;
  application: ApplicationView | null;
  document: DocumentView | null;
  sanction_document_id: string | null;
  suggested_actions: string[];
  /** "contact" | "agents" | "agents_unavailable" for side channels. */
  intent: string | null;
  /** Which specialist agents answered, when the question was delegated. */
  agent_route: string[];
  citations: string[];
}

export interface UploadResponse {
  session_id: string;
  state: string;
  reply: string;
  document: DocumentView | null;
  application: ApplicationView | null;
  sanction_document_id: string | null;
}

export interface TranscriptMessage {
  role: "customer" | "assistant" | "system";
  content: string;
  created_at: string;
}

export interface SessionSummary {
  session_id: string;
  state: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  last_message: string | null;
  last_role: string | null;
  application_id: string | null;
  requested_amount_paise: number | null;
}

export interface SessionList {
  sessions: SessionSummary[];
  total: number;
}

export interface SessionView {
  session_id: string;
  state: string;
  customer_id: string;
  application: ApplicationView | null;
  created_at: string;
  updated_at: string;
}

export interface TraceStep {
  at: string;
  from_state: string;
  to_state: string;
  event: string;
  handled_by: string;
}

export interface SessionTrace {
  session_id: string;
  state: string;
  application_id: string | null;
  steps: TraceStep[];
  messages: number;
}

export interface ApiErrorBody {
  error: {
    code: string;
    message: string;
    request_id: string;
    details?: unknown;
  };
}
