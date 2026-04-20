-- Execute no SQL Editor do Supabase
create extension if not exists pgcrypto;

create table if not exists public.tb_usuario (
  id uuid primary key default gen_random_uuid(),
  auth_user_id uuid,
  nome text not null,
  email text not null unique,
  tipo_conta text not null default 'Personal Trainer',
  nascimento date,
  created_at timestamptz not null default now()
);

create table if not exists public.tb_aluno (
  id uuid primary key default gen_random_uuid(),
  nome text not null,
  email text not null unique,
  telefone text,
  objetivo text,
  status text default 'ativo',
  plano text default 'mensal',
  created_at timestamptz not null default now()
);

create table if not exists public.tb_treino (
  id uuid primary key default gen_random_uuid(),
  aluno_id uuid references public.tb_aluno(id) on delete cascade,
  nome text not null,
  observacoes text,
  exercicios_raw text,
  exercicios jsonb not null default '[]'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists public.tb_agenda (
  id uuid primary key default gen_random_uuid(),
  aluno_id uuid references public.tb_aluno(id) on delete set null,
  titulo text not null,
  tipo text default 'Aula',
  inicio timestamptz,
  termino timestamptz,
  status text default 'pendente',
  observacoes text,
  created_at timestamptz not null default now()
);

create table if not exists public.tb_avaliacao (
  id uuid primary key default gen_random_uuid(),
  aluno_id uuid references public.tb_aluno(id) on delete cascade,
  sexo text,
  idade integer,
  peso numeric(10,2),
  estatura numeric(10,2),
  altura numeric(10,2),
  gordura numeric(10,2),
  imc numeric(10,2),
  classificacao text,
  gordura_nivel text,
  massa_gorda numeric(10,2),
  massa_magra numeric(10,2),
  peso_ideal numeric(10,2),
  relacao_cq numeric(10,2),
  soma_dobras numeric(10,2),
  tricipital numeric(10,2),
  subscapular numeric(10,2),
  suprailiaca numeric(10,2),
  abdominal numeric(10,2),
  peitoral numeric(10,2),
  coxa numeric(10,2),
  perna numeric(10,2),
  braco_direito numeric(10,2),
  peitoral_circ numeric(10,2),
  cintura numeric(10,2),
  quadril numeric(10,2),
  coxa_direita numeric(10,2),
  perna_direita numeric(10,2),
  observacoes text,
  data text,
  created_at timestamptz not null default now()
);

create index if not exists idx_tb_treino_aluno on public.tb_treino (aluno_id);
create index if not exists idx_tb_agenda_aluno on public.tb_agenda (aluno_id);
create index if not exists idx_tb_avaliacao_aluno on public.tb_avaliacao (aluno_id);

alter table public.tb_usuario enable row level security;
alter table public.tb_aluno enable row level security;
alter table public.tb_treino enable row level security;
alter table public.tb_agenda enable row level security;
alter table public.tb_avaliacao enable row level security;

-- Politicas abertas para ambiente de desenvolvimento.
-- Em producao, troque por politicas com auth.uid().
do $$
begin
  if not exists (select 1 from pg_policies where policyname = 'dev_full_tb_usuario') then
    create policy dev_full_tb_usuario on public.tb_usuario for all using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where policyname = 'dev_full_tb_aluno') then
    create policy dev_full_tb_aluno on public.tb_aluno for all using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where policyname = 'dev_full_tb_treino') then
    create policy dev_full_tb_treino on public.tb_treino for all using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where policyname = 'dev_full_tb_agenda') then
    create policy dev_full_tb_agenda on public.tb_agenda for all using (true) with check (true);
  end if;
  if not exists (select 1 from pg_policies where policyname = 'dev_full_tb_avaliacao') then
    create policy dev_full_tb_avaliacao on public.tb_avaliacao for all using (true) with check (true);
  end if;
end $$;
