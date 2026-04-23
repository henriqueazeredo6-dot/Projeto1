import json
import os
import secrets
from datetime import datetime
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from supabase import Client, create_client

load_dotenv()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, "templates"),
    static_folder=os.path.join(BASE_DIR, "static"),
)
app.config["SECRET_KEY"] = os.getenv("FLASK_SECRET_KEY", "confie-dev-secret")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY") or os.getenv("SUPABASE_KEY", "")

TABLE_ALUNOS = os.getenv("SUPABASE_TABLE_ALUNOS", "tb_aluno")
TABLE_EXERCICIOS = os.getenv("SUPABASE_TABLE_EXERCICIOS", "tb_exercicio")
TABLE_TREINOS = os.getenv("SUPABASE_TABLE_TREINOS", "tb_treino")
TABLE_AGENDA = os.getenv("SUPABASE_TABLE_AGENDA", "tb_agenda")
TABLE_AVALIACOES = os.getenv("SUPABASE_TABLE_AVALIACOES", "tb_avaliacao")
TABLE_MENSAGENS = os.getenv("SUPABASE_TABLE_MENSAGENS", "tb_mensagem")
TABLE_USUARIOS = os.getenv("SUPABASE_TABLE_USUARIOS", "tb_usuario")

supabase: Optional[Client] = None
if SUPABASE_URL and SUPABASE_KEY:
    supabase = create_client(SUPABASE_URL, SUPABASE_KEY)


def _is_ready() -> bool:
    return supabase is not None


def _clean_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in payload.items() if v is not None and v != ""}


def _run_query(operation) -> Dict[str, Any]:
    if not _is_ready():
        return {"ok": False, "data": [], "error": "Supabase nao configurado."}
    try:
        response = operation()
        return {"ok": True, "data": response.data or [], "error": None}
    except Exception as exc:
        app.logger.exception("Erro no Supabase")
        return {"ok": False, "data": [], "error": str(exc)}


def _select(table: str, *, filters: Optional[Dict[str, Any]] = None, order: str = "created_at", desc: bool = True):
    def _op():
        query = supabase.table(table).select("*")
        if filters:
            for key, value in filters.items():
                query = query.eq(key, value)
        query = query.order(order, desc=desc)
        return query.execute()

    return _run_query(_op)


def _select_one(table: str, row_id: str):
    def _op():
        return supabase.table(table).select("*").eq("id", row_id).limit(1).execute()

    result = _run_query(_op)
    if not result["ok"]:
        return result
    result["data"] = result["data"][0] if result["data"] else None
    return result


def _insert(table: str, payload: Dict[str, Any]):
    payload = _clean_payload(payload)

    def _op():
        return supabase.table(table).insert(payload).execute()

    return _run_query(_op)


def _update(table: str, row_id: str, payload: Dict[str, Any]):
    payload = _clean_payload(payload)

    def _op():
        return supabase.table(table).update(payload).eq("id", row_id).execute()

    return _run_query(_op)


def _delete(table: str, row_id: str):
    def _op():
        return supabase.table(table).delete().eq("id", row_id).execute()

    return _run_query(_op)


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
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_local_to_iso(value: str) -> Optional[str]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
        return dt.isoformat()
    except ValueError:
        return None


def _format_date(value: str) -> str:
    if not value:
        return ""
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%d/%m/%Y")
    except ValueError:
        return value


def _format_time(value: str) -> str:
    if not value:
        return "--:--"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.strftime("%H:%M")
    except ValueError:
        return value


def _classificacao_imc(imc: Optional[float]) -> str:
    if imc is None:
        return "Nao classificado"
    if imc < 18.5:
        return "Abaixo do peso"
    if imc < 25:
        return "Peso normal"
    if imc < 30:
        return "Sobrepeso"
    return "Obesidade"


def _ensure_form_token(scope: str) -> str:
    key = f"csrf_{scope}"
    token = session.get(key)
    if not token:
        token = secrets.token_urlsafe(24)
        session[key] = token
    return token


def _is_valid_form_token(scope: str, token: str) -> bool:
    if not token:
        return False
    return session.get(f"csrf_{scope}") == token


def _parse_exercicios_raw(raw: str) -> List[Dict[str, str]]:
    if not raw:
        return []
    items: List[Dict[str, str]] = []
    normalized = raw.replace("\n", ",")
    for chunk in normalized.split(","):
        line = chunk.strip()
        if not line:
            continue
        if "|" in line:
            nome, prescricao = line.split("|", 1)
            items.append({"nome": nome.strip(), "prescricao": prescricao.strip()})
        else:
            items.append({"nome": line, "prescricao": "--"})
    return items


def _normalize_treino(row: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(row)
    exercicios = data.get("exercicios")
    exercicios_raw = data.get("exercicios_raw")

    if isinstance(exercicios, str):
        try:
            exercicios = json.loads(exercicios)
        except json.JSONDecodeError:
            exercicios = None

    if not isinstance(exercicios, list):
        exercicios = _parse_exercicios_raw(exercicios_raw or "")

    if not exercicios_raw and exercicios:
        exercicios_raw = ", ".join(
            [f"{item.get('nome', '')} | {item.get('prescricao', '--')}" for item in exercicios]
        )

    data["exercicios"] = exercicios
    data["exercicios_raw"] = exercicios_raw or ""
    return data


def _normalize_agenda(row: Dict[str, Any]) -> Dict[str, Any]:
    data = dict(row)
    status = (data.get("status") or "pendente").lower()
    data["status"] = status
    data["status_classe"] = status
    data["inicio"] = _format_time(data.get("inicio", ""))
    data["termino"] = _format_time(data.get("termino", ""))
    return data


def _medidas_avaliacao(avaliacao: Dict[str, Any]) -> List[Dict[str, str]]:
    labels = {
        "tricipital": "Tricipital",
        "subscapular": "Subscapular",
        "suprailiaca": "Suprailiaca",
        "abdominal": "Abdominal",
        "peitoral": "Peitoral",
        "coxa": "Coxa",
        "perna": "Perna",
        "braco_direito": "Braco direito",
        "peitoral_circ": "Peitoral circ.",
        "cintura": "Cintura",
        "quadril": "Quadril",
        "coxa_direita": "Coxa direita",
        "perna_direita": "Perna direita",
    }

    medidas: List[Dict[str, str]] = []
    for key, label in labels.items():
        value = avaliacao.get(key)
        if value not in (None, ""):
            medidas.append({"nome": label, "valor": str(value)})
    return medidas


def _render_dashboard_context() -> Dict[str, Any]:
    alunos_result = _select(TABLE_ALUNOS)
    agenda_result = _select(TABLE_AGENDA)
    treinos_result = _select(TABLE_TREINOS)

    alunos = alunos_result["data"] if alunos_result["ok"] else []
    compromissos = [_normalize_agenda(item) for item in (agenda_result["data"] if agenda_result["ok"] else [])]
    treinos = [_normalize_treino(item) for item in (treinos_result["data"] if treinos_result["ok"] else [])]

    return {
        "pagina_ativa": "dashboard",
        "total_alunos": len(alunos),
        "total_treinos": len(treinos),
        "total_compromissos": len(compromissos),
        "compromissos": compromissos[:5],
    }


@app.route("/")
def index():
    planos = [
        {
            "nome": "Essencial",
            "preco": "R$ 49",
            "periodo": "/mes",
            "beneficios": ["Ate 20 alunos", "Agenda basica", "Suporte por email"],
            "popular": False,
            "url": "/cadastro",
        },
        {
            "nome": "Pro",
            "preco": "R$ 99",
            "periodo": "/mes",
            "beneficios": ["Alunos ilimitados", "Treinos completos", "Relatorios de evolucao"],
            "popular": True,
            "badge": "Mais vendido",
            "url": "/cadastro",
        },
    ]
    return render_template("index.html", planos=planos)


@app.route("/health")
def health():
    return jsonify({"status": "ok", "supabase": _is_ready()})


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "GET" and session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        if not email or not senha:
            flash("Informe email e senha.", "error")
            return redirect(url_for("login"))

        if not _is_ready():
            flash("Configure SUPABASE_URL e SUPABASE_KEY no .env.", "error")
            return redirect(url_for("login"))

        try:
            auth_result = supabase.auth.sign_in_with_password({"email": email, "password": senha})
            user = getattr(auth_result, "user", None)
            if not user:
                flash("Nao foi possivel autenticar.", "error")
                return redirect(url_for("login"))
            session["user_id"] = user.id
            session["user_email"] = user.email
            flash("Login realizado com sucesso.", "success")
            return redirect(url_for("dashboard"))
        except Exception as exc:
            error_text = str(exc)
            error_text_lower = error_text.lower()
            if "email not confirmed" in error_text_lower:
                flash("Seu email ainda nao foi confirmado no Supabase. Confirme o email e tente novamente.", "error")
            elif "invalid login credentials" in error_text_lower:
                flash("Email ou senha invalidos. Se voce acabou de se cadastrar, confirme o email antes de entrar.", "error")
            else:
                flash(f"Falha no login: {error_text}", "error")
            return redirect(url_for("login"))

    return render_template("Login.html")


@app.route("/login/reenviar-confirmacao", methods=["POST"])
def reenviar_confirmacao():
    email = request.form.get("email", "").strip().lower()
    if not email:
        flash("Informe seu email para reenviar a confirmacao.", "error")
        return redirect(url_for("login"))

    if not _is_ready():
        flash("Configure SUPABASE_URL e SUPABASE_KEY no .env.", "error")
        return redirect(url_for("login"))

    try:
        supabase.auth.resend({"type": "signup", "email": email})
        flash("Se o email existir, enviamos um novo link de confirmacao. Verifique caixa de spam/lixo.", "success")
    except Exception as exc:
        flash(f"Nao foi possivel reenviar a confirmacao: {exc}", "error")
    return redirect(url_for("login"))


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("Sessao encerrada.", "success")
    return redirect(url_for("login"))


@app.route("/logout", methods=["GET"])
def logout_get():
    session.clear()
    return redirect(url_for("login"))


@app.route("/cadastro", methods=["GET", "POST"])
def cadastro():
    if request.method == "POST":
        nome = request.form.get("nome", "").strip()
        email = request.form.get("email", "").strip().lower()
        senha = request.form.get("senha", "")
        confirmar = request.form.get("confirmar_senha") or request.form.get("confirmar-senha")
        tipo_conta = request.form.get("tipo_conta") or request.form.get("tipo-conta") or "Personal Trainer"
        nascimento = request.form.get("nascimento", "")

        if not nome or not email or not senha:
            flash("Preencha os campos obrigatorios.", "error")
            return redirect(url_for("cadastro"))

        if senha != confirmar:
            flash("As senhas nao conferem.", "error")
            return redirect(url_for("cadastro"))

        if not _is_ready():
            flash("Configure SUPABASE_URL e SUPABASE_KEY no .env.", "error")
            return redirect(url_for("cadastro"))

        try:
            needs_email_confirmation = False
            if os.getenv("SUPABASE_SERVICE_KEY"):
                auth_result = supabase.auth.admin.create_user(
                    {
                        "email": email,
                        "password": senha,
                        "email_confirm": True,
                    }
                )
            else:
                auth_result = supabase.auth.sign_up({"email": email, "password": senha})
                needs_email_confirmation = True
            user = getattr(auth_result, "user", None)
            user_id = user.id if user else None

            _insert(
                TABLE_USUARIOS,
                {
                    "auth_user_id": user_id,
                    "nome": nome,
                    "email": email,
                    "tipo_conta": tipo_conta,
                    "nascimento": nascimento,
                },
            )
            if needs_email_confirmation:
                flash("Cadastro realizado. Verifique seu email para confirmar a conta antes de fazer login.", "success")
            else:
                flash("Cadastro realizado. Agora faca login.", "success")
            return redirect(url_for("login"))
        except Exception as exc:
            flash(f"Falha no cadastro: {exc}", "error")
            return redirect(url_for("cadastro"))

    return render_template("Cadastro.html")


@app.route("/dashboard")
def dashboard():
    context = _render_dashboard_context()
    return render_template("dashboard.html", **context)


@app.route("/alunos", methods=["GET", "POST"])
def alunos():
    if request.method == "POST":
        payload = {
            "nome": request.form.get("nome"),
            "email": request.form.get("email"),
            "telefone": request.form.get("telefone"),
            "objetivo": request.form.get("objetivo"),
            "status": request.form.get("status", "ativo"),
            "plano": request.form.get("plano", "mensal"),
        }

        aluno_result = _insert(TABLE_ALUNOS, payload)
        if not aluno_result["ok"]:
            flash(f"Erro ao cadastrar aluno: {aluno_result['error']}", "error")
        else:
            flash("Aluno cadastrado com sucesso.", "success")

            email = (request.form.get("email") or "").strip().lower()
            senha = request.form.get("senha")
            if email and senha and _is_ready():
                try:
                    supabase.auth.sign_up({"email": email, "password": senha})
                except Exception:
                    app.logger.warning("Nao foi possivel criar usuario auth para o aluno %s", email)

        return redirect(url_for("alunos"))

    busca = (request.args.get("busca") or "").strip().lower()
    status = (request.args.get("status") or "").strip().lower()

    result = _select(TABLE_ALUNOS)
    alunos_data = result["data"] if result["ok"] else []

    if busca:
        alunos_data = [
            aluno
            for aluno in alunos_data
            if busca in str(aluno.get("nome", "")).lower() or busca in str(aluno.get("email", "")).lower()
        ]

    if status:
        alunos_data = [aluno for aluno in alunos_data if str(aluno.get("status", "")).lower() == status]

    context = {
        "pagina_ativa": "alunos",
        "alunos": alunos_data,
        "total_alunos": len(alunos_data),
        "filtros": {"busca": busca, "status": status},
    }
    return render_template("alunos.html", **context)


@app.route("/alunos/<aluno_id>")
def aluno_perfil(aluno_id: str):
    return redirect(url_for("evolucao", aluno_id=aluno_id))


@app.route("/alunos/<aluno_id>/editar", methods=["POST", "GET"])
def editar_aluno(aluno_id: str):
    if request.method == "POST":
        payload = {
            "nome": request.form.get("nome"),
            "email": request.form.get("email"),
            "telefone": request.form.get("telefone"),
            "objetivo": request.form.get("objetivo"),
            "status": request.form.get("status"),
            "plano": request.form.get("plano"),
        }
        result = _update(TABLE_ALUNOS, aluno_id, payload)
        if result["ok"]:
            flash("Aluno atualizado.", "success")
        else:
            flash(f"Erro ao atualizar aluno: {result['error']}", "error")
        return redirect(url_for("alunos"))

    result = _select_one(TABLE_ALUNOS, aluno_id)
    if not result["ok"] or not result["data"]:
        flash("Aluno nao encontrado.", "error")
        return redirect(url_for("alunos"))
    return jsonify(result["data"])


@app.route("/alunos/<aluno_id>/excluir", methods=["POST"])
def excluir_aluno(aluno_id: str):
    result = _delete(TABLE_ALUNOS, aluno_id)
    if result["ok"]:
        flash("Aluno removido.", "success")
    else:
        flash(f"Erro ao remover aluno: {result['error']}", "error")
    return redirect(url_for("alunos"))


@app.route("/exercicios", methods=["GET", "POST"])
def exercicios():
    if request.method == "POST":
        payload = {
            "nome": request.form.get("nome"),
            "grupo_muscular": request.form.get("grupo_muscular"),
            "dificuldade": request.form.get("dificuldade"),
            "descricao": request.form.get("descricao"),
            "url_video": request.form.get("url_video"),
            "url_imagem": request.form.get("url_imagem"),
            "status": request.form.get("status", "ativo"),
        }
        result = _insert(TABLE_EXERCICIOS, payload)
        if result["ok"]:
            flash("Exercicio cadastrado com sucesso.", "success")
        else:
            flash(f"Erro ao cadastrar exercicio: {result['error']}", "error")
        return redirect(url_for("exercicios"))

    busca = (request.args.get("busca") or "").strip().lower()
    grupo = (request.args.get("grupo") or "").strip().lower()
    dificuldade = (request.args.get("dificuldade") or "").strip().lower()

    result = _select(TABLE_EXERCICIOS)
    exercicios_data = result["data"] if result["ok"] else []

    if busca:
        exercicios_data = [
            item
            for item in exercicios_data
            if busca in str(item.get("nome", "")).lower()
            or busca in str(item.get("grupo_muscular", "")).lower()
            or busca in str(item.get("descricao", "")).lower()
        ]

    if grupo:
        exercicios_data = [
            item for item in exercicios_data if str(item.get("grupo_muscular", "")).lower() == grupo
        ]

    if dificuldade:
        exercicios_data = [
            item for item in exercicios_data if str(item.get("dificuldade", "")).lower() == dificuldade
        ]

    return render_template(
        "exercicios.html",
        pagina_ativa="exercicios",
        exercicios=exercicios_data,
        total_exercicios=len(exercicios_data),
        filtros={"busca": busca, "grupo": grupo, "dificuldade": dificuldade},
    )


@app.route("/exercicios/<exercicio_id>/editar", methods=["POST", "GET"])
def editar_exercicio(exercicio_id: str):
    if request.method == "POST":
        payload = {
            "nome": request.form.get("nome"),
            "grupo_muscular": request.form.get("grupo_muscular"),
            "dificuldade": request.form.get("dificuldade"),
            "descricao": request.form.get("descricao"),
            "url_video": request.form.get("url_video"),
            "url_imagem": request.form.get("url_imagem"),
            "status": request.form.get("status"),
        }
        result = _update(TABLE_EXERCICIOS, exercicio_id, payload)
        if result["ok"]:
            flash("Exercicio atualizado.", "success")
        else:
            flash(f"Erro ao atualizar exercicio: {result['error']}", "error")
        return redirect(url_for("exercicios"))

    result = _select_one(TABLE_EXERCICIOS, exercicio_id)
    if not result["ok"] or not result["data"]:
        flash("Exercicio nao encontrado.", "error")
        return redirect(url_for("exercicios"))
    return jsonify(result["data"])


@app.route("/exercicios/<exercicio_id>/excluir", methods=["POST"])
def excluir_exercicio(exercicio_id: str):
    result = _delete(TABLE_EXERCICIOS, exercicio_id)
    if result["ok"]:
        flash("Exercicio removido.", "success")
    else:
        flash(f"Erro ao remover exercicio: {result['error']}", "error")
    return redirect(url_for("exercicios"))


@app.route("/mensagens")
def mensagens():
    contato_id = request.args.get("contato_id")
    alunos_result = _select(TABLE_ALUNOS)
    contatos_raw = alunos_result["data"] if alunos_result["ok"] else []

    contatos = [
        {
            "id": contato.get("id"),
            "nome": contato.get("nome") or "Aluno",
            "email": contato.get("email") or "Sem email",
        }
        for contato in contatos_raw
    ]

    conversa_ativa = None
    if contato_id:
        conversa_ativa = next((item for item in contatos if str(item.get("id")) == str(contato_id)), None)
    if not conversa_ativa and contatos:
        conversa_ativa = contatos[0]

    mensagens_lista: List[Dict[str, Any]] = []
    if conversa_ativa and conversa_ativa.get("id"):
        mensagens_result = _select(
            TABLE_MENSAGENS,
            filters={"aluno_id": conversa_ativa["id"]},
            order="created_at",
            desc=False,
        )
        mensagens_raw = mensagens_result["data"] if mensagens_result["ok"] else []
        for item in mensagens_raw:
            remetente = item.get("remetente") or "aluno"
            autor = item.get("autor") or ("Voce" if remetente == "profissional" else conversa_ativa["nome"])
            mensagens_lista.append(
                {
                    "id": item.get("id"),
                    "remetente": remetente,
                    "autor": autor,
                    "texto": item.get("texto") or "",
                    "horario": _format_time(item.get("created_at") or ""),
                }
            )

    return render_template(
        "mensagens.html",
        pagina_ativa="mensagens",
        logo_nome="CONFIE Personal",
        profissional_nome=session.get("user_email", "Personal Trainer"),
        contatos=contatos,
        conversa_ativa=conversa_ativa or {},
        mensagens=mensagens_lista,
        csrf_token=_ensure_form_token("mensagens"),
    )


@app.route("/mensagens/enviar", methods=["POST"])
def enviar_mensagem():
    contato_id = (request.form.get("contato_id") or "").strip()
    texto = (request.form.get("mensagem") or "").strip()
    csrf_token = request.form.get("csrf_token", "")

    if not _is_valid_form_token("mensagens", csrf_token):
        flash("Falha de seguranca no envio. Atualize a pagina e tente novamente.", "error")
        return redirect(url_for("mensagens", contato_id=contato_id))

    if not contato_id:
        flash("Selecione um contato para enviar a mensagem.", "error")
        return redirect(url_for("mensagens"))

    if not texto:
        flash("Digite uma mensagem antes de enviar.", "error")
        return redirect(url_for("mensagens", contato_id=contato_id))

    if len(texto) > 2000:
        flash("A mensagem ultrapassa o limite de 2000 caracteres.", "error")
        return redirect(url_for("mensagens", contato_id=contato_id))

    aluno_result = _select_one(TABLE_ALUNOS, contato_id)
    if not aluno_result["ok"] or not aluno_result["data"]:
        flash("Contato invalido para envio.", "error")
        return redirect(url_for("mensagens"))

    payload = {
        "aluno_id": contato_id,
        "profissional_id": request.form.get("profissional_id") or session.get("user_id"),
        "remetente": "profissional",
        "autor": session.get("user_email", "Personal Trainer"),
        "texto": texto,
        "canal": request.form.get("canal") or "painel",
    }
    result = _insert(TABLE_MENSAGENS, payload)
    if result["ok"]:
        flash("Mensagem enviada.", "success")
    else:
        flash(f"Erro ao enviar mensagem: {result['error']}", "error")

    return redirect(url_for("mensagens", contato_id=contato_id))


@app.route("/treinos")
def treinos():
    aluno_id = request.args.get("aluno_id")
    editar_treino_id = request.args.get("editar_treino_id")
    excluir_treino_id = request.args.get("excluir_treino_id")

    alunos_result = _select(TABLE_ALUNOS)
    alunos_data = alunos_result["data"] if alunos_result["ok"] else []

    treinos_filters = {"aluno_id": aluno_id} if aluno_id else None
    treinos_result = _select(TABLE_TREINOS, filters=treinos_filters)
    treinos_data = [_normalize_treino(item) for item in (treinos_result["data"] if treinos_result["ok"] else [])]

    aluno_selecionado = None
    if aluno_id:
        aluno_selecionado = next((item for item in alunos_data if str(item.get("id")) == str(aluno_id)), None)

    treino_edicao = None
    if editar_treino_id:
        edit_result = _select_one(TABLE_TREINOS, editar_treino_id)
        treino_edicao = _normalize_treino(edit_result["data"]) if edit_result["ok"] and edit_result["data"] else None

    treino_exclusao = None
    if excluir_treino_id:
        del_result = _select_one(TABLE_TREINOS, excluir_treino_id)
        treino_exclusao = _normalize_treino(del_result["data"]) if del_result["ok"] and del_result["data"] else None

    return render_template(
        "treinos.html",
        pagina_ativa="treinos",
        alunos=alunos_data,
        aluno_selecionado=aluno_selecionado,
        treinos=treinos_data,
        treino_edicao=treino_edicao,
        treino_exclusao=treino_exclusao,
    )


@app.route("/treinos/aluno/<aluno_id>")
def treinos_aluno(aluno_id: str):
    return redirect(url_for("treinos", aluno_id=aluno_id))


@app.route("/treinos/<treino_id>")
def visualizar_treino(treino_id: str):
    result = _select_one(TABLE_TREINOS, treino_id)
    if not result["ok"] or not result["data"]:
        return jsonify({"error": "Treino nao encontrado"}), 404
    return jsonify(_normalize_treino(result["data"]))


@app.route("/treinos/novo", methods=["POST"])
def criar_treino():
    exercicios_raw = request.form.get("exercicios_raw", "")
    payload = {
        "aluno_id": request.form.get("aluno_id"),
        "nome": request.form.get("nome"),
        "observacoes": request.form.get("observacoes"),
        "exercicios_raw": exercicios_raw,
        "exercicios": _parse_exercicios_raw(exercicios_raw),
    }
    result = _insert(TABLE_TREINOS, payload)
    if result["ok"]:
        flash("Treino criado.", "success")
    else:
        flash(f"Erro ao criar treino: {result['error']}", "error")
    return redirect(url_for("treinos", aluno_id=request.form.get("aluno_id")))


@app.route("/treinos/editar/<treino_id>", methods=["POST"])
def atualizar_treino(treino_id: str):
    exercicios_raw = request.form.get("exercicios_raw", "")
    payload = {
        "aluno_id": request.form.get("aluno_id"),
        "nome": request.form.get("nome"),
        "observacoes": request.form.get("observacoes"),
        "exercicios_raw": exercicios_raw,
        "exercicios": _parse_exercicios_raw(exercicios_raw),
    }
    result = _update(TABLE_TREINOS, treino_id, payload)
    if result["ok"]:
        flash("Treino atualizado.", "success")
    else:
        flash(f"Erro ao atualizar treino: {result['error']}", "error")
    return redirect(url_for("treinos", aluno_id=request.form.get("aluno_id")))


@app.route("/treinos/excluir/<treino_id>", methods=["POST"])
def remover_treino(treino_id: str):
    aluno_id = request.form.get("aluno_id")
    result = _delete(TABLE_TREINOS, treino_id)
    if result["ok"]:
        flash("Treino excluido.", "success")
    else:
        flash(f"Erro ao excluir treino: {result['error']}", "error")
    return redirect(url_for("treinos", aluno_id=aluno_id))


@app.route("/agenda", methods=["GET", "POST"])
def agenda():
    if request.method == "POST":
        payload = {
            "titulo": request.form.get("titulo"),
            "aluno_id": request.form.get("aluno_id"),
            "inicio": _datetime_local_to_iso(request.form.get("inicio", "")),
            "termino": _datetime_local_to_iso(request.form.get("termino", "")),
            "tipo": "Aula",
            "status": "pendente",
            "observacoes": request.form.get("observacoes"),
        }
        result = _insert(TABLE_AGENDA, payload)
        if result["ok"]:
            flash("Compromisso criado.", "success")
        else:
            flash(f"Erro ao criar compromisso: {result['error']}", "error")
        return redirect(url_for("agenda"))

    agenda_result = _select(TABLE_AGENDA)
    alunos_result = _select(TABLE_ALUNOS)

    compromissos = [_normalize_agenda(item) for item in (agenda_result["data"] if agenda_result["ok"] else [])]
    alunos = alunos_result["data"] if alunos_result["ok"] else []

    return render_template(
        "agenda.html",
        pagina_ativa="agenda",
        compromissos=compromissos,
        alunos=alunos,
        data_referencia=datetime.now().strftime("%d/%m/%Y"),
    )


def _atualizar_status_agenda(agenda_id: str, status: str):
    result = _update(TABLE_AGENDA, agenda_id, {"status": status})
    if result["ok"]:
        flash("Status atualizado.", "success")
    else:
        flash(f"Erro ao atualizar status: {result['error']}", "error")
    return redirect(url_for("agenda"))


@app.route("/agenda/confirmar/<agenda_id>", methods=["POST"])
def confirmar_agenda(agenda_id: str):
    return _atualizar_status_agenda(agenda_id, "confirmado")


@app.route("/agenda/concluir/<agenda_id>", methods=["POST"])
def concluir_agenda(agenda_id: str):
    return _atualizar_status_agenda(agenda_id, "concluido")


@app.route("/agenda/cancelar/<agenda_id>", methods=["POST"])
def cancelar_agenda(agenda_id: str):
    return _atualizar_status_agenda(agenda_id, "cancelado")


@app.route("/avaliacoes", methods=["GET", "POST"])
def avaliacoes():
    if request.method == "POST":
        peso = _to_float(request.form.get("peso"))
        estatura = _to_float(request.form.get("estatura"))
        gordura = _to_float(request.form.get("gordura"))

        imc = round(peso / (estatura * estatura), 2) if peso and estatura else None
        classificacao = _classificacao_imc(imc)

        dobras_keys = ["tricipital", "subscapular", "suprailiaca", "abdominal", "peitoral", "coxa", "perna"]
        soma_dobras = round(
            sum(_to_float(request.form.get(key)) or 0 for key in dobras_keys),
            2,
        )

        massa_gorda = round((peso * gordura / 100), 2) if peso and gordura is not None else None
        massa_magra = round(peso - massa_gorda, 2) if peso and massa_gorda is not None else None
        peso_ideal = round((estatura * estatura) * 22, 2) if estatura else None

        cintura = _to_float(request.form.get("cintura"))
        quadril = _to_float(request.form.get("quadril"))
        relacao_cq = round(cintura / quadril, 2) if cintura and quadril else None

        payload = {
            "aluno_id": request.form.get("aluno_id"),
            "sexo": request.form.get("sexo"),
            "peso": peso,
            "estatura": estatura,
            "altura": estatura,
            "idade": _to_int(request.form.get("idade")),
            "gordura": gordura,
            "imc": imc,
            "classificacao": classificacao,
            "gordura_nivel": "Normal" if gordura is None or gordura < 25 else "Elevado",
            "massa_gorda": massa_gorda,
            "massa_magra": massa_magra,
            "peso_ideal": peso_ideal,
            "relacao_cq": relacao_cq,
            "soma_dobras": soma_dobras,
            "observacoes": request.form.get("observacoes"),
            "data": datetime.now().strftime("%d/%m/%Y"),
            "tricipital": _to_float(request.form.get("tricipital")),
            "subscapular": _to_float(request.form.get("subscapular")),
            "suprailiaca": _to_float(request.form.get("suprailiaca")),
            "abdominal": _to_float(request.form.get("abdominal")),
            "peitoral": _to_float(request.form.get("peitoral")),
            "coxa": _to_float(request.form.get("coxa")),
            "perna": _to_float(request.form.get("perna")),
            "braco_direito": _to_float(request.form.get("braco_direito")),
            "peitoral_circ": _to_float(request.form.get("peitoral_circ")),
            "cintura": cintura,
            "quadril": quadril,
            "coxa_direita": _to_float(request.form.get("coxa_direita")),
            "perna_direita": _to_float(request.form.get("perna_direita")),
        }

        result = _insert(TABLE_AVALIACOES, payload)
        if result["ok"]:
            flash("Avaliacao salva.", "success")
        else:
            flash(f"Erro ao salvar avaliacao: {result['error']}", "error")

        return redirect(url_for("avaliacoes", aluno_id=request.form.get("aluno_id")))

    aluno_id = request.args.get("aluno_id")
    alunos_result = _select(TABLE_ALUNOS)
    alunos = alunos_result["data"] if alunos_result["ok"] else []

    filters = {"aluno_id": aluno_id} if aluno_id else None
    avaliacoes_result = _select(TABLE_AVALIACOES, filters=filters)
    avaliacoes_data = avaliacoes_result["data"] if avaliacoes_result["ok"] else []

    aluno_selecionado = None
    if aluno_id:
        aluno_selecionado = next((item for item in alunos if str(item.get("id")) == str(aluno_id)), None)

    avaliacao_atual = avaliacoes_data[0] if avaliacoes_data else None
    historico = avaliacoes_data[1:] if len(avaliacoes_data) > 1 else []

    if avaliacao_atual and aluno_selecionado:
        avaliacao_atual = {**avaliacao_atual, "aluno_nome": aluno_selecionado.get("nome", "")}

    medidas = _medidas_avaliacao(avaliacao_atual or {})

    return render_template(
        "avaliacoes.html",
        pagina_ativa="avaliacoes",
        alunos=alunos,
        aluno_selecionado=aluno_selecionado,
        avaliacao_atual=avaliacao_atual,
        historico=historico,
        medidas=medidas,
    )


@app.route("/evolucao")
def evolucao():
    aluno_id = request.args.get("aluno_id")
    alunos_result = _select(TABLE_ALUNOS)
    alunos = alunos_result["data"] if alunos_result["ok"] else []

    filters = {"aluno_id": aluno_id} if aluno_id else None
    avaliacoes_result = _select(TABLE_AVALIACOES, filters=filters)
    avaliacoes_data = avaliacoes_result["data"] if avaliacoes_result["ok"] else []

    aluno_selecionado = None
    if aluno_id:
        aluno_selecionado = next((item for item in alunos if str(item.get("id")) == str(aluno_id)), None)

    ultima_avaliacao = avaliacoes_data[0] if avaliacoes_data else None

    return render_template(
        "evolucao.html",
        pagina_ativa="evolucao",
        alunos=alunos,
        aluno_selecionado=aluno_selecionado,
        ultima_avaliacao=ultima_avaliacao,
        total_avaliacoes=len(avaliacoes_data),
        historico=avaliacoes_data,
    )


# API REST
@app.route("/api/alunos", methods=["GET", "POST"])
def api_alunos():
    if request.method == "GET":
        result = _select(TABLE_ALUNOS)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    payload = request.get_json(silent=True) or {}
    result = _insert(TABLE_ALUNOS, payload)
    status_code = 201 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/alunos/<aluno_id>", methods=["GET", "PUT", "DELETE"])
def api_aluno_id(aluno_id: str):
    if request.method == "GET":
        result = _select_one(TABLE_ALUNOS, aluno_id)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    if request.method == "PUT":
        payload = request.get_json(silent=True) or {}
        result = _update(TABLE_ALUNOS, aluno_id, payload)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    result = _delete(TABLE_ALUNOS, aluno_id)
    status_code = 200 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/exercicios", methods=["GET", "POST"])
def api_exercicios():
    if request.method == "GET":
        result = _select(TABLE_EXERCICIOS)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    payload = request.get_json(silent=True) or {}
    result = _insert(TABLE_EXERCICIOS, payload)
    status_code = 201 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/exercicios/<exercicio_id>", methods=["GET", "PUT", "DELETE"])
def api_exercicio_id(exercicio_id: str):
    if request.method == "GET":
        result = _select_one(TABLE_EXERCICIOS, exercicio_id)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    if request.method == "PUT":
        payload = request.get_json(silent=True) or {}
        result = _update(TABLE_EXERCICIOS, exercicio_id, payload)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    result = _delete(TABLE_EXERCICIOS, exercicio_id)
    status_code = 200 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/mensagens", methods=["GET", "POST"])
def api_mensagens():
    if request.method == "GET":
        aluno_id = request.args.get("aluno_id")
        filters = {"aluno_id": aluno_id} if aluno_id else None
        result = _select(TABLE_MENSAGENS, filters=filters, order="created_at", desc=False)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    payload = request.get_json(silent=True) or {}
    result = _insert(TABLE_MENSAGENS, payload)
    status_code = 201 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/mensagens/<mensagem_id>", methods=["GET", "PUT", "DELETE"])
def api_mensagem_id(mensagem_id: str):
    if request.method == "GET":
        result = _select_one(TABLE_MENSAGENS, mensagem_id)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    if request.method == "PUT":
        payload = request.get_json(silent=True) or {}
        result = _update(TABLE_MENSAGENS, mensagem_id, payload)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    result = _delete(TABLE_MENSAGENS, mensagem_id)
    status_code = 200 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/treinos", methods=["GET", "POST"])
def api_treinos():
    if request.method == "GET":
        aluno_id = request.args.get("aluno_id")
        filters = {"aluno_id": aluno_id} if aluno_id else None
        result = _select(TABLE_TREINOS, filters=filters)
        if result["ok"]:
            result["data"] = [_normalize_treino(item) for item in result["data"]]
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    payload = request.get_json(silent=True) or {}
    if isinstance(payload.get("exercicios_raw"), str) and "exercicios" not in payload:
        payload["exercicios"] = _parse_exercicios_raw(payload["exercicios_raw"])
    result = _insert(TABLE_TREINOS, payload)
    status_code = 201 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/treinos/<treino_id>", methods=["GET", "PUT", "DELETE"])
def api_treino_id(treino_id: str):
    if request.method == "GET":
        result = _select_one(TABLE_TREINOS, treino_id)
        if result["ok"] and result["data"]:
            result["data"] = _normalize_treino(result["data"])
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    if request.method == "PUT":
        payload = request.get_json(silent=True) or {}
        if isinstance(payload.get("exercicios_raw"), str) and "exercicios" not in payload:
            payload["exercicios"] = _parse_exercicios_raw(payload["exercicios_raw"])
        result = _update(TABLE_TREINOS, treino_id, payload)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    result = _delete(TABLE_TREINOS, treino_id)
    status_code = 200 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/agenda", methods=["GET", "POST"])
def api_agenda():
    if request.method == "GET":
        result = _select(TABLE_AGENDA)
        if result["ok"]:
            result["data"] = [_normalize_agenda(item) for item in result["data"]]
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    payload = request.get_json(silent=True) or {}
    result = _insert(TABLE_AGENDA, payload)
    status_code = 201 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/agenda/<agenda_id>", methods=["GET", "PUT", "DELETE"])
def api_agenda_id(agenda_id: str):
    if request.method == "GET":
        result = _select_one(TABLE_AGENDA, agenda_id)
        if result["ok"] and result["data"]:
            result["data"] = _normalize_agenda(result["data"])
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    if request.method == "PUT":
        payload = request.get_json(silent=True) or {}
        result = _update(TABLE_AGENDA, agenda_id, payload)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    result = _delete(TABLE_AGENDA, agenda_id)
    status_code = 200 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/avaliacoes", methods=["GET", "POST"])
def api_avaliacoes():
    if request.method == "GET":
        aluno_id = request.args.get("aluno_id")
        filters = {"aluno_id": aluno_id} if aluno_id else None
        result = _select(TABLE_AVALIACOES, filters=filters)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    payload = request.get_json(silent=True) or {}
    result = _insert(TABLE_AVALIACOES, payload)
    status_code = 201 if result["ok"] else 400
    return jsonify(result), status_code


@app.route("/api/avaliacoes/<avaliacao_id>", methods=["GET", "PUT", "DELETE"])
def api_avaliacao_id(avaliacao_id: str):
    if request.method == "GET":
        result = _select_one(TABLE_AVALIACOES, avaliacao_id)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    if request.method == "PUT":
        payload = request.get_json(silent=True) or {}
        result = _update(TABLE_AVALIACOES, avaliacao_id, payload)
        status_code = 200 if result["ok"] else 400
        return jsonify(result), status_code

    result = _delete(TABLE_AVALIACOES, avaliacao_id)
    status_code = 200 if result["ok"] else 400
    return jsonify(result), status_code


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    debug = os.getenv("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
