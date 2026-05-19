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
SUPABASE_SERVICE_KEY=...
FLASK_SECRET_KEY=...
```

Para cadastro e login local, a tabela `tb_usuario` precisa ter a coluna:

```sql
senha_hash text
```

Como o backend salva usuarios diretamente em `tb_usuario`, mantenha a RLS ligada e use `SUPABASE_SERVICE_KEY` no `.env` do backend. Essa chave deve ficar apenas no servidor e nunca deve ir para o frontend.

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

## Google Calendar na agenda

Esta integracao permite que o personal conecte a propria conta Google e visualize os eventos futuros do Google Calendar dentro da tela `Agenda`.

### Como configurar no Google Cloud

1. Acesse o Google Cloud Console.
2. Crie ou selecione um projeto.
3. Em `APIs e servicos > Biblioteca`, habilite `Google Calendar API`.
4. Em `APIs e servicos > Tela de consentimento OAuth`, configure o app.
5. Em `APIs e servicos > Credenciais`, crie um `ID do cliente OAuth`.
6. Escolha o tipo `Aplicativo da Web`.
7. Adicione esta URI em `URIs de redirecionamento autorizados`:

```text
http://127.0.0.1:5000/google-calendar/callback
```

8. Copie o `Client ID` e o `Client Secret`.
9. Preencha no `.env`:

```env
GOOGLE_CLIENT_ID=...
GOOGLE_CLIENT_SECRET=...
GOOGLE_REDIRECT_URI=http://127.0.0.1:5000/google-calendar/callback
GOOGLE_CALENDAR_SCOPES=https://www.googleapis.com/auth/calendar.readonly
GOOGLE_CALENDAR_MAX_EVENTS=100
```

10. Reinicie o servidor.
11. Entre como personal e abra `Agenda`.
12. Clique em `Conectar Google Calendar`.
13. Autorize o acesso na conta Google.
14. Ao voltar para a plataforma, os eventos futuros aparecem no painel `Google Calendar`.

Observacao:
- os tokens OAuth ficam em `.tokens/` e nao entram no Git
- a tela mostra os eventos futuros das agendas conectadas ao Google do personal
- a rota `GET /api/google-calendar/events` retorna os eventos em JSON para testes ou integracoes
- para producao, troque `GOOGLE_REDIRECT_URI` pela URL publicada do backend, por exemplo `https://seu-backend.onrender.com/google-calendar/callback`, e cadastre exatamente a mesma URL no Google Cloud

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
- nunca escreva caminhos absolutos locais no codigo
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
