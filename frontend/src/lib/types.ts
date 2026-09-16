export interface DatabaseStatus {
  ok: boolean
  dialect: string
  database: string | null
  host: string | null
  port: number | null
  server_version: string | null
  error: string | null
}

export interface EngineStatus {
  key: string
  name: string
  role: string
  optional: boolean
  available: boolean
  version: string | null
}

export interface LLMStatus {
  provider: 'demo' | 'anthropic' | 'openai'
  model: string
  api_key_configured: boolean
  mode: 'offline-deterministic' | 'remote'
}

export interface HealthResponse {
  status: 'ok' | 'degraded'
  app: string
  version: string
  environment: string
  demo_mode: boolean
  server_time: string
  database: DatabaseStatus
  engines: EngineStatus[]
  llm: LLMStatus
}
