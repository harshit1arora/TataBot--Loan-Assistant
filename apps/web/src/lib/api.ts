// Single API client: bearer token, hard timeout, typed errors.
// The base URL is the same origin (nginx in docker, vite proxy in dev), so there is
// no CORS surface and no second hostname to configure.

import type {
  ApiErrorBody,
  ApplicationView,
  ChatResponse,
  CustomerProfile,
  RegisterCustomerRequest,
  RegisterCustomerResponse,
  SessionList,
  SessionTrace,
  SessionView,
  SignedUrlResponse,
  SupportMessageCreated,
  SupportMessageView,
  SupportTopic,
  TokenResponse,
  TranscriptMessage,
  UploadResponse,
} from "./types";

const BASE_URL: string = import.meta.env.VITE_API_BASE_URL ?? "";
const DEFAULT_TIMEOUT_MS = 15000;

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;
  readonly requestId: string;

  constructor(status: number, code: string, message: string, requestId = "-") {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

let token: string | null = sessionStorage.getItem("tatabot.token");
let expiresAt = Number(sessionStorage.getItem("tatabot.expiresAt") ?? 0);

export function setToken(value: string, expiresInSeconds: number): void {
  token = value;
  expiresAt = Date.now() + expiresInSeconds * 1000;
  sessionStorage.setItem("tatabot.token", value);
  sessionStorage.setItem("tatabot.expiresAt", String(expiresAt));
}

export function clearToken(): void {
  token = null;
  expiresAt = 0;
  sessionStorage.removeItem("tatabot.token");
  sessionStorage.removeItem("tatabot.expiresAt");
  sessionStorage.removeItem("tatabot.sessionId");
}

export function hasToken(): boolean {
  return Boolean(token) && Date.now() < expiresAt;
}

async function request<T>(
  path: string,
  init: RequestInit = {},
  timeoutMs = DEFAULT_TIMEOUT_MS,
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);

  const headers = new Headers(init.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (init.body && !(init.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }

  try {
    const response = await fetch(`${BASE_URL}${path}`, {
      ...init,
      headers,
      signal: controller.signal,
    });

    if (response.status === 401) {
      clearToken();
    }

    if (!response.ok) {
      let code = "request_failed";
      let message = `Request failed (${response.status}).`;
      let requestId = "-";
      try {
        const body = (await response.json()) as ApiErrorBody;
        code = body.error?.code ?? code;
        message = body.error?.message ?? message;
        requestId = body.error?.request_id ?? requestId;
      } catch {
        /* non-JSON error body */
      }
      throw new ApiError(response.status, code, message, requestId);
    }

    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  } catch (error) {
    if (error instanceof ApiError) throw error;
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError(408, "timeout", "The server took too long to respond.");
    }
    throw new ApiError(0, "network_error", "Could not reach the server.");
  } finally {
    clearTimeout(timer);
  }
}

// --- auth ------------------------------------------------------------------
export async function login(customerId: string, phone: string): Promise<void> {
  const body = await request<TokenResponse>("/auth/token", {
    method: "POST",
    body: JSON.stringify({ customer_id: customerId, phone }),
  });
  setToken(body.access_token, body.expires_in);
}

export function profile(): Promise<CustomerProfile> {
  return request<CustomerProfile>("/v1/customers/me");
}

export function registerCustomer(
  payload: RegisterCustomerRequest,
): Promise<RegisterCustomerResponse> {
  return request<RegisterCustomerResponse>("/v1/customers", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function myApplications(): Promise<ApplicationView[]> {
  return request<ApplicationView[]>("/v1/applications");
}

// --- support ---------------------------------------------------------------
export function sendSupportMessage(payload: {
  name: string;
  contact: string;
  topic: SupportTopic;
  message: string;
}): Promise<SupportMessageCreated> {
  return request<SupportMessageCreated>("/v1/support/messages", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function mySupportMessages(): Promise<SupportMessageView[]> {
  return request<SupportMessageView[]>("/v1/support/messages");
}

// --- conversation ----------------------------------------------------------
export function sendMessage(message: string, sessionId: string | null): Promise<ChatResponse> {
  return request<ChatResponse>("/chat", {
    method: "POST",
    body: JSON.stringify(sessionId ? { message, session_id: sessionId } : { message }),
  });
}

export function sessionStatus(sessionId: string): Promise<SessionView> {
  return request<SessionView>(`/sessions/${sessionId}`);
}

export function listSessions(limit = 20): Promise<SessionList> {
  return request<SessionList>(`/sessions?limit=${limit}`);
}

export function sessionMessages(sessionId: string): Promise<TranscriptMessage[]> {
  return request<TranscriptMessage[]>(`/sessions/${sessionId}/messages`);
}

export function sessionTrace(sessionId: string): Promise<SessionTrace> {
  return request<SessionTrace>(`/sessions/${sessionId}/trace`);
}

export function uploadDocument(sessionId: string, file: File): Promise<UploadResponse> {
  const form = new FormData();
  form.append("file", file);
  form.append("doc_type", "salary_slip");
  return request<UploadResponse>(`/sessions/${sessionId}/documents`, {
    method: "POST",
    body: form,
  }, 30000);
}

// --- documents -------------------------------------------------------------
export function signedUrl(documentId: string): Promise<SignedUrlResponse> {
  return request<SignedUrlResponse>(`/v1/documents/${documentId}/signed-url`);
}

/** Opens a short-lived signed link. The token is single-purpose and expires in 60s. */
export async function downloadDocument(documentId: string): Promise<void> {
  const { url } = await signedUrl(documentId);
  window.open(`${BASE_URL}${url}`, "_blank", "noopener,noreferrer");
}
