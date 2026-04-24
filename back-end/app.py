import os
import secrets
from datetime import datetime
from functools import wraps
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import Flask, flash, get_flashed_messages, redirect, render_template, request, session, url_for
from supabase import Client, create_client
from werkzeug.security import check_password_hash, generate_password_hash
from paths import BASE_DIR, ENV_FILE, STATIC_DIR, TEMPLATES_DIR


load_dotenv(ENV_FILE)
app = Flask(
    __name__,
    template_folder=str(TEMPLATES_DIR),
    static_folder=str(STATIC_DIR),
)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "confie-dev-secret")


SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "")

TABLE_USUARIOS = os.getenv("SUPABASE_TABLE_USUARIOS", "tb_usuario")
TABLE_ALUNOS = os.getenv("SUPABASE_TABLE_ALUNOS", "tb_aluno")
TABLE_TREINOS = os.getenv("SUPABASE_TABLE_TREINOS", "tb_treino")
TABLE_AGENDA = os.getenv("SUPABASE_TABLE_AGENDA", "tb_agenda")
TABLE_AVALIACOES = os.getenv("SUPABASE_TABLE_AVALIACOES", "tb_avaliacao")
TABLE_EXERCICIOS = os.getenv("SUPABASE_TABLE_EXERCICIOS", "tb_exercicios")
TABLE_MENSAGENS = os.getenv("SUPABASE_TABLE_MENSAGENS", "tb_mensagens")
TABLE_OBSERVACOES = os.getenv("SUPABASE_TABLE_OBSERVACOES", "tb_observacao")
TABLE_ANAMNESES = os.getenv("SUPABASE_TABLE_ANAMNESES", "tb_anamnese")
TABLE_PAGAMENTOS = os.getenv("SUPABASE_TABLE_PAGAMENTOS", "tb_pagamento")
TABLE_PLANOS = os.getenv("SUPABASE_TABLE_PLANOS", "tb_plano")
TABLE_EXECUCOES = os.getenv("SUPABASE_TABLE_EXECUCOES", "tb_execucao_treino")

BRAND_NAME = os.getenv("BRAND_NAME", "CONFIE PERSONAL")
BRAND_LOGO_URL = os.getenv("BRAND_LOGO_URL", "")
DEFAULT_PORT = int(os.getenv("PORT", "5000"))
DEV_BYPASS_AUTH = os.getenv("DEV_BYPASS_AUTH", "0").strip().lower() in {"1", "true", "yes", "on"}
DEV_PERSONAL_ID = "11111111-1111-1111-1111-111111111111"
DEV_ALUNO_ID = "22222222-2222-2222-2222-222222222222"

supabase: Optional[Client] = None
supabase_admin: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
if SUPABASE_URL and SUPABASE_SERVICE_KEY:
    supabase_admin = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

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
        query = _client().table(table).select("*")
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
        return _client().table(table).select("*").eq("id", row_id).limit(1).execute()

    result = _run_query(_op)
    if result["ok"]:
        result["data"] = result["data"][0] if result["data"] else None
    return result


def _select_first_by(table: str, field: str, value: Any) -> Dict[str, Any]:
    def _op():
        return _client().table(table).select("*").eq(field, value).limit(1).execute()

    result = _run_query(_op)
    if result["ok"]:
        result["data"] = result["data"][0] if result["data"] else None
    return result


def _insert(table: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = _clean_payload(payload)

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
    return "does not exist" in lowered or "42p01" in lowered or "42703" in lowered


def _table_has_local_passwords() -> bool:
    global _LOCAL_PASSWORD_SUPPORT
    if _LOCAL_PASSWORD_SUPPORT is not None:
        return _LOCAL_PASSWORD_SUPPORT
    if not _ready():
        _LOCAL_PASSWORD_SUPPORT = False
        return False
    try:
        _client().table(TABLE_USUARIOS).select("senha_hash").limit(1).execute()
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


def _is_student_path(path: str) -> bool:
    return path == "/aluno" or path.startswith("/aluno/") or path in {"/agenda-aluno", "/evolucao-aluno"}


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
    by_email = _select_first_by(TABLE_ALUNOS, "email", current["email"])
    if by_email["ok"] and by_email["data"]:
        return by_email["data"]
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
        "configuracoes_url": url_for("dashboard"),
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
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        name = _first(row, "nome", "name", default="Aluno")
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
                "plano": _first(row, "plano", default="Nao definido"),
                "avatar_iniciais": _initials(name),
            }
        )
    return normalized


def _parse_exercises(raw: Any) -> List[Dict[str, Any]]:
    if isinstance(raw, list):
        items = [str(item).strip() for item in raw if str(item).strip()]
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
        exercises = _parse_exercises(_first(row, "exercicios_raw", "exercicios", default=""))
        aluno_ref = alunos_por_id.get(_first(row, "aluno_id", default=""), {})
        normalized.append(
            {
                **row,
                "id": row.get("id", ""),
                "nome": _first(row, "nome", "name", default="Treino"),
                "aluno_id": _first(row, "aluno_id", default=""),
                "aluno_nome": _first(row, "aluno_nome", default=aluno_ref.get("nome", "Aluno")),
                "status": _human_status(_first(row, "status", default="ativo")),
                "grupo_muscular": _first(row, "grupo_muscular", default="Treino personalizado"),
                "observacoes": _first(row, "observacoes", "notes", default=""),
                "exercicios_raw": _first(row, "exercicios_raw", "exercicios", default=""),
                "exercicios_lista": exercises,
                "total_exercicios": _to_int(_first(row, "total_exercicios", default=len(exercises))) or len(exercises),
                "atualizado_em": _fmt_date(_first(row, "updated_at", "created_at")),
                "video_url": _first(row, "video_url", default=""),
            }
        )
    return normalized


def _schedule_rows() -> List[Dict[str, Any]]:
    rows = _load_rows(TABLE_AGENDA)
    alunos_por_id = {row["id"]: row for row in _students()}
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        aluno_ref = alunos_por_id.get(_first(row, "aluno_id", default=""), {})
        status = _slug_status(_first(row, "status", default="pendente"))
        title = _first(row, "titulo", "nome", "title", default="Aula")
        start = _first(row, "inicio", "data_hora_inicio", "data_hora", "start_time", "starts_at", default="")
        end = _first(row, "termino", "data_hora_fim", "end_time", "ends_at", default="")
        google_calendar_url = _first(row, "google_calendar_url", default="")
        if not google_calendar_url and start:
            start_raw = str(start).replace("-", "").replace(":", "").replace("T", "").split(".")[0]
            end_raw = str(end or start).replace("-", "").replace(":", "").replace("T", "").split(".")[0]
            google_calendar_url = f"https://calendar.google.com/calendar/render?action=TEMPLATE&text={title}&dates={start_raw}/{end_raw}"
        hours = _fmt_hour_range(start, end)
        start_hour, end_hour = hours.split(" - ")
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
                "tipo": _first(row, "tipo", "category", default="Aula"),
                "observacoes": _first(row, "observacoes", "notes", default=""),
                "google_calendar_url": google_calendar_url,
            }
        )
    return normalized


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


def _assessments(aluno_id: Optional[str] = None) -> List[Dict[str, Any]]:
    rows = _load_rows(TABLE_AVALIACOES, filters={"aluno_id": aluno_id} if aluno_id else None)
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
                "data": _fmt_date(_first(row, "created_at", "data_avaliacao")),
                "observacoes": _first(row, "observacoes", default=""),
                "historico_label": f"Avaliacao {_first(row, 'numero', default='1')}",
                "status_label": metrics["classificacao"],
                "resumo": metrics["classificacao"],
                "objetivo": _first(row, "objetivo", default="Nao informado"),
            }
        )
    return normalized


def _exercises() -> List[Dict[str, Any]]:
    result = _select(TABLE_EXERCICIOS)
    if not result["ok"]:
        return []
    rows = result["data"]
    normalized: List[Dict[str, Any]] = []
    for row in rows:
        normalized.append(
            {
                **row,
                "id": row.get("id", ""),
                "nome": _first(row, "nome", "name", default="Exercicio"),
                "grupo_muscular": _first(row, "grupo_muscular", default="Nao informado"),
                "descricao": _first(row, "descricao", "description", default=""),
                "imagem_url": _first(row, "imagem_url", default=""),
            }
        )
    return normalized


def _optional_rows(table: str, *, order: Optional[str] = None, desc: bool = False) -> List[Dict[str, Any]]:
    if not _ready():
        return []
    try:
        query = _client().table(table).select("*")
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
    rows = _optional_rows(TABLE_PAGAMENTOS, order="atualizado_em", desc=True)
    if not rows:
        return [
            {
                "id": aluno["id"],
                "aluno_nome": aluno["nome"],
                "email": aluno["email"],
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
        status = _slug_status(_first(row, "status", "status_pagamento", default="pendente"))
        normalized.append(
            {
                **row,
                "id": row.get("id", ""),
                "aluno_nome": _first(row, "aluno_nome", default="Aluno"),
                "email": _first(row, "email", default=""),
                "status": status,
                "status_label": _human_status(status).upper(),
                "status_color": "paid" if status == "pago" else "pending" if status == "pendente" else "late",
                "atualizado_em": _fmt_date(_first(row, "atualizado_em", "updated_at", "created_at")) or "Sem atualizacao",
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
                "descricao": _first(row, "descricao", default=""),
                "gerenciar_url": url_for("gerenciar_plano", plano_id=row.get("id", "")),
            }
        )
    return normalized


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
        else:
            existing = _find_user_by_email(email)
            if existing["ok"] and existing["data"]:
                flash("Ja existe uma conta com esse email.", "error")
            else:
                auth_user_id = ""
                if _table_has_local_passwords():
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
                    flash(created["error"] or "Nao foi possivel criar a conta.", "error")
                else:
                    try:
                        auth_response = _client().auth.sign_up(
                            {
                                "email": email,
                                "password": senha,
                                "options": {
                                    "data": {"nome": nome, "tipo_conta": tipo_conta, "nascimento": nascimento},
                                    "email_redirect_to": url_for("login", _external=True),
                                },
                            }
                        )
                        auth_user_id = getattr(getattr(auth_response, "user", None), "id", "") or ""
                    except Exception as exc:
                        flash(f"Nao foi possivel cadastrar no Supabase Auth: {exc}", "error")
                        return render_template("Cadastro.html", **_common_brand_context())

                    profile_result = _insert(
                        TABLE_USUARIOS,
                        {
                            "auth_user_id": auth_user_id,
                            "nome": nome,
                            "email": email,
                            "tipo_conta": tipo_conta,
                            "nascimento": nascimento,
                        },
                    )
                    if profile_result["ok"]:
                        flash("Cadastro realizado. Confirme seu email no Supabase e depois faca login.", "success")
                        return redirect(url_for("login"))
                    flash(profile_result["error"] or "Conta criada no Auth, mas houve erro ao salvar o perfil.", "error")

    return render_template("Cadastro.html", **_common_brand_context())


@app.route("/login", methods=["GET", "POST"])
@app.route("/Login.html", methods=["GET", "POST"])
def login():
    if DEV_BYPASS_AUTH:
        flash("Modo teste ativo: voce entrou automaticamente sem precisar fazer login.", "info")
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "").strip()
        if not email or not senha:
            flash("Informe email e senha.", "error")
            return render_template("Login.html", **_common_brand_context())

        user_data: Optional[Dict[str, Any]] = None

        if _table_has_local_passwords():
            result = _find_user_by_email(email)
            row = result["data"] if result["ok"] else None
            if not row or not row.get("senha_hash") or not check_password_hash(row["senha_hash"], senha):
                flash("Email ou senha invalidos.", "error")
                return render_template("Login.html", **_common_brand_context())
            user_data = row
        else:
            try:
                auth_response = _client().auth.sign_in_with_password({"email": email, "password": senha})
                auth_user = getattr(auth_response, "user", None)
                result = _find_user_by_email(email)
                user_data = result["data"] if result["ok"] else None
                if not user_data:
                    created = _insert(
                        TABLE_USUARIOS,
                        {
                            "auth_user_id": getattr(auth_user, "id", ""),
                            "nome": getattr(getattr(auth_user, "user_metadata", {}), "get", lambda _k, _d="": "")("nome", "")
                            if auth_user
                            else "",
                            "email": email,
                            "tipo_conta": "Personal Trainer",
                        },
                    )
                    if created["ok"] and created["data"]:
                        user_data = created["data"][0]
                    else:
                        user_data = {"id": "", "auth_user_id": getattr(auth_user, "id", ""), "nome": email.split("@")[0], "email": email, "tipo_conta": "Personal Trainer"}
            except Exception as exc:
                flash(f"Email ou senha invalidos: {exc}", "error")
                return render_template("Login.html", **_common_brand_context())

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
    return redirect(url_for("login"))


@app.get("/dashboard")
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
        criar_treino_url=url_for("criar_treino"),
        agendar_aula_url=url_for("agenda") + "#nova-aula",
        total_avaliacoes=len(avaliacoes_lista),
        **_personal_context("dashboard"),
    )


@app.route("/alunos", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def alunos():
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return redirect(url_for("alunos"))
        payload = {
            "nome": request.form.get("nome"),
            "email": request.form.get("email"),
            "telefone": request.form.get("telefone"),
            "objetivo": request.form.get("objetivo"),
            "status": request.form.get("status"),
            "plano": request.form.get("plano"),
        }
        result = _insert(TABLE_ALUNOS, payload)
        flash("Aluno criado com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel criar o aluno."), "success" if result["ok"] else "error")
        return redirect(url_for("alunos"))

    search = request.args.get("busca", "").strip().lower()
    alunos_lista = _students()
    if search:
        alunos_lista = [aluno for aluno in alunos_lista if search in aluno["nome"].lower() or search in aluno["email"].lower()]
    return render_template(
        "alunos.html",
        alunos=alunos_lista,
        busca=search,
        filtros={"busca": search, "status": request.args.get("status", "")},
        total_alunos=len(alunos_lista),
        criar_aluno_url=url_for("alunos"),
        excluir_aluno_base_url="/alunos",
        editar_aluno_base_url="/alunos",
        detalhes_aluno_base_url="/alunos",
        csrf_form_token=_csrf_token,
        **_personal_context("alunos"),
    )


@app.get("/alunos/<aluno_id>")
@login_required
def aluno_perfil(aluno_id: str):
    return redirect(url_for("avaliacoes", aluno_id=aluno_id))


@app.post("/alunos/<aluno_id>/excluir")
@login_required
def excluir_aluno(aluno_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
    else:
        result = _delete(TABLE_ALUNOS, aluno_id)
        flash("Aluno excluido com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel excluir o aluno."), "success" if result["ok"] else "error")
    return redirect(url_for("alunos"))


@app.get("/treinos")
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def treinos():
    alunos_lista = _students()
    aluno_id = request.args.get("aluno_id", "")
    treino_edicao_id = request.args.get("editar_treino_id", "")
    treino_exclusao_id = request.args.get("excluir_treino_id", "")
    treinos_lista = _trainings(aluno_id or None)
    aluno_selecionado = next((aluno for aluno in alunos_lista if aluno["id"] == aluno_id), alunos_lista[0] if alunos_lista else None)
    if aluno_selecionado and not aluno_id:
        treinos_lista = _trainings(aluno_selecionado["id"])
    treino_edicao = next((treino for treino in treinos_lista if treino["id"] == treino_edicao_id), {})
    treino_exclusao = next((treino for treino in treinos_lista if treino["id"] == treino_exclusao_id), {})
    return render_template(
        "treinos.html",
        alunos=alunos_lista,
        aluno_selecionado=aluno_selecionado,
        treinos=treinos_lista,
        treino_edicao=treino_edicao,
        treino_exclusao=treino_exclusao,
        url_treinos_aluno_base="/treinos/aluno",
        visualizar_treino_base="/treinos",
        criar_treino_url=url_for("criar_treino"),
        editar_treino_base="/treinos/editar",
        excluir_treino_base="/treinos/excluir",
        csrf_form_token=_csrf_token,
        **_personal_context("treinos"),
    )


@app.get("/treinos/aluno/<aluno_id>")
@login_required
def treinos_aluno(aluno_id: str):
    return redirect(url_for("treinos", aluno_id=aluno_id))


@app.get("/treinos/<treino_id>")
@login_required
def visualizar_treino(treino_id: str):
    treino = next((item for item in _trainings() if item["id"] == treino_id), None)
    if not treino:
        flash("Treino nao encontrado.", "error")
        return redirect(url_for("treinos"))
    return redirect(url_for("treinos", aluno_id=treino.get("aluno_id", ""), editar_treino_id=treino_id))


@app.post("/treinos/novo")
@login_required
def criar_treino():
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("treinos"))
    result = _insert(
        TABLE_TREINOS,
        {
            "nome": request.form.get("nome"),
            "aluno_id": request.form.get("aluno_id"),
            "exercicios_raw": request.form.get("exercicios_raw"),
            "observacoes": request.form.get("observacoes"),
            "status": "ativo",
        },
    )
    flash("Treino criado com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel criar o treino."), "success" if result["ok"] else "error")
    return redirect(request.form.get("origem_url") or url_for("treinos", aluno_id=request.form.get("aluno_id", "")))


@app.post("/treinos/editar/<treino_id>")
@login_required
def editar_treino(treino_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("treinos"))
    result = _update(
        TABLE_TREINOS,
        treino_id,
        {
            "nome": request.form.get("nome"),
            "aluno_id": request.form.get("aluno_id"),
            "exercicios_raw": request.form.get("exercicios_raw"),
            "observacoes": request.form.get("observacoes"),
        },
    )
    flash("Treino atualizado com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel atualizar o treino."), "success" if result["ok"] else "error")
    return redirect(url_for("treinos", aluno_id=request.form.get("aluno_id", "")))


@app.post("/treinos/excluir/<treino_id>")
@login_required
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
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def agenda():
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return redirect(url_for("agenda"))
        aluno_id = request.form.get("aluno_id")
        aluno = next((item for item in _students() if item["id"] == aluno_id), None)
        payload = {
            "titulo": request.form.get("titulo"),
            "aluno_id": aluno_id,
            "aluno_nome": aluno["nome"] if aluno else "",
            "inicio": request.form.get("inicio"),
            "termino": request.form.get("termino"),
            "observacoes": request.form.get("observacoes"),
            "status": "agendado",
        }
        result = _insert(TABLE_AGENDA, payload)
        flash("Aula agendada com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel agendar a aula."), "success" if result["ok"] else "error")
        return redirect(url_for("agenda"))

    compromissos = _schedule_rows()
    for compromisso in compromissos:
        compromisso["pode_cancelar"] = compromisso["status_classe"] in {"agendado", "confirmado", "pendente"}
    total_compromissos = len([item for item in compromissos if item["status_classe"] != "cancelado"])
    return render_template(
        "agenda.html",
        compromissos=compromissos,
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


@app.post("/agenda/confirmar/<agenda_id>")
@login_required
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
def cancelar_agenda(agenda_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
    else:
        result = _update(TABLE_AGENDA, agenda_id, {"status": "cancelado"})
        flash("Aula cancelada." if result["ok"] else (result["error"] or "Nao foi possivel cancelar a aula."), "success" if result["ok"] else "error")
    return redirect(url_for("agenda"))


@app.route("/avaliacoes", methods=["GET", "POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def avaliacoes():
    if request.method == "POST":
        csrf_error = _require_csrf()
        if csrf_error:
            flash(csrf_error, "error")
            return redirect(url_for("avaliacoes"))
        aluno_id = request.form.get("aluno_id")
        aluno = next((item for item in _students() if item["id"] == aluno_id), None)
        payload = {
            "aluno_id": aluno_id,
            "aluno_nome": aluno["nome"] if aluno else "",
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
            "observacoes": request.form.get("observacoes"),
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


@app.route("/evolucao", methods=["GET", "POST"])
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
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def observacoes():
    alunos_lista = _students()
    aluno_id = request.values.get("aluno_id", "")
    aluno_ativo = next((item for item in alunos_lista if item["id"] == aluno_id), alunos_lista[0] if alunos_lista else None)
    observacao = {}
    if aluno_ativo:
        result = _select_first_by(TABLE_OBSERVACOES, "aluno_id", aluno_ativo["id"])
        if result["ok"] and result["data"]:
            observacao = result["data"]
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
        existing = _select_first_by(TABLE_OBSERVACOES, "aluno_id", request.form.get("aluno_id"))
        if existing["ok"] and existing["data"]:
            result = _update(TABLE_OBSERVACOES, existing["data"]["id"], payload)
        else:
            result = _insert(TABLE_OBSERVACOES, payload)
        flash("Observacao salva com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel salvar a observacao."), "success" if result["ok"] else "error")
        return redirect(url_for("observacoes", aluno_id=request.form.get("aluno_id", "")))

    return render_template(
        "observacoes.html",
        alunos=alunos_lista,
        aluno_ativo=aluno_ativo,
        observacao=observacao,
        historico=[
            {
                **observacao,
                "data": _fmt_date(_first(observacao, "updated_at", "created_at")),
                "hora": _fmt_datetime(_first(observacao, "updated_at", "created_at"))[-5:] if _first(observacao, "updated_at", "created_at") else "",
                "aluno_nome": aluno_ativo["nome"] if aluno_ativo else "Aluno",
                "observacao_transcrita": _first(observacao, "observacao_transcrita", "observacao", default=""),
            }
        ] if observacao else [],
        aluno_id_selecionado=aluno_ativo["id"] if aluno_ativo else "",
        form={
            "foco_treino": _first(observacao, "foco_treino", default=""),
            "observacao_transcrita": _first(observacao, "observacao_transcrita", "observacao", default=""),
            "proximo_ajuste": _first(observacao, "proximo_ajuste", default=""),
        },
        salvar_observacao_url=url_for("observacoes"),
        csrf_form_token=_csrf_token,
        **_personal_context("observacoes"),
    )


@app.route("/anamnese", methods=["GET", "POST"])
@app.route("/anamnese/salvar", methods=["POST"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def anamnese():
    alunos_lista = _students()
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
        flash("Anamnese salva com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel salvar a anamnese."), "success" if result["ok"] else "error")
        return redirect(url_for("anamnese", aluno_id=request.form.get("aluno_id", "")))

    return render_template(
        "anamnese.html",
        alunos=alunos_lista,
        aluno_ativo=aluno_ativo,
        anamnese=anamnese_atual,
        buscar_anamnese_url=url_for("anamnese"),
        salvar_anamnese_url=url_for("anamnese"),
        csrf_form_token=_csrf_token,
        **_personal_context("anamnese"),
    )


@app.route("/exercicios", methods=["GET"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def exercicios():
    return render_template(
        "exercicios.html",
        exercicios=_exercises(),
        busca=request.args.get("busca", ""),
        exercicio_edicao={},
        salvar_exercicio_url=url_for("salvar_exercicio"),
        editar_exercicio_url_base="/exercicios/editar",
        excluir_exercicio_url_base="/exercicios/excluir",
        csrf_form_token=_csrf_token,
        **_personal_context("exercicios"),
    )


@app.post("/exercicios/salvar")
@login_required
def salvar_exercicio():
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("exercicios"))
    exercicio_id = request.form.get("exercicio_id", "")
    payload = {
        "nome": request.form.get("nome"),
        "grupo_muscular": request.form.get("grupo_muscular"),
        "descricao": request.form.get("descricao"),
        "imagem_url": request.form.get("imagem_url"),
        "video_url": request.form.get("video_url"),
    }
    result = _update(TABLE_EXERCICIOS, exercicio_id, payload) if exercicio_id else _insert(TABLE_EXERCICIOS, payload)
    flash("Exercicio salvo com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel salvar o exercicio."), "success" if result["ok"] else "error")
    return redirect(url_for("exercicios"))


@app.post("/exercicios/excluir/<exercicio_id>")
@login_required
def excluir_exercicio(exercicio_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
    else:
        result = _delete(TABLE_EXERCICIOS, exercicio_id)
        flash("Exercicio excluido com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel excluir o exercicio."), "success" if result["ok"] else "error")
    return redirect(url_for("exercicios"))


@app.route("/mensagens", methods=["GET"])
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
    flash("Mensagem enviada." if result["ok"] else (result["error"] or "Nao foi possivel enviar a mensagem."), "success" if result["ok"] else "error")
    return redirect(url_for("mensagens", contato_id=request.form.get("contato_id", "")))


@app.route("/financeiro", methods=["GET"])
@login_required
@role_required("Personal Trainer", "Admin", "Professor")
def financeiro():
    pagamentos = _payment_rows()
    planos = _plans()
    receita = sum(_to_float(_first(item, "valor", default=0)) or 0 for item in pagamentos if item.get("status") == "pago")
    return render_template(
        "financeiro.html",
        pagamentos=pagamentos,
        planos=planos,
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
def alterar_status_pagamento(pagamento_id: str):
    csrf_error = _require_csrf()
    if csrf_error:
        flash(csrf_error, "error")
        return redirect(url_for("financeiro"))
    status = _slug_status(request.form.get("status_pagamento", "pendente"))
    result = _update(TABLE_PAGAMENTOS, pagamento_id, {"status": status, "atualizado_em": datetime.utcnow().isoformat()})
    flash("Status alterado com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel alterar o status."), "success" if result["ok"] else "error")
    return redirect(url_for("financeiro"))


@app.post("/financeiro/planos")
@login_required
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
    flash("Plano criado com sucesso." if result["ok"] else (result["error"] or "Nao foi possivel criar o plano."), "success" if result["ok"] else "error")
    return redirect(url_for("financeiro"))


@app.get("/financeiro/planos/<plano_id>")
@login_required
def gerenciar_plano(plano_id: str):
    return redirect(url_for("financeiro"))


@app.route("/agenda-aluno")
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


@app.post("/agenda/marcar")
@login_required
@role_required("Aluno")
def marcar_aula_aluno():
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
            "aluno_nome": aluno.get("nome"),
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
    result = _update(TABLE_AGENDA, agenda_id, {"aluno_id": None, "aluno_nome": None, "status": "disponivel"})
    flash("Agendamento cancelado." if result["ok"] else (result["error"] or "Nao foi possivel cancelar o agendamento."), "success" if result["ok"] else "error")
    return redirect(url_for("agenda_aluno"))


@app.get("/aluno/dashboard")
@login_required
@role_required("Aluno")
def aluno_dashboard():
    aluno = _current_student_row() or {}
    treinos_lista = _trainings(aluno.get("id"))
    avaliacoes_lista = _assessments(aluno.get("id"))
    treino_do_dia = treinos_lista[0] if treinos_lista else {}
    if treino_do_dia:
        treino_do_dia["exercicio_destaque"] = treino_do_dia.get("exercicios_lista", [{}])[0].get("nome", "Exercicio principal") if treino_do_dia.get("exercicios_lista") else "Exercicio principal"
        treino_do_dia["prescricao"] = treino_do_dia.get("observacoes") or "Consulte os detalhes para iniciar."
    return render_template(
        "aluno_dashboard.html",
        treino_do_dia=treino_do_dia,
        total_checkins=len([item for item in _schedule_rows() if item.get("aluno_id") == aluno.get("id") and item["status"] == "concluido"]),
        total_avaliacoes=len(avaliacoes_lista),
        iniciar_treino_url=url_for("aluno_treino_execucao", treino_id=treino_do_dia.get("id", "")) if treino_do_dia else url_for("aluno_meu_treino"),
        **_student_context("dashboard"),
    )


@app.get("/aluno/treinos")
@app.get("/aluno/meu-treino")
@login_required
@role_required("Aluno")
def aluno_meu_treino():
    aluno = _current_student_row() or {}
    treinos_lista = _trainings(aluno.get("id"))
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
        **_student_context("meu_treino"),
    )


@app.get("/aluno/treino/<treino_id>/execucao")
@login_required
@role_required("Aluno")
def aluno_treino_execucao(treino_id: str):
    aluno = _current_student_row() or {}
    treinos_lista = _trainings(aluno.get("id"))
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
        concluir_treino_destino=url_for("concluir_treino_execucao", treino_id=treino_id),
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
    result = _update(TABLE_TREINOS, treino_id, {"status": "concluido"})
    flash("Treino concluido." if result["ok"] else (result["error"] or "Nao foi possivel concluir o treino."), "success" if result["ok"] else "error")
    return redirect(url_for("aluno_meu_treino", treino_id=treino_id))


@app.route("/aluno/mensagens", methods=["GET"])
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
    flash("Mensagem enviada." if result["ok"] else (result["error"] or "Nao foi possivel enviar a mensagem."), "success" if result["ok"] else "error")
    return redirect(url_for("aluno_mensagens", contato_id=request.form.get("contato_id", "")))


@app.get("/evolucao-aluno")
@app.get("/aluno/evolucao")
@login_required
@role_required("Aluno")
def evolucao_aluno():
    aluno = _current_student_row() or {}
    historico = _assessments(aluno.get("id"))
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
        **_student_context("evolucao"),
    )


@app.get("/configuracoes")
@login_required
def configuracoes():
    flash("Tela de configuracoes ainda nao foi separada. Voce foi redirecionado ao dashboard.", "info")
    role = str(session.get("user_role", "")).strip().lower()
    return redirect(url_for("aluno_dashboard" if role == "aluno" else "dashboard"))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=DEFAULT_PORT, debug=True)
