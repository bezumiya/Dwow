# Dwow

**🇺🇸 [English version](README.md)**

Rich Presence para **World of Warcraft Classic** (Classic Era, Anniversary e
MoP Classic) que mostra no seu perfil do Discord — em tempo real — o que o seu
personagem está fazendo: enfrentando um chefe, na fila de masmorra (com o
verdadeiro olho do LFG), voando na sua própria montaria, pescando, morto após
um wipe… mais de 45 estados distintos, em português ou inglês.

```
┌────────────────────┐   pixels codificados    ┌──────────────────────┐
│  WoW Classic       │ ──── (na tela) ───────► │  Companion (Python)  │
│  + addon Dwow│                         │  captura → decodifica│
│  (API oficial,     │                         │  → Rich Presence     │
│   zero injeção)    │                         └──────────┬───────────┘
└────────────────────┘                                    ▼
                                                      Discord
```

**Por que pixels?** Addons de WoW são sandboxed: não podem usar rede nem gravar
arquivos em tempo real. O addon desenha os dados como uma faixa minúscula de
células coloridas (3 px de altura) no canto superior esquerdo, e o companion lê
essa faixa capturando a janela — a mesma técnica do CraftPresence. Detalhes em
[docs/PROTOCOLO.md](docs/PROTOCOLO.md).

**Seguro:** o addon usa só a API oficial de addons; o companion apenas *lê* a
tela — não injeta nada no jogo, não lê memória e não envia input. Nunca
automatize input junto com este projeto: essa é a linha vermelha da Blizzard.

## Requisitos

- Windows 10/11, Discord desktop aberto
- Python 3.10+ com `pypresence` e `Pillow` (`pip install pypresence pillow`)
- WoW em modo **janela ou janela sem borda**, anti-aliasing (MSAA) desligado

## Instalação

### 1. Addon

Copie `addon/Dwow` para a pasta AddOns do sabor que você joga:

```
World of Warcraft\_classic_era_\Interface\AddOns\Dwow   (Classic Era / Hardcore / SoD)
World of Warcraft\_classic_\Interface\AddOns\Dwow       (MoP Classic)
World of Warcraft\_anniversary_\Interface\AddOns\Dwow   (Anniversary)
```

No jogo, `/dwow` liga/desliga o export e `/dwow status` imprime o payload
atual (útil para diagnosticar).

### 2. Aplicação no Discord

1. Acesse <https://discord.com/developers/applications> → **New Application**.
   Dê o nome `World of Warcraft Classic` (é o que aparece como título do jogo).
2. Copie o **Application ID**.
3. (Opcional, para os retratos) Em **Rich Presence → Art Assets**, suba suas
   artes com as chaves `wow_classic`, `class_<classe>` e
   `race_<raça>_<male|female>`.

### 3. Configuração do companion

```bash
cd companion
copy config.example.json config.json
```

Edite o `config.json`:

| Chave | Significado |
|---|---|
| `application_id` | o Application ID do seu app no Discord (obrigatório) |
| `language` | `"pt"` ou `"en"` — idioma das frases do card |
| `use_race_image`, `show_realm`, `show_guild`, `show_xp`, `show_gold` | liga/desliga detalhes do card |
| `bnet.*` | opcional: render 3D do seu personagem via Battle.net API — crie um client grátis em <https://develop.battle.net>, preencha `client_id`/`client_secret`, ponha `enabled: true` e escolha `region` (`us`/`eu`) e `flavor` (`era`/`mop`/`anniversary`) |
| `widget.*` | suporte experimental a Profile Widgets (desligado por padrão) |

> **Nunca commite o `config.json`** — ele guarda seus segredos e está no
> `.gitignore`.

### 4. Rodar

```bash
python main.py
```

Com o WoW e o Discord abertos, seu perfil atualiza em ~15 s (limite do
Discord). O presence se limpa sozinho ~60 s depois de fechar o jogo.

**Auto-start (recomendado):** registre uma tarefa oculta de logon para o
companion ficar sempre esperando o jogo — rode uma vez no PowerShell:

```powershell
cd companion
.\install_autostart.ps1            # instala e inicia (invisível; log em companion.log)
.\install_autostart.ps1 -Remove    # desinstala
```

## Recursos

- **45+ estados** com ordem de prioridade: morte/wipe, chefes (com % de HP),
  bandeira/orbe de PvP, timers de afogamento e fadiga, voos de táxi por
  facção, profissões, casa de leilões, correio, vendedor/conserto, duelos,
  ressurreições, ociosidade…
- **Fila de masmorra/raid**: a textura verdadeira do olho do LFG aparece na
  miniatura enquanto você está na fila (LFD/RF no MoP, LFG Tool no
  Era/Anniversary, filas de BG em todos); o pop da fila toma o card por
  alguns segundos.
- **Sua montaria de verdade**: o nome na frase e o ícone dela na miniatura —
  o personagem fica sempre como imagem grande; estados ao vivo (voo, formas,
  morte…) aparecem como o ícone pequeno.
- **Formas de druida/xamã/priest/lock**: urso, gato, coruja lunar, viagem,
  voo, lobo fantasma, shadowform… cada uma com seu ícone, ao vivo.
- **Render 3D do personagem** (opcional, Battle.net API) como imagem do card,
  com retratos de raça como fallback.
- **Captura robusta**: janela certa do jogo, DPI awareness, relocação da
  faixa (addons de viewport), detecção de jogo travado, payload com checksum.

## Problemas comuns

| Sintoma | Solução |
|---|---|
| "Sem dados válidos" no log | personagem precisa estar no mundo; veja `/dwow status`; desligue MSAA; use modo janela/sem borda |
| Presence nunca atualiza | o Discord desktop precisa estar aberto antes do companion; confira o `application_id` |
| Render borrado/desatualizado | o render da Battle.net só atualiza no logout; personagem novo dá 404 por algumas horas (o retrato de raça cobre enquanto isso) |
| Olho da fila não aparece | `/reload` depois de atualizar o addon; fila LFD/RF só existe no MoP |

## Licença / avisos

Projeto pessoal, sem afiliação com a Blizzard Entertainment ou o Discord.
World of Warcraft e seus assets são © Blizzard Entertainment. O addon apenas
lê dados da API oficial e desenha pixels; sem garantias.
