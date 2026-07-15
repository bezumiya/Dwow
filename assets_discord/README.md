# Assets para o Discord Developer Portal

Esta pasta contém as imagens usadas pelo Rich Presence do **Dwow**.

No [Discord Developer Portal](https://discord.com/developers/applications),
abra sua aplicação e envie cada PNG em **Rich Presence → Art Assets**.

O nome do arquivo sem `.png` deve ser mantido como a chave do asset. Exemplos:

| Arquivo | Chave no Discord |
|---|---|
| `wow_classic.png` | `wow_classic` |
| `class_warrior.png` | `class_warrior` |
| `class_mage.png` | `class_mage` |
| `race_orc_male.png` | `race_orc_male` |
| `race_nightelf_female.png` | `race_nightelf_female` |

Não altere letras, espaços ou o formato das chaves: o companion gera esses
nomes automaticamente a partir da classe, raça e gênero do personagem.

## Conteúdo

- `wow_classic.png`: imagem padrão do Rich Presence.
- `class_*.png`: ícones das 11 classes suportadas pelo projeto.
- `race_*_male.png` e `race_*_female.png`: retratos das 13 raças suportadas.

Após o upload, o Discord pode levar alguns minutos para disponibilizar todas
as imagens. Reinicie o companion caso um asset recém-enviado não apareça.

World of Warcraft e seus assets são © Blizzard Entertainment. Estas imagens
são fornecidas somente para configuração deste projeto pessoal, sem afiliação
com a Blizzard Entertainment ou o Discord.
