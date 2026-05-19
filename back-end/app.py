import os
import json
import secrets
from io import BytesIO
from pathlib import Path
from datetime import datetime, timedelta
from functools import wraps
from typing import Any, Dict, List, Optional
from uuid import UUID

from dotenv import load_dotenv
from flask import Flask, flash, get_flashed_messages, redirect, render_template, request, send_file, session, url_for
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from supabase import Client, create_client
from werkzeug.security import check_password_hash, generate_password_hash
from paths import BASE_DIR, ENV_FILE, STATIC_DIR, TEMPLATES_DIR, TOKENS_DIR


load_dotenv(ENV_FILE, override=True)
app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR),
)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY") or secrets.token_hex(32)
if not os.getenv("FLASK_SECRET_KEY"):
    app.logger.warning("FLASK_SECRET_KEY nao configurada. Uma chave temporaria foi gerada para esta execucao.")


SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

TABLE_USUARIOS = os.getenv("SUPABASE_TABLE_USUARIOS", "tb_usuario")
TABLE_ALUNOS = os.getenv("SUPABASE_TABLE_ALUNOS", "tb_aluno")
TABLE_TREINOS = os.getenv("SUPABASE_TABLE_TREINOS", "tb_treino")
TABLE_AGENDA = os.getenv("SUPABASE_TABLE_AGENDA", "tb_agenda")
TABLE_AVALIACOES = os.getenv("SUPABASE_TABLE_AVALIACOES", "tb_avaliacao")
TABLE_EXERCICIOS = os.getenv("SUPABASE_TABLE_EXERCICIOS", "tb_exercicios")
TABLE_GRUPOS_MUSCULARES = os.getenv("SUPABASE_TABLE_GRUPOS_MUSCULARES", "tb_grupo_muscular")
TABLE_MENSAGENS = os.getenv("SUPABASE_TABLE_MENSAGENS", "tb_mensagens")
TABLE_OBSERVACOES = os.getenv("SUPABASE_TABLE_OBSERVACOES", "tb_observacao")
TABLE_ANAMNESES = os.getenv("SUPABASE_TABLE_ANAMNESES", "tb_anamnese")
TABLE_PAGAMENTOS = os.getenv("SUPABASE_TABLE_PAGAMENTOS", "tb_parcela")
TABLE_PLANOS = os.getenv("SUPABASE_TABLE_PLANOS", "tb_plano")
TABLE_EXECUCOES = os.getenv("SUPABASE_TABLE_EXECUCOES", "tb_execucao_treino")

BRAND_NAME = os.getenv("BRAND_NAME", "CONFIE PERSONAL")
BRAND_LOGO_URL = os.getenv("BRAND_LOGO_URL", "")
DEFAULT_PORT = int(os.getenv("PORT", "5000"))
DEV_BYPASS_AUTH = os.getenv("DEV_BYPASS_AUTH", "0").strip().lower() in {"1", "true", "yes", "on"}
DEV_PERSONAL_ID = "11111111-1111-1111-1111-111111111111"
DEV_ALUNO_ID = "22222222-2222-2222-2222-222222222222"
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI", f"http://127.0.0.1:{DEFAULT_PORT}/google-calendar/callback").strip()
GOOGLE_CALENDAR_SCOPES = [
    scope.strip()
    for scope in os.getenv("GOOGLE_CALENDAR_SCOPES", "https://www.googleapis.com/auth/calendar.readonly").split(",")
    if scope.strip()
]
try:
    GOOGLE_CALENDAR_MAX_EVENTS = max(1, int(os.getenv("GOOGLE_CALENDAR_MAX_EVENTS", "100")))
except ValueError:
    GOOGLE_CALENDAR_MAX_EVENTS = 100
supabase: Optional[Client] = None
supabase_admin: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    try:
        supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)
    except Exception as exc:
        app.logger.warning("SUPABASE_SERVICE_KEY invalida ou incompativel: %s", exc)
        supabase_admin = None

_LOCAL_PASSWORD_SUPPORT: Optional[bool] = None


def _ready() -> bool:
    return supabase is not None


def _client() -> Client:
    if not supabase:
        raise RuntimeError("Supabase nao configurado.")
    return supabase


def _admin_client() -> Client:
    return supabase_admin or _client()


def _csrf_token() -> str:
    token = session.get("_csrf_token")
    if not token:
        token = secrets.token_hex(32)
        session["_csrf_token"] = token
    return token


@app.context_processor
def _inject_template_helpers():
    flashed = get_flashed_messages(with_categories=True)
    success_message = next((message for category, message in flashed if category in {"success", "info"}), "")
    error_message = next((message for category, message in flashed if category == "error"), "")
    return {
        "csrf_token": _csrf_token,
        "csrf_form_token": _csrf_token,
        "current_year": datetime.now().year,
        "sucesso": success_message,
        "erro": error_message,
    }


def _require_csrf() -> Optional[str]:
    expected = session.get("_csrf_token")
    provided = request.form.get("csrf_token", "")
    if not expected or not provided or not secrets.compare_digest(expected, provided):
        return "Token de seguranca invalido. Atualize a pagina e tente novamente."
    return None


def _first(row: Dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if key in row and row.get(key) not in (None, ""):
            return row.get(key)
    return default


def _clean_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    clean: Dict[str, Any] = {}
    for key, value in payload.items():
        if value is None:
            continue
        if isinstance(value, str):
            value = value.strip()
            if value == "":
                continue
        clean[key] = value
    return clean


def _run_query(operation) -> Dict[str, Any]:
    if not _ready():
        return {"ok": False, "data": [], "error": "Supabase nao configurado."}
    try:
        result = operation()
        return {"ok": True, "data": result.data or [], "error": None}
    except Exception as exc:
        app.logger.exception("Erro ao consultar o Supabase")
        return {"ok": False, "data": [], "error": str(exc)}


def _select(
    table: str,
    *,
    filters: Optional[Dict[str, Any]] = None,
    order: Optional[str] = None,
    desc: bool = False,
    limit: Optional[int] = None,
) -> Dict[str, Any]:
    def _op():
        query = _admin_client().table(table).select("*")
        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)
        if order:
            query = query.order(order, desc=desc)
        if limit:
            query = query.limit(limit)
        return query.execute()

    return _run_query(_op)


def _select_one(table: str, row_id: str) -> Dict[str, Any]:
    def _op():
        return _admin_client().table(table).select("*").eq("id", row_id).limit(1).execute()

    result = _run_query(_op)
    if result["ok"]:
        result["data"] = result["data"][0] if result["data"] else None
    return result


def _select_first_by(table: str, field: str, value: Any) -> Dict[str, Any]:
    def _op():
        return _admin_client().table(table).select("*").eq(field, value).limit(1).execute()

    result = _run_query(_op)
    if result["ok"]:
        result["data"] = result["data"][0] if result["data"] else None
    return result


def _insert(table: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = _clean_payload(payload)

    def _op():
        return _admin_client().table(table).insert(payload).execute()

    return _run_query(_op)


def _insert_raw(table: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    def _op():
        return _admin_client().table(table).insert(payload).execute()

    return _run_query(_op)


def _update(table: str, row_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = _clean_payload(payload)

    def _op():
        return _admin_client().table(table).update(payload).eq("id", row_id).execute()

    return _run_query(_op)


def _delete(table: str, row_id: str) -> Dict[str, Any]:
    def _op():
        return _admin_client().table(table).delete().eq("id", row_id).execute()

    return _run_query(_op)


def _missing_table_error(error: Optional[str]) -> bool:
    if not error:
        return False
    lowered = error.lower()
    return (
        "does not exist" in lowered
        or "could not find the table" in lowered
        or "pgrst205" in lowered
        or "42p01" in lowered
    )


def _message_table_error_message(error: Optional[str]) -> str:
    if _missing_table_error(error):
        return f"Tabela de mensagens nao encontrada no Supabase. Crie ou configure a tabela {TABLE_MENSAGENS} para habilitar o envio."
    return error or "Nao foi possivel enviar a mensagem."


def _anamnese_table_error_message(error: Optional[str]) -> str:
    if _missing_table_error(error):
        return f"Tabela de anamnese nao encontrada no Supabase. Execute o schema para criar {TABLE_ANAMNESES} antes de salvar."
    return error or "Nao foi possivel salvar a anamnese."


def _observacao_table_error_message(error: Optional[str]) -> str:
    if _missing_table_error(error):
        return f"Tabela de observacoes nao encontrada no Supabase. Execute o schema para criar {TABLE_OBSERVACOES} antes de salvar."
    return error or "Nao foi possivel salvar a observacao."


def _missing_column_error(error: Optional[str], column: str = "") -> bool:
    if not error:
        return False
    lowered = error.lower()
    column_match = not column or column.lower() in lowered
    return column_match and (
        "could not find" in lowered
        or "schema cache" in lowered
        or "pgrst204" in lowered
        or "42703" in lowered
    )


def _plan_table_error_message(error: Optional[str]) -> str:
    if _missing_table_error(error):
        return f"Tabela de planos nao encontrada no Supabase. Execute o schema para criar {TABLE_PLANOS}."
    if _missing_column_error(error):
        return f"Estrutura da tabela {TABLE_PLANOS} incompleta no Supabase. Execute o schema ou adicione as colunas nome, descricao, preco, duracao_dias e recorrente."
    return error or "Nao foi possivel criar o plano."


def _table_has_local_passwords() -> bool:
    global _LOCAL_PASSWORD_SUPPORT
    if _LOCAL_PASSWORD_SUPPORT is not None:
        return _LOCAL_PASSWORD_SUPPORT
    if not _ready():
        _LOCAL_PASSWORD_SUPPORT = False
        return False
    try:
        _admin_client().table(TABLE_USUARIOS).select("senha_hash").limit(1).execute()
        _LOCAL_PASSWORD_SUPPORT = True
    except Exception as exc:
        _LOCAL_PASSWORD_SUPPORT = False
        app.logger.warning("Modo de senha local indisponivel: %s", exc)
    return _LOCAL_PASSWORD_SUPPORT


def _to_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value: Any) -> Optional[int]:
    if value in (None, ""):
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _to_uuid_or_none(value: Any) -> Optional[str]:
    if not value:
        return None
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError):
        return None


def _fmt_date(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f"):
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%d/%m/%Y")
        except ValueError:
            try:
                return datetime.strptime(text, fmt).strftime("%d/%m/%Y")
            except ValueError:
                continue
    return text


def _fmt_datetime(value: Any) -> str:
    if not value:
        return ""
    text = str(value)
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y %H:%M")
    except ValueError:
        return text


def _fmt_hour_range(start: Any, end: Any) -> str:
    def _hour(value: Any) -> str:
        if not value:
            return "--:--"
        text = str(value)
        try:
            return datetime.fromisoformat(text.replace("Z", "+00:00")).strftime("%H:%M")
        except ValueError:
            if "T" in text:
                return text.split("T", 1)[1][:5]
            return text[:5]

    return f"{_hour(start)} - {_hour(end)}"


def _fmt_time(value: Any) -> str:
    if not value:
        return "--:--"
    text = str(value)
    if "T" in text:
        text = text.split("T", 1)[1]
    return text[:5] if text else "--:--"


def _currency(value: Any) -> str:
    number = _to_float(value)
    if number is None:
        return "R$ 0,00"
    return f"R$ {number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _slug_status(value: Any) -> str:
    text = str(value or "pendente").strip().lower()
    return {
        "confirmed": "confirmado",
        "done": "concluido",
        "paid": "pago",
        "open": "disponivel",
    }.get(text, text)


PAYMENT_STATUS_TO_DB = {"pendente": 1, "pago": 2, "atrasado": 3}
PAYMENT_STATUS_FROM_DB = {1: "pendente", 2: "pago", 3: "atrasado"}
AGENDA_META_PREFIX = "__agenda_meta__:"


def _is_uuid(value: Any) -> bool:
    if not value:
        return False
    try:
        UUID(str(value))
        return True
    except (TypeError, ValueError):
        return False


def _slug_text(value: Any) -> str:
    return str(value or "").strip().lower().replace(" ", "-").replace("_", "-")


def _payment_status_slug(value: Any) -> str:
    if isinstance(value, int):
        return PAYMENT_STATUS_FROM_DB.get(value, "pendente")
    text = str(value or "").strip()
    if text.isdigit():
        return PAYMENT_STATUS_FROM_DB.get(int(text), "pendente")
    return _slug_status(text)


def _payment_status_db(value: Any) -> int:
    return PAYMENT_STATUS_TO_DB.get(_slug_status(value), 1)


def _split_datetime_local(value: Any) -> Dict[str, str]:
    text = str(value or "").strip()
    if not text:
        return {"data": "", "hora": ""}
    try:
        parsed = datetime.fromisoformat(text)
        return {"data": parsed.date().isoformat(), "hora": parsed.time().replace(microsecond=0).isoformat()}
    except ValueError:
        if "T" in text:
            data, hora = text.split("T", 1)
            return {"data": data, "hora": hora[:8]}
        return {"data": text[:10], "hora": text[11:19] if len(text) >= 16 else ""}


def _combine_date_time(data: Any, hora: Any) -> str:
    date_part = str(data or "").strip()
    time_part = str(hora or "").strip()
    if not date_part:
        return ""
    if not time_part:
        return date_part
    return f"{date_part}T{time_part}"


def _human_status(value: Any) -> str:
    status = _slug_status(value)
    return {
        "pendente": "Pendente",
        "confirmado": "Confirmado",
        "concluido": "Concluido",
        "cancelado": "Cancelado",
        "disponivel": "Disponivel",
        "agendado": "Agendado",
        "pago": "Pago",
        "atrasado": "Atrasado",
    }.get(status, str(value or "Pendente"))


def _initials(name: str) -> str:
    parts = [part for part in str(name or "").split() if part]
    if not parts:
        return "AL"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[-1][0]).upper()


def _build_agenda_observacao(titulo: Any, observacoes: Any, termino_hora: Any) -> str:
    meta = {
        "titulo": str(titulo or "").strip(),
        "termino": str(termino_hora or "").strip(),
    }
    body = str(observacoes or "").strip()
    payload = AGENDA_META_PREFIX + json.dumps(meta, ensure_ascii=False)
    return f"{payload}\n{body}".strip()


def _parse_agenda_observacao(value: Any) -> Dict[str, str]:
    text = str(value or "").strip()
    if not text.startswith(AGENDA_META_PREFIX):
        return {"titulo": "", "termino": "", "observacoes": text}

    first_line, _, remainder = text.partition("\n")
    raw_meta = first_line[len(AGENDA_META_PREFIX):].strip()
    try:
        meta = json.loads(raw_meta) if raw_meta else {}
    except json.JSONDecodeError:
        meta = {}
    return {
        "titulo": str(meta.get("titulo", "")).strip(),
        "termino": str(meta.get("termino", "")).strip(),
        "observacoes": remainder.strip(),
    }


def _default_end_from_start(start_value: Any) -> str:
    text = str(start_value or "").strip()
    if not text:
        return ""
    try:
        end_dt = datetime.fromisoformat(text.replace("Z", "+00:00")).replace(second=0, microsecond=0) + timedelta(hours=1)
        return end_dt.isoformat()
    except ValueError:
        return ""


def _session_user() -> Dict[str, Any]:
    return {
        "id": session.get("user_id", ""),
        "email": session.get("user_email", ""),
        "nome": session.get("user_nome", ""),
        "tipo_conta": session.get("user_role", ""),
        "auth_user_id": session.get("auth_user_id", ""),
    }


def _set_session_user(user: Dict[str, Any]) -> None:
    session["user_id"] = user.get("id", "")
    session["user_email"] = user.get("email", "")
    session["user_nome"] = user.get("nome", "")
    session["user_role"] = user.get("tipo_conta", "")
    session["auth_user_id"] = user.get("auth_user_id", "")
    _csrf_token()


def _clear_session() -> None:
    session.clear()


def _google_calendar_enabled() -> bool:
    return bool(GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET and GOOGLE_REDIRECT_URI)


def _google_token_file(email: str) -> Path:
    safe_email = "".join(ch if ch.isalnum() else "_" for ch in (email or "user").lower())
    return TOKENS_DIR / f"google_calendar_{safe_email}.json"


def _google_client_config() -> Dict[str, Any]:
    return {
        "web": {
            "client_id": GOOGLE_CLIENT_ID,
            "client_secret": GOOGLE_CLIENT_SECRET,
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "redirect_uris": [GOOGLE_REDIRECT_URI],
        }
    }


def _google_oauth_flow(state: Optional[str] = None) -> Flow:
    flow = Flow.from_client_config(_google_client_config(), scopes=GOOGLE_CALENDAR_SCOPES, state=state)
    flow.redirect_uri = GOOGLE_REDIRECT_URI
    return flow


def _save_google_credentials(email: str, credentials: Credentials) -> None:
    if not email:
        return
    TOKENS_DIR.mkdir(parents=True, exist_ok=True)
    _google_token_file(email).write_text(credentials.to_json(), encoding="utf-8")


def _load_google_credentials(email: str) -> Optional[Credentials]:
    if not _google_calendar_enabled() or not email:
        return None
    token_file = _google_token_file(email)
    if not token_file.exists():
        return None
    try:
        credentials = Credentials.from_authorized_user_file(str(token_file), GOOGLE_CALENDAR_SCOPES)
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(GoogleAuthRequest())
            _save_google_credentials(email, credentials)
        return credentials if credentials and credentials.valid else None
    except Exception as exc:
        app.logger.warning("Nao foi possivel carregar token do Google Calendar: %s", exc)
        return None


def _delete_google_credentials(email: str) -> None:
    if not email:
        return
    token_file = _google_token_file(email)
    if token_file.exists():
        token_file.unlink()


def _google_event_dt(value: str) -> Optional[datetime]:
    if not value:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        if text.endswith("Z"):
            text = text.replace("Z", "+00:00")
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.strptime(text, "%Y-%m-%d")
        except ValueError:
            return None


def _fmt_google_event_label(start_value: str, end_value: str) -> str:
    start_dt = _google_event_dt(start_value)
    end_dt = _google_event_dt(end_value)
    if not start_dt:
        return "Horario nao informado"
    if "T" not in str(start_value):
        return f"{start_dt.strftime('%d/%m/%Y')} (dia todo)"
    if end_dt:
        return f"{start_dt.strftime('%d/%m/%Y %H:%M')} - {end_dt.strftime('%H:%M')}"
    return start_dt.strftime("%d/%m/%Y %H:%M")


def _google_calendar_context() -> Dict[str, Any]:
    current = _session_user()
    email = current.get("email", "")
    base_context = {
        "enabled": _google_calendar_enabled(),
        "connected": False,
        "events": [],
        "calendar_count": 0,
        "error": "",
        "connect_url": url_for("google_calendar_connect"),
        "disconnect_url": url_for("google_calendar_disconnect"),
    }
    if not base_context["enabled"]:
        base_context["error"] = "Configure GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET e GOOGLE_REDIRECT_URI para conectar o Google Calendar."
        return base_context

    credentials = _load_google_credentials(email)
    if not credentials:
        return base_context

    try:
        service = build("calendar", "v3", credentials=credentials, cache_discovery=False)
        calendar_items: List[Dict[str, Any]] = []
        page_token = None
        while True:
            response = service.calendarList().list(pageToken=page_token).execute()
            calendar_items.extend(response.get("items", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        now = datetime.utcnow().isoformat() + "Z"
        collected_events: List[Dict[str, Any]] = []
        for calendar_item in calendar_items:
            calendar_id = calendar_item.get("id")
            if not calendar_id:
                continue
            events_response = service.events().list(
                calendarId=calendar_id,
                timeMin=now,
                singleEvents=True,
                orderBy="startTime",
                maxResults=min(GOOGLE_CALENDAR_MAX_EVENTS, 50),
            ).execute()
            calendar_name = calendar_item.get("summaryOverride") or calendar_item.get("summary") or "Google Calendar"
            for event in events_response.get("items", []):
                start_value = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date") or ""
                end_value = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date") or ""
                sort_dt = _google_event_dt(start_value) or datetime.max
                collected_events.append(
                    {
                        "id": event.get("id", ""),
                        "titulo": event.get("summary") or "Evento sem titulo",
                        "calendar_nome": calendar_name,
                        "intervalo": _fmt_google_event_label(start_value, end_value),
                        "local": event.get("location", ""),
                        "descricao": event.get("description", ""),
                        "link": event.get("htmlLink", ""),
                        "organizador": event.get("organizer", {}).get("displayName") or event.get("organizer", {}).get("email", ""),
                        "status": event.get("status", "confirmed"),
                        "status_classe": "cancelado" if event.get("status") == "cancelled" else "confirmado",
                        "sort_dt": sort_dt,
                    }
                )

        collected_events.sort(key=lambda item: item["sort_dt"])
        for event in collected_events:
            event.pop("sort_dt", None)

        base_context.update(
            {
                "connected": True,
                "events": collected_events[:GOOGLE_CALENDAR_MAX_EVENTS],
                "calendar_count": len(calendar_items),
            }
        )
        return base_context
    except HttpError as exc:
        base_context["error"] = f"Falha ao consultar o Google Calendar: {exc}"
        return base_context
    except Exception as exc:
        app.logger.exception("Erro ao carregar eventos do Google Calendar")
        base_context["error"] = f"Nao foi possivel carregar os eventos do Google Calendar: {exc}"
        return base_context


def _is_student_path(path: str) -> bool:
    legacy_student_paths = {
        "/agenda-aluno",
        "/agenda-aluno.html",
        "/aluno_dashboard.html",
        "/aluno_meu_treino.html",
        "/aluno_mensagens.html",
        "/aluno_treino_execucao.html",
        "/evolucao-aluno",
        "/evolucao-aluno.html",
    }
    return path == "/aluno" or path.startswith("/aluno/") or path in legacy_student_paths


def _dev_user_for_path(path: str) -> Dict[str, Any]:
    if _is_student_path(path):
        return {
            "id": DEV_ALUNO_ID,
            "email": "aluno.teste@confie.local",
            "nome": "Aluno Teste",
            "tipo_conta": "Aluno",
            "auth_user_id": "dev-auth-aluno",
        }
    return {
        "id": DEV_PERSONAL_ID,
        "email": "personal.teste@confie.local",
        "nome": "Personal Teste",
        "tipo_conta": "Personal Trainer",
        "auth_user_id": "dev-auth-personal",
    }


def _ensure_dev_session() -> None:
    if not DEV_BYPASS_AUTH or request.endpoint == "static":
        return
    current = _session_user()
    expected = _dev_user_for_path(request.path)
    if current["email"] != expected["email"] or current["tipo_conta"] != expected["tipo_conta"]:
        _set_session_user(expected)


@app.before_request
def _apply_dev_auth_bypass():
    _ensure_dev_session()


def _find_user_by_email(email: str) -> Dict[str, Any]:
    return _select_first_by(TABLE_USUARIOS, "email", email.strip().lower())


def _local_auth_schema_message() -> str:
    return (
        "A tabela tb_usuario precisa ter a coluna senha_hash do tipo text. "
        "No Supabase, rode: alter table public.tb_usuario add column if not exists senha_hash text;"
    )


def _auth_write_error_message(error: Optional[str]) -> str:
    if not error:
        return "Nao foi possivel criar a conta."
    lowered = error.lower()
    if "row-level security" in lowered or "42501" in lowered:
        return (
            "O Supabase bloqueou o cadastro por RLS. Preencha SUPABASE_SERVICE_KEY no .env "
            "com a service_role key do projeto ou crie uma policy de insert para tb_usuario."
        )
    if "invalid input syntax for type uuid" in lowered and "senha_hash" in lowered:
        return "A coluna senha_hash esta com tipo errado. Ela precisa ser text, nao uuid."
    return error


def _current_user_row() -> Optional[Dict[str, Any]]:
    email = (session.get("user_email") or "").strip().lower()
    if not email:
        return _dev_user_for_path(request.path) if DEV_BYPASS_AUTH else None
    result = _find_user_by_email(email)
    if result["ok"] and result["data"]:
        return result["data"]
    return _dev_user_for_path(request.path) if DEV_BYPASS_AUTH else None


def _current_student_row() -> Optional[Dict[str, Any]]:
    current = _session_user()
    if not current["email"]:
        if DEV_BYPASS_AUTH:
            return {
                "id": DEV_ALUNO_ID,
                "nome": "Aluno Teste",
                "email": "aluno.teste@confie.local",
                "telefone": "",
                "objetivo": "Testar as telas",
                "status": "ativo",
                "plano": "Teste",
            }
        return None
    current_email = str(current["email"] or "").strip().lower()
    current_user_id = str(current["id"] or "").strip()
    current_auth_user_id = str(current["auth_user_id"] or "").strip()

    by_email = _select_first_by(TABLE_ALUNOS, "email", current_email)
    if by_email["ok"] and by_email["data"]:
        return by_email["data"]

    for row in _load_rows(TABLE_ALUNOS):
        row_email = str(_first(row, "email", default="")).strip().lower()
        row_id = str(_first(row, "id", default="")).strip()
        row_auth_user_id = str(_first(row, "auth_user_id", default="")).strip()
        if current_email and row_email == current_email:
            return row
        if current_auth_user_id and row_auth_user_id == current_auth_user_id:
            return row
        if current_user_id and row_id == current_user_id:
            return row

    if DEV_BYPASS_AUTH:
        return {
            "id": DEV_ALUNO_ID,
            "nome": current["nome"] or "Aluno Teste",
            "email": current["email"] or "aluno.teste@confie.local",
            "telefone": "",
            "objetivo": "Testar as telas",
            "status": "ativo",
            "plano": "Teste",
        }
    return None


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if DEV_BYPASS_AUTH:
            _ensure_dev_session()
        if not session.get("user_email"):
            flash("Entre na plataforma para continuar.", "error")
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def role_required(*allowed_roles: str):
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if DEV_BYPASS_AUTH:
                _ensure_dev_session()
            current_role = (session.get("user_role") or "").strip().lower()
            if current_role not in [role.lower() for role in allowed_roles]:
                flash("Voce nao tem permissao para acessar esta area.", "error")
                return redirect(url_for("dashboard" if current_role != "aluno" else "aluno_dashboard"))
            return view(*args, **kwargs)

        return wrapped

    return decorator


def _common_brand_context() -> Dict[str, Any]:
    return {
        "marca_nome": BRAND_NAME,
        "marca_logo_url_valor": BRAND_LOGO_URL,
        "brand_name": BRAND_NAME,
        "brand_logo_url": BRAND_LOGO_URL,
        "home_url": "/index.html",
    }


def _personal_context(pagina_ativa: str) -> Dict[str, Any]:
    user = _session_user()
    return {
        **_common_brand_context(),
        "pagina_ativa": pagina_ativa,
        "profissional_id": user["id"],
        "profissional_nome": user["nome"] or "Personal Trainer",
        "nome_usuario": user["nome"] or "Personal Trainer",
        "dashboard_url": url_for("dashboard"),
        "alunos_url": url_for("alunos"),
        "treinos_url": url_for("treinos"),
        "agenda_url": url_for("agenda"),
        "mensagens_url": url_for("mensagens"),
        "anamnese_url": url_for("anamnese"),
        "observacoes_url": url_for("observacoes"),
        "avaliacoes_url": url_for("avaliacoes"),
        "evolucao_url": url_for("evolucao"),
        "financeiro_url": url_for("financeiro"),
        "exercicios_url": url_for("exercicios"),
        "configuracoes_url": url_for("configuracoes"),
        "logout_url": url_for("logout"),
    }


def _student_context(pagina_ativa: str) -> Dict[str, Any]:
    user = _session_user()
    aluno = _current_student_row() or {}
    aluno_nome = _first(aluno, "nome", default=user["nome"] or "Aluno")
    aluno_id = _first(aluno, "id", default=user["id"])
    return {
        **_common_brand_context(),
        "pagina_ativa": pagina_ativa,
        "aluno_nome": aluno_nome,
        "aluno_id": aluno_id,
        "dashboard_url": url_for("aluno_dashboard"),
        "aluno_dashboard_url": url_for("aluno_dashboard"),
        "meu_treino_url": url_for("aluno_meu_treino"),
        "aluno_treinos_url": url_for("aluno_meu_treino"),
        "agenda_aluno_url": url_for("agenda_aluno"),
        "aluno_agenda_url": url_for("agenda_aluno"),
        "mensagens_url": url_for("aluno_mensagens"),
        "aluno_mensagens_url": url_for("aluno_mensagens"),
        "evolucao_url": url_for("evolucao_aluno"),
        "evolucao_aluno_url": url_for("evolucao_aluno"),
        "logout_url": url_for("logout"),
    }


def _load_rows(table: str, *, filters: Optional[Dict[str, Any]] = None, order: Optional[str] = None, desc: bool = False) -> List[Dict[str, Any]]:
    result = _select(table, filters=filters, order=order, desc=desc)
    if not result["ok"]:
        return []
    return result["data"]


def _students() -> List[Dict[str, Any]]:
    rows = _load_rows(TABLE_ALUNOS)
    planos_por_id = {str(row.get("id")): row for row in _optional_rows(TABLE_PLANOS)}
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        name = _first(row, "nome", "name", default="Aluno")
        plano_id = _first(row, "plano", default="")
        plano_ref = planos_por_id.get(str(plano_id), {})
        normalized.append(
            {
                **row,
                "id": row.get("id", ""),
                "nome": name,
                "email": _first(row, "email", default=""),
                "telefone": _first(row, "telefone", "celular", "phone", default=""),
                "data_nascimento": _fmt_date(_first(row, "data_nascimento", "nascimento")),
                "objetivo": _first(row, "objetivo", "goal", default="Nao informado"),
                "status": _human_status(_first(row, "status", default="ativo")),
                "plano_id": plano_id,
                "plano": _first(row, "plano_descricao", default=_first(plano_ref, "nome", default=plano_id or "Nao definido")),
                "avatar_iniciais": _initials(name),
            }
        )
    return normalized


def _parse_exercises(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        parsed_items: List[Dict[str, Any]] = []
        for index, item in enumerate(raw, start=1):
            if isinstance(item, dict):
                name = _first(item, "nome", "name", "exercicio", default="").strip()
                if not name:
                    continue
                parsed_items.append(
                    {
                        "id": _first(item, "id", default=f"ex-{index}"),
                        "nome": name,
                        "series": _first(item, "series", default="3"),
                        "repeticoes": _first(item, "repeticoes", "reps", default="12"),
                        "descanso": _first(item, "descanso", default="60s"),
                        "prescricao": _first(item, "prescricao", default=""),
                        "status": _first(item, "status", default="Pendente"),
                    }
                )
            else:
                text_item = str(item).strip()
                if text_item:
                    parsed_items.append(
                        {
                            "id": f"ex-{index}",
                            "nome": text_item.split("-", 1)[0].strip(),
                            "series": "3",
                            "repeticoes": "12",
                            "descanso": "60s",
                            "status": "Pendente",
                        }
                    )
        return parsed_items
    else:
        text = str(raw or "").replace("\r", "\n")
        text = text.replace(";", "\n").replace("|", "\n")
        items = [part.strip() for part in text.split("\n") if part.strip()]
    parsed: List[Dict[str, Any]] = []
    for index, item in enumerate(items, start=1):
        parsed.append(
            {
                "id": f"ex-{index}",
                "nome": item.split("-", 1)[0].strip(),
                "series": "3",
                "repeticoes": "12",
                "descanso": "60s",
                "status": "Pendente",
            }
        )
    return parsed


def _trainings(aluno_id: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _load_rows(TABLE_TREINOS, filters={"aluno_id": aluno_id} if aluno_id else None)
    alunos_por_id = {row["id"]: row for row in _students()}
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        exercises_raw = _first(row, "exercicios_raw", "exercicios", "observacao", default="")
        exercises = _parse_exercises(exercises_raw)
        aluno_ref = alunos_por_id.get(_first(row, "aluno_id", default=""), {})
        normalized.append(
            {
                **row,
                "id": row.get("id", ""),
                "nome": _first(row, "nome", "name", "descricao", default="Treino"),
                "aluno_id": _first(row, "aluno_id", default=""),
                "aluno_nome": _first(row, "aluno_nome", default=aluno_ref.get("nome", "Aluno")),
                "status": _human_status(_first(row, "status", default="ativo")),
                "grupo_muscular": _first(row, "grupo_muscular", default="Treino personalizado"),
                "observacoes": _first(row, "observacoes", "observacao", "notes", default=""),
                "exercicios_raw": exercises_raw,
                "exercicios": exercises,
                "exercicios_lista": exercises,
                "total_exercicios": _to_int(_first(row, "total_exercicios", default=len(exercises))) or len(exercises),
                "atualizado_em": _fmt_date(_first(row, "updated_at", "created_at", "data_criacao")),
                "video_url": _first(row, "video_url", default=""),
            }
        )
    if aluno_id:
        aluno_id_normalized = str(aluno_id)
        normalized = [
            treino
            for treino in normalized
            if str(treino.get("aluno_id", "")) == aluno_id_normalized
        ]
    return normalized


def _schedule_rows() -> List[Dict[str, Any]]:
    rows = _load_rows(TABLE_AGENDA)
    alunos_por_id = {row["id"]: row for row in _students()}
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        aluno_ref = alunos_por_id.get(_first(row, "aluno_id", default=""), {})
        status = _slug_status(_first(row, "status", default="pendente"))
        observacao_bruta = _first(row, "observacao", "observacoes", "notes", default="")
        agenda_meta = _parse_agenda_observacao(observacao_bruta)
        observacao = agenda_meta["observacoes"]
        title = _first(
            row,
            "titulo",
            "nome",
            "title",
            default=agenda_meta["titulo"] or (str(observacao).splitlines()[0] if observacao else ("Horario disponivel" if status == "disponivel" else "Aula")),
        )
        start = _first(row, "inicio", "data_hora_inicio", "data_hora", "start_time", "starts_at", default="")
        if not start:
            start = _combine_date_time(_first(row, "data", default=""), _first(row, "hora", default=""))
        end = _first(row, "termino", "data_hora_fim", "end_time", "ends_at", default="")
        if not end and agenda_meta["termino"]:
            end = _combine_date_time(_first(row, "data", default=""), agenda_meta["termino"])
        if start and row.get("hora") and "T" not in str(start):
            start = f"{start}T{str(row.get('hora'))[:5]}"
        if not end:
            end = _default_end_from_start(start)
        google_calendar_url = _first(row, "google_calendar_url", default="")
        if not google_calendar_url and start:
            start_raw = str(start).replace("-", "").replace(":", "").replace("T", "").split(".")[0]
            end_raw = str(end or start).replace("-", "").replace(":", "").replace("T", "").split(".")[0]
            google_calendar_url = f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={title}&dates={start_raw}/{end_raw}"
        start_hour = _fmt_time(start)
        end_hour = _fmt_time(end)
        hours = start_hour if end_hour == "--:--" else f"{start_hour} - {end_hour}"
        normalized.append(
            {
                **row,
                "id": row.get("id", ""),
                "titulo": title,
                "aluno_id": _first(row, "aluno_id", default=""),
                "aluno_nome": _first(row, "aluno_nome", default=aluno_ref.get("nome", "")),
                "status": _human_status(status),
                "status_slug": status,
                "status_label": _human_status(status),
                "status_class": status,
                "status_classe": status,
                "inicio": start_hour,
                "termino": end_hour,
                "inicio_iso": start,
                "termino_iso": end,
                "data": _fmt_date(start),
                "hora": hours,
                "tipo": _first(row, "tipo", "category", default="Horario disponivel" if status == "disponivel" else "Aula"),
                "observacoes": observacao,
                "google_calendar_url": google_calendar_url,
            }
        )
    return normalized


def _assessment_metrics_legacy(row: Dict[str, Any]) -> Dict[str, Any]:
    peso = _to_float(_first(row, "peso"))
    altura_cm = _to_float(_first(row, "estatura", "altura"))
    gordura = _to_float(_first(row, "gordura", "percentual_gordura"))
    cintura = _to_float(_first(row, "cintura"))
    quadril = _to_float(_first(row, "quadril"))
    imc: Optional[float] = None
    if peso and altura_cm:
        altura_m = altura_cm / 100
        if altura_m > 0:
            imc = peso / (altura_m * altura_m)
    massa_gorda = peso * (gordura / 100) if peso is not None and gordura is not None else None
    massa_magra = peso - massa_gorda if peso is not None and massa_gorda is not None else None
    relacao = cintura / quadril if cintura and quadril else None
    soma_dobras = sum(
        item
        for item in [
            _to_float(_first(row, "tricipital")),
            _to_float(_first(row, "subscapular")),
            _to_float(_first(row, "suprailiaca")),
            _to_float(_first(row, "abdominal")),
            _to_float(_first(row, "peitoral")),
            _to_float(_first(row, "coxa")),
            _to_float(_first(row, "perna")),
        ]
        if item is not None
    )
    if gordura is None:
        classificacao_gordura = "Nao informada"
    elif gordura <= 14:
        classificacao_gordura = "Excelente"
    elif gordura <= 20:
        classificacao_gordura = "Boa"
    elif gordura <= 25:
        classificacao_gordura = "Moderada"
    else:
        classificacao_gordura = "Alta"
    if imc is None:
        classificacao_imc = "Nao informada"
    elif imc < 18.5:
        classificacao_imc = "Baixo peso"
    elif imc < 25:
        classificacao_imc = "Peso normal"
    elif imc < 30:
        classificacao_imc = "Sobrepeso"
    else:
        classificacao_imc = "Obesidade"
    peso_ideal = None
    if massa_magra is not None:
        peso_ideal = massa_magra / (1 - 0.14)
    return {
        "imc": f"{imc:.2f}".replace(".", ",") if imc is not None else "—",
        "gordura": f"{gordura:.0f}%" if gordura is not None and gordura.is_integer() else (f"{gordura:.2f}%".replace(".", ",") if gordura is not None else "—"),
        "massa_gorda": f"{massa_gorda:.2f} kg".replace(".", ",") if massa_gorda is not None else "—",
        "massa_magra": f"{massa_magra:.2f} kg".replace(".", ",") if massa_magra is not None else "—",
        "classificacao": classificacao_imc,
        "classificacao_gordura": classificacao_gordura,
        "gordura_nivel": classificacao_gordura,
        "peso_ideal": f"{peso_ideal:.2f} kg".replace(".", ",") if peso_ideal is not None else "—",
        "soma_dobras": f"{soma_dobras:.0f} mm" if soma_dobras else "—",
        "relacao_cq": f"{relacao:.2f}".replace(".", ",") if relacao is not None else "—",
    }


def _assessment_metrics(row: Dict[str, Any]) -> Dict[str, Any]:
    peso = _to_float(_first(row, "peso"))
    altura_cm = _to_float(_first(row, "estatura", "altura"))
    gordura = _to_float(_first(row, "gordura", "percentual_gordura"))
    cintura = _to_float(_first(row, "cintura"))
    quadril = _to_float(_first(row, "quadril"))
    imc: Optional[float] = None
    if peso and altura_cm:
        altura_m = altura_cm / 100
        if altura_m > 0:
            imc = peso / (altura_m * altura_m)
    massa_gorda = peso * (gordura / 100) if peso is not None and gordura is not None else None
    massa_magra = peso - massa_gorda if peso is not None and massa_gorda is not None else None
    relacao = cintura / quadril if cintura and quadril else None
    soma_dobras = sum(
        item
        for item in [
            _to_float(_first(row, "tricipital")),
            _to_float(_first(row, "subscapular")),
            _to_float(_first(row, "suprailiaca")),
            _to_float(_first(row, "abdominal")),
            _to_float(_first(row, "peitoral")),
            _to_float(_first(row, "coxa")),
            _to_float(_first(row, "perna")),
        ]
        if item is not None
    )
    if gordura is None:
        classificacao_gordura = "Não informada"
    elif gordura <= 14:
        classificacao_gordura = "Excelente"
    elif gordura <= 20:
        classificacao_gordura = "Boa"
    elif gordura <= 25:
        classificacao_gordura = "Moderada"
    else:
        classificacao_gordura = "Alta"
    if imc is None:
        classificacao_imc = "Não informada"
    elif imc < 18.5:
        classificacao_imc = "Baixo peso"
    elif imc < 25:
        classificacao_imc = "Peso normal"
    elif imc < 30:
        classificacao_imc = "Sobrepeso"
    else:
        classificacao_imc = "Obesidade"
    peso_ideal = None
    if massa_magra is not None:
        peso_ideal = massa_magra / (1 - 0.14)
    return {
        "imc": f"{imc:.2f}".replace(".", ",") if imc is not None else "—",
        "gordura": f"{gordura:.0f}%" if gordura is not None and gordura.is_integer() else (f"{gordura:.2f}%".replace(".", ",") if gordura is not None else "—"),
        "massa_gorda": f"{massa_gorda:.2f} kg".replace(".", ",") if massa_gorda is not None else "—",
        "massa_magra": f"{massa_magra:.2f} kg".replace(".", ",") if massa_magra is not None else "—",
        "classificacao": classificacao_imc,
        "classificacao_gordura": classificacao_gordura,
        "gordura_nivel": classificacao_gordura,
        "peso_ideal": f"{peso_ideal:.2f} kg".replace(".", ",") if peso_ideal is not None else "—",
        "soma_dobras": f"{soma_dobras:.0f} mm" if soma_dobras else "—",
        "relacao_cq": f"{relacao:.2f}".replace(".", ",") if relacao is not None else "—",
    }


def _assessments(aluno_id: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _load_rows(TABLE_AVALIACOES, filters={"aluno_id": aluno_id} if aluno_id else None, order="data", desc=True)
    alunos_por_id = {row["id"]: row for row in _students()}
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        aluno_ref = alunos_por_id.get(_first(row, "aluno_id", default=""), {})
        metrics = _assessment_metrics(row)
        normalized.append(
            {
                **row,
                **metrics,
                "id": row.get("id", ""),
                "aluno_id": _first(row, "aluno_id", default=""),
                "aluno_nome": _first(row, "aluno_nome", default=aluno_ref.get("nome", "Aluno")),
                "peso": f"{_first(row, 'peso', default='0')} kg",
                "altura": f"{_first(row, 'estatura', 'altura', default='0')} cm",
                "data": _fmt_date(_first(row, "data", "created_at", "data_avaliacao")),
                "observacoes": _first(row, "observacoes", "observacao", default=""),
                "historico_label": f"Avaliacao {_first(row, 'numero', default='1')}",
                "status_label": metrics["classificacao"],
                "resumo": metrics["classificacao"],
                "objetivo": _first(row, "objetivo", default="Nao informado"),
                "exportar_pdf_url": url_for("exportar_avaliacao_pdf", avaliacao_id=row.get("id", "")) if row.get("id") else "",
            }
        )
    return normalized


def _exercises() -> List[Dict[str, Any]]:
    result = _select(TABLE_EXERCICIOS)
    if not result["ok"]:
        return []
    rows = result["data"]
    grupos_por_id = {str(row.get("id")): row for row in _optional_rows(TABLE_GRUPOS_MUSCULARES)}
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        grupo_ref = grupos_por_id.get(str(_first(row, "grupo_muscular_id", default="")), {})
        normalized.append(
            {
                **row,
                "id": row.get("id", ""),
                "nome": _first(row, "nome", "name", default="Exercicio"),
                "grupo_muscular": _first(row, "grupo_muscular", default=_first(grupo_ref, "nome", default=_first(row, "grupo_muscular_id", default="Nao informado"))),
                "descricao": _first(row, "descricao", "description", default=""),
                "video_url": _first(row, "video_url", "link_execucao", default=""),
                "imagem_url": _first(row, "imagem_url", default=""),
                "video_url": _first(row, "video_url", "link_execucao", default=""),
            }
        )
    return normalized


def _safe_pdf_filename(text: Any, *, fallback: str = "avaliacao") -> str:
    raw = str(text or "").strip().lower()
    if not raw:
        return fallback
    sanitized = []
    for char in raw:
        if char.isalnum():
            sanitized.append(char)
        elif char in {" ", "-", "_"}:
            sanitized.append("-")
    compact = "".join(sanitized).strip("-")
    while "--" in compact:
        compact = compact.replace("--", "-")
    return compact or fallback


def _avaliacao_pdf_document_legacy(avaliacao: Dict[str, Any]) -> BytesIO:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=16 * mm,
        rightMargin=16 * mm,
        topMargin=16 * mm,
        bottomMargin=14 * mm,
        title="Laudo de Avaliacao Fisica",
        author=BRAND_NAME,
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="ConfieKicker", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.HexColor("#ff5a0a"), spaceAfter=6))
    styles.add(ParagraphStyle(name="ConfieTitle", fontName="Helvetica-Bold", fontSize=24, leading=27, textColor=colors.HexColor("#111111"), spaceAfter=8))
    styles.add(ParagraphStyle(name="ConfieBody", fontName="Helvetica", fontSize=10.5, leading=14, textColor=colors.HexColor("#2d313a")))
    styles.add(ParagraphStyle(name="ConfieSmall", fontName="Helvetica", fontSize=9, leading=12, textColor=colors.HexColor("#5f6674")))
    styles.add(ParagraphStyle(name="ConfieCardLabel", fontName="Helvetica-Bold", fontSize=8, leading=10, textColor=colors.HexColor("#727a89")))
    styles.add(ParagraphStyle(name="ConfieCardValue", fontName="Helvetica-Bold", fontSize=18, leading=21, textColor=colors.HexColor("#111111")))
    styles.add(ParagraphStyle(name="ConfieSection", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=colors.HexColor("#111111"), spaceAfter=8))

    aluno_nome = _first(avaliacao, "aluno_nome", default="Aluno")
    resumo_cards = [
        ("PESO", _first(avaliacao, "peso", default="—")),
        ("IMC", _first(avaliacao, "imc", default="—")),
        ("% GORDURA", _first(avaliacao, "gordura", default="—")),
        ("MASSA MAGRA", _first(avaliacao, "massa_magra", default="—")),
    ]
    leitura_cards = [
        ("CLASSIFICACAO", _first(avaliacao, "classificacao", default="—")),
        ("% GORDURA", _first(avaliacao, "gordura_nivel", default="—")),
        ("MASSA GORDA", _first(avaliacao, "massa_gorda", default="—")),
        ("PESO IDEAL", _first(avaliacao, "peso_ideal", default="—")),
        ("RELACAO C/Q", _first(avaliacao, "relacao_cq", default="—")),
        ("SOMA DAS DOBRAS", _first(avaliacao, "soma_dobras", default="—")),
    ]
    medidas_cards = [
        ("TRICIPITAL", _first(avaliacao, "tricipital", default="—")),
        ("SUBSCAPULAR", _first(avaliacao, "subscapular", default="—")),
        ("SUPRAILIACA", _first(avaliacao, "suprailiaca", default="—")),
        ("ABDOMINAL", _first(avaliacao, "abdominal", default="—")),
        ("PEITORAL", _first(avaliacao, "peitoral", default="—")),
        ("COXA", _first(avaliacao, "coxa", default="—")),
        ("PERNA", _first(avaliacao, "perna", default="—")),
        ("BRACO DIREITO", _first(avaliacao, "braco_direito", default="—")),
        ("PEITORAL CIRC.", _first(avaliacao, "peitoral_circ", default="—")),
        ("CINTURA", _first(avaliacao, "cintura", default="—")),
        ("QUADRIL", _first(avaliacao, "quadril", default="—")),
        ("COXA DIREITA", _first(avaliacao, "coxa_direita", default="—")),
        ("PERNA DIREITA", _first(avaliacao, "perna_direita", default="—")),
    ]

    story = [
        Paragraph(BRAND_NAME, styles["ConfieKicker"]),
        Paragraph("LAUDO DE AVALIACAO FISICA", styles["ConfieTitle"]),
        Paragraph(
            f"<b>Aluno:</b> {aluno_nome}<br/><b>Data da avaliacao:</b> {_first(avaliacao, 'data', default='—')}<br/><b>Classificacao:</b> {_first(avaliacao, 'classificacao', default='—')}",
            styles["ConfieBody"],
        ),
        Spacer(1, 8),
    ]

    summary_table = Table(
        [[Paragraph(label, styles["ConfieCardLabel"]), Paragraph(value, styles["ConfieCardValue"])] for label, value in resumo_cards],
        colWidths=[38 * mm, 43 * mm],
    )
    summary_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#dadde5")),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#dadde5")),
                ("BACKGROUND", (0, 0), (-1, -1), colors.white),
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                ("TOPPADDING", (0, 0), (-1, -1), 8),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.extend([summary_table, Spacer(1, 12)])

    story.append(Paragraph("LEITURA CORPORAL", styles["ConfieSection"]))
    leitura_rows = []
    for index in range(0, len(leitura_cards), 2):
        left = leitura_cards[index]
        right = leitura_cards[index + 1] if index + 1 < len(leitura_cards) else ("", "")
        leitura_rows.append(
            [
                Paragraph(f"<b>{left[0]}</b><br/>{left[1]}", styles["ConfieBody"]),
                Paragraph(f"<b>{right[0]}</b><br/>{right[1]}", styles["ConfieBody"]) if right[0] else "",
            ]
        )
    leitura_table = Table(leitura_rows, colWidths=[86 * mm, 86 * mm])
    leitura_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#dadde5")),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#dadde5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.extend([leitura_table, Spacer(1, 12)])

    story.append(Paragraph("DOBRAS E PERIMETROS", styles["ConfieSection"]))
    medidas_rows = []
    for index in range(0, len(medidas_cards), 2):
        left = medidas_cards[index]
        right = medidas_cards[index + 1] if index + 1 < len(medidas_cards) else ("", "")
        medidas_rows.append(
            [
                Paragraph(f"<b>{left[0]}</b><br/>{left[1]}", styles["ConfieBody"]),
                Paragraph(f"<b>{right[0]}</b><br/>{right[1]}", styles["ConfieBody"]) if right[0] else "",
            ]
        )
    medidas_table = Table(medidas_rows, colWidths=[86 * mm, 86 * mm])
    medidas_table.setStyle(
        TableStyle(
            [
                ("BOX", (0, 0), (-1, -1), 0.7, colors.HexColor("#dadde5")),
                ("INNERGRID", (0, 0), (-1, -1), 0.7, colors.HexColor("#dadde5")),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("LEFTPADDING", (0, 0), (-1, -1), 8),
                ("RIGHTPADDING", (0, 0), (-1, -1), 8),
                ("TOPPADDING", (0, 0), (-1, -1), 9),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
            ]
        )
    )
    story.extend([medidas_table, Spacer(1, 12)])

    observacoes = _first(avaliacao, "observacoes", default="")
    if observacoes:
        story.append(Paragraph("OBSERVACOES", styles["ConfieSection"]))
        story.append(Paragraph(observacoes.replace("\n", "<br/>"), styles["ConfieBody"]))
        story.append(Spacer(1, 10))

    story.append(Paragraph("Documento gerado pela plataforma CONFIE Personal.", styles["ConfieSmall"]))
    doc.build(story)
    buffer.seek(0)
    return buffer


def _avaliacao_pdf_document(avaliacao: Dict[str, Any]) -> BytesIO:
    from reportlab.lib.colors import HexColor
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfbase.pdfmetrics import stringWidth
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    pdf.setTitle("Laudo de Avaliação Física")
    pdf.setAuthor(BRAND_NAME)

    page_width, page_height = A4
    orange = HexColor("#ff5a0a")
    orange_light = HexColor("#ffb79d")
    brown = HexColor("#a35b38")
    black = HexColor("#111216")
    muted = HexColor("#5d606b")
    border = HexColor("#d4d7de")
    line = HexColor("#111216")

    aluno_nome = _first(avaliacao, "aluno_nome", default="Aluno")
    data_avaliacao = _first(avaliacao, "data", default="—")
    classificacao = _first(avaliacao, "classificacao", default="—")

    def clean(value: Any, default: str = "—") -> str:
        text = str(value if value is not None else "").strip()
        if not text or text in {"â€”", "None"}:
            return default
        return text

    def with_unit(value: Any, unit: str) -> str:
        text = clean(value)
        if text == "—":
            return text
        lower = text.lower()
        if unit.lower() in lower or "%" in lower:
            return text
        return f"{text} {unit}"

    def tracked(text: str) -> str:
        return " ".join(str(text).upper())

    def fit_font(text: str, font_name: str, size: float, max_width: float, min_size: float = 7) -> float:
        current = size
        while current > min_size and stringWidth(text, font_name, current) > max_width:
            current -= 0.5
        return current

    def draw_wrapped_text(text: str, x: float, y: float, width: float, font_size: float, leading: float, color: Any = muted) -> None:
        words = clean(text, "").split()
        if not words:
            return
        pdf.setFillColor(color)
        pdf.setFont("Helvetica", font_size)
        current = ""
        cursor_y = y
        for word in words:
            candidate = f"{current} {word}".strip()
            if stringWidth(candidate, "Helvetica", font_size) <= width:
                current = candidate
                continue
            pdf.drawString(x, cursor_y, current)
            cursor_y -= leading
            current = word
        if current:
            pdf.drawString(x, cursor_y, current)

    def draw_chrome(page_number: int) -> None:
        emitted_at = datetime.now().strftime("%d/%m/%Y, %H:%M")
        pdf.setFillColor(black)
        pdf.setFont("Helvetica", 8)
        pdf.drawString(24, page_height - 22, emitted_at)
        pdf.drawCentredString(page_width / 2, page_height - 22, "Laudo de Avaliação Física")
        pdf.drawString(24, 18, "about:blank")
        pdf.drawRightString(page_width - 24, 18, f"{page_number}/2")

    def draw_box(x: float, y: float, width: float, height: float, stroke: Any = border, stroke_width: float = 0.7) -> None:
        pdf.setStrokeColor(stroke)
        pdf.setLineWidth(stroke_width)
        pdf.rect(x, y, width, height, stroke=1, fill=0)

    def draw_card(x: float, y: float, width: float, height: float, label: str, value: Any, value_size: float = 16) -> None:
        draw_box(x, y, width, height)
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica", 9)
        label_lines = str(label).split("\n")
        for index, label_line in enumerate(label_lines):
            pdf.drawString(x + 12, y + height - 21 - (index * 11), tracked(label_line))

        value_text = clean(value)
        size = fit_font(value_text.replace("\n", " "), "Helvetica-Bold", value_size, width - 24, 8)
        pdf.setFillColor(black)
        pdf.setFont("Helvetica-Bold", size)
        value_y = y + 18 if len(label_lines) == 1 else y + 16
        if "\n" in value_text:
            parts = value_text.split("\n")
            for index, part in enumerate(parts):
                pdf.drawString(x + 12, value_y + (len(parts) - index - 1) * (size + 1), part)
        else:
            if len(label_lines) > 1:
                value_y = y + 11
            pdf.drawString(x + 12, value_y, value_text)

    def draw_table_box(x: float, y: float, width: float, height: float, title: str, rows: List[tuple[str, str]]) -> None:
        draw_box(x, y, width, height)
        pdf.setFillColor(black)
        pdf.setFont("Helvetica-Bold", 18)
        pdf.drawString(x + 13, y + height - 29, title)
        pdf.setFillColor(muted)
        pdf.setFont("Helvetica-Bold", 8.5)
        pdf.drawString(x + 13, y + height - 60, tracked("Medida"))
        pdf.drawString(x + width * 0.62, y + height - 60, tracked("Valor"))
        cursor_y = y + height - 70
        pdf.setStrokeColor(line)
        pdf.setLineWidth(0.7)
        pdf.line(x + 13, cursor_y, x + width - 13, cursor_y)
        pdf.setFillColor(black)
        pdf.setFont("Helvetica", 12.5)
        for label, value in rows:
            cursor_y -= 19
            pdf.drawString(x + 13, cursor_y, label)
            pdf.drawString(x + width * 0.62, cursor_y, clean(value))
            pdf.line(x + 13, cursor_y - 8, x + width - 13, cursor_y - 8)

    resumo_cards = [
        ("PESO", with_unit(_first(avaliacao, "peso", default="—"), "kg")),
        ("IMC", _first(avaliacao, "imc", default="—")),
        ("% GORDURA", _first(avaliacao, "gordura", default="—")),
        ("MASSA MAGRA", with_unit(_first(avaliacao, "massa_magra", default="—"), "kg")),
    ]
    leitura_cards = [
        ("CLASSIFICAÇÃO", classificacao),
        ("% GORDURA", _first(avaliacao, "gordura_nivel", "classificacao_gordura", default="—")),
        ("MASSA GORDA", with_unit(_first(avaliacao, "massa_gorda", default="—"), "kg")),
        ("PESO IDEAL", with_unit(_first(avaliacao, "peso_ideal", default="—"), "kg")),
        ("RELAÇÃO C/Q", _first(avaliacao, "relacao_cq", default="—")),
        ("SOMA DE\nDOBRAS", with_unit(_first(avaliacao, "soma_dobras", default="—"), "mm")),
    ]
    dobras = [
        ("Tricipital", with_unit(_first(avaliacao, "tricipital", default="—"), "mm")),
        ("Subscapular", with_unit(_first(avaliacao, "subscapular", default="—"), "mm")),
        ("Suprailíaca", with_unit(_first(avaliacao, "suprailiaca", default="—"), "mm")),
        ("Abdominal", with_unit(_first(avaliacao, "abdominal", default="—"), "mm")),
        ("Peitoral", with_unit(_first(avaliacao, "peitoral", default="—"), "mm")),
        ("Coxa", with_unit(_first(avaliacao, "coxa", default="—"), "mm")),
        ("Perna", with_unit(_first(avaliacao, "perna", default="—"), "mm")),
    ]
    circunferencias = [
        ("Braço direito", with_unit(_first(avaliacao, "braco_direito", default="—"), "cm")),
        ("Peitoral", with_unit(_first(avaliacao, "peitoral_circ", "peitoral_circunferencia", default="—"), "cm")),
        ("Cintura", with_unit(_first(avaliacao, "cintura", default="—"), "cm")),
        ("Quadril", with_unit(_first(avaliacao, "quadril", default="—"), "cm")),
        ("Coxa direita", with_unit(_first(avaliacao, "coxa_direita", default="—"), "cm")),
        ("Perna direita", with_unit(_first(avaliacao, "perna_direita", default="—"), "cm")),
    ]

    draw_chrome(1)
    draw_box(34, 585, 528, 222)
    pdf.setFillColor(orange)
    pdf.setFont("Helvetica-Bold", 11)
    pdf.drawString(56, 775, "C O N F I E  P E R S O N A L")
    draw_box(275, 760, 266, 25, orange_light, 0.7)
    pdf.setFillColor(brown)
    header_title = "L A U D O  P R O F I S S I O N A L  D E  A V A L I A Ç Ã O  F Í S I C A"
    pdf.setFont("Helvetica-Bold", fit_font(header_title, "Helvetica-Bold", 9.5, 244, 7))
    pdf.drawCentredString(408, 769.5, header_title)
    pdf.setFillColor(black)
    aluno_size = fit_font(str(aluno_nome).upper(), "Helvetica-Bold", 28, 430, 18)
    pdf.setFont("Helvetica-Bold", aluno_size)
    pdf.drawString(56, 723, str(aluno_nome).upper())
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 12)
    pdf.drawString(56, 702, f"Data da avaliação: {data_avaliacao} • Classificação: {classificacao}")

    for index, (label, value) in enumerate(resumo_cards):
        draw_card([56, 180, 304, 428][index], 607, 114, 82, label, value, 18)

    draw_box(34, 314, 306, 261)
    pdf.setFillColor(black)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(47, 546, "DESTAQUES DA AVALIAÇÃO")
    for position, (label, value) in zip([(47, 471), (192, 471), (47, 404), (192, 404), (47, 337), (192, 337)], leitura_cards):
        draw_card(position[0], position[1], 135, 57, label, value, 14)

    draw_box(352, 314, 210, 261)
    pdf.setFillColor(black)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(365, 546, "FICHA BASE")
    draw_card(365, 452, 72, 77, "IDADE", with_unit(_first(avaliacao, "idade", default="—"), "anos"), 15)
    draw_card(446, 452, 103, 77, "SEXO", _first(avaliacao, "sexo", default="Masculino"), 15)
    draw_card(365, 366, 72, 77, "ALTURA", with_unit(_first(avaliacao, "altura", "estatura", default="—"), "cm"), 15)
    draw_card(446, 366, 103, 77, "PESO", with_unit(_first(avaliacao, "peso", default="—"), "kg"), 15)

    pdf.showPage()
    draw_chrome(2)
    draw_table_box(34, 545, 258, 252, "DOBRAS CUTÂNEAS", dobras)
    draw_table_box(304, 545, 258, 252, "CIRCUNFERÊNCIAS", circunferencias)

    draw_box(34, 397, 258, 135)
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(48, 510, tracked("Responsável técnico"))
    pdf.setFillColor(black)
    pdf.setFont("Helvetica-Bold", 18)
    pdf.drawString(48, 482, "CONFIE Personal")
    pdf.setStrokeColor(muted)
    pdf.setLineWidth(0.7)
    pdf.line(48, 444, 278, 444)
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 10.5)
    pdf.drawString(48, 426, "Assinatura / carimbo profissional")

    draw_box(304, 397, 258, 135)
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 9)
    pdf.drawString(318, 510, tracked("Entrega do laudo"))
    draw_wrapped_text(
        "Documento gerado para acompanhamento da evolução física e apoio ao planejamento de treino.",
        318,
        490,
        212,
        12,
        14,
        muted,
    )
    pdf.setStrokeColor(muted)
    pdf.line(318, 431, 548, 431)
    pdf.setFillColor(muted)
    pdf.setFont("Helvetica", 10.5)
    pdf.drawString(318, 413, f"Data de emissão: {data_avaliacao}")

    pdf.setStrokeColor(line)
    pdf.setLineWidth(0.8)
    pdf.line(34, 382, 562, 382)
    draw_wrapped_text(
        "Este laudo resume as principais métricas coletadas na avaliação física e deve ser interpretado em conjunto com o histórico do aluno, objetivos e acompanhamento profissional.",
        34,
        363,
        528,
        10,
        15,
        muted,
    )

    pdf.save()
    buffer.seek(0)
    return buffer


def _get_or_create_muscle_group_id(nome: Any) -> Optional[str]:
    group_name = str(nome or "").strip()
    if not group_name:
        return None
    if _is_uuid(group_name):
        return group_name
    existing = _select_first_by(TABLE_GRUPOS_MUSCULARES, "nome", group_name)
    if existing["ok"] and existing["data"]:
        return existing["data"].get("id")
    created = _insert(TABLE_GRUPOS_MUSCULARES, {"nome": group_name})
    if created["ok"] and created["data"]:
        return created["data"][0].get("id")
    return None


def _optional_rows(table: str, *, order: Optional[str] = None, desc: bool = False) -> List[Dict[str, Any]]:
    if not _ready():
        return []
    try:
        query = _admin_client().table(table).select("*")
        if order:
            query = query.order(order, desc=desc)
        response = query.execute()
        return response.data or []
    except Exception:
        return []


def _messages_for_personal(contact_id: Optional[str]) -> Dict[str, Any]:
    contatos = _students()
    for contato in contatos:
        contato["url"] = url_for("mensagens", contato_id=contato["id"])
    conversa_ativa = next((contato for contato in contatos if contato["id"] == contact_id), contatos[0] if contatos else None)
    mensagens = _optional_rows(TABLE_MENSAGENS, order="created_at")
    filtered: List[Dict[str, Any]] = []
    if conversa_ativa:
        for row in mensagens:
            if _first(row, "contato_id", "aluno_id", default="") == conversa_ativa["id"]:
                filtered.append(
                    {
                        "id": row.get("id", ""),
                        "autor": _first(row, "autor_nome", "autor", default="Mensagem"),
                        "texto": _first(row, "texto", "mensagem", default=""),
                        "horario": _fmt_datetime(_first(row, "created_at", default="")),
                        "remetente": "profissional" if str(_first(row, "autor", default="")).strip().lower() == "personal" else "aluno",
                    }
                )
    return {
        "contatos": contatos,
        "conversa_ativa": conversa_ativa or {},
        "mensagens": filtered,
        "ultima_mensagem_id": filtered[-1]["id"] if filtered else "",
    }


def _messages_for_student(contact_id: Optional[str]) -> Dict[str, Any]:
    usuarios = _optional_rows(TABLE_USUARIOS)
    contatos: List[Dict[str, Any]] = []
    for row in usuarios:
        if str(_first(row, "tipo_conta", default="")).strip().lower() == "aluno":
            continue
        contatos.append(
            {
                "id": row.get("id", ""),
                "nome": _first(row, "nome", default="Personal"),
                "email": _first(row, "email", default=""),
                "url": url_for("aluno_mensagens", contato_id=row.get("id", "")),
            }
        )
    conversa_ativa = next((contato for contato in contatos if contato["id"] == contact_id), contatos[0] if contatos else None)
    mensagens = _optional_rows(TABLE_MENSAGENS, order="created_at")
    filtered: List[Dict[str, Any]] = []
    if conversa_ativa:
        for row in mensagens:
            if _first(row, "contato_id", "profissional_id", default="") == conversa_ativa["id"]:
                filtered.append(
                    {
                        "id": row.get("id", ""),
                        "autor": _first(row, "autor_nome", "autor", default="Mensagem"),
                        "texto": _first(row, "texto", "mensagem", default=""),
                        "horario": _fmt_datetime(_first(row, "created_at", default="")),
                        "remetente": "aluno" if str(_first(row, "autor", default="")).strip().lower() == "aluno" else "profissional",
                    }
                )
    return {
        "contatos": contatos,
        "conversa_ativa": conversa_ativa or {},
        "mensagens": filtered,
        "ultima_mensagem_id": filtered[-1]["id"] if filtered else "",
    }


def _payment_rows() -> List[Dict[str, Any]]:
    rows = _optional_rows(TABLE_PAGAMENTOS, order="data_parcela", desc=True)
    alunos = _students()
    planos = _plans()
    alunos_por_id = {row["id"]: row for row in alunos}
    planos_por_aluno = {row["id"]: row["planos"] for row in _student_plan_rows(alunos, planos)}
    if not rows:
        return [
            {
                "id": aluno["id"],
                "aluno_id": aluno["id"],
                "aluno_nome": aluno["nome"],
                "email": aluno["email"],
                "planos": planos_por_aluno.get(aluno["id"], []),
                "plano_resumo": ", ".join(plano["nome"] for plano in planos_por_aluno.get(aluno["id"], [])) or "Sem plano",
                "valor": 0,
                "status": "pendente",
                "status_label": "Pendente",
                "status_color": "pending",
                "atualizado_em": "Sem atualizacao",
                "alterar_status_url": url_for("alterar_status_pagamento", pagamento_id=aluno["id"]),
            }
            for aluno in _students()
        ]
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        aluno_ref = alunos_por_id.get(_first(row, "aluno_id", default=""), {})
        aluno_id = _first(row, "aluno_id", default="")
        planos_aluno = planos_por_aluno.get(aluno_id, [])
        status = _payment_status_slug(_first(row, "status_parcela", "status", "status_pagamento", default="pendente"))
        normalized.append(
            {
                **row,
                "id": row.get("id", ""),
                "aluno_nome": _first(row, "aluno_nome", default=aluno_ref.get("nome", "Aluno")),
                "email": _first(row, "email", default=aluno_ref.get("email", "")),
                "planos": planos_aluno,
                "plano_resumo": ", ".join(plano["nome"] for plano in planos_aluno) or "Sem plano",
                "status": status,
                "status_label": _human_status(status).upper(),
                "status_color": "paid" if status == "pago" else "pending" if status == "pendente" else "late",
                "atualizado_em": _fmt_date(_first(row, "data_recebimento", "data_parcela", "created_at")) or "Sem atualizacao",
                "alterar_status_url": url_for("alterar_status_pagamento", pagamento_id=row.get("id", "")),
            }
        )
    return normalized


def _plans() -> List[Dict[str, Any]]:
    rows = _optional_rows(TABLE_PLANOS)
    if not rows:
        return [
            {"id": "starter", "nome": "Starter", "preco": "R$ 49", "descricao": "Plano mensal", "gerenciar_url": url_for("financeiro")},
            {"id": "pro", "nome": "Pro", "preco": "R$ 99", "descricao": "Plano mais popular", "gerenciar_url": url_for("financeiro")},
        ]
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                **row,
                "id": row.get("id", ""),
                "nome": _first(row, "nome", default="Plano"),
                "preco": _currency(_first(row, "preco", "valor", default=0)),
                "preco_valor": _first(row, "preco", "valor", default=0),
                "descricao": _first(row, "descricao", default=""),
                "duracao_dias": _first(row, "duracao_dias", default=30),
                "recorrente": bool(_first(row, "recorrente", default=True)),
                "gerenciar_url": url_for("gerenciar_plano", plano_id=row.get("id", "")),
            }
        )
    return normalized


def _student_plan_rows(alunos: List[Dict[str, Any]], planos: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    planos_por_id = {str(plano.get("id", "")): plano for plano in planos}
    rows: List[Dict[str, Any]] = []
    for aluno in alunos:
        linked_plan_ids: List[str] = []
        raw_values = [
            _first(aluno, "plano_id", default=""),
            aluno.get("plano") if str(aluno.get("plano", "")).strip() in planos_por_id else "",
            _first(aluno, "planos", "planos_ids", "plano_ids", default=[]),
        ]
        for raw_value in raw_values:
            values = raw_value if isinstance(raw_value, list) else [raw_value]
            for value in values:
                plan_id = str(value or "").strip()
                if plan_id and plan_id not in linked_plan_ids:
                    linked_plan_ids.append(plan_id)

        for plano in planos:
            aluno_id = str(_first(plano, "aluno_id", default="")).strip()
            if aluno_id and aluno_id == str(aluno.get("id", "")) and str(plano.get("id", "")) not in linked_plan_ids:
                linked_plan_ids.append(str(plano.get("id", "")))

        linked_plans: List[Dict[str, Any]] = []
        for plan_id in linked_plan_ids:
            plano_ref = planos_por_id.get(plan_id)
            if plano_ref:
                linked_plans.append(plano_ref)
            elif plan_id and plan_id.lower() not in {"nao definido", "não definido"}:
                linked_plans.append({"id": plan_id, "nome": plan_id, "preco": "", "periodo": ""})

        rows.append(
            {
                "id": aluno.get("id", ""),
                "nome": aluno.get("nome", "Aluno"),
                "email": aluno.get("email", ""),
                "planos": linked_plans,
                "total_planos": len(linked_plans),
            }
        )
    return rows


def _db_plan_options() -> List[Dict[str, Any]]:
    return [plan for plan in _plans() if _is_uuid(plan.get("id"))]


def _resolve_plan_id(value: Any) -> Optional[str]:
    text = str(value or "").strip()
    if not text:
        return None
    if _is_uuid(text):
        return text
    wanted = _slug_text(text)
    for plan in _db_plan_options():
        if wanted in {_slug_text(plan.get("id")), _slug_text(plan.get("nome"))}:
            return str(plan["id"])
    return None


def _landing_resources() -> List[Dict[str, Any]]:
    return [
        {"icone": "AL", "titulo": "Gestao de alunos", "descricao": "Cadastre, acompanhe e gerencie todos os seus alunos em um unico lugar."},
        {"icone": "TR", "titulo": "Treinos personalizados", "descricao": "Crie planilhas de treino sob medida com banco de exercicios e organizacao centralizada."},
        {"icone": "AG", "titulo": "Agenda inteligente", "descricao": "Gerencie horarios, sessoes e compromissos com uma rotina mais clara."},
        {"icone": "EV", "titulo": "Acompanhamento", "descricao": "Acompanhe evolucao, avaliacoes e progresso de cada aluno em um unico painel."},
    ]


def _landing_plans() -> List[Dict[str, Any]]:
    db_plans = _plans()
    if len(db_plans) >= 3:
        return db_plans[:3]
    return [
        {"nome": "Starter", "preco": "R$ 49", "periodo": "/mes", "beneficios": ["Ate 10 alunos", "Treinos ilimitados", "Agenda basica"], "popular": False, "url": url_for("cadastro")},
        {"nome": "Pro", "preco": "R$ 99", "periodo": "/mes", "beneficios": ["Alunos ilimitados", "Google Calendar", "Relatorios financeiros", "Mensagens ilimitadas"], "popular": True, "url": url_for("cadastro")},
        {"nome": "Enterprise", "preco": "R$ 199", "periodo": "/mes", "beneficios": ["Tudo do Pro", "Multiplos personais", "API personalizada", "Suporte prioritario"], "popular": False, "url": url_for("cadastro")},
    ]


@app.get("/health")
def health():
    return {"ok": True, "supabase": _ready()}


@app.route("/")
@app.route("/index.html")
def index():
    return render_template(
        "index.html",
        recursos=_landing_resources(),
        planos=_landing_plans(),
        hero_title_top="Transforme",
        hero_title_bottom="seu treino",
        hero_copy="Plataforma completa para Personal Trainers gerenciarem alunos, treinos e agendas em um so lugar",
        hero_primary_cta="Comecar agora",
        hero_secondary_cta="Entrar",
        badge_popular="Popular",
        **_common_brand_context(),
    )


@app.route("/cadastro", methods=["GET", "POST"])
@app.route("/Cadastro.html", methods=["GET", "POST"])
def cadastro():
    if DEV_BYPASS_AUTH:
        flash("Modo teste ativo: cadastro e login foram desativados temporariamente para facilitar a validacao das telas.", "info")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return render_template("Cadastro.html", **_common_brand_context())

        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "").strip()
        tipo_conta = request.form.get("tipo-conta", "Personal Trainer").strip()
        nascimento = request.form.get("nascimento", "").strip()
        confirmar = request.form.get("confirmar-senha", "").strip()

        if not nome or not email or not senha:
            flash("Preencha nome, email e senha.", "error")
        elif senha != confirmar:
            flash("As senhas nao conferem.", "error")
        elif not _ready():
            flash("Supabase nao configurado neste computador.", "error")
        elif not _table_has_local_passwords():
            flash(_local_auth_schema_message(), "error")
        else:
            existing = _find_user_by_email(email)
            if existing["ok"] and existing["data"]:
                flash("Ja existe uma conta com esse email.", "error")
            else:
                payload = {
                    "nome": nome,
                    "email": email,
                    "senha_hash": generate_password_hash(senha),
                    "tipo_conta": tipo_conta,
                    "nascimento": nascimento,
                }
                created = _insert(TABLE_USUARIOS, payload)
                if created["ok"]:
                    flash("Cadastro realizado com sucesso. Agora voce ja pode entrar.", "success")
                    return redirect(url_for("login"))
                flash(_auth_write_error_message(created["error"]), "error")

    return render_template("Cadastro.html", **_common_brand_context())


@app.route("/login", methods=["GET", "POST"])
@app.route("/login.html", methods=["GET", "POST"])
@app.route("/Login.html", methods=["GET", "POST"])
def login():
    if DEV_BYPASS_AUTH:
        flash("Modo teste ativo: voce entrou automaticamente sem precisar fazer login.", "info")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return render_template("Login.html", **_common_brand_context())

        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "").strip()
        if not email or not senha:
            flash("Informe email e senha.", "error")
            return render_template("Login.html", **_common_brand_context())

        user_data: Optional[Dict[str, Any]] = None

        if not _table_has_local_passwords():
            flash(_local_auth_schema_message(), "error")
            return render_template("Login.html", **_common_brand_context())

        result = _find_user_by_email(email)
        row = result["data"] if result["ok"] else None
        if not row:
            flash("Email ou senha invalidos.", "error")
            return render_template("Login.html", **_common_brand_context())

        senha_hash = row.get("senha_hash")
        if not senha_hash:
            flash("Este usuario ainda nao possui senha cadastrada. Crie uma nova conta ou atualize a coluna senha_hash.", "error")
            return render_template("Login.html", **_common_brand_context())

        if not check_password_hash(str(senha_hash), senha):
            flash("Email ou senha invalidos.", "error")
            return render_template("Login.html", **_common_brand_context())

        user_data = row

        if not user_data:
            flash("Nao foi possivel localizar o perfil desse usuario.", "error")
            return render_template("Login.html", **_common_brand_context())

        user_payload = {
            "id": user_data.get("id", ""),
            "auth_user_id": user_data.get("auth_user_id", ""),
            "nome": _first(user_data, "nome", default=email.split("@")[0]),
            "email": email,
            "tipo_conta": _first(user_data, "tipo_conta", default="Personal Trainer"),
        }
        _set_session_user(user_payload)
        role = str(user_payload["tipo_conta"]).strip().lower()
        return redirect(url_for("aluno_dashboard" if role == "aluno" else "dashboard"))

    return render_template("Login.html", **_common_brand_context())


@app.route("/logout", methods=["GET", "POST"])
def logout():
    _clear_session()
    flash("Sessao encerrada.", "success")
    return redirect("/index.html")


@app.get("/abrir-como-desenvolvedor")
def abrir_como_desenvolvedor():
    if not DEV_BYPASS_AUTH:
        flash("O modo desenvolvedor esta desativado neste ambiente.", "error")
        return redirect(url_for("login"))
    perfil = (request.args.get("perfil", "personal") or "personal").strip().lower()
    destino = "/aluno/dashboard" if perfil == "aluno" else "/dashboard"
    _set_session_user(_dev_user_for_path(destino))
    flash("Modo desenvolvedor ativo. Login liberado temporariamente para teste das telas.", "info")
    return redirect(url_for("aluno_dashboard" if perfil == "aluno" else "dashboard"))


@app.get("/google-calendar/connect")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def google_calendar_connect():
    if not _google_calendar_enabled():
        flash("Google Calendar nao configurado neste ambiente.", "error")
        return redirect(url_for("agenda"))
    flow = _google_oauth_flow()
    authorization_url, state = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
    )
    session["google_oauth_state"] = state
    return redirect(authorization_url)


@app.get("/google-calendar/callback")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def google_calendar_callback():
    if not _google_calendar_enabled():
        flash("Google Calendar nao configurado neste ambiente.", "error")
        return redirect(url_for("agenda"))
    state = session.get("google_oauth_state")
    if not state:
        flash("A autorizacao do Google expirou. Tente conectar novamente.", "error")
        return redirect(url_for("agenda"))
    try:
        flow = _google_oauth_flow(state=state)
        flow.fetch_token(authorization_response=request.url)
        current = _session_user()
        _save_google_credentials(current.get("email", ""), flow.credentials)
        session.pop("google_oauth_state", None)
        flash("Google Calendar conectado com sucesso.", "success")
    except Exception as exc:
        app.logger.exception("Erro ao concluir OAuth do Google Calendar")
        flash(f"Nao foi possivel concluir a conexao com o Google Calendar: {exc}", "error")
    return redirect(url_for("agenda"))


@app.post("/google-calendar/disconnect")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def google_calendar_disconnect():
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("agenda"))
    _delete_google_credentials(_session_user().get("email", ""))
    session.pop("google_oauth_state", None)
    flash("Google Calendar desconectado.", "success")
    return redirect(url_for("agenda"))


@app.get("/dashboard")
@app.get("/dashboard.html")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def dashboard():
    alunos = _students()
    treinos_lista = _trainings()
    agenda_lista = _schedule_rows()
    avaliacoes_lista = _assessments()
    pagamentos = _payment_rows()
    receita = 0.0
    for pagamento in pagamentos:
        if pagamento.get("status") == "pago":
            receita += _to_float(_first(pagamento, "valor", default=0)) or 0.0
    return render_template(
        "dashboard.html",
        total_alunos=len(alunos),
        total_sessoes=len([item for item in agenda_lista if item["status_classe"] == "concluido"]),
        total_receita=_currency(receita),
        total_checkins=len([item for item in agenda_lista if item["status_classe"] in ("confirmado", "concluido", "agendado")]),
        variacao_checkins="",
        adicionar_aluno_destino=url_for("alunos") + "#novo-aluno",
        adicionar_aluno_url=url_for("alunos") + "#novo-aluno",
        criar_treino_url=url_for("treinos") + "#novo-treino-modal",
        agendar_aula_url=url_for("agenda") + "#nova-aula",
        total_avaliacoes=len(avaliacoes_lista),
        **_personal_context("dashboard"),
    )


@app.route("/alunos", methods=["GET", "POST"])
@app.route("/alunos.html", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def alunos():
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return redirect(url_for("alunos"))
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha_inicial = request.form.get("senha", "").strip()
        criar_login = request.form.get("criar_login") == "1"
        status_aluno = _slug_status(request.form.get("status") or "ativo")
        if status_aluno not in {"ativo", "inativo"}:
            status_aluno = "ativo"
        if criar_login and not email:
            flash("Para criar login para o aluno, informe um email.", "error")
            return redirect(url_for("alunos") + "#novo-aluno")
        if criar_login:
            existing = _find_user_by_email(email)
            if existing["ok"] and existing["data"]:
                flash("Ja existe um usuario com esse email. Use outro email para criar o login do aluno.", "error")
                return redirect(url_for("alunos") + "#novo-aluno")
        plano_id = _resolve_plan_id(request.form.get("plano"))
        payload = {
            "nome": nome,
            "email": email,
            "telefone": request.form.get("telefone"),
            "objetivo": request.form.get("objetivo"),
            "data_nascimento": request.form.get("data_nascimento") or request.form.get("nascimento"),
            "experiencias_anteriores": request.form.get("experiencias_anteriores"),
            "restricoes_fisicas": request.form.get("restricoes_fisicas"),
            "status": status_aluno,
            "plano": plano_id,
        }
        result = _insert(TABLE_ALUNOS, payload)
        if not result["ok"]:
            flash(result["error"] or "Nao foi possivel criar o aluno.", "error")
            return redirect(url_for("alunos"))
        if criar_login:
            login_password = senha_inicial or "1111"
            user_payload = {
                "nome": nome,
                "email": email,
                "tipo_conta": "Aluno",
                "nascimento": request.form.get("data_nascimento") or request.form.get("nascimento"),
                "senha_hash": generate_password_hash(login_password),
            }
            user_result = _insert(TABLE_USUARIOS, user_payload)
            if not user_result["ok"]:
                flash(
                    "Aluno criado, mas nao foi possivel criar o login. "
                    + (user_result["error"] or "Verifique a tabela de usuarios."),
                    "error",
                )
                return redirect(url_for("alunos"))
            if senha_inicial:
                flash("Aluno criado com sucesso e login liberado.", "success")
            else:
                flash("Aluno criado com sucesso. Como a senha ficou em branco, o login inicial foi definido como 1111.", "success")
            return redirect(url_for("alunos"))
        flash("Aluno criado com sucesso.", "success")
        return redirect(url_for("alunos"))

    search = request.args.get("busca", "").strip().lower()
    aluno_edicao_id = request.args.get("editar_aluno_id", "")
    alunos_lista = _students()
    if search:
        alunos_lista = [aluno for aluno in alunos_lista if search in aluno["nome"].lower() or search in aluno["email"].lower()]
    aluno_edicao = next((aluno for aluno in alunos_lista if aluno["id"] == aluno_edicao_id), {})
    form = {}
    if aluno_edicao:
        form = {
            **aluno_edicao,
            "plano": aluno_edicao.get("plano_id", ""),
            "status": _slug_status(aluno_edicao.get("status", "ativo")) if _slug_status(aluno_edicao.get("status", "ativo")) in {"ativo", "inativo"} else "ativo",
        }
    return render_template(
        "alunos.html",
        alunos=alunos_lista,
        aluno_edicao=aluno_edicao,
        form=form,
        busca=search,
        filtros={"busca": search, "status": request.args.get("status", "")},
        total_alunos=len(alunos_lista),
        planos=_db_plan_options(),
        criar_aluno_url=url_for("alunos"),
        excluir_aluno_base_url="/alunos",
        editar_aluno_base_url="/alunos",
        detalhes_aluno_base_url="/alunos",
        csrf_form_token=_csrf_token,
        **_personal_context("alunos"),
    )


@app.get("/alunos/novo")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def novo_aluno_redirect():
    return redirect(url_for("alunos") + "#novo-aluno")


@app.get("/alunos/<aluno_id>")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def aluno_perfil(aluno_id: str):
    return redirect(url_for("avaliacoes", aluno_id=aluno_id))


@app.route("/alunos/<aluno_id>/editar", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def editar_aluno(aluno_id: str):
    aluno_result = _select_one(TABLE_ALUNOS, aluno_id)
    aluno_row = aluno_result["data"] if aluno_result["ok"] else None
    if not aluno_row:
        flash("Aluno nao encontrado.", "error")
        return redirect(url_for("alunos"))

    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return redirect(url_for("editar_aluno", aluno_id=aluno_id))
        status_aluno = _slug_status(request.form.get("status") or "ativo")
        if status_aluno not in {"ativo", "inativo"}:
            status_aluno = "ativo"
        payload = {
            "nome": request.form.get("nome"),
            "email": request.form.get("email"),
            "telefone": request.form.get("telefone"),
            "objetivo": request.form.get("objetivo"),
            "status": status_aluno,
            "plano": _resolve_plan_id(request.form.get("plano")),
        }
        result = _update(TABLE_ALUNOS, aluno_id, payload)
        flash("Aluno atualizado com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel atualizar o aluno."), "success" if result["ok"] else "error")
        return redirect(url_for("alunos"))

    return redirect(url_for("alunos", editar_aluno_id=aluno_id) + "#novo-aluno")


@app.post("/alunos/<aluno_id>/excluir")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def excluir_aluno(aluno_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
    else:
        result = _delete(TABLE_ALUNOS, aluno_id)
        flash("Aluno excluido com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel excluir o aluno."), "success" if result["ok"] else "error")
    return redirect(url_for("alunos"))


@app.get("/treinos")
@app.get("/treinos.html")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def treinos():
    alunos_lista = _students()
    aluno_id = request.args.get("aluno_id", "")
    treino_visualizacao_id = request.args.get("visualizar_treino_id", "")
    treino_edicao_id = request.args.get("editar_treino_id", "")
    treino_exclusao_id = request.args.get("excluir_treino_id", "")
    aluno_selecionado = next((aluno for aluno in alunos_lista if aluno["id"] == aluno_id), None)
    treinos_lista = _trainings(aluno_selecionado["id"]) if aluno_selecionado else []
    treino_visualizacao = next((treino for treino in treinos_lista if treino["id"] == treino_visualizacao_id), {})
    treino_edicao = next((treino for treino in treinos_lista if treino["id"] == treino_edicao_id), {})
    treino_exclusao = next((treino for treino in treinos_lista if treino["id"] == treino_exclusao_id), {})
    return render_template(
        "treinos.html",
        alunos=alunos_lista,
        exercicios=_exercises(),
        aluno_selecionado=aluno_selecionado,
        treinos=treinos_lista,
        treino_visualizacao=treino_visualizacao,
        treino_edicao=treino_edicao,
        treino_exclusao=treino_exclusao,
        url_treinos_aluno_base="/treinos/aluno",
        visualizar_treino_base="/treinos",
        visualizar_treino_url_base="/treinos",
        criar_treino_url=url_for("criar_treino"),
        editar_treino_base="/treinos/editar",
        editar_treino_url_base="/treinos/editar",
        excluir_treino_base="/treinos/excluir",
        csrf_form_token=_csrf_token,
        **_personal_context("treinos"),
    )


@app.get("/treinos/aluno/<aluno_id>")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def treinos_aluno(aluno_id: str):
    return redirect(url_for("treinos", aluno_id=aluno_id))


@app.get("/treinos/<treino_id>")
@app.get("/treinos/<treino_id>/")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def visualizar_treino(treino_id: str):
    treino = next((item for item in _trainings() if item["id"] == treino_id), None)
    if not treino:
        flash("Treino nao encontrado.", "error")
        return redirect(url_for("treinos"))
    return redirect(url_for("treinos", aluno_id=treino.get("aluno_id", ""), visualizar_treino_id=treino_id) + "#visualizar-treino-modal")


@app.get("/treinos/visualizar")
@app.get("/treinos/visualizar/")
@login_required
def visualizar_treino_sem_id():
    return redirect(url_for("treinos"))


@app.get("/treinos/visualizar/<treino_id>")
@app.get("/treinos/visualizar/<treino_id>/")
@login_required
def visualizar_treino_legacy(treino_id: str):
    return visualizar_treino(treino_id)


@app.get("/treinos/novo")
@app.get("/treinos/novo/")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def abrir_criacao_treino():
    aluno_id = request.args.get("aluno_id", "")
    target = url_for("treinos", aluno_id=aluno_id) if aluno_id else url_for("treinos")
    return redirect(target + "#novo-treino-modal")


@app.post("/treinos/novo")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def criar_treino():
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("treinos"))
    exercicios_raw = request.form.get("exercicios_raw") or ""
    exercicios = [item.strip() for item in exercicios_raw.replace("\r", "\n").replace(";", "\n").split("\n") if item.strip()]
    payload = {
        "nome": request.form.get("nome"),
        "aluno_id": request.form.get("aluno_id"),
        "observacoes": request.form.get("observacoes"),
        "exercicios_raw": exercicios_raw,
        "exercicios": exercicios,
        "created_at": datetime.utcnow().isoformat(),
    }
    result = _insert(TABLE_TREINOS, payload)
    if not result["ok"] and (
        _missing_column_error(result["error"], "nome")
        or _missing_column_error(result["error"], "exercicios")
        or _missing_column_error(result["error"], "exercicios_raw")
        or _missing_column_error(result["error"], "observacoes")
    ):
        result = _insert(
            TABLE_TREINOS,
            {
                "descricao": request.form.get("nome"),
                "aluno_id": request.form.get("aluno_id"),
                "observacao": exercicios_raw or request.form.get("observacoes"),
                "data_criacao": datetime.utcnow().date().isoformat(),
                "created_at": datetime.utcnow().isoformat(),
            },
        )
    flash("Treino criado com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel criar o treino."), "success" if result["ok"] else "error")
    return redirect(request.form.get("origem_url") or url_for("treinos", aluno_id=request.form.get("aluno_id", "")))


@app.post("/treinos/editar/<treino_id>")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def editar_treino(treino_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("treinos"))
    exercicios_raw = request.form.get("exercicios_raw") or ""
    exercicios = [item.strip() for item in exercicios_raw.replace("\r", "\n").replace(";", "\n").split("\n") if item.strip()]
    payload = {
        "nome": request.form.get("nome"),
        "aluno_id": request.form.get("aluno_id"),
        "observacoes": request.form.get("observacoes"),
        "exercicios_raw": exercicios_raw,
        "exercicios": exercicios,
    }
    result = _update(TABLE_TREINOS, treino_id, payload)
    if not result["ok"] and (
        _missing_column_error(result["error"], "nome")
        or _missing_column_error(result["error"], "exercicios")
        or _missing_column_error(result["error"], "exercicios_raw")
        or _missing_column_error(result["error"], "observacoes")
    ):
        result = _update(
            TABLE_TREINOS,
            treino_id,
            {
                "descricao": request.form.get("nome"),
                "aluno_id": request.form.get("aluno_id"),
                "observacao": exercicios_raw or request.form.get("observacoes"),
            },
        )
    flash("Treino atualizado com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel atualizar o treino."), "success" if result["ok"] else "error")
    return redirect(url_for("treinos", aluno_id=request.form.get("aluno_id", "")))


@app.get("/treinos/editar")
@app.get("/treinos/editar/")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def abrir_edicao_treino_sem_id():
    return redirect(url_for("treinos"))


@app.get("/treinos/editar/<treino_id>")
@app.get("/treinos/editar/<treino_id>/")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def abrir_edicao_treino(treino_id: str):
    treino = next((item for item in _trainings() if item["id"] == treino_id), None)
    if not treino:
        flash("Treino nao encontrado.", "error")
        return redirect(url_for("treinos"))
    return redirect(url_for("treinos", aluno_id=treino.get("aluno_id", ""), editar_treino_id=treino_id) + "#editar-treino-modal")


@app.post("/treinos/excluir/<treino_id>")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def excluir_treino(treino_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("treinos"))
    aluno_id = request.form.get("aluno_id", "")
    result = _delete(TABLE_TREINOS, treino_id)
    flash("Treino excluido com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel excluir o treino."), "success" if result["ok"] else "error")
    return redirect(url_for("treinos", aluno_id=aluno_id))


@app.route("/agenda", methods=["GET", "POST"])
@app.route("/agenda.html", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def agenda():
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return redirect(url_for("agenda"))
        tipo_registro = (request.form.get("tipo_registro") or "agendamento").strip().lower()
        aluno_id = request.form.get("aluno_id") or None
        inicio = _split_datetime_local(request.form.get("inicio"))
        termino_hora = (request.form.get("termino_hora") or "").strip()
        titulo = request.form.get("titulo", "").strip()
        observacoes = request.form.get("observacoes", "").strip()
        if not inicio["data"]:
            flash("Informe a data e horario da aula.", "error")
            return redirect(url_for("agenda"))
        if tipo_registro == "agendamento" and not aluno_id:
            flash("Selecione um aluno para agendar a aula.", "error")
            return redirect(url_for("agenda"))
        status = "disponivel" if tipo_registro == "disponibilidade" else "agendado"
        titulo_padrao = "Horario disponivel" if status == "disponivel" else "Aula"
        payload = {
            "data": inicio["data"],
            "hora": inicio["hora"],
            "aluno_id": None if status == "disponivel" else aluno_id,
            "status": status,
            "observacao": _build_agenda_observacao(titulo or titulo_padrao, observacoes, termino_hora),
        }
        result = _insert(TABLE_AGENDA, payload)
        if result["ok"]:
            mensagem = "Horario disponivel criado com sucesso." if status == "disponivel" else "Aula agendada com sucesso."
            flash(mensagem, "success")
        else:
            flash(result["error"] or "Nao foi possivel salvar o horario.", "error")
        return redirect(url_for("agenda"))

    compromissos = _schedule_rows()
    google_calendar = _google_calendar_context()
    for compromisso in compromissos:
        compromisso["pode_cancelar"] = compromisso["status_classe"] in {"agendado", "confirmado", "pendente"}
    total_compromissos = len([item for item in compromissos if item["status_classe"] != "cancelado"])
    return render_template(
        "agenda.html",
        compromissos=compromissos,
        google_calendar=google_calendar,
        alunos=_students(),
        total_compromissos=total_compromissos,
        data_referencia=_fmt_date(datetime.now().date().isoformat()),
        criar_aula_url=url_for("agenda"),
        confirmar_url_base="/agenda/confirmar",
        concluir_url_base="/agenda/concluir",
        cancelar_url_base="/agenda/cancelar",
        csrf_form_token=_csrf_token,
        **_personal_context("agenda"),
    )


@app.get("/agenda/nova")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def nova_aula_redirect():
    return redirect(url_for("agenda") + "#nova-aula")


@app.post("/agenda/confirmar/<agenda_id>")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def confirmar_agenda(agenda_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
    else:
        result = _update(TABLE_AGENDA, agenda_id, {"status": "confirmado"})
        flash("Aula confirmada." if result["ok"] else (result["error"] or "Nao foi possivel confirmar a aula."), "success" if result["ok"] else "error")
    return redirect(url_for("agenda"))


@app.post("/agenda/concluir/<agenda_id>")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def concluir_agenda(agenda_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
    else:
        result = _update(TABLE_AGENDA, agenda_id, {"status": "concluido"})
        flash("Aula concluida." if result["ok"] else (result["error"] or "Nao foi possivel concluir a aula."), "success" if result["ok"] else "error")
    return redirect(url_for("agenda"))


@app.post("/agenda/cancelar/<agenda_id>")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def cancelar_agenda(agenda_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
    else:
        result = _update(TABLE_AGENDA, agenda_id, {"status": "cancelado"})
        flash("Aula cancelada." if result["ok"] else (result["error"] or "Nao foi possivel cancelar a aula."), "success" if result["ok"] else "error")
    return redirect(url_for("agenda"))


@app.route("/avaliacoes", methods=["GET", "POST"])
@app.route("/avaliacoes.html", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def avaliacoes():
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return redirect(url_for("avaliacoes"))
        aluno_id = request.form.get("aluno_id")
        payload = {
            "aluno_id": aluno_id,
            "data": request.form.get("data") or datetime.utcnow().date().isoformat(),
            "sexo": request.form.get("sexo"),
            "peso": request.form.get("peso"),
            "estatura": request.form.get("estatura"),
            "idade": request.form.get("idade"),
            "gordura": request.form.get("gordura"),
            "tricipital": request.form.get("tricipital"),
            "subscapular": request.form.get("subscapular"),
            "suprailiaca": request.form.get("suprailiaca"),
            "abdominal": request.form.get("abdominal"),
            "peitoral": request.form.get("peitoral"),
            "coxa": request.form.get("coxa"),
            "perna": request.form.get("perna"),
            "braco_direito": request.form.get("braco_direito"),
            "peitoral_circ": request.form.get("peitoral_circ"),
            "cintura": request.form.get("cintura"),
            "quadril": request.form.get("quadril"),
            "coxa_direita": request.form.get("coxa_direita"),
            "perna_direita": request.form.get("perna_direita"),
            "observacao": request.form.get("observacoes"),
        }
        result = _insert(TABLE_AVALIACOES, payload)
        flash("Avaliacao salva com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel salvar a avaliacao."), "success" if result["ok"] else "error")
        return redirect(url_for("avaliacoes", aluno_id=aluno_id))

    alunos_lista = _students()
    aluno_id = request.args.get("aluno_id", "")
    aluno_selecionado = next((item for item in alunos_lista if item["id"] == aluno_id), alunos_lista[0] if alunos_lista else None)
    avaliacoes_lista = _assessments(aluno_selecionado["id"] if aluno_selecionado else None)
    avaliacao_atual = avaliacoes_lista[0] if avaliacoes_lista else {}
    medidas = []
    if avaliacao_atual:
        medidas = [
            {"nome": "Tricipital", "valor": _first(avaliacao_atual, "tricipital", default="—")},
            {"nome": "Subscapular", "valor": _first(avaliacao_atual, "subscapular", default="—")},
            {"nome": "Suprailiaca", "valor": _first(avaliacao_atual, "suprailiaca", default="—")},
            {"nome": "Abdominal", "valor": _first(avaliacao_atual, "abdominal", default="—")},
            {"nome": "Peitoral", "valor": _first(avaliacao_atual, "peitoral", default="—")},
            {"nome": "Coxa", "valor": _first(avaliacao_atual, "coxa", default="—")},
            {"nome": "Perna", "valor": _first(avaliacao_atual, "perna", default="—")},
            {"nome": "Braco direito", "valor": _first(avaliacao_atual, "braco_direito", default="—")},
            {"nome": "Peitoral", "valor": _first(avaliacao_atual, "peitoral_circ", default="—")},
            {"nome": "Cintura", "valor": _first(avaliacao_atual, "cintura", default="—")},
            {"nome": "Quadril", "valor": _first(avaliacao_atual, "quadril", default="—")},
            {"nome": "Coxa direita", "valor": _first(avaliacao_atual, "coxa_direita", default="—")},
            {"nome": "Perna direita", "valor": _first(avaliacao_atual, "perna_direita", default="—")},
        ]
    return render_template(
        "avaliacoes.html",
        alunos=alunos_lista,
        aluno_selecionado=aluno_selecionado,
        avaliacao=avaliacao_atual,
        avaliacao_atual=avaliacao_atual,
        historico=avaliacoes_lista,
        historico_avaliacoes=avaliacoes_lista,
        medidas=medidas,
        avaliacao_descricao="Uma leitura mais elegante e rapida da composicao corporal e das medidas coletadas.",
        criar_avaliacao_url=url_for("avaliacoes"),
        csrf_form_token=_csrf_token,
        **_personal_context("avaliacoes"),
    )


@app.get("/avaliacoes/<avaliacao_id>/pdf")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def exportar_avaliacao_pdf(avaliacao_id: str):
    result = _select_one(TABLE_AVALIACOES, avaliacao_id)
    if not result["ok"] or not result["data"]:
        flash("Avaliacao nao encontrada.", "error")
        return redirect(url_for("avaliacoes"))
    avaliacao = next((item for item in _assessments(_first(result["data"], "aluno_id", default=None)) if item.get("id") == avaliacao_id), None)
    if not avaliacao:
        flash("Nao foi possivel montar o laudo da avaliacao.", "error")
        return redirect(url_for("avaliacoes"))
    try:
        pdf_buffer = _avaliacao_pdf_document(avaliacao)
    except ModuleNotFoundError:
        flash("A biblioteca de PDF ainda nao esta instalada. Rode pip install -r requirements.txt.", "error")
        return redirect(url_for("avaliacoes", aluno_id=avaliacao.get("aluno_id", "")))
    filename = f"laudo-avaliacao-{_safe_pdf_filename(avaliacao.get('aluno_nome'))}-{_safe_pdf_filename(avaliacao.get('data'))}.pdf"
    return send_file(pdf_buffer, mimetype="application/pdf", as_attachment=True, download_name=filename)


@app.route("/evolucao", methods=["GET", "POST"])
@app.route("/evolucao.html", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def evolucao():
    alunos_lista = _students()
    aluno_id = request.values.get("aluno_id", "")
    aluno_ativo = next((item for item in alunos_lista if item["id"] == aluno_id), alunos_lista[0] if alunos_lista else None)
    historico = _assessments(aluno_ativo["id"] if aluno_ativo else None)
    ultima = historico[0] if historico else {}
    return render_template(
        "evolucao.html",
        alunos=alunos_lista,
        aluno_ativo=aluno_ativo,
        aluno_selecionado=aluno_ativo,
        ultima_avaliacao=ultima,
        resumo_atual=ultima,
        historico_avaliacoes=historico,
        historico=historico,
        peso_atual=ultima.get("peso", "—"),
        gordura_atual=ultima.get("gordura", "—"),
        altura_atual=ultima.get("altura", "—"),
        total_avaliacoes=len(historico),
        resumo_avaliacao=ultima,
        **_personal_context("evolucao"),
    )


@app.route("/observacoes", methods=["GET", "POST"])
@app.route("/observacoes.html", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def observacoes():
    alunos_lista = _students()
    aluno_id = request.values.get("aluno_id", "")
    aluno_ativo = next((item for item in alunos_lista if item["id"] == aluno_id), None)
    observacoes_lista = []
    if aluno_ativo:
        result = _select(
            TABLE_OBSERVACOES,
            filters={"aluno_id": aluno_ativo["id"]},
            order="created_at",
            desc=True,
        )
        if result["ok"]:
            observacoes_lista = result["data"]
        elif not result["ok"] and _missing_table_error(result["error"]):
            flash(_observacao_table_error_message(result["error"]), "error")
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return redirect(url_for("observacoes", aluno_id=aluno_id))
        payload = {
            "aluno_id": request.form.get("aluno_id"),
            "foco_treino": request.form.get("foco_treino"),
            "observacao": request.form.get("observacao_transcrita") or request.form.get("observacao"),
            "observacao_transcrita": request.form.get("observacao_transcrita") or request.form.get("observacao"),
            "proximo_ajuste": request.form.get("proximo_ajuste"),
            "updated_at": datetime.utcnow().isoformat(),
        }
        result = _insert(TABLE_OBSERVACOES, payload)
        flash("Observacao salva com sucesso." if result["ok"] else _observacao_table_error_message(result["error"]), "success" if result["ok"] else "error")
        return redirect(url_for("observacoes", aluno_id=request.form.get("aluno_id", "")))

    historico_observacoes = [
        {
            **item,
            "data": _fmt_date(_first(item, "created_at", "updated_at")),
            "hora": _fmt_datetime(_first(item, "created_at", "updated_at"))[-5:] if _first(item, "created_at", "updated_at") else "",
            "aluno_nome": aluno_ativo["nome"] if aluno_ativo else "Aluno",
            "observacao_transcrita": _first(item, "observacao_transcrita", "observacao", default=""),
        }
        for item in observacoes_lista
    ]

    return render_template(
        "observacoes.html",
        alunos=alunos_lista,
        aluno_ativo=aluno_ativo,
        observacao=historico_observacoes[0] if historico_observacoes else {},
        historico=historico_observacoes,
        aluno_id_selecionado=aluno_ativo["id"] if aluno_ativo else "",
        form={
            "foco_treino": "",
            "observacao_transcrita": "",
            "proximo_ajuste": "",
        },
        salvar_observacao_url=url_for("observacoes"),
        csrf_form_token=_csrf_token,
        **_personal_context("observacoes"),
    )


@app.route("/anamnese/salvar", methods=["GET", "POST"])
@app.route("/anamnese/salvar/", methods=["GET", "POST"])
@app.route("/anamnese", methods=["GET", "POST"])
@app.route("/anamnese.html", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def anamnese():
    if request.method == "GET" and request.path.rstrip("/") == "/anamnese/salvar":
        return redirect(url_for("anamnese", aluno_id=request.args.get("aluno_id", "")))
    alunos_lista = _students()
    busca = request.values.get("busca", "").strip()
    if busca:
        termo = busca.lower()
        alunos_lista = [
            aluno
            for aluno in alunos_lista
            if termo in aluno["nome"].lower() or termo in aluno["email"].lower()
        ]
    aluno_id = request.values.get("aluno_id", "")
    aluno_ativo = next((item for item in alunos_lista if item["id"] == aluno_id), alunos_lista[0] if alunos_lista else None)
    anamnese_atual = {}
    if aluno_ativo:
        result = _select_first_by(TABLE_ANAMNESES, "aluno_id", aluno_ativo["id"])
        if result["ok"] and result["data"]:
            anamnese_atual = result["data"]
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return redirect(url_for("anamnese", aluno_id=request.form.get("aluno_id", "")))
        payload = {
            "aluno_id": request.form.get("aluno_id"),
            "historico_medico": request.form.get("historico_medico"),
            "restricoes_fisicas": request.form.get("restricoes_fisicas"),
            "lesoes": request.form.get("lesoes"),
            "atividade_fisica_anterior": request.form.get("atividade_fisica_anterior"),
            "objetivos": request.form.get("objetivos"),
            "observacoes": request.form.get("observacoes"),
            "updated_at": datetime.utcnow().isoformat(),
        }
        if request.form.get("anamnese_id"):
            result = _update(TABLE_ANAMNESES, request.form.get("anamnese_id"), payload)
        else:
            result = _insert(TABLE_ANAMNESES, payload)
        flash("Anamnese salva com sucesso." if result["ok"] else _anamnese_table_error_message(result["error"]), "success" if result["ok"] else "error")
        return redirect(url_for("anamnese", aluno_id=request.form.get("aluno_id", "")))

    return render_template(
        "anamnese.html",
        alunos=alunos_lista,
        aluno_ativo=aluno_ativo,
        anamnese=anamnese_atual,
        busca=busca,
        buscar_anamnese_url=url_for("anamnese"),
        salvar_anamnese_url="/anamnese/salvar",
        csrf_form_token=_csrf_token,
        **_personal_context("anamnese"),
    )


@app.get("/anamnese/buscar")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def buscar_anamnese_redirect():
    return redirect(url_for("anamnese", aluno_id=request.args.get("aluno_id", "")))


@app.route("/exercicios", methods=["GET"])
@app.route("/exercicios.html", methods=["GET"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def exercicios():
    exercicio_edicao_id = request.args.get("editar_exercicio_id", "")
    exercicios_lista = _exercises()
    exercicio_edicao = next((item for item in exercicios_lista if item["id"] == exercicio_edicao_id), {})
    return render_template(
        "exercicios.html",
        exercicios=exercicios_lista,
        busca=request.args.get("busca", ""),
        exercicio_edicao=exercicio_edicao,
        modal_titulo="Editar exercicio" if exercicio_edicao else "Novo exercicio",
        salvar_exercicio_url=url_for("salvar_exercicio"),
        editar_exercicio_url_base="/exercicios/editar",
        excluir_exercicio_url_base="/exercicios/excluir",
        csrf_form_token=_csrf_token,
        **_personal_context("exercicios"),
    )


@app.get("/exercicios/editar")
@app.get("/exercicios/editar/")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def abrir_edicao_exercicio_sem_id():
    return redirect(url_for("exercicios"))


@app.get("/exercicios/editar/<exercicio_id>")
@app.get("/exercicios/editar/<exercicio_id>/")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def abrir_edicao_exercicio(exercicio_id: str):
    return redirect(url_for("exercicios", editar_exercicio_id=exercicio_id) + "#novo-exercicio-modal")


@app.route("/exercicios/upload-imagem", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def upload_imagem_exercicio_redirect():
    flash("Upload de imagem ainda nao esta ativo. Use URL de video ou imagem por enquanto.", "info")
    return redirect(url_for("exercicios"))


@app.post("/exercicios/salvar")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def salvar_exercicio():
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("exercicios"))
    exercicio_id = request.form.get("exercicio_id", "")
    grupo_muscular_id = _get_or_create_muscle_group_id(request.form.get("grupo_muscular"))
    payload = {
        "nome": request.form.get("nome"),
        "grupo_muscular_id": grupo_muscular_id,
        "descricao": request.form.get("descricao"),
        "link_execucao": request.form.get("video_url"),
    }
    result = _update(TABLE_EXERCICIOS, exercicio_id, payload) if exercicio_id else _insert(TABLE_EXERCICIOS, payload)
    flash("Exercicio salvo com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel salvar o exercicio."), "success" if result["ok"] else "error")
    return redirect(url_for("exercicios"))


@app.post("/exercicios/excluir/<exercicio_id>")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def excluir_exercicio(exercicio_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
    else:
        result = _delete(TABLE_EXERCICIOS, exercicio_id)
        flash("Exercicio excluido com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel excluir o exercicio."), "success" if result["ok"] else "error")
    return redirect(url_for("exercicios"))


@app.route("/mensagens", methods=["GET"])
@app.route("/mensagens.html", methods=["GET"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def mensagens():
    contact_id = request.args.get("contato_id", "")
    context = _messages_for_personal(contact_id)
    return render_template(
        "mensagens.html",
        enviar_mensagem_url=url_for("enviar_mensagem"),
        canal_mensagem="painel",
        **context,
        **_personal_context("mensagens"),
    )


@app.post("/mensagens/enviar")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def enviar_mensagem():
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("mensagens"))
    payload = {
        "contato_id": request.form.get("contato_id"),
        "profissional_id": request.form.get("profissional_id"),
        "texto": request.form.get("mensagem"),
        "autor": "Personal",
        "autor_nome": _session_user()["nome"] or "Personal",
        "canal": request.form.get("canal"),
        "created_at": datetime.utcnow().isoformat(),
    }
    result = _insert(TABLE_MENSAGENS, payload)
    flash("Mensagem enviada." if result["ok"] else _message_table_error_message(result["error"]), "success" if result["ok"] else "error")
    return redirect(url_for("mensagens", contato_id=request.form.get("contato_id", "")))


@app.route("/mensagens/atualizar", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def atualizar_mensagens_redirect():
    return redirect(url_for("mensagens", contato_id=request.values.get("contato_id", "")))


@app.route("/mensagens/upload", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def upload_mensagem_redirect():
    flash("Upload de arquivo em mensagens ainda nao esta ativo.", "info")
    return redirect(url_for("mensagens", contato_id=request.values.get("contato_id", "")))


@app.route("/financeiro", methods=["GET"])
@app.route("/financeiro.html", methods=["GET"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def financeiro():
    pagamentos = _payment_rows()
    planos = _plans()
    alunos = _students()
    plano_edicao_id = request.args.get("editar_plano_id", "")
    plano_edicao = next((plano for plano in planos if str(plano.get("id")) == str(plano_edicao_id)), {})
    receita = sum(_to_float(_first(item, "valor", default=0)) or 0 for item in pagamentos if item.get("status") == "pago")
    return render_template(
        "financeiro.html",
        pagamentos=pagamentos,
        planos=planos,
        alunos=alunos,
        alunos_planos=_student_plan_rows(alunos, planos),
        plano_edicao=plano_edicao,
        receita_estimada=_currency(receita),
        receita_descricao="Recebimentos registrados",
        total_sessoes=len(_schedule_rows()),
        sessoes_descricao="Aulas cadastradas",
        total_planos_ativos=len(planos),
        planos_descricao="Planos disponiveis",
        abrir_novo_plano_url=url_for("financeiro") + "#novo-plano",
        alterar_status_pagamento_url_base="/financeiro/pagamentos",
        gerenciar_plano_url_base="/financeiro/planos",
        criar_plano_url=url_for("criar_plano"),
        csrf_form_token=_csrf_token,
        **_personal_context("financeiro"),
    )


@app.post("/financeiro/pagamentos/<pagamento_id>/status")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def alterar_status_pagamento(pagamento_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("financeiro"))
    status = _slug_status(request.form.get("status_pagamento", "pendente"))
    status_db = _payment_status_db(status)
    existing = _select_one(TABLE_PAGAMENTOS, pagamento_id)
    payload = {"status_parcela": status_db}
    if status == "pago":
        payload["data_recebimento"] = datetime.utcnow().date().isoformat()
    if existing["ok"] and existing["data"]:
        result = _update(TABLE_PAGAMENTOS, pagamento_id, payload)
    else:
        payload.update(
            {
                "aluno_id": pagamento_id,
                "data_parcela": datetime.utcnow().date().isoformat(),
                "valor": request.form.get("valor") or 0,
            }
        )
        result = _insert(TABLE_PAGAMENTOS, payload)
    flash("Status alterado com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel alterar o status."), "success" if result["ok"] else "error")
    return redirect(url_for("financeiro"))


@app.post("/financeiro/planos")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def criar_plano():
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("financeiro"))
    payload = {
        "nome": request.form.get("nome"),
        "descricao": request.form.get("descricao"),
        "preco": request.form.get("preco"),
        "duracao_dias": request.form.get("duracao_dias"),
        "recorrente": True if request.form.get("recorrente") else False,
    }
    result = _insert(TABLE_PLANOS, payload)
    if not result["ok"] and _missing_column_error(result["error"], "duracao_dias"):
        payload.pop("duracao_dias", None)
        result = _insert(TABLE_PLANOS, payload)
    aluno_ids = request.form.getlist("aluno_ids")
    legacy_aluno_id = request.form.get("aluno_id", "")
    if legacy_aluno_id and legacy_aluno_id not in aluno_ids:
        aluno_ids.append(legacy_aluno_id)
    alunos_vinculados = True
    if result["ok"] and aluno_ids:
        plano_criado = result["data"][0] if result.get("data") else {}
        plano_id = plano_criado.get("id")
        if plano_id:
            for aluno_id in aluno_ids:
                vinculo = _update(TABLE_ALUNOS, aluno_id, {"plano": plano_id})
                if not vinculo["ok"] and _missing_column_error(vinculo["error"], "plano"):
                    vinculo = _update(TABLE_ALUNOS, aluno_id, {"plano_id": plano_id})
                alunos_vinculados = alunos_vinculados and vinculo["ok"]
    if result["ok"] and aluno_ids and not alunos_vinculados:
        flash("Plano criado, mas nao foi possivel vincular todos os alunos selecionados.", "error")
    else:
        flash("Plano criado com sucesso." if result["ok"] else _plan_table_error_message(result["error"]), "success" if result["ok"] else "error")
    return redirect(url_for("financeiro"))


@app.route("/financeiro/planos/<plano_id>", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def gerenciar_plano(plano_id: str):
    if request.method == "GET":
        plano = _select_one(TABLE_PLANOS, plano_id)
        if not plano["ok"] or not plano["data"]:
            flash("Plano nao encontrado.", "error")
            return redirect(url_for("financeiro"))
        return redirect(url_for("financeiro", editar_plano_id=plano_id) + "#editar-plano")

    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("financeiro", editar_plano_id=plano_id) + "#editar-plano")
    payload = {
        "nome": request.form.get("nome"),
        "descricao": request.form.get("descricao"),
        "preco": request.form.get("preco"),
        "duracao_dias": request.form.get("duracao_dias"),
        "recorrente": True if request.form.get("recorrente") else False,
    }
    result = _update(TABLE_PLANOS, plano_id, payload)
    if not result["ok"] and _missing_column_error(result["error"], "duracao_dias"):
        payload.pop("duracao_dias", None)
        result = _update(TABLE_PLANOS, plano_id, payload)
    flash("Plano atualizado com sucesso." if result["ok"] else _plan_table_error_message(result["error"]), "success" if result["ok"] else "error")
    return redirect(url_for("financeiro"))


@app.route("/agenda-aluno")
@app.route("/agenda-aluno.html")
@app.route("/aluno/agenda")
@login_required
@role_required("Aluno")
def agenda_aluno():
    aluno = _current_student_row()
    horarios = []
    agendamentos = []
    for item in _schedule_rows():
        if item["status_classe"] in ("disponivel", "pendente") and not item.get("aluno_id"):
            horarios.append(item)
        elif aluno and item.get("aluno_id") == aluno.get("id") and item["status_classe"] != "cancelado":
            item["pode_cancelar"] = item["status_classe"] in {"agendado", "confirmado", "pendente"}
            agendamentos.append(item)
    return render_template(
        "agenda-aluno.html",
        horarios_disponiveis=horarios,
        agendamentos=agendamentos,
        marcar_aula_url=url_for("marcar_aula_aluno"),
        cancelar_agendamento_url_base="/agenda/cancelar-agendamento",
        total_compromissos=len(agendamentos),
        **_student_context("agenda"),
    )


@app.get("/meu-treino")
@login_required
@role_required("Aluno")
def meu_treino_legacy_redirect():
    return redirect(url_for("aluno_meu_treino"))


@app.post("/agenda/marcar")
@login_required
@role_required("Aluno")
def marcar_aula_aluno():
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("agenda_aluno"))
    aluno = _current_student_row()
    if not aluno:
        flash("Aluno nao localizado para este login.", "error")
        return redirect(url_for("agenda_aluno"))
    horario_id = request.form.get("horario_id")
    if not horario_id:
        flash("Horario invalido.", "error")
        return redirect(url_for("agenda_aluno"))
    result = _update(
        TABLE_AGENDA,
        horario_id,
        {
            "aluno_id": aluno.get("id"),
            "status": "agendado",
        },
    )
    flash("Aula marcada com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel marcar a aula."), "success" if result["ok"] else "error")
    return redirect(url_for("agenda_aluno"))


@app.post("/agenda/cancelar-agendamento/<agenda_id>")
@login_required
@role_required("Aluno")
def cancelar_agendamento_aluno(agenda_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("agenda_aluno"))
    result = _update(TABLE_AGENDA, agenda_id, {"aluno_id": None, "status": "disponivel"})
    flash("Agendamento cancelado." if result["ok"] else (result["error"] or "Nao foi possivel cancelar o agendamento."), "success" if result["ok"] else "error")
    return redirect(url_for("agenda_aluno"))


@app.get("/aluno/dashboard")
@app.get("/aluno_dashboard.html")
@login_required
@role_required("Aluno")
def aluno_dashboard():
    aluno = _current_student_row() or {}
    aluno_id = aluno.get("id")
    treinos_lista = _trainings(aluno_id) if aluno_id else []
    avaliacoes_lista = _assessments(aluno_id) if aluno_id else []
    treino_do_dia = treinos_lista[0] if treinos_lista else {}
    if treino_do_dia:
        treino_do_dia["exercicio_destaque"] = treino_do_dia.get("exercicios_lista", [{}])[0].get("nome", "Exercicio principal") if treino_do_dia.get("exercicios_lista") else "Exercicio principal"
        treino_do_dia["prescricao"] = treino_do_dia.get("observacoes") or "Consulte os detalhes para iniciar."
    return render_template(
        "aluno_dashboard.html",
        treino_do_dia=treino_do_dia,
        total_checkins=len([item for item in _schedule_rows() if aluno_id and item.get("aluno_id") == aluno_id and item["status"] == "concluido"]),
        total_avaliacoes=len(avaliacoes_lista),
        iniciar_treino_url=url_for("aluno_treino_execucao", treino_id=treino_do_dia.get("id", "")) if treino_do_dia else url_for("aluno_meu_treino"),
        **_student_context("dashboard"),
    )


@app.get("/aluno/treinos")
@app.get("/aluno/meu-treino")
@app.get("/aluno_meu_treino.html")
@login_required
@role_required("Aluno")
def aluno_meu_treino():
    aluno = _current_student_row() or {}
    aluno_id = aluno.get("id")
    treinos_lista = _trainings(aluno_id) if aluno_id else []
    treino_id = request.args.get("treino_id", "")
    treino_ativo = next((item for item in treinos_lista if item["id"] == treino_id), treinos_lista[0] if treinos_lista else {})
    treino_index = treinos_lista.index(treino_ativo) if treino_ativo in treinos_lista else 0
    treino_anterior = treinos_lista[treino_index - 1] if treinos_lista and treino_index > 0 else None
    treino_proximo = treinos_lista[treino_index + 1] if treinos_lista and treino_index < len(treinos_lista) - 1 else None
    return render_template(
        "aluno_meu_treino.html",
        total_treinos_resumo=len(treinos_lista),
        treino=treino_ativo,
        treino_ativo_id=treino_ativo.get("id", ""),
        treino_total_exercicios=treino_ativo.get("total_exercicios", 0),
        treino_series_resumo=sum(1 for _ in treino_ativo.get("exercicios_lista", [])),
        treino_status_resumo=treino_ativo.get("status", "Nao iniciado"),
        treino_detalhes_destino=url_for("aluno_meu_treino", treino_id=treino_ativo.get("id", "")) if treino_ativo else url_for("aluno_meu_treino"),
        treino_iniciar_destino=url_for("aluno_treino_execucao", treino_id=treino_ativo.get("id", "")) if treino_ativo else url_for("aluno_meu_treino"),
        treino_anterior_destino=url_for("aluno_meu_treino", treino_id=treino_anterior["id"]) if treino_anterior else "",
        treino_proximo_destino=url_for("aluno_meu_treino", treino_id=treino_proximo["id"]) if treino_proximo else "",
        retorno_treinos_destino=url_for("aluno_meu_treino"),
        aluno_treino_detalhe_base="/aluno/meu-treino",
        iniciar_treino_base="/aluno/treino",
        aluno_treino_execucao_url_base="/aluno/treino",
        **_student_context("meu_treino"),
    )


@app.get("/aluno/treinos/iniciar")
@app.get("/aluno_treino_execucao.html")
@login_required
@role_required("Aluno")
def iniciar_treino_aluno_redirect():
    aluno = _current_student_row() or {}
    aluno_id = aluno.get("id")
    treinos_lista = _trainings(aluno_id) if aluno_id else []
    treino_id = request.args.get("treino_id", "")
    if treino_id and any(item["id"] == treino_id for item in treinos_lista):
        return redirect(url_for("aluno_treino_execucao", treino_id=treino_id))
    if treinos_lista:
        return redirect(url_for("aluno_treino_execucao", treino_id=treinos_lista[0]["id"]))
    return redirect(url_for("aluno_meu_treino"))


@app.get("/aluno/treino/<treino_id>/execucao")
@login_required
@role_required("Aluno")
def aluno_treino_execucao(treino_id: str):
    aluno = _current_student_row() or {}
    aluno_id = aluno.get("id")
    treinos_lista = _trainings(aluno_id) if aluno_id else []
    treino = next((item for item in treinos_lista if item["id"] == treino_id), None)
    if not treino:
        flash("Treino nao encontrado.", "error")
        return redirect(url_for("aluno_meu_treino"))
    exercicios = []
    for index, exercicio in enumerate(treino.get("exercicios_lista", []), start=1):
        exercicios.append({**exercicio, "id": exercicio.get("id") or f"ex-{index}"})
    return render_template(
        "aluno_treino_execucao.html",
        treino=treino,
        treino_id=treino_id,
        exercicios=exercicios,
        registrar_serie_destino=url_for("registrar_serie_treino", treino_id=treino_id),
        registrar_serie_url=url_for("registrar_serie_treino", treino_id=treino_id),
        concluir_treino_destino=url_for("concluir_treino_execucao", treino_id=treino_id),
        concluir_treino_url=url_for("concluir_treino_execucao", treino_id=treino_id),
        treino_proximo_destino="",
        retorno_treinos_destino=url_for("aluno_meu_treino"),
        **_student_context("meu_treino"),
    )


@app.post("/aluno/treino/<treino_id>/serie")
@login_required
@role_required("Aluno")
def registrar_serie_treino(treino_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("aluno_treino_execucao", treino_id=treino_id))
    aluno = _current_student_row() or {}
    result = _insert(
        TABLE_EXECUCOES,
        {
            "aluno_id": aluno.get("id"),
            "treino_id": treino_id,
            "exercicio_id": request.form.get("exercicio_id"),
            "serie_registrada": True,
            "created_at": datetime.utcnow().isoformat(),
        },
    )
    flash("Serie registrada." if result["ok"] else (result["error"] or "Nao foi possivel registrar a serie."), "success" if result["ok"] else "error")
    return redirect(url_for("aluno_treino_execucao", treino_id=treino_id))


@app.post("/aluno/treino/<treino_id>/concluir")
@login_required
@role_required("Aluno")
def concluir_treino_execucao(treino_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("aluno_treino_execucao", treino_id=treino_id))
    aluno = _current_student_row() or {}
    result = _insert(
        TABLE_EXECUCOES,
        {
            "aluno_id": aluno.get("id"),
            "treino_id": treino_id,
            "status": "concluido",
            "serie_registrada": False,
            "created_at": datetime.utcnow().isoformat(),
        },
    )
    flash("Treino concluido." if result["ok"] else (result["error"] or "Nao foi possivel concluir o treino."), "success" if result["ok"] else "error")
    return redirect(url_for("aluno_meu_treino", treino_id=treino_id))


@app.route("/aluno/mensagens", methods=["GET"])
@app.route("/aluno_mensagens.html", methods=["GET"])
@login_required
@role_required("Aluno")
def aluno_mensagens():
    contact_id = request.args.get("contato_id", "")
    context = _messages_for_student(contact_id)
    return render_template(
        "aluno_mensagens.html",
        enviar_mensagem_url=url_for("enviar_mensagem_aluno"),
        canal_mensagem="painel_aluno",
        **context,
        **_student_context("mensagens"),
    )


@app.post("/aluno/mensagens/enviar")
@login_required
@role_required("Aluno")
def enviar_mensagem_aluno():
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("aluno_mensagens"))
    payload = {
        "contato_id": request.form.get("contato_id"),
        "aluno_id": request.form.get("aluno_id"),
        "texto": request.form.get("mensagem"),
        "autor": "Aluno",
        "autor_nome": _student_context("mensagens")["aluno_nome"],
        "canal": request.form.get("canal"),
        "created_at": datetime.utcnow().isoformat(),
    }
    result = _insert(TABLE_MENSAGENS, payload)
    flash("Mensagem enviada." if result["ok"] else _message_table_error_message(result["error"]), "success" if result["ok"] else "error")
    return redirect(url_for("aluno_mensagens", contato_id=request.form.get("contato_id", "")))


@app.route("/aluno/mensagens/contatos", methods=["GET", "POST"])
@app.route("/aluno/mensagens/conversa", methods=["GET", "POST"])
@app.route("/aluno/mensagens/atualizar", methods=["GET", "POST"])
@login_required
@role_required("Aluno")
def aluno_mensagens_redirects():
    return redirect(url_for("aluno_mensagens", contato_id=request.values.get("contato_id", "")))


@app.route("/aluno/mensagens/upload", methods=["GET", "POST"])
@login_required
@role_required("Aluno")
def aluno_mensagens_upload_redirect():
    flash("Upload de arquivo em mensagens ainda nao esta ativo.", "info")
    return redirect(url_for("aluno_mensagens", contato_id=request.values.get("contato_id", "")))


@app.get("/evolucao-aluno")
@app.get("/evolucao-aluno.html")
@app.get("/aluno/evolucao")
@login_required
@role_required("Aluno")
def evolucao_aluno():
    aluno = _current_student_row() or {}
    aluno_id = str(aluno.get("id") or "").strip()
    historico = _assessments(aluno_id) if aluno_id else []
    ultima = historico[0] if historico else {}
    anterior = historico[1] if len(historico) > 1 else {}
    variacao = {
        "peso": "Sem dados",
        "gordura": "Sem dados",
        "massa_magra": "Sem dados",
        "imc": "Sem dados",
    }
    if anterior:
        for campo in ("peso", "gordura", "massa_magra", "imc"):
            atual = _first(ultima, campo, default="")
            previo = _first(anterior, campo, default="")
            if atual and previo:
                variacao[campo] = f"{previo} -> {atual}"
    return render_template(
        "evolucao-aluno.html",
        historico_avaliacoes=historico,
        historico=historico,
        ultima_avaliacao=ultima,
        resumo_atual=ultima,
        peso_atual=ultima.get("peso", "—"),
        gordura_atual=ultima.get("gordura", "—"),
        altura_atual=ultima.get("altura", "—"),
        total_avaliacoes=len(historico),
        resumo_avaliacao=ultima,
        variacao=variacao,
        aluno_sincronizado=bool(aluno_id),
        aviso_sincronizacao="" if aluno_id else "Seu login ainda não está vinculado a um aluno cadastrado. Use o mesmo email do cadastro do aluno para sincronizar a evolução.",
        **_student_context("evolucao"),
    )


@app.route("/configuracoes", methods=["GET", "POST"])
@app.route("/configuracoes.html", methods=["GET", "POST"])
@login_required
def configuracoes():
    role = str(session.get("user_role", "")).strip().lower()
    if role == "aluno":
        return redirect(url_for("aluno_dashboard"))
    usuario = _current_user_row() or {}
    google_calendar = _google_calendar_context()
    defaults = {
        "nome_marca": marca_nome if (marca_nome := BRAND_NAME) else "CONFIE Personal",
        "botao_principal": "Comecar agora",
        "titulo_topo": "Transforme",
        "titulo_destaque": "Seu Treino",
        "botao_secundario": "Entrar",
        "rodape": "© 2026 CONFIE Personal. Todos os direitos reservados.",
        "subtitulo": "Plataforma completa para Personal Trainers gerenciarem alunos, treinos e agendas em um so lugar",
        "apresentacao_nome": "Diogo Bezzi Jaeger",
        "apresentacao_resumo": "Bacharel e licenciado em Educacao Fisica desde 2014, com atuacao voltada para saude, performance e acompanhamento individualizado.",
        "especialidades": "Musculacao, Futebol, Futsal, Natacao e Ginastica Laboral",
        "formacao_atual": "Resistance Training Specialist (RTS)",
        "mostrar_apresentacao": True,
        "mostrar_planos": True,
        "mostrar_recursos": True,
    }
    config = dict(defaults)
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
        else:
            if request.form.get("acao") == "restaurar":
                flash("Configuracoes restauradas para os valores padrao.", "success")
                return redirect(url_for("configuracoes"))
            config.update(
                {
                    "nome_marca": request.form.get("nome_marca", defaults["nome_marca"]).strip() or defaults["nome_marca"],
                    "botao_principal": request.form.get("botao_principal", defaults["botao_principal"]).strip() or defaults["botao_principal"],
                    "titulo_topo": request.form.get("titulo_topo", defaults["titulo_topo"]).strip() or defaults["titulo_topo"],
                    "titulo_destaque": request.form.get("titulo_destaque", defaults["titulo_destaque"]).strip() or defaults["titulo_destaque"],
                    "botao_secundario": request.form.get("botao_secundario", defaults["botao_secundario"]).strip() or defaults["botao_secundario"],
                    "rodape": request.form.get("rodape", defaults["rodape"]).strip() or defaults["rodape"],
                    "subtitulo": request.form.get("subtitulo", defaults["subtitulo"]).strip() or defaults["subtitulo"],
                    "apresentacao_nome": request.form.get("apresentacao_nome", defaults["apresentacao_nome"]).strip() or defaults["apresentacao_nome"],
                    "apresentacao_resumo": request.form.get("apresentacao_resumo", defaults["apresentacao_resumo"]).strip() or defaults["apresentacao_resumo"],
                    "especialidades": request.form.get("especialidades", defaults["especialidades"]).strip() or defaults["especialidades"],
                    "formacao_atual": request.form.get("formacao_atual", defaults["formacao_atual"]).strip() or defaults["formacao_atual"],
                    "mostrar_apresentacao": request.form.get("mostrar_apresentacao") == "on",
                    "mostrar_planos": request.form.get("mostrar_planos") == "on",
                    "mostrar_recursos": request.form.get("mostrar_recursos") == "on",
                }
            )
            flash("Previa atualizada. Quando quiser, a persistencia pode ser ligada ao banco.", "success")
    return render_template(
        "configuracoes.html",
        page_title="CONFIE - Configuracoes",
        usuario_email=_first(usuario, "email", default=_session_user().get("email", "")),
        usuario_tipo_conta=_first(usuario, "tipo_conta", default="Personal Trainer"),
        usuario_nascimento=_fmt_date(_first(usuario, "nascimento", default="")) or "Nao informado",
        google_calendar=google_calendar,
        google_calendar_preview=google_calendar.get("events", [])[:3],
        config=config,
        **_personal_context("configuracoes"),
    )


def _json_payload() -> Dict[str, Any]:
    payload = request.get_json(silent=True)
    return payload if isinstance(payload, dict) else {}


def _api_response(result: Dict[str, Any], *, success_status: int = 200):
    status = success_status if result["ok"] else 400
    return {"ok": result["ok"], "data": result["data"], "error": result["error"]}, status


def _api_create(table: str, payload: Dict[str, Any], required: Optional[List[str]] = None):
    missing = [field for field in (required or []) if not payload.get(field)]
    if missing:
        return {"ok": False, "data": None, "error": f"Campos obrigatorios ausentes: {', '.join(missing)}"}, 400
    return _api_response(_insert(table, payload), success_status=201)


def _api_update(table: str, row_id: str, payload: Dict[str, Any]):
    if not payload:
        return {"ok": False, "data": None, "error": "Envie ao menos um campo para atualizar."}, 400
    return _api_response(_update(table, row_id, payload))


def _api_delete(table: str, row_id: str):
    return _api_response(_delete(table, row_id))


def _only(payload: Dict[str, Any], allowed: List[str]) -> Dict[str, Any]:
    return {key: payload.get(key) for key in allowed if key in payload}


@app.get("/api/alunos")
@login_required
def api_listar_alunos():
    return {"ok": True, "data": _students(), "error": None}


@app.post("/api/alunos")
@login_required
def api_criar_aluno():
    payload = _json_payload()
    aluno = {
        "nome": payload.get("nome"),
        "email": payload.get("email"),
        "objetivo": payload.get("objetivo"),
        "data_nascimento": payload.get("data_nascimento"),
        "experiencias_anteriores": payload.get("experiencias_anteriores"),
        "restricoes_fisicas": payload.get("restricoes_fisicas"),
        "plano_id": payload.get("plano_id"),
        "auth_user_id": payload.get("auth_user_id"),
    }
    missing = [field for field in ("nome", "email") if not aluno.get(field)]
    if missing:
        return {"ok": False, "data": None, "error": f"Campos obrigatorios ausentes: {', '.join(missing)}"}, 400
    return _api_response(_insert_raw(TABLE_ALUNOS, aluno), success_status=201)


@app.get("/api/alunos/<aluno_id>")
@login_required
def api_obter_aluno(aluno_id: str):
    result = _select_one(TABLE_ALUNOS, aluno_id)
    status = 200 if result["ok"] and result["data"] else 404
    if result["ok"] and not result["data"]:
        result["error"] = "Aluno nao encontrado."
    return {"ok": result["ok"] and bool(result["data"]), "data": result["data"], "error": result["error"]}, status


@app.put("/api/alunos/<aluno_id>")
@login_required
def api_atualizar_aluno(aluno_id: str):
    return _api_update(
        TABLE_ALUNOS,
        aluno_id,
        _only(
            _json_payload(),
            ["nome", "email", "objetivo", "data_nascimento", "experiencias_anteriores", "restricoes_fisicas", "plano_id", "auth_user_id"],
        ),
    )


@app.delete("/api/alunos/<aluno_id>")
@login_required
def api_excluir_aluno(aluno_id: str):
    return _api_delete(TABLE_ALUNOS, aluno_id)


@app.get("/api/treinos")
@login_required
def api_listar_treinos():
    aluno_id = request.args.get("aluno_id") or None
    return {"ok": True, "data": _trainings(aluno_id), "error": None}


@app.post("/api/treinos")
@login_required
def api_criar_treino():
    payload = _json_payload()
    return _api_create(
        TABLE_TREINOS,
        {
            "descricao": payload.get("descricao") or payload.get("nome"),
            "aluno_id": payload.get("aluno_id"),
            "observacao": payload.get("observacao") or payload.get("observacoes") or payload.get("exercicios_raw"),
        },
        required=["descricao", "aluno_id"],
    )


@app.get("/api/treinos/<treino_id>")
@login_required
def api_obter_treino(treino_id: str):
    treino = next((item for item in _trainings() if item["id"] == treino_id), None)
    status = 200 if treino else 404
    return {"ok": bool(treino), "data": treino, "error": None if treino else "Treino nao encontrado."}, status


@app.put("/api/treinos/<treino_id>")
@login_required
def api_atualizar_treino(treino_id: str):
    payload = _json_payload()
    mapped = {
        "descricao": payload.get("descricao") or payload.get("nome"),
        "aluno_id": payload.get("aluno_id"),
        "observacao": payload.get("observacao") or payload.get("observacoes") or payload.get("exercicios_raw"),
    }
    return _api_update(TABLE_TREINOS, treino_id, mapped)


@app.delete("/api/treinos/<treino_id>")
@login_required
def api_excluir_treino(treino_id: str):
    return _api_delete(TABLE_TREINOS, treino_id)


@app.get("/api/agenda")
@login_required
def api_listar_agenda():
    return {"ok": True, "data": _schedule_rows(), "error": None}


@app.get("/api/google-calendar/events")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def api_google_calendar_events():
    google_calendar = _google_calendar_context()
    if not google_calendar["enabled"]:
        return {
            "ok": False,
            "connected": False,
            "calendar_count": 0,
            "data": [],
            "error": google_calendar["error"],
        }, 503
    if not google_calendar["connected"]:
        return {
            "ok": False,
            "connected": False,
            "calendar_count": 0,
            "data": [],
            "error": google_calendar["error"] or "Google Calendar ainda nao conectado.",
        }, 200
    if google_calendar["error"]:
        return {
            "ok": False,
            "connected": True,
            "calendar_count": google_calendar["calendar_count"],
            "data": google_calendar["events"],
            "error": google_calendar["error"],
        }, 502
    return {
        "ok": True,
        "connected": True,
        "calendar_count": google_calendar["calendar_count"],
        "data": google_calendar["events"],
        "error": None,
    }


@app.post("/api/agenda")
@login_required
def api_criar_agenda():
    payload = _json_payload()
    aluno_id = payload.get("aluno_id")
    status = _slug_status(payload.get("status") or ("disponivel" if not aluno_id else "agendado"))
    titulo = payload.get("titulo") or ("Horario disponivel" if status == "disponivel" else "Aula")
    observacoes = payload.get("observacoes") or payload.get("observacao") or ""
    return _api_create(
        TABLE_AGENDA,
        {
            "data": payload.get("data") or str(payload.get("inicio") or "")[:10],
            "hora": payload.get("hora") or str(payload.get("inicio") or "")[11:16],
            "aluno_id": None if status == "disponivel" else aluno_id,
            "observacao": _build_agenda_observacao(titulo, observacoes, payload.get("termino_hora") or payload.get("termino")),
            "status": status,
        },
        required=["data", "hora"],
    )


@app.get("/api/agenda/<agenda_id>")
@login_required
def api_obter_agenda(agenda_id: str):
    item = next((row for row in _schedule_rows() if row["id"] == agenda_id), None)
    status = 200 if item else 404
    return {"ok": bool(item), "data": item, "error": None if item else "Agenda nao encontrada."}, status


@app.put("/api/agenda/<agenda_id>")
@login_required
def api_atualizar_agenda(agenda_id: str):
    payload = _json_payload()
    status = _slug_status(payload.get("status"))
    titulo = payload.get("titulo")
    observacoes = payload.get("observacoes") or payload.get("observacao")
    mapped = {
        "data": payload.get("data") or str(payload.get("inicio") or "")[:10],
        "hora": payload.get("hora") or str(payload.get("inicio") or "")[11:16],
        "aluno_id": None if status == "disponivel" else payload.get("aluno_id"),
        "status": payload.get("status"),
    }
    if titulo is not None or observacoes is not None or payload.get("termino_hora") is not None or payload.get("termino") is not None:
        mapped["observacao"] = _build_agenda_observacao(titulo or "", observacoes or "", payload.get("termino_hora") or payload.get("termino") or "")
    return _api_update(TABLE_AGENDA, agenda_id, mapped)


@app.delete("/api/agenda/<agenda_id>")
@login_required
def api_excluir_agenda(agenda_id: str):
    return _api_delete(TABLE_AGENDA, agenda_id)


@app.get("/api/avaliacoes")
@login_required
def api_listar_avaliacoes():
    aluno_id = request.args.get("aluno_id") or None
    return {"ok": True, "data": _assessments(aluno_id), "error": None}


@app.post("/api/avaliacoes")
@login_required
def api_criar_avaliacao():
    payload = _json_payload()
    aluno_id = payload.get("aluno_id")
    aluno = next((item for item in _students() if item["id"] == aluno_id), None)
    allowed_fields = [
        "data",
        "peso",
        "estatura",
        "idade",
        "observacao",
    ]
    avaliacao = {field: payload.get(field) for field in allowed_fields}
    avaliacao.update({"aluno_id": aluno_id, "observacao": payload.get("observacao") or payload.get("observacoes")})
    return _api_create(TABLE_AVALIACOES, avaliacao, required=["aluno_id"])


@app.get("/api/avaliacoes/<avaliacao_id>")
@login_required
def api_obter_avaliacao(avaliacao_id: str):
    result = _select_one(TABLE_AVALIACOES, avaliacao_id)
    status = 200 if result["ok"] and result["data"] else 404
    if result["ok"] and not result["data"]:
        result["error"] = "Avaliacao nao encontrada."
    return {"ok": result["ok"] and bool(result["data"]), "data": result["data"], "error": result["error"]}, status


@app.put("/api/avaliacoes/<avaliacao_id>")
@login_required
def api_atualizar_avaliacao(avaliacao_id: str):
    return _api_update(TABLE_AVALIACOES, avaliacao_id, _only(_json_payload(), ["data", "idade", "peso", "estatura", "observacao", "aluno_id"]))


@app.delete("/api/avaliacoes/<avaliacao_id>")
@login_required
def api_excluir_avaliacao(avaliacao_id: str):
    return _api_delete(TABLE_AVALIACOES, avaliacao_id)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=DEFAULT_PORT, debug=True)
