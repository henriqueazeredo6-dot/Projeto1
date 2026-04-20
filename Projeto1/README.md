# Confie Personal - Backend Flask + Supabase

Este projeto agora possui um backend completo em Flask integrado ao Supabase, com:

- Autenticacao (login/cadastro) usando Supabase Auth
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
pip install -r requirements.txt
```

## 3) Rodar aplicacao

```bash
cd Projeto1
python app.py
```

A aplicacao sobe em `http://localhost:5000`.

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

