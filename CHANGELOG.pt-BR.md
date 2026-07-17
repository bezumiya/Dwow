# Histórico de versões

**[English](CHANGELOG.md)**

## v0.3.0 — Project Ascension e releases multi-cliente

### Adicionado

- Suporte oficial ao Project Ascension 3.3.5, testado ao vivo com o Discord.
- Manifest `Dwow_Ascension.toc` e pacote `Dwow-Addon-Ascension` dedicado.
- Perfis para Classic Era, Anniversary, TBC Classic, MoP Classic e Ascension.
- Decodificação adaptativa de pixels fracionários para clientes antigos derivados do Wrath.
- Documentação dos assets do Discord em inglês, com tradução PT-BR separada.

### Melhorado

- Captura BitBlt mais rápida, com fallback seguro para PrintWindow.
- Tratamento mais resistente de AFK, janela minimizada, captura obsoleta e jogo travado.
- Logs de recuperação, saúde, transições AFK e publicação do Rich Presence.
- Logs operacionais automáticos em inglês ou português conforme o idioma do sistema.
- Fallbacks para APIs antigas de timers, texturas, grupos, movimento e montarias.

### Pacotes

- A release agora possui ZIPs separados para Classic Era, Anniversary,
  TBC Classic, MoP Classic e Ascension, além do companion Windows compartilhado.
- Usuários existentes devem baixar o ZIP correspondente ao seu cliente.
- No Ascension, use `"client": "ascension"`; o render Battle.net é desativado
  automaticamente porque personagens não oficiais não existem na API da Blizzard.
