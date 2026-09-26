# claude-code-discord-hq

**Controle suas sessões do Claude Code pelo celular.** Um servidor do Discord descrito como código, mais avisos que te chamam quando uma sessão de IA precisa de você.

[English](README.md) · [Formato do design](docs/design-format.md) · [Modelo de segurança](docs/security-model.md) · [Modelo de ameaças](docs/threat-model.md)

> A documentação detalhada em `docs/` está em inglês. Este README é a versão completa em português.

[![CI](https://github.com/Fabiano-Arthur/claude-code-discord-hq/actions/workflows/ci.yml/badge.svg)](https://github.com/Fabiano-Arthur/claude-code-discord-hq/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

---

## O que é

São duas ferramentas que funcionam bem juntas, mas também funcionam separadas:

1. **Servidor como código.** Você descreve o seu servidor do Discord num único arquivo TOML: cargos, categorias, canais, quem vê o quê, quais canais são só leitura, tags de fórum, webhooks, configurações de Comunidade e mensagens fixadas. O `discord-hq plan` mostra o que está diferente no servidor real. O `discord-hq apply` deixa o servidor igual ao design, de forma idempotente: se você rodar de novo, nada muda.
2. **Avisos do Claude Code.** Um hook de `Notification`/`Stop` e um pequeno vigia avisam, no Mac e no Discord, quando uma sessão:
   - pede aprovação;
   - parou;
   - travou sem progresso;
   - está esperando você;
   - abriu o pull request.

   Um painel ao vivo, numa única mensagem, mostra todas as sessões de uma vez.

Com o plugin oficial do Discord para o Claude Code (`/plugin install discord@claude-plugins-official`), você conversa com a sua sessão principal pelo celular e recebe um aviso quando o trabalho está pronto para revisão.

## Por quê: o garçom e a cozinha

O projeto nasceu de um jeito de trabalhar com o Claude Code que usa o restaurante como metáfora:

| Papel | O que é | O que faz |
|---|---|---|
| **Garçom** (*waiter*) | a sua sessão principal do Claude Code | Conversa com você, anota os pedidos, manda para a cozinha e serve o resultado. **Nunca cozinha**: não mexe no código. |
| **Cozinha** (*kitchen*) | uma sessão tmux por pedido, cada uma no seu próprio git worktree | Cuida de um pedido só, até abrir o pull request. Vários pedidos ficam no fogo ao mesmo tempo. |
| **Chef** | você | Prova (revisa) e faz o merge. |
| **Convidado** (*guest*) | alguém que você convida | Faz pedidos que ficam esperando a aprovação do chef. |

O garçom fica sempre disponível porque nunca se enterra numa tarefa só. A cozinha prepara vários pratos ao mesmo tempo porque cada pedido fica isolado. O que falta é um **balcão**: um ponto para falar com o garçom de onde você estiver e para saber quando um prato ficou pronto ou quando um cozinheiro travou. Esse balcão é este servidor do Discord. Mais detalhes em [docs/waiter-kitchen.md](docs/waiter-kitchen.md).

Você não precisa adotar o fluxo inteiro. A parte de servidor como código serve para qualquer servidor do Discord, e os avisos servem para qualquer sessão do Claude Code que rode num git worktree ou numa sessão tmux.

### Vocabulário (pt → en)

O código, a CLI e as mensagens estão em inglês. A equivalência é esta:

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
| manifesto da leva | batch manifest |
| aguarda humano (⏳) | waiting for you (⏳) |
| travada (🧊) | stalled (🧊) |
| arquiteto (bot admin temporário) | admin bot / architect |

## Como funciona

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/assets/how-it-works.pt-BR-dark.svg">
  <img src="docs/assets/how-it-works.pt-BR-light.svg" width="880" alt="Diagrama de como o claude-code-discord-hq funciona. Você conversa com um servidor Discord pelo celular ou desktop; o discord-hq apply transforma o design.toml nos cargos, canais, permissões e webhooks dele. Em #table e #orders, o bot (plugin oficial do Discord) leva suas mensagens à sessão garçom no tmux, que despacha o trabalho para as sessões de cozinha (tmux + git worktrees). O discord-hq hook e o discord-hq watch leem eventos do hook, telas do tmux, transcripts e manifestos da leva, publicam por webhooks, sem token de bot, em #served, #alerts e #panel, e também mostram uma notificação do macOS com o comando tmux attach no clipboard.">
</picture>

<details>
<summary>Versão em texto</summary>

```
                 você (celular / desktop)
                          │
                 servidor Discord  ◄─────────── discord-hq apply
     ┌────────────────────┼─────────────────────┐   (design.toml → cargos,
     │ #table   #orders   │ #served  #alerts    │    canais, permissões,
     │ (papo)   (fóruns)  │ #panel (ao vivo)    │    webhooks)
     └────────┬───────────┴──────────▲──────────┘
              │ bot (plugin oficial   │ webhooks (sem token de bot)
              │ do Discord)           │
      ┌───────▼────────┐     ┌────────┴─────────────────────────────┐
      │ sessão garçom  │     │ discord-hq hook   (Notification/Stop)│
      │ (tmux: waiter) │     │ discord-hq watch  (a cada 2 minutos) │
      └───────┬────────┘     └────────▲─────────────────────────────┘
              │ despacha              │ lê: eventos do hook, telas do tmux,
      ┌───────▼─────────────────┐     │ transcripts, manifestos da leva
      │ kitchen-a  kitchen-b ...│─────┘
      │ (tmux + git worktrees)  │   e mais: notificação do macOS com o
      └─────────────────────────┘   comando tmux attach no clipboard
```

</details>

- **`discord-hq plan` / `apply`** usam um token temporário de bot admin. Os dois leem o servidor, calculam o diff e aplicam. O canal é identificado por (nome, tipo, categoria), nunca só pelo nome. As permissões são gravadas em cada canal, porque o Discord não propaga a permissão da categoria para os canais que já existem. Veja [docs/design-format.md](docs/design-format.md).
- **`discord-hq hook`** roda nos eventos `Notification` e `Stop` do Claude Code. Ele só age dentro das sessões de cozinha, que reconhece pela pasta do git worktree ou pelo prefixo da sessão tmux.
- **`discord-hq watch`** roda a cada 2 minutos (LaunchAgent no macOS, cron no Linux). Ele faz três coisas:
  - aponta as sessões cuja tela mostra "esc to interrupt" mas cujo transcript parou de andar;
  - avisa sobre as unidades marcadas com ⏳ num manifesto de leva;
  - atualiza a mensagem única do painel ao vivo.
- Os avisos chegam ao Discord por **webhooks**, não por token de bot, e só mencionam você.

## Início rápido

Requisitos: Python 3.11+, git, tmux e uma conta no Discord. No macOS você recebe notificação nativa. No Linux também funciona, mas só com os avisos no Discord.

1. **Clone e instale:**
   ```sh
   git clone https://github.com/Fabiano-Arthur/claude-code-discord-hq.git
   cd claude-code-discord-hq
   ./install.sh --dry-run   # mostra o que ele faria
   ./install.sh             # pede confirmação antes de gravar cada arquivo
   ```
2. **Crie um servidor** no Discord e ative o Modo Desenvolvedor (Configurações → Avançado).
3. **Crie um bot admin temporário** e convide-o para o servidor: [docs/bot-setup.md](docs/bot-setup.md). Coloque o token dele e o id do servidor em `~/.config/claude-code-discord-hq/.env`.
4. **Escolha um design:** `cp examples/restaurant.toml design.toml`, ou comece pelo `examples/minimal.toml`, e depois edite.
5. **Confira antes:** `.venv/bin/discord-hq plan`
6. **Aplique:** `.venv/bin/discord-hq apply`. Depois **resete o token do bot admin** no Developer Portal. Você só vai precisar dele de novo quando quiser mudar o servidor.
7. **Ative os avisos:** cole no `~/.claude/settings.json` o trecho de hook que o `install.sh` imprimiu e preencha `DISCORD_HQ_MENTION_USER_ID` no `.env`.
8. **Conecte o garçom:** instale o plugin oficial do Discord no Claude Code, adicione `source .../shell/waiter.zsh` ao `~/.zshrc` e rode `waiter`. Depois rode `.venv/bin/discord-hq access --bot waiter` e digite nessa sessão os comandos que ele imprimir.

## Comandos

| Comando | O que faz |
|---|---|
| `discord-hq plan [--design FILE]` | Mostra o que o `apply` mudaria. Só leitura. |
| `discord-hq apply [--design FILE] [--yes] [--allow-delete]` | Deixa o servidor igual ao design. Pede confirmação antes e não apaga nada sem `--allow-delete`. |
| `discord-hq audit-forum CHANNEL_ID` | Lista os posts de um fórum antes de você movê-lo ou renomeá-lo. Só leitura. |
| `discord-hq access --bot NAME` | Imprime os comandos `/discord:access` para os canais de um bot. Não edita nada. |
| `discord-hq hook` | O hook do Claude Code. Lê o evento no stdin, não imprime nada e sempre sai com código 0. |
| `discord-hq watch` | Uma rodada do vigia: sessões travadas, unidades em pausa, painel ao vivo. |

Toda configuração é uma variável de ambiente ou uma linha em `~/.config/claude-code-discord-hq/.env`. O [`.env.example`](.env.example) documenta cada uma.

## Segurança

Aqui vai o resumo. A versão completa está em [docs/security-model.md](docs/security-model.md) e [docs/threat-model.md](docs/threat-model.md):

- **O token de admin é temporário.** Use no `apply` e depois resete. Os bots que conversam com o Claude Code nunca precisam de admin.
- **Os segredos ficam fora do repositório.** Os tokens ficam em `~/.config/claude-code-discord-hq/.env` e as URLs de webhook em `webhooks.json`, os dois com permissão 0600. O `state.json` só guarda ids e está no `.gitignore`. Token e URL de webhook nunca aparecem no stdout, em log ou em exceção.
- **Mensagem é dado, não instrução.** Tudo o que um bot lê num canal pode ser prompt injection. O design mantém a DM fechada (pela allowlist do plugin), dá ao convidado um canal próprio em que o bot só responde quando é mencionado e nunca deixa dois bots respondendo no mesmo canal. O `discord-hq access` imprime comandos em vez de editar o `access.json` do plugin.
- **O hook não quebra a sua sessão.** Ele tem timeouts curtos, nunca lança exceção, nunca imprime nada e sempre sai com código 0.
- **O instalador pergunta antes.** O `install.sh` pede confirmação antes de cada gravação. Ele nunca edita o `~/.claude/settings.json` nem o arquivo rc do seu shell: só imprime o que você deve colar.

Achou uma vulnerabilidade? Veja o [SECURITY.md](SECURITY.md).

## Perguntas frequentes

**Ele chama a API do Discord por conta própria?**
Só `plan`, `apply` e `audit-forum` usam a API de bot, e só quando você roda esses comandos. O hook e o vigia só postam pelos webhooks que você criou.

**O `apply` vai apagar o que já existe no meu servidor?**
Não. Ele só gerencia o que o design declara. Canais de outras categorias e permissões de outros usuários ou cargos ficam como estão. Ele só apaga os canais cujo id você listar em `[cleanup]`, e só com `--allow-delete`.

**E se eu perder o `state.json`?**
Cargos, categorias, canais e webhooks nunca são duplicados: quem manda é o servidor real, e o próximo `apply` recria o arquivo (mesmo que nada mais tenha mudado). A única coisa registrada só no `state.json` é quais `[[pinned_messages]]` já foram postadas, então essas mensagens seriam postadas de novo. O `discord-hq access` precisa do arquivo, então rode o `apply` antes.

**Renomeei a categoria de um canal no design e apareceu um canal novo. Por quê?**
A identidade de um canal é (nome, tipo, categoria). Mover canais automaticamente já corrompeu um servidor de verdade, então um canal que muda de lugar é criado do zero e o antigo fica lá para você decidir o que fazer. Para renomear a categoria sem trocar nada de lugar, use `rename_from` nela: o mesmo id continua com os seus canais e os posts dos fóruns.

**Dá para usar sem tmux ou sem worktrees?**
A parte de servidor como código, sim. Os avisos precisam de um jeito de separar as sessões de cozinha das outras. Eles procuram uma pasta `.worktrees/<nome>` (configurável) ou um prefixo de sessão tmux (`kitchen-` por padrão).

**Linux? Windows?**
Linux: sim, só com os avisos no Discord (sem notificação nativa) e com uma linha no cron no lugar do LaunchAgent. Windows: a parte de servidor como código deve funcionar com Python; o resto não foi testado.

**Tem alguma ligação com a Anthropic ou com o Discord?**
Não. É um projeto open source independente.

## Como contribuir

Issues e pull requests são bem-vindos: veja o [CONTRIBUTING.md](CONTRIBUTING.md). A suíte de testes nunca fala com o Discord e nunca mexe nas suas sessões tmux de verdade.

## Licença

[MIT](LICENSE) © 2026 Fabiano Arthur
