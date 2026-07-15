# Protocolo de pixels Dwow — versão 1

**🇺🇸 [English version](PROTOCOL.md)**

Canal de exportação de dados do addon (Lua, dentro do WoW) para o app companion
(Python, fora do jogo). O addon desenha uma faixa de células coloridas no canto
superior esquerdo da tela; o companion captura a janela e decodifica as cores.

**Qualquer mudança neste protocolo precisa ser espelhada em dois lugares:**
`addon/Dwow/Encoder.lua` (codificador) e `companion/decoder.py` (decodificador).

## Geometria

- Cada **célula** é um quadrado de `CELL_PX` pixels físicos (padrão: **3**).
  O companion lê apenas o pixel central da célula, então borrões leves de
  anti-aliasing nas bordas não corrompem a leitura.
- As células são dispostas da esquerda para a direita, com quebra de linha a
  cada `CELLS_PER_ROW` células (padrão: **128**), ancoradas no canto superior
  esquerdo da tela (0,0).
- O addon usa `SetIgnoreParentScale` + `SetScale(768 / alturaFisica)` para que
  1 unidade de UI = 1 pixel físico, independente da escala de UI do jogador.

## Layout das células

Cada célula carrega 3 bytes (R, G, B).

| Célula | Conteúdo |
|---|---|
| 0 | Magic A: RGB **(192, 255, 238)** — âncora/calibração |
| 1 | Magic B: RGB **(13, 21, 234)** — âncora/calibração |
| 2 | R = versão do protocolo (**1**), G = tamanho do payload (byte baixo), B = tamanho (byte alto) |
| 3 | R = contador de sequência (0–255, incrementa a cada redesenho; heartbeat), G/B = reservado (0) |
| 4 | Checksum **Adler-24** do payload: R = bits 23–16, G = bits 15–8, B = bits 7–0 |
| 5+ | Payload: bytes UTF-8, 3 por célula, última célula preenchida com zeros |

O companion valida os dois magics com tolerância de ±4 por canal (detecta
overlay cobrindo a faixa, gamma/HDR alterando cores, ou janela errada). Os
demais bytes são lidos sem tolerância — o checksum protege contra corrupção.

## Checksum Adler-24

Adler-32 clássico (mod 65521) truncado aos 24 bits baixos, para caber em uma
célula: em Python, `zlib.adler32(payload) & 0xFFFFFF`; em Lua, implementação
direta em `Encoder.lua` (`ns.Adler24`).

## Payload

String UTF-8 com campos separados por `|`, nesta ordem (o addon substitui
qualquer `|` dentro de um valor por `/`):

| # | Campo | Exemplo | Observação |
|---|---|---|---|
| 1 | name | `Grubento` | `UnitName("player")` |
| 2 | realm | `Firemaw` | `GetRealmName()` |
| 3 | class_token | `WARRIOR` | independente de idioma; usado como chave de asset |
| 4 | class_name | `Guerreiro` | localizado |
| 5 | race | `Orc` | localizado |
| 6 | level | `47` | inteiro |
| 7 | zone | `Profundezas Rocha Negra` | `GetRealZoneText()` |
| 8 | subzone | `Taverna` | pode ser vazio |
| 9 | instance_name | `Blackrock Depths` | vazio quando fora de instância |
| 10 | instance_type | `party` | `none`, `party`, `raid`, `pvp`, `arena` ou `scenario` (MoP) |
| 11 | hp_pct | `100` | 0–100 |
| 12 | dead | `0` | `1` = morto ou fantasma |
| 13 | xp_pct | `62` | 0–100 |
| 14 | group_size | `5` | 0 = sozinho |
| 15 | group_max | `5` | maxPlayers da instância (ex.: 3, 5, 10, 15, 25, 40); fallback 5/40 fora de instância |
| 16 | guild | `Os Bravos` | pode ser vazio |
| 17 | race_token | `NightElf` | apêndice opcional; token do arquivo de raça (`Scourge` = morto-vivo) |
| 18 | gender | `m` | apêndice opcional; `m` ou `f` (`UnitSex` 3 = f) |
| 19 | flags | `34` | apêndice; bitfield: 1 táxi, 2 combate, 4 descansando, 8 montado (nunca junto com táxi), 16 nadando, 32 AFK, 64 fantasma, 128 furtivo, 256 voando (`IsFlying`), 512 caindo (2 ticks seguidos), 1024 pescando |
| 20 | target | `Ragnaros` | apêndice; alvo hostil vivo atual (vazio sem alvo) |
| 21 | target_hp | `43` | apêndice; vida do alvo em % |
| 22 | target_class | `worldboss` | apêndice; `UnitClassification` do alvo |
| 23 | money | `1234567` | apêndice; dinheiro em cobre (÷10000 = ouro) |
| 24 | faction | `Horde` | apêndice; token de `UnitFactionGroup` (infere a criatura do táxi) |
| 25 | form | `Forma de Viagem` | apêndice; nome localizado da metamorfose ativa, vazio sem forma |
| 26 | form_id | `783` | apêndice; spellID da forma (0 quando o cliente usa a assinatura antiga sem spellID) |
| 27 | activity | `hearth:Orgrimmar` | apêndice; atividade especial vigente: `token` ou `token:arg` (tabela abaixo), vazio sem atividade |
| 28 | difficulty | `2` | apêndice; `difficultyID` de `GetInstanceInfo` (0 fora de instância; 2=Heroica, 3=10j, 4=25j, 5=10H, 6=25H, 7=LFR, 8=Desafio, 9=40j) |
| 29 | target_level | `43` | apêndice; `UnitLevel("target")` do alvo hostil (`-1` = "??", 0 = sem alvo) |
| 30 | mount_spell | `64658` | apêndice; spellID da montaria ativa via `C_MountJournal.GetMountInfoByID` (`isActive`); 0 desmontado |
| 31 | mount_name | `Lobo Negro` | apêndice; nome localizado da montaria ativa |

### Tokens de activity (campo 27)

O addon escolhe UM token por tick (a ordem de checagem em `BuildActivity` é a
prioridade). Formato `token` ou `token:argumento`; o argumento nunca contém `|`.

| Token | Arg | Significado |
|---|---|---|
| `flag` | — | carregando bandeira/orbe de battleground (auras 23333/23335/34976 + orbes de Kotmogu 121164/121175/121176/121177) |
| `boss:{nome}` | nome do encontro | luta de chefe ativa (`ENCOUNTER_START/END`) |
| `breath:{pct}` | % de fôlego | submerso gastando ar (`GetMirrorTimerProgress`, só com `scale < 0` = drenando) |
| `fatigue:{pct}` | % de fadiga | em águas de fadiga mortal (timer `EXHAUSTION` drenando) |
| `hearth:{local}` | bind location | conjurando Pedra de Regresso (8690) ou Chamado Astral (556) |
| `teleport:{cidade}` / `portal:{cidade}` | cidade | teleporte/portal de mago (tabela de spellIDs auditada) |
| `smelt` `disenchant` `mine` `herb` `skin` `prospect` `mill` | — | profissão em cast (comparação por nome de spell) |
| `firstaid` | — | canalizando bandagem (nome == `GetSpellInfo(746)`) |
| `res:{nome}` | quem ressuscita | `RESURRECT_REQUEST` (expira ao reviver ou 60s) |
| `spirit:{s}` | segundos | fantasma na área do Curandeiro Espiritual |
| `duel:{nome}` | oponente | `DUEL_REQUESTED`→`DUEL_FINISHED` (limpa em loading/10min) |
| `trade:{nome}` | parceiro | janela de troca aberta (`UnitName("NPC")`) |
| `cinematic` | — | `CINEMATIC_START/STOP` + `PLAY_MOVIE/STOP_MOVIE` |
| `vehicle:{nome}` | veículo | `UnitInVehicle` (MoP) |
| `bgwin` `bgloss` `bgtie` | — | `GetBattlefieldWinner` vs facção |
| `ah` `mail` `bank` `guildbank` `vendor` `repair` `trainer` `stable` `barber` `read` `taximap` `petition` | — | janelas de UI (pares SHOW/CLOSED; `repair` exige custo > 0) |
| `invite:{nome}` | quem convidou | convite de grupo pendente (expira 60s/ao agrupar) |
| `feign` | — | Fingir de Morto (aura 5384; `UnitIsFeignDeath` não funciona no próprio jogador) |
| `eat` `drink` `eatdrink` | — | auras com nome == `GetSpellInfo(433)`/`(430)` |
| `floatfall` | — | caindo com Queda Lenta/Levitação (auras 130/1706) |
| `waterwalk` | — | Andar sobre as Águas (auras 546/3714/11319) fora d'água |
| `tram` | — | instanceID 369 (Metrô das Profundezas), sem gate de IsInInstance |
| `ffa` | — | `UnitIsPVPFreeForAll` |
| `skull` | — | `GetRaidTargetIndex("player") == 8` |
| `lowdur:{pct}` | % durabilidade | média < 25% ou peça quebrada (slots 1–18, poll a cada 10s) |
| `bgqueue:{bg}` / `bgconfirm:{bg}` | mapa | fila/convite de battleground (`GetBattlefieldStatus`) |
| `lfd` `rf` | — | na fila do Dungeon/Raid Finder (`GetLFGMode`, só MoP) |
| `lfgpop` | — | fila popou: proposta/role check pendente (urgente, prioridade alta) |
| `lfgapp` / `lfglist` | — | inscrito num grupo premade / grupo próprio listado (`C_LFGList`, todos os flavors) |
| `idle:{min}` | minutos | parado ≥ 5 min sem combate/cast/movimento |

Campos novos só podem ser **acrescentados ao final** (o decodificador ignora
campos extras); remover ou reordenar campos exige bump da versão do protocolo.

O payload é limitado a **`MAX_PAYLOAD_BYTES` = 600 bytes**; o addon trunca o
excedente por bytes (um caractere UTF-8 cortado ao meio vira U+FFFD no
decodificador — cosmético, nunca erro).

## Localização da faixa

A faixa fica normalmente em (0,0), mas addons de viewport (que deslocam o
`WorldFrame` para abrir espaço para arte de UI) podem movê-la. O decodificador
primeiro tenta a última origem conhecida; se o magic não estiver lá, varre a
região superior esquerda (`SEARCH_W`×`SEARCH_H` = 600×300 px) atrás do par
Magic A/Magic B e cacheia a nova origem.

## Comportamento

- O addon redesenha a faixa **1x por segundo**, mesmo sem mudança nos dados —
  o contador de sequência avança e serve de heartbeat.
- `/dwow` no jogo alterna a faixa (oculta = companion perde o magic e limpa o
  presence após `clear_after_seconds`).
- O companion só envia update ao Discord quando os dados relevantes mudam **e**
  respeitando o intervalo mínimo de 15 s entre updates (limite histórico do
  Discord para presence).
