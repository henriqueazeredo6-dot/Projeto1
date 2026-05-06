-- Migração de compatibilidade Flask <-> Supabase
-- Execute este arquivo no SQL Editor do Supabase antes de testar o Flask.

create extension if not exists pgcrypto;

-- ETAPA 1: correções estruturais
alter table if exists public.tb_plano
  alter column id set default gen_random_uuid();

alter table if exists public.tb_plano
  drop constraint if exists tb_plano_id_fkey;

alter table if exists public.tb_aluno
  alter column plano drop default;

alter table if exists public.tb_aluno
  alter column auth_user_id drop default;

alter table if exists public.tb_itens_treino
  drop constraint if exists "tb_itens_treino_id_fkey";

alter table if exists public.tb_itens_treino
  drop constraint if exists "tb_itens_treino_exercício_id_fkey";

do $$
begin
  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'tb_itens_treino'
      and column_name = 'exercício_id'
  ) and not exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'tb_itens_treino'
      and column_name = 'exercicio_id'
  ) then
    alter table public.tb_itens_treino rename column "exercício_id" to exercicio_id;
  end if;
end $$;

do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'tb_itens_treino_treino_id_fkey'
  ) then
    alter table public.tb_itens_treino
      add constraint tb_itens_treino_treino_id_fkey
      foreign key (treino_id)
      references public.tb_treino(id)
      on delete cascade;
  end if;

  if exists (
    select 1
    from information_schema.columns
    where table_schema = 'public'
      and table_name = 'tb_itens_treino'
      and column_name = 'exercicio_id'
  ) and not exists (
    select 1 from pg_constraint where conname = 'tb_itens_treino_exercicio_id_fkey'
  ) then
    alter table public.tb_itens_treino
      add constraint tb_itens_treino_exercicio_id_fkey
      foreign key (exercicio_id)
      references public.tb_exercicios(id);
  end if;
end $$;

-- ETAPA 2: tabelas que o Flask usa e que não existem no SQL informado
create table if not exists public.tb_mensagens (
  id uuid primary key default gen_random_uuid(),
  contato_id uuid,
  profissional_id uuid,
  aluno_id uuid references public.tb_aluno(id) on delete cascade,
  autor text,
  autor_nome text,
  texto text not null,
  canal text default 'painel',
  created_at timestamp with time zone not null default now()
);

-- A tela de execução do aluno registra séries executadas; isso é diferente
-- da prescrição de exercícios em tb_itens_treino.
create table if not exists public.tb_execucao_treino (
  id uuid primary key default gen_random_uuid(),
  treino_id uuid references public.tb_treino(id) on delete cascade,
  aluno_id uuid references public.tb_aluno(id) on delete cascade,
  exercicio_id text,
  serie_registrada boolean default true,
  status text default 'registrado',
  created_at timestamp with time zone not null default now()
);

-- ETAPA 6: uma avaliação física tem um único conjunto de medidas;
-- por isso os campos antropométricos ficam na própria tb_avaliacao.
alter table if exists public.tb_avaliacao
  add column if not exists sexo text,
  add column if not exists gordura numeric,
  add column if not exists tricipital numeric,
  add column if not exists subscapular numeric,
  add column if not exists suprailiaca numeric,
  add column if not exists abdominal numeric,
  add column if not exists peitoral numeric,
  add column if not exists coxa numeric,
  add column if not exists perna numeric,
  add column if not exists braco_direito numeric,
  add column if not exists peitoral_circ numeric,
  add column if not exists cintura numeric,
  add column if not exists quadril numeric,
  add column if not exists coxa_direita numeric,
  add column if not exists perna_direita numeric,
  add column if not exists created_at timestamp with time zone not null default now();

-- ETAPA 7: parcela pendente não deve exigir data de recebimento.
alter table if exists public.tb_parcela
  alter column data_recebimento drop not null;

create index if not exists idx_tb_aluno_plano on public.tb_aluno (plano);
create index if not exists idx_tb_agenda_data on public.tb_agenda (data);
create index if not exists idx_tb_parcela_aluno on public.tb_parcela (aluno_id);
create index if not exists idx_tb_execucao_treino_treino on public.tb_execucao_treino (treino_id);

-- Planos básicos para que o cadastro de aluno envie um UUID real.
insert into public.tb_plano (id, nome, descricao, preco, duracao_dias, recorrente, ativo)
values
  ('11111111-0000-4000-8000-000000000001', 'Starter', 'Plano mensal inicial', 49, 30, true, true),
  ('11111111-0000-4000-8000-000000000002', 'Premium', 'Plano mensal completo', 99, 30, true, true),
  ('11111111-0000-4000-8000-000000000003', 'Consultoria online', 'Plano online para acompanhamento remoto', 199, 30, true, true)
on conflict (id) do update
set
  nome = excluded.nome,
  descricao = excluded.descricao,
  preco = excluded.preco,
  duracao_dias = excluded.duracao_dias,
  recorrente = excluded.recorrente,
  ativo = excluded.ativo;

-- RLS: com service_role no Flask, o backend consegue operar sem abrir dados ao público.
alter table if exists public.tb_mensagens enable row level security;
alter table if exists public.tb_execucao_treino enable row level security;
