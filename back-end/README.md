# Confie Personal - Backend Flask + Supabase

Este projeto agora possui um backend completo em Flask integrado ao Supabase, com:

- Autenticacao local no Flask usando a tabela `tb_usuario`
- CRUD de Alunos
- CRUD de Treinos
- CRUD de Agenda
- CRUD de Avaliacoes
- Dashboard com dados reais
- API REST em `/api/*`

## 1) Configurar Supabase

1. Crie um projeto no Supabase.
2. Abra o SQL Editor e execute o arquivo `supabase_schema.sql`.
3. Copie `.env.example` para `.env` e preencha as chaves:

```env
SUPABASE_URL=...
SUPABASE_KEY=...
FLASK_SECRET_KEY=...
```

## 2) Instalar dependencias

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 3) Rodar aplicacao

```bash
copy .env.example .env
python app.py
```

A aplicacao sobe em `http://localhost:5000`.

## Portabilidade

Para o projeto rodar em qualquer computador apos o clone:

- `app.py` carrega o `.env` pela pasta do proprio projeto, sem depender do diretorio atual do terminal
- `paths.py` centraliza os caminhos do projeto (`BASE_DIR`, `TEMPLATES_DIR`, `STATIC_DIR`, `ENV_FILE`)
- `run_site.ps1`, `start_site.ps1` e `stop_site.ps1` usam a pasta onde o script esta, em vez de caminhos absolutos
- os scripts procuram primeiro o Python da `.venv`; se ela nao existir, usam `python` do sistema
- `.gitignore` evita versionar `.venv`, `.deps`, logs e `.env`

## Padrao para novos arquivos

Para evitar caminhos absolutos no futuro:

- sempre importe caminhos de `paths.py` quando precisar acessar arquivos locais
- nunca escreva algo como `C:\...` ou `/Users/...` no codigo
- use `project_path(...)` para montar subpastas do projeto
- rode a checagem antes de subir alteracoes

```bash
python scripts/check_portability.py
```

No PowerShell:

```powershell
.\check_portability.ps1
```

## Rotas principais

- `GET /` Home
- `GET/POST /login`
- `GET/POST /cadastro`
- `GET /dashboard`
- `GET/POST /alunos`
- `GET /treinos`
- `GET/POST /agenda`
- `GET/POST /avaliacoes`
- `GET /evolucao`

## API REST

- `GET/POST /api/alunos`
- `GET/PUT/DELETE /api/alunos/<id>`
- `GET/POST /api/treinos`
- `GET/PUT/DELETE /api/treinos/<id>`
- `GET/POST /api/agenda`
- `GET/PUT/DELETE /api/agenda/<id>`
- `GET/POST /api/avaliacoes`
- `GET/PUT/DELETE /api/avaliacoes/<id>`

## Observacao de seguranca

As politicas RLS no SQL estao abertas para facilitar desenvolvimento.
Antes de publicar em producao, restrinja as politicas por usuario (`auth.uid()`).

