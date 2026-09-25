# claude-code-discord-hq

**Comande suas sessões do Claude Code pelo celular.** Um servidor Discord descrito como código, e avisos que dizem quando uma sessão de IA precisa de você.

[English](README.md) · [Formato do desenho](docs/design-format.md) · [Modelo de segurança](docs/security-model.md) · [Modelo de ameaças](docs/threat-model.md)

> A documentação detalhada em `docs/` está em inglês. Este README é a versão completa em português.

---

## O que é

São duas ferramentas que funcionam bem juntas, e também cada uma sozinha:

1. **Servidor como código.** Você descreve o servidor Discord num arquivo TOML: cargos, categorias, canais, quem vê o quê, quais canais são só leitura, tags de fórum, webhooks, Community e mensagens fixadas. O `discord-hq plan` mostra a diferença para o servidor real. O `discord-hq apply` deixa o servidor igual ao desenho, de forma idempotente: rodar de novo não muda nada.
2. **Avisos do Claude Code.** Um hook de `Notification`/`Stop` e um pequeno vigia avisam, no Mac e no Discord, quando uma sessão:
   - pede aprovação;
   - parou;
   - travou sem progresso;
   - está esperando você;
   - abriu o pull request.

   Uma mensagem de painel vivo mostra todas as sessões de uma vez.

Junto com o plugin oficial de Discord do Claude Code (`/plugin install discord@claude-plugins-official`), você conversa com a sessão principal pelo celular e é chamado quando o trabalho está pronto para revisar.

## Por quê: o garçom e a cozinha

O projeto nasceu de um jeito de trabalhar com o Claude Code que usa um restaurante como metáfora:

| Papel | O que é | O que faz |
|---|---|---|
| **Garçom** (*waiter*) | a sua sessão principal do Claude Code | Conversa com você, anota os pedidos, manda para a cozinha e serve o resultado. **Nunca cozinha**: não edita código. |
| **Cozinha** (*kitchen*) | uma sessão tmux por pedido, cada uma no seu git worktree | Trabalha num pedido só até o pull request abrir. Vários pedidos cozinham em paralelo. |
| **Chef** | você | Prova (revisa) e faz o merge. |
| **Convidado** (*guest*) | alguém que você convida | Faz pedidos que esperam a aprovação do chef. |

O garçom continua disponível porque nunca fica preso numa tarefa. A cozinha faz vários pratos ao mesmo tempo porque cada pedido é isolado. Falta um **balcão**: um lugar para falar com o garçom de qualquer lugar, e para ser avisado quando um prato fica pronto ou um cozinheiro trava. Esse balcão é o servidor Discord. Mais em [docs/waiter-kitchen.md](docs/waiter-kitchen.md).

Você não precisa adotar o fluxo inteiro. O servidor como código serve para qualquer servidor Discord, e os avisos servem para qualquer sessão do Claude Code rodando num git worktree ou numa sessão tmux.

### Vocabulário (pt → en)

O código, a CLI e as mensagens estão em inglês. Esta é a equivalência:

| Português | Inglês (no projeto) |
|---|---|
| garçom | waiter |
| cozinha | kitchen |
| chef | chef |
| convidado | guest |
| pedido | order |
| servido / pronto | served / ready |
| balcão | counter |
| vigia | watchdog (`discord-hq watch`) |
| painel | panel |
| desenho (do servidor) | design (`design.toml`) |
| manifesto da leva | batch manifest |
| aguarda humano (⏳) | waiting for you (⏳) |
| travada (🧊) | stalled (🧊) |
| arquiteto (bot admin temporário) | admin bot / architect |

## Como funciona

```
                 você (celular / desktop)
                          │
                   servidor Discord  ◄────────── discord-hq apply
     ┌────────────────────┼─────────────────────┐   (design.toml → cargos,
     │ #table   #orders   │ #served  #alerts    │    canais, permissões,
     │ (conversa)(fóruns) │ #panel (painel vivo)│    webhooks)
     └────────┬───────────┴──────────▲──────────┘
              │ bot (plugin oficial   │ webhooks (sem token de bot)
              │ de Discord)           │
      ┌───────▼────────┐     ┌────────┴─────────────────────────────┐
      │ sessão garçom  │     │ discord-hq hook   (Notification/Stop)│
      │ (tmux: waiter) │     │ discord-hq watch  (a cada 2 minutos) │
      └───────┬────────┘     └────────▲─────────────────────────────┘
              │ despacha              │ lê: eventos do hook, telas do tmux,
      ┌───────▼─────────────────┐     │ transcripts, manifestos da leva
      │ kitchen-a  kitchen-b ...│─────┘
      │ (tmux + git worktrees)  │   e ainda: notificação do macOS com o
      └─────────────────────────┘   comando de attach na área de transferência
```

- **`discord-hq plan` / `apply`** usam um token de bot admin temporário. Leem o servidor, calculam o diff e aplicam. Um canal é casado por (nome, tipo, categoria), nunca só pelo nome. As permissões são gravadas em cada canal, porque o Discord não propaga a permissão da categoria para canais que já existem. Ver [docs/design-format.md](docs/design-format.md).
- **`discord-hq hook`** roda nos eventos `Notification` e `Stop` do Claude Code. Só age dentro de sessões de cozinha, que reconhece por uma pasta de git worktree ou por um prefixo de sessão tmux.
- **`discord-hq watch`** roda a cada 2 minutos (LaunchAgent no macOS, cron no Linux). Faz três coisas:
  - acusa sessões cuja tela diz "esc to interrupt" mas cujo transcript parou de andar;
  - avisa das unidades marcadas com ⏳ num manifesto de leva;
  - edita uma única mensagem de painel vivo.
- Os avisos chegam ao Discord por **webhooks**, não por token de bot, e mencionam só você.

## Início rápido

Requisitos: Python 3.11+, git, tmux e uma conta no Discord. No macOS há notificação nativa. No Linux também funciona, só com os avisos no Discord.

1. **Clone e instale:**
   ```sh
   git clone https://github.com/Fabiano-Arthur/claude-code-discord-hq.git
   cd claude-code-discord-hq
   ./install.sh --dry-run   # mostra o que faria
   ./install.sh             # pergunta antes de cada escrita
   ```
2. **Crie um servidor** no Discord e ligue o Modo Desenvolvedor (Configurações → Avançado).
3. **Crie um bot admin temporário** e convide-o: [docs/bot-setup.md](docs/bot-setup.md). Ponha o token e o id do servidor em `~/.config/claude-code-discord-hq/.env`.
4. **Escolha um desenho:** `cp examples/restaurant.toml design.toml`, ou parta do `examples/minimal.toml`, e edite.
5. **Veja antes:** `.venv/bin/discord-hq plan`
6. **Aplique:** `.venv/bin/discord-hq apply`. Depois **resete o token do bot admin** no Developer Portal. Você só vai precisar dele de novo para mudar o servidor.
7. **Ligue os avisos:** cole no `~/.claude/settings.json` o trecho de hooks que o `install.sh` imprimiu, e preencha `DISCORD_HQ_MENTION_USER_ID` no `.env`.
8. **Conecte o garçom:** instale o plugin oficial de Discord no Claude Code, ponha `source .../shell/waiter.zsh` no `~/.zshrc` e rode `waiter`. Depois rode `.venv/bin/discord-hq access --bot waiter` e digite os comandos impressos nessa sessão.

## Comandos

| Comando | O que faz |
|---|---|
| `discord-hq plan [--design ARQ]` | Mostra o que o `apply` mudaria. Só leitura. |
| `discord-hq apply [--design ARQ] [--yes] [--allow-delete]` | Deixa o servidor igual ao desenho. Pergunta antes, e segura as deleções sem `--allow-delete`. |
| `discord-hq audit-forum ID_DO_CANAL` | Lista os posts de um fórum antes de mover ou renomear. Só leitura. |
| `discord-hq access --bot NOME` | Imprime os comandos `/discord:access` dos canais de um bot. Nunca edita nada. |
| `discord-hq hook` | O hook do Claude Code. Lê o evento no stdin, não imprime nada, sempre sai 0. |
| `discord-hq watch` | Uma rodada do vigia: sessões travadas, unidades em pausa, painel vivo. |

Todas as configurações são variáveis de ambiente, ou linhas em `~/.config/claude-code-discord-hq/.env`. O [`.env.example`](.env.example) documenta cada uma.

## Segurança

Resumo aqui; a versão completa está em [docs/security-model.md](docs/security-model.md) e [docs/threat-model.md](docs/threat-model.md):

- **O token de admin é temporário.** Use-o no `apply` e depois resete. Os bots que conversam com o Claude Code nunca precisam de admin.
- **Os segredos ficam fora do repositório.** Os tokens ficam em `~/.config/claude-code-discord-hq/.env` e as URLs de webhook em `webhooks.json`, ambos com modo 0600. O `state.json` guarda só ids e está no `.gitignore`. Token e URL de webhook nunca aparecem no stdout, em log ou em exceção.
- **Mensagem é dado, não instrução.** Tudo o que um bot lê num canal pode ser prompt injection. O desenho mantém a DM fechada (allowlist do plugin), dá ao convidado um canal próprio com resposta só por menção, e nunca deixa dois bots responderem no mesmo canal. O `discord-hq access` imprime comandos em vez de editar o `access.json` do plugin.
- **O hook não quebra a sua sessão.** Tem timeouts curtos, nunca lança exceção, nunca imprime e sempre sai 0.
- **O instalador pergunta antes.** O `install.sh` confirma cada escrita. Nunca edita o `~/.claude/settings.json` nem o rc do shell; só imprime o que colar.

Achou uma vulnerabilidade? Veja o [SECURITY.md](SECURITY.md).

## Perguntas frequentes

**Isso chama a API do Discord sozinho?**
Só `plan`, `apply` e `audit-forum` usam a API de bot, e só quando você roda. O hook e o vigia só postam pelos webhooks que você criou.

**O `apply` vai apagar o meu servidor atual?**
Não. Ele só gerencia o que o desenho declara. Canais de outras categorias e permissões de outros usuários ou cargos ficam como estão. Só apaga canais cujo id você listar em `[cleanup]`, e só com `--allow-delete`.

**E se eu perder o `state.json`?**
Cargos, categorias, canais e webhooks nunca são duplicados: o servidor real é a fonte da verdade, e o próximo `apply` refaz o arquivo (mesmo sem nenhuma outra mudança). A única coisa guardada só no `state.json` é quais `[[pinned_messages]]` já foram postadas, então essas seriam postadas de novo. O `discord-hq access` precisa do arquivo, então rode o `apply` antes.

**Mudei a categoria de um canal no desenho e ganhei um canal novo. Por quê?**
A identidade de um canal é (nome, tipo, categoria). Mover canais automaticamente já corrompeu um servidor de verdade, então um canal movido nasce novo e o antigo fica para você apagar. Para renomear uma categoria sem perder nada, use `rename_from`: o mesmo id mantém os canais e os posts dos fóruns.

**Funciona sem tmux ou worktrees?**
O servidor como código, sim. Os avisos precisam distinguir as sessões de cozinha. Eles procuram uma pasta `.worktrees/<nome>` (configurável) ou um prefixo de sessão tmux (`kitchen-` por padrão).

**Linux? Windows?**
Linux: sim, só com avisos no Discord (sem notificação nativa) e uma linha de cron no lugar do LaunchAgent. Windows: o servidor como código deve funcionar com Python; o resto não foi testado.

**Tem ligação com a Anthropic ou com o Discord?**
Não. É um projeto open source independente.

## Contribuindo

Issues e pull requests são bem-vindos: veja o [CONTRIBUTING.md](CONTRIBUTING.md). A suíte de testes nunca fala com o Discord e nunca mexe nas suas sessões tmux reais.

## Licença

[MIT](LICENSE) © 2026 Fabiano Arthur
